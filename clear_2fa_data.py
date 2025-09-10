#!/usr/bin/env python3
"""
Clear 2FA data for kreg@cardcapture.io in staging database
"""
import os
from supabase import create_client, Client

# Staging Supabase configuration
SUPABASE_URL = "https://ftlweumoajawitlszpqx.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ0bHdldW1vYWphd2l0bHN6cHF4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0MzI2NzE2MiwiZXhwIjoyMDU4ODQzMTYyfQ.SEsM-nY72fr_36jAN4Tjj_YL_8T0qOtCyKmV7kxQey8"

def main():
    # Create Supabase client with service role key
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    try:
        # Find kreg@cardcapture.io user
        print("Finding user kreg@cardcapture.io...")
        auth_response = supabase.auth.admin.list_users()
        
        user_id = None
        for user in auth_response:
            if user.email == "kreg@cardcapture.io":
                user_id = user.id
                print(f"Found user: {user.email} with ID: {user_id}")
                break
        
        if not user_id:
            print("User kreg@cardcapture.io not found!")
            return
        
        # Clear trusted devices
        print("Clearing trusted devices...")
        trusted_devices_result = supabase.table('trusted_devices').delete().eq('user_id', user_id).execute()
        print(f"Deleted {len(trusted_devices_result.data) if trusted_devices_result.data else 0} trusted devices")
        
        # Clear MFA settings
        print("Clearing MFA settings...")
        mfa_settings_result = supabase.table('user_mfa_settings').delete().eq('user_id', user_id).execute()
        print(f"Deleted {len(mfa_settings_result.data) if mfa_settings_result.data else 0} MFA settings")
        
        # Clear any MFA factors using admin API
        print("Clearing MFA factors...")
        try:
            factors = supabase.auth.admin.mfa.list_factors(user_id)
            for factor in factors:
                supabase.auth.admin.mfa.delete_factor(factor.id)
                print(f"Deleted MFA factor: {factor.id}")
        except Exception as e:
            print(f"Note: Could not clear MFA factors via admin API: {e}")
        
        print("✅ Successfully cleared all 2FA data for kreg@cardcapture.io")
        print("You can now test 2FA enrollment from scratch!")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()