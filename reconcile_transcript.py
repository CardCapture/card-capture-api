#!/usr/bin/env python3
"""
CLI to run GPA reconciliation variants on a parsed transcript result.
Usage:
  python3 reconcile_transcript.py --file /path/to/transcript.pdf
"""
import sys
import os
import json
import click

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
from app.services.transcript_parser.gemini_transcript_service import parse_transcript_file
from app.services.transcript_parser.gpa_reconcile import compute_gpa_variants


@click.command()
@click.option('--file', 'file_path', required=True, type=click.Path(exists=True), help='Transcript PDF path')
@click.option('--debug-json', is_flag=True, help='Print parsed JSON before reconciliation')
def main(file_path: str, debug_json: bool):
    data = parse_transcript_file(file_path)
    if debug_json:
        print("\n=== PARSED JSON (truncated) ===")
        print(json.dumps({
            "student": data.get("student", {}),
            "courses_count": len(data.get("courses", [])),
            "gpa_calculation": data.get("gpa_calculation", {})
        }, indent=2))

    variants = compute_gpa_variants(data)
    print("\n=== GPA RECONCILIATION VARIANTS ===")
    print(f"{'Variant':35} {'GPA':>8} {'Δ vs reported':>15}")
    print("-" * 64)
    for name, gpa, delta in variants:
        delta_str = f"{delta:+.3f}" if name != 'reported_gpa' else ''
        print(f"{name:35} {gpa:8.3f} {delta_str:>15}")


if __name__ == '__main__':
    main()


