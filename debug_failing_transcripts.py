#!/usr/bin/env python3
"""
Quick debug script to investigate failing transcripts.
Examines why certain transcripts return 0.00 GPA.
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.transcript_parser.gemini_transcript_service import parse_transcript_file

# Failing transcripts
FAILING_TRANSCRIPTS = [
    "Transcripts 2/CASTRO, RICARDO.pdf",
    "Transcripts 2/Gonzalez Otero, Yubell Karely.pdf",
    "Transcripts 2/Vazquez, Victoria Alessandria.pdf",
]


def debug_transcript(filepath: str):
    """Debug a single transcript and show detailed info."""
    print("=" * 80)
    print(f"DEBUGGING: {filepath}")
    print("=" * 80)
    print()

    try:
        result = parse_transcript_file(filepath)

        # Student info
        student = result.get('student', {})
        print(f"Student Name: {student.get('name', 'N/A')}")
        print(f"Reported GPA: {student.get('reported_gpa', 'N/A')}")
        print()

        # Course summary
        courses = result.get('courses', [])
        print(f"Total Courses Extracted: {len(courses)}")
        print()

        # GPA calculation
        gpa_calc = result.get('gpa_calculation', {})
        print("GPA CALCULATION:")
        print(f"  Calculated GPA: {gpa_calc.get('calculated_gpa', 'N/A')}")
        print(f"  Total Credits: {gpa_calc.get('total_credits', 'N/A')}")
        print(f"  Courses Included: {gpa_calc.get('courses_included', 'N/A')}")
        print(f"  Weighted Courses: {gpa_calc.get('weighted_courses', 'N/A')}")
        print()

        # Analyze course inclusion
        included_courses = [c for c in courses if c.get('include_in_gpa', True)]
        excluded_courses = [c for c in courses if not c.get('include_in_gpa', True)]

        print(f"Courses Included in GPA: {len(included_courses)}")
        print(f"Courses Excluded from GPA: {len(excluded_courses)}")
        print()

        if excluded_courses:
            print("EXCLUDED COURSES ANALYSIS:")
            exclusion_reasons = {}
            for course in excluded_courses:
                reason = course.get('exclusion_reason', 'unknown')
                exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1

            for reason, count in exclusion_reasons.items():
                print(f"  {reason}: {count} courses")
            print()

            print("SAMPLE EXCLUDED COURSES (first 5):")
            for course in excluded_courses[:5]:
                print(f"  - {course.get('course_name', 'N/A')}")
                print(f"    Grade: {course.get('final_grade_numeric', 'N/A')}")
                print(f"    Credits: {course.get('credits_earned', 'N/A')}")
                print(f"    Exclusion Reason: {course.get('exclusion_reason', 'N/A')}")
                print(f"    Include in GPA: {course.get('include_in_gpa', 'N/A')}")
                print()

        # Show sample included courses
        if included_courses:
            print("SAMPLE INCLUDED COURSES (first 3):")
            for course in included_courses[:3]:
                print(f"  - {course.get('course_name', 'N/A')}")
                print(f"    Grade: {course.get('final_grade_numeric', 'N/A')}")
                print(f"    Credits: {course.get('credits_earned', 'N/A')}")
                print(f"    Quality Points: {course.get('quality_points', 'N/A')}")
                print()

        # Save full JSON for detailed analysis
        output_file = f"debug_{os.path.basename(filepath).replace('.pdf', '')}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Full JSON saved to: {output_file}")
        print()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        print()


def main():
    """Debug all failing transcripts."""
    print("DEBUGGING FAILING TRANSCRIPTS")
    print("=" * 80)
    print()

    for transcript in FAILING_TRANSCRIPTS:
        debug_transcript(transcript)
        input("Press Enter to continue to next transcript...")
        print("\n\n")


if __name__ == '__main__':
    main()
