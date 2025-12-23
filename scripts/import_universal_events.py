"""
Import TACROA events from CSV into universal_events table.

Usage:
    python scripts/import_universal_events.py [--dry-run] [--file path/to/csv]

Options:
    --dry-run       Print what would be imported without actually inserting
    --file          Path to CSV file (default: TACROA Events - All Events.csv)
"""

import csv
import os
import re
import sys
from datetime import datetime, time
from typing import Optional, Dict, List
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)


def get_supabase_client() -> Client:
    """Create Supabase client from environment variables."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    return create_client(url, key)


def parse_date(date_str: str) -> Optional[str]:
    """
    Parse date string like 'Monday, September 08, 2025' to 'YYYY-MM-DD'.
    Returns None if parsing fails.
    """
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()

    # Remove ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)
    date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)

    # Fix common typos
    date_str = date_str.replace('Septmber', 'September')
    date_str = date_str.replace('Ocotber', 'October')
    date_str = date_str.replace('Novemeber', 'November')

    # Normalize format - add comma after day name if missing
    date_str = re.sub(r'^(\w+)\s+(\w+)', r'\1, \2', date_str)
    # Fix double commas that might result
    date_str = date_str.replace(',,', ',')

    # Remove the day name prefix if present
    formats = [
        "%A, %B %d, %Y",      # Monday, September 08, 2025
        "%A, %B %d",          # Monday, September 22 (assume 2025)
        "%B %d, %Y",          # September 08, 2025
        "%B %d %Y",           # September 08 2025
        "%m/%d/%Y",           # 09/08/2025
        "%Y-%m-%d",           # 2025-09-08
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            # If year is 1900 (default), use 2025
            if parsed.year == 1900:
                parsed = parsed.replace(year=2025)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def parse_time(time_str: str) -> Optional[str]:
    """
    Parse time string like '9:00:00 AM' to 'HH:MM:SS'.
    Returns None if parsing fails.
    """
    if not time_str or not time_str.strip():
        return None

    time_str = time_str.strip()

    formats = [
        "%I:%M:%S %p",    # 9:00:00 AM
        "%I:%M %p",       # 9:00 AM
        "%H:%M:%S",       # 09:00:00
        "%H:%M",          # 09:00
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(time_str, fmt)
            return parsed.strftime("%H:%M:%S")
        except ValueError:
            continue

    return None


def is_region_header(row: Dict) -> tuple[bool, str]:
    """
    Check if a row is a region header (e.g., 'DALLAS I (September 8-12, 2025)').
    Returns (is_header, region_name).
    """
    fair_name = row.get('Fair Name', '').strip()

    # Region headers have only the first column filled, rest are empty
    other_cols = [
        row.get('Fair Date', ''),
        row.get('Fair Location', ''),
        row.get('Fair Address (Street Address)', ''),
    ]

    if fair_name and all(not col.strip() for col in other_cols):
        # Extract region name (remove the date range in parentheses)
        region = re.sub(r'\s*\([^)]+\)\s*$', '', fair_name).strip()
        return True, region

    return False, ''


def is_cancelled(fair_name: str) -> bool:
    """Check if an event is cancelled."""
    return 'CANCELLED' in fair_name.upper() or 'CANCELED' in fair_name.upper()


def clean_phone(phone: str) -> str:
    """Clean up phone number formatting."""
    if not phone:
        return ''
    return phone.strip()


def clean_text(text: str) -> str:
    """Clean up text field (trim, remove Windows line endings)."""
    if not text:
        return ''
    return text.strip().replace('\r', '')


def parse_csv_row(row: Dict, current_region: str) -> Optional[Dict]:
    """
    Parse a CSV row into a universal_events record.
    Returns None if the row should be skipped.
    """
    fair_name = clean_text(row.get('Fair Name', ''))
    fair_date_str = clean_text(row.get('Fair Date', ''))

    # Skip empty rows
    if not fair_name:
        return None

    # Skip cancelled events
    if is_cancelled(fair_name):
        print(f"  Skipping cancelled: {fair_name}")
        return None

    # Parse date
    event_date = parse_date(fair_date_str)
    if not event_date:
        print(f"  Skipping (no valid date): {fair_name} - date: '{fair_date_str}'")
        return None

    # Parse times
    start_time = parse_time(clean_text(row.get('Fair Start Time', '')))
    end_time = parse_time(clean_text(row.get('Fair End Time', '')))

    # Build the record
    record = {
        'name': fair_name,
        'event_date': event_date,
        'start_time': start_time,
        'end_time': end_time,
        'location': clean_text(row.get('Fair Location', '')),
        'address': clean_text(row.get('Fair Address (Street Address)', '')),
        'city': clean_text(row.get('Fair Address (City)', '')),
        'state': 'TX',
        'zip': clean_text(row.get('Fair Address (Zip)', '')),
        'student_population': clean_text(row.get('Student Population (FR, TR)', '')),
        'contact_name': clean_text(row.get('Fair Contact Name', '')),
        'contact_email': clean_text(row.get('Fair Contact Email', '')),
        'contact_phone': clean_phone(row.get('Fair Contact Phone Number', '')),
        'contact_name_secondary': clean_text(row.get('Fair Contact Name (Secondary)', '')),
        'contact_email_secondary': clean_text(row.get('Fair Contact Email (Secondary)', '')),
        'contact_phone_secondary': clean_phone(row.get('Fair Contact Phone Number (Secondary)', '')),
        'registration_url': clean_text(row.get('Registration URL (if using their own)', '')),
        'region': current_region,
        'status': 'active',
        'metadata': {}
    }

    # Remove empty optional fields
    for key in ['start_time', 'end_time', 'location', 'address', 'city', 'zip',
                'student_population', 'contact_name', 'contact_email', 'contact_phone',
                'contact_name_secondary', 'contact_email_secondary', 'contact_phone_secondary',
                'registration_url']:
        if not record[key]:
            record[key] = None

    return record


def parse_csv_file(filepath: str) -> List[Dict]:
    """
    Parse the TACROA events CSV file.
    Returns list of event records.
    """
    events = []
    current_region = ''

    # Read with Windows line endings handling
    with open(filepath, 'r', encoding='utf-8-sig', newline='') as f:
        # Skip potential BOM and read content
        content = f.read().replace('\r\n', '\n').replace('\r', '\n')

    # Parse CSV from string
    lines = content.strip().split('\n')
    reader = csv.DictReader(lines[1:], fieldnames=[
        'Fair Name', 'Fair Date', 'Fair Start Time', 'Fair End Time',
        'Fair Location', 'Student Population (FR, TR)',
        'Fair Address (Street Address)', 'Fair Address (City)',
        'Fair Address (Zip)', 'Fair Contact Name', 'Fair Contact Email',
        'Fair Contact Phone Number', 'Fair Contact Name (Secondary)',
        'Fair Contact Email (Secondary)', 'Fair Contact Phone Number (Secondary)',
        'Registration URL (if using their own)', 'Extra'
    ])

    # First line might be a region header
    first_line = lines[0].split(',')[0].strip().strip('"')
    if first_line and '(' in first_line:
        current_region = re.sub(r'\s*\([^)]+\)\s*$', '', first_line).strip()
        print(f"Initial region: {current_region}")

    for row in reader:
        # Check if this is a region header
        is_header, region = is_region_header(row)
        if is_header:
            current_region = region
            print(f"Region: {current_region}")
            continue

        # Parse the event row
        event = parse_csv_row(row, current_region)
        if event:
            events.append(event)

    return events


def import_events(events: List[Dict], dry_run: bool = False) -> int:
    """
    Import events into the universal_events table.
    Returns count of imported events.
    """
    if dry_run:
        print(f"\n=== DRY RUN: Would import {len(events)} events ===\n")
        for i, event in enumerate(events[:10], 1):
            print(f"{i}. {event['name']} ({event['event_date']}) - {event['city']}, {event['state']}")
        if len(events) > 10:
            print(f"... and {len(events) - 10} more events")
        return len(events)

    # Connect to Supabase
    client = get_supabase_client()

    print(f"\n=== Importing {len(events)} events ===\n")

    imported = 0
    errors = 0

    # Insert in batches of 50
    batch_size = 50
    for i in range(0, len(events), batch_size):
        batch = events[i:i + batch_size]
        try:
            result = client.table('universal_events').insert(batch).execute()
            imported += len(batch)
            print(f"Imported batch {i // batch_size + 1}: {len(batch)} events")
        except Exception as e:
            print(f"Error importing batch {i // batch_size + 1}: {e}")
            errors += len(batch)
            # Try inserting one by one to find the problematic record
            for event in batch:
                try:
                    client.table('universal_events').insert(event).execute()
                    imported += 1
                except Exception as e2:
                    print(f"  Failed: {event['name']} - {e2}")

    print(f"\n=== Import Complete ===")
    print(f"Successfully imported: {imported}")
    print(f"Errors: {errors}")

    return imported


def main():
    parser = argparse.ArgumentParser(description='Import TACROA events into universal_events table')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be imported without actually inserting')
    parser.add_argument('--file', type=str, default=None, help='Path to CSV file')
    args = parser.parse_args()

    # Find the CSV file
    if args.file:
        csv_path = args.file
    else:
        # Look in common locations
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)

        possible_paths = [
            os.path.join(project_root, 'TACROA Events - All Events.csv'),
            os.path.join(project_root, 'TACROA_Events.csv'),
        ]

        csv_path = None
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break

        if not csv_path:
            print("Error: Could not find TACROA events CSV file")
            print(f"Looked in: {possible_paths}")
            sys.exit(1)

    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)

    print(f"Parsing CSV: {csv_path}")
    events = parse_csv_file(csv_path)
    print(f"\nFound {len(events)} valid events")

    # Import events
    import_events(events, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
