#!/usr/bin/env python3
"""
Batch validation script for transcript parser.
Runs all transcripts through the parser and compares results against human-recorded GPAs.
"""
import sys
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import traceback

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.transcript_parser.gemini_transcript_service import parse_transcript_file


# Human-recorded GPAs for validation
# Using flexible keys to match various filename formats
HUMAN_GPAS = {
    "Castro, Ricardo": 3.69,
    "Davis, Christopher": 3.83,
    "Escobedo, Juan": 4.61,
    "Freeney, Ariana": 2.77,
    "Golatt, Nathaniel": 2.51,
    "Gonzalez, Yubell": 3.96,
    "Gonzalez Otero, Yubell": 3.96,  # Alternative spelling
    "Huynh, Tai": 3.67,
    "Johnston, Jeremiah": 2.95,
    "Jones, Je'von": 3.32,
    "Jones, Je'Von": 3.32,  # Alternative capitalization
    "Norris, Avery": 4.2,
    "Stoneham, Kevin": 2.73,
    "Strait, Josiah": 3.76,
    "Tullous, Mark": 4.21,
    "Vasquez, Victoria": 3.17,
    "Vazquez, Victoria": 3.17,  # Alternative spelling
}


def normalize_name(filename: str) -> str:
    """
    Normalize transcript filename to match human GPA keys.
    E.g., "CASTRO, RICARDO.pdf" -> "Castro, Ricardo"
    """
    # Remove .pdf extension
    name = filename.replace('.pdf', '')

    # Handle different formats
    parts = name.split(',')
    if len(parts) >= 2:
        last_name = parts[0].strip()
        first_name = parts[1].strip().split()[0]  # Take only first name, ignore middle names/suffixes

        # Title case
        last_name = last_name.title()
        first_name = first_name.title()

        return f"{last_name}, {first_name}"

    return name


def match_filename_to_human_gpa(filename: str) -> Tuple[str, float]:
    """
    Match a transcript filename to its human-recorded GPA.
    Returns (normalized_name, gpa) or raises KeyError if not found.
    """
    normalized = normalize_name(filename)

    # Try exact match first
    if normalized in HUMAN_GPAS:
        return normalized, HUMAN_GPAS[normalized]

    # Try fuzzy matching (in case of naming differences)
    for human_name, gpa in HUMAN_GPAS.items():
        # Check if the key parts match
        if human_name.lower() in normalized.lower() or normalized.lower() in human_name.lower():
            return human_name, gpa

    raise KeyError(f"No human GPA found for: {normalized} (from file: {filename})")


def parse_single_transcript(file_path: Path) -> dict:
    """
    Parse a single transcript and return results with error handling.
    Returns dict with success status, data, and any errors.
    """
    result = {
        'filename': file_path.name,
        'success': False,
        'error': None,
        'calculated_gpa': None,
        'human_gpa': None,
        'student_name': None,
        'raw_data': None,
    }

    try:
        # Match to human GPA
        human_name, human_gpa = match_filename_to_human_gpa(file_path.name)
        result['human_gpa'] = human_gpa
        result['student_name'] = human_name

        # Parse transcript
        print(f"  Parsing {file_path.name}...")
        transcript_data = parse_transcript_file(str(file_path))
        result['raw_data'] = transcript_data

        # Extract calculated GPA
        gpa_calc = transcript_data.get('gpa_calculation', {})
        calculated_gpa = gpa_calc.get('calculated_gpa')

        if calculated_gpa is not None:
            result['calculated_gpa'] = float(calculated_gpa)
            result['success'] = True
        else:
            result['error'] = "No GPA calculation in response"

    except KeyError as e:
        result['error'] = f"Name matching error: {str(e)}"
    except Exception as e:
        result['error'] = f"{type(e).__name__}: {str(e)}"
        result['traceback'] = traceback.format_exc()

    return result


