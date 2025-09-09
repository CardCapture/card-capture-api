#!/usr/bin/env python3
"""
Create trusted_devices table in Supabase staging database
"""
import psycopg2
from psycopg2.extras import RealDictCursor

# Staging database connection string from .env
DATABASE_URL = "postgresql://postgres:7b4Mk4tm43J.DKM@db.ftlweumoajawitlszpqx.supabase.co:5432/postgres"

# SQL to create the table
sql = """
-- Create trusted_devices table for MFA device trust
CREATE TABLE IF NOT EXISTS public.trusted_devices (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    device_token_hash VARCHAR(255) NOT NULL,
    device_name VARCHAR(255),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, device_token_hash)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_trusted_devices_user_id ON public.trusted_devices(user_id);
CREATE INDEX IF NOT EXISTS idx_trusted_devices_token_hash ON public.trusted_devices(device_token_hash);

-- Enable Row Level Security
ALTER TABLE public.trusted_devices ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist
DROP POLICY IF EXISTS "Users can manage their own trusted devices" ON public.trusted_devices;
DROP POLICY IF EXISTS "Service role can manage all trusted devices" ON public.trusted_devices;

-- Create policy to allow users to manage their own trusted devices
CREATE POLICY "Users can manage their own trusted devices" ON public.trusted_devices
    FOR ALL 
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Create policy for service role to manage all trusted devices
CREATE POLICY "Service role can manage all trusted devices" ON public.trusted_devices
    FOR ALL 
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
"""

def main():
    conn = None
    cursor = None
    try:
        print("Connecting to staging database...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        print("Creating trusted_devices table...")
        cursor.execute(sql)
        conn.commit()
        print("✅ Table created successfully!")
        
        # Verify table exists
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'trusted_devices'
            ORDER BY ordinal_position;
        """)
        
        columns = cursor.fetchall()
        print("\n✅ Table structure:")
        for col in columns:
            print(f"  - {col[0]}: {col[1]}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("\nMigration complete!")

if __name__ == "__main__":
    main()