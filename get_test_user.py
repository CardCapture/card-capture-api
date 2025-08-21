#!/usr/bin/env python3
"""
Find an existing user in the database for testing
"""

import os
import sys

# Add the app directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up environment for testing
os.environ['SUPABASE_URL'] = 'https://ftlweumoajawitlszpqx.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ0bHdldW1vYWphd2l0bHN6cHF4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0MzI2NzE2MiwiZXhwIjoyMDU4ODQzMTYyfQ.SEsM-nY72fr_36jAN4Tjj_YL_8T0qOtCyKmV7kxQey8'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = os.environ['SUPABASE_KEY']

from app.core.clients import get_supabase_client

def get_test_user():
    """Find an existing user for testing"""
    print("🔍 Finding test user in database...")
    
    supabase_client = get_supabase_client()
    
    # Get any user
    users_response = supabase_client.table("users").select("id, email").limit(5).execute()
    
    if users_response.data:
        print(f"📋 Found {len(users_response.data)} users:")
        for user in users_response.data:
            print(f"   ID: {user['id']}")
            print(f"   Email: {user.get('email', 'No email')}")
            print()
        
        return users_response.data[0]['id']
    else:
        print("❌ No users found in database")
        return None

if __name__ == "__main__":
    user_id = get_test_user()
    if user_id:
        print(f"✅ Use this user_id for testing: {user_id}")
    else:
        print("❌ No users available for testing")