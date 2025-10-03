#!/usr/bin/env python3
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.core.clients import get_supabase_client

sb = get_supabase_client()

# Check for serial 0324534
print("=" * 70)
print("CHECKING DATABASE FOR SERIAL 0324534")
print("=" * 70)

# Check students table
student = sb.table("students").select("*").eq("serial_number", "0324534").execute()
if student.data:
    s = student.data[0]
    print(f"\n✅ STUDENT RECORD FOUND:")
    print(f"   ID: {s['id']}")
    print(f"   Serial: {s.get('serial_number')}")
    print(f"   Name: {s.get('first_name')} {s.get('last_name')}")
    print(f"   Email: {s.get('email')}")
    print(f"   Cell: {s.get('cell')}")
    print(f"   High School: {s.get('high_school')}")
    print(f"   Major: {s.get('major')}")
else:
    print("\n❌ No student found with serial 0324534")

# Check interactions for this event
event_id = "e42327ef-71b7-4667-a863-2861b158e71b"
school_id = "bf564045-5547-4c5f-91b9-06fe2aaa3448"

interaction = sb.table("student_school_interactions")\
    .select("*")\
    .eq("school_id", school_id)\
    .eq("event_id", event_id)\
    .order("created_at", desc=True)\
    .limit(1)\
    .execute()

if interaction.data:
    i = interaction.data[0]
    print(f"\n✅ INTERACTION RECORD FOUND:")
    print(f"   ID: {i['id']}")
    print(f"   Student ID: {i.get('student_id')}")
    print(f"   Source: {i.get('source_method')}")
    print(f"   Review Status: {i.get('review_status')}")
    print(f"   Fields: {len(i.get('fields', {}))}")
else:
    print(f"\n❌ No interaction found for event {event_id}")

print("\n" + "=" * 70)