def calculate_metrics(results: List[dict]) -> dict:
    """
    Calculate accuracy metrics from parsing results.
    """
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]

    metrics = {
        'total_transcripts': len(results),
        'successful_parses': len(successful),
        'failed_parses': len(failed),
        'success_rate': len(successful) / len(results) if results else 0,
    }

    if successful:
        errors = []
        absolute_errors = []

        for result in successful:
            error = result['calculated_gpa'] - result['human_gpa']
            errors.append(error)
            absolute_errors.append(abs(error))

        metrics['mean_error'] = sum(errors) / len(errors)
        metrics['mean_absolute_error'] = sum(absolute_errors) / len(absolute_errors)
        metrics['max_error'] = max(absolute_errors)
        metrics['min_error'] = min(absolute_errors)

        # Count within tolerance thresholds
        metrics['within_0.1'] = sum(1 for e in absolute_errors if e <= 0.1)
        metrics['within_0.25'] = sum(1 for e in absolute_errors if e <= 0.25)
        metrics['within_0.5'] = sum(1 for e in absolute_errors if e <= 0.5)

    return metrics


def generate_report(results: List[dict], metrics: dict, output_dir: Path):
    """
    Generate detailed validation report.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = output_dir / f"validation_report_{timestamp}.txt"
    json_file = output_dir / f"validation_results_{timestamp}.json"

    # Generate text report
    with open(report_file, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("TRANSCRIPT PARSER VALIDATION REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Overall metrics
        f.write("OVERALL METRICS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total Transcripts:     {metrics['total_transcripts']}\n")
        f.write(f"Successful Parses:     {metrics['successful_parses']}\n")
        f.write(f"Failed Parses:         {metrics['failed_parses']}\n")
        f.write(f"Success Rate:          {metrics['success_rate']:.1%}\n\n")

        if metrics['successful_parses'] > 0:
            f.write("ACCURACY METRICS\n")
            f.write("-" * 80 + "\n")
            f.write(f"Mean Error:            {metrics['mean_error']:+.3f}\n")
            f.write(f"Mean Absolute Error:   {metrics['mean_absolute_error']:.3f}\n")
            f.write(f"Max Error:             {metrics['max_error']:.3f}\n")
            f.write(f"Min Error:             {metrics['min_error']:.3f}\n\n")

            f.write("ACCURACY THRESHOLDS\n")
            f.write("-" * 80 + "\n")
            total = metrics['successful_parses']
            f.write(f"Within ±0.10:          {metrics['within_0.1']}/{total} ({metrics['within_0.1']/total:.1%})\n")
            f.write(f"Within ±0.25:          {metrics['within_0.25']}/{total} ({metrics['within_0.25']/total:.1%})\n")
            f.write(f"Within ±0.50:          {metrics['within_0.5']}/{total} ({metrics['within_0.5']/total:.1%})\n\n")

        # Individual results
        f.write("INDIVIDUAL RESULTS\n")
        f.write("-" * 80 + "\n\n")

        # Successful parses
        successful = [r for r in results if r['success']]
        if successful:
            f.write("Successful Parses:\n\n")
            for result in successful:
                error = result['calculated_gpa'] - result['human_gpa']
                f.write(f"  {result['student_name']}\n")
                f.write(f"    File:           {result['filename']}\n")
                f.write(f"    Human GPA:      {result['human_gpa']:.2f}\n")
                f.write(f"    Calculated GPA: {result['calculated_gpa']:.2f}\n")
                f.write(f"    Error:          {error:+.3f}\n")
                f.write(f"    Abs Error:      {abs(error):.3f}\n")
                f.write("\n")

        # Failed parses
        failed = [r for r in results if not r['success']]
        if failed:
            f.write("\nFailed Parses:\n\n")
            for result in failed:
                f.write(f"  {result.get('student_name', 'UNKNOWN')}\n")
                f.write(f"    File:      {result['filename']}\n")
                f.write(f"    Error:     {result['error']}\n")
                if 'traceback' in result:
                    f.write(f"    Traceback:\n")
                    for line in result['traceback'].split('\n'):
                        f.write(f"      {line}\n")
                f.write("\n")

    # Save JSON results
    with open(json_file, 'w') as f:
        json.dump({
            'metrics': metrics,
            'results': results,
            'timestamp': timestamp,
        }, f, indent=2)

    return report_file, json_file


def main():
    """
    Main validation function.
    """
    print("=" * 80)
    print("TRANSCRIPT PARSER VALIDATION")
    print("=" * 80)
    print()

    # Setup paths
    base_dir = Path(__file__).parent
    transcripts_dir = base_dir / "Transcripts 2"
    output_dir = base_dir / "validation_results"
    output_dir.mkdir(exist_ok=True)

    if not transcripts_dir.exists():
        print(f"Error: Transcripts directory not found: {transcripts_dir}")
        sys.exit(1)

    # Get all PDF files
    transcript_files = sorted(transcripts_dir.glob("*.pdf"))
    print(f"Found {len(transcript_files)} transcript files\n")

    # Process each transcript
    results = []
    for i, file_path in enumerate(transcript_files, 1):
        print(f"[{i}/{len(transcript_files)}] Processing {file_path.name}...")
        result = parse_single_transcript(file_path)
        results.append(result)

        if result['success']:
            error = result['calculated_gpa'] - result['human_gpa']
            print(f"  ✓ Success: Calculated={result['calculated_gpa']:.2f}, Human={result['human_gpa']:.2f}, Error={error:+.3f}")
        else:
            print(f"  ✗ Failed: {result['error']}")
        print()

    # Calculate metrics
    print("=" * 80)
    print("CALCULATING METRICS...")
    print("=" * 80)
    print()

    metrics = calculate_metrics(results)

    # Display summary
    print(f"Total Transcripts:     {metrics['total_transcripts']}")
    print(f"Successful Parses:     {metrics['successful_parses']}")
    print(f"Failed Parses:         {metrics['failed_parses']}")
    print(f"Success Rate:          {metrics['success_rate']:.1%}")

    if metrics['successful_parses'] > 0:
        print()
        print(f"Mean Absolute Error:   {metrics['mean_absolute_error']:.3f}")
        print(f"Mean Error:            {metrics['mean_error']:+.3f}")
        print()
        total = metrics['successful_parses']
        print(f"Within ±0.10:          {metrics['within_0.1']}/{total} ({metrics['within_0.1']/total:.1%})")
        print(f"Within ±0.25:          {metrics['within_0.25']}/{total} ({metrics['within_0.25']/total:.1%})")
        print(f"Within ±0.50:          {metrics['within_0.5']}/{total} ({metrics['within_0.5']/total:.1%})")

    # Generate report
    print()
    print("=" * 80)
    print("GENERATING REPORTS...")
    print("=" * 80)
    report_file, json_file = generate_report(results, metrics, output_dir)
    print(f"✓ Text Report: {report_file}")
    print(f"✓ JSON Data:   {json_file}")
    print()

    # Production readiness assessment
    print("=" * 80)
    print("PRODUCTION READINESS ASSESSMENT")
    print("=" * 80)
    print()

    if metrics['success_rate'] >= 0.95 and metrics.get('mean_absolute_error', float('inf')) <= 0.25:
        print("✓ READY FOR PRODUCTION")
        print("  The parser demonstrates high reliability and accuracy.")
    elif metrics['success_rate'] >= 0.85 and metrics.get('mean_absolute_error', float('inf')) <= 0.5:
        print("⚠ CONDITIONALLY READY")
        print("  The parser shows promise but may need human review for edge cases.")
    else:
        print("✗ NOT READY FOR PRODUCTION")
        print("  The parser needs further refinement before production deployment.")

    print()
    print("Review the detailed report for specific failures and recommendations.")
    print()


if __name__ == '__main__':
    main()
