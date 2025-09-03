#!/usr/bin/env python3
"""
Transcript parser CLI using card-capture-api Gemini infrastructure.
"""
import sys
import os
import json
import csv
from pathlib import Path
from datetime import datetime
import click

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.transcript_parser.gemini_transcript_service import parse_transcript_file


@click.command()
@click.option('--file', 'file_path', required=True, type=click.Path(exists=True),
              help='Path to transcript file (PDF, PNG, JPG, etc.)')
@click.option('--outdir', default='.', type=click.Path(),
              help='Output directory for CSV files (default: current directory)')
@click.option('--debug', is_flag=True, help='Show raw Gemini response')
@click.option('--json-output', is_flag=True, help='Also save raw JSON response')
def main(file_path: str, outdir: str, debug: bool, json_output: bool):
    """
    Parse transcript files using Gemini Vision API.
    
    This tool leverages the existing card-capture-api Gemini configuration
    and outputs structured CSV files for further processing.
    """
    
    try:
        click.echo("🤖 Card Capture Transcript Parser")
        click.echo("=" * 50)
        click.echo(f"📄 Input: {file_path}")
        click.echo(f"📊 Output: {outdir}")
        click.echo()
        
        # Parse transcript
        click.echo("🧠 Analyzing transcript with Gemini...")
        transcript_data = parse_transcript_file(file_path)
        
        if debug:
            click.echo("\n=== RAW GEMINI RESPONSE ===")
            click.echo(json.dumps(transcript_data, indent=2))
            click.echo("=" * 50)
        
        # Save JSON if requested
        if json_output:
            json_path = Path(outdir) / f"transcript_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(json_path, 'w') as f:
                json.dump(transcript_data, f, indent=2)
            click.echo(f"💾 Saved JSON: {json_path}")
        
        # Export to CSV
        click.echo("📊 Exporting to CSV...")
        csv_files = export_to_csv(transcript_data, outdir)
        
        for csv_file in csv_files:
            click.echo(f"✅ Created: {csv_file}")
        
        # Show summary
        show_summary(transcript_data)
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        if debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def export_to_csv(transcript_data: dict, outdir: str) -> list:
    """Export transcript data to CSV files."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    students_file = outdir / f"students_{timestamp}.csv"
    courses_file = outdir / f"courses_{timestamp}.csv"
    
    # Export students.csv
    student_data = transcript_data.get('student', {})
    gpa_calc = transcript_data.get('gpa_calculation', {})
    
    students_row = {
        'name': student_data.get('name', ''),
        'date_of_birth': student_data.get('date_of_birth', ''),
        'student_id': student_data.get('student_id', ''),
        'school': student_data.get('school', ''),
        'district': student_data.get('district', ''),
        'reported_gpa': student_data.get('reported_gpa', ''),
        'class_rank': student_data.get('class_rank', ''),
        'class_size': student_data.get('class_size', ''),
        'calculated_gpa': gpa_calc.get('calculated_gpa', ''),
        'total_credits': gpa_calc.get('total_credits', ''),
        'courses_included': gpa_calc.get('courses_included', ''),
        'weighted_courses': gpa_calc.get('weighted_courses', ''),
    }
    
    with open(students_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=students_row.keys())
        writer.writeheader()
        writer.writerow(students_row)
    
    # Export courses.csv
    courses = transcript_data.get('courses', [])
    if courses:
        course_fieldnames = [
            'school_year', 'term', 'grade_level', 'course_code', 'course_name',
            'credits_attempted', 'credits_earned', 'final_grade_numeric', 
            'final_grade_letter', 'advanced_course', 'weight_eligible', 
            'include_in_gpa', 'confidence', 'raw_text'
        ]
        
        with open(courses_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=course_fieldnames)
            writer.writeheader()
            
            for course in courses:
                # Flatten semester grades
                semester_grades = course.get('semester_grades', {})
                row = {key: course.get(key, '') for key in course_fieldnames}
                writer.writerow(row)
    
    return [str(students_file), str(courses_file)]


def show_summary(transcript_data: dict):
    """Show parsing summary."""
    click.echo("\n📈 Parsing Summary")
    click.echo("=" * 30)
    
    student = transcript_data.get('student', {})
    courses = transcript_data.get('courses', [])
    gpa_calc = transcript_data.get('gpa_calculation', {})
    
    # Student info
    if student.get('name'):
        click.echo(f"👤 Student: {student['name']}")
    if student.get('school'):
        click.echo(f"🏫 School: {student['school']}")
    
    # GPA info
    if gpa_calc:
        click.echo(f"🎯 Calculated GPA: {gpa_calc.get('calculated_gpa', 'N/A')}")
        if student.get('reported_gpa'):
            reported = student['reported_gpa']
            calculated = gpa_calc.get('calculated_gpa', 0)
            diff = calculated - reported if calculated and reported else 0
            click.echo(f"📄 Reported GPA: {reported}")
            click.echo(f"🔄 Difference: {diff:+.2f}")
    
    # Course stats
    click.echo(f"📚 Total Courses: {len(courses)}")
    if gpa_calc:
        click.echo(f"📋 Included in GPA: {gpa_calc.get('courses_included', 0)}")
        click.echo(f"⚖️  Weighted Courses: {gpa_calc.get('weighted_courses', 0)}")
    
    # Confidence stats
    confidences = [c.get('confidence', 1.0) for c in courses if c.get('confidence')]
    if confidences:
        avg_confidence = sum(confidences) / len(confidences)
        click.echo(f"🎯 Avg Confidence: {avg_confidence:.2f}")
    
    # Parsing notes
    notes = transcript_data.get('parsing_notes', [])
    if notes:
        click.echo("\n📝 Notes:")
        for note in notes:
            click.echo(f"  • {note}")


if __name__ == '__main__':
    main()
