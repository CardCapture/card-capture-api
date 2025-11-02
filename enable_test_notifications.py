#!/usr/bin/env python3
"""
Helper script to enable notifications for a school for testing
"""

import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from app.core.clients import get_supabase_client


def list_schools():
    """List all schools"""
    supabase = get_supabase_client()
    response = supabase.table("schools").select("id, name, notification_email, notifications_enabled").execute()
    return response.data


def enable_notifications(school_id, email):
    """Enable notifications for a school"""
    supabase = get_supabase_client()
    response = supabase.table("schools").update({
        "notification_email": email,
        "notifications_enabled": True
    }).eq("id", school_id).execute()
    return response.data


def main():
    print("=" * 60)
    print("ENABLE NOTIFICATIONS FOR TESTING")
    print("=" * 60)

    schools = list_schools()

    print("\nAvailable schools:")
    for i, school in enumerate(schools, 1):
        status = "✓ Enabled" if school.get('notifications_enabled') else "✗ Disabled"
        email = school.get('notification_email') or "No email"
        print(f"{i}. {school['name']} ({status}, {email})")

    print("\n" + "=" * 60)
    school_num = int(input("Select school number: "))

    if school_num < 1 or school_num > len(schools):
        print("Invalid school number")
        return

    school = schools[school_num - 1]
    print(f"\nSelected: {school['name']}")

    email = input("Enter notification email address: ")

    print(f"\nEnabling notifications for {school['name']}...")
    print(f"Email: {email}")

    result = enable_notifications(school['id'], email)

    if result:
        print("\n✅ Notifications enabled successfully!")
        print(f"School: {school['name']}")
        print(f"Email: {email}")
        print("\nYou can now run the test script: python3 test_notifications.py")
    else:
        print("\n❌ Failed to enable notifications")


if __name__ == "__main__":
    main()
