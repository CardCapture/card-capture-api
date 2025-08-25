#!/usr/bin/env python3
"""
Debug script to monitor exactly what gets written to the database
"""
import sys
import os
import uuid
from datetime import datetime, timezone
import time

sys.path.insert(0, os.path.dirname(__file__))

from app.core.clients import get_supabase_client
from app.services.uploads_service import upload_to_supabase_storage_from_path
from app.worker.worker_unified import process_job_unified

DEFAULT_USER_ID = "f8714b88-f5c7-404c-b4fa-2304e014a44b"
DEFAULT_EVENT_ID = "06ecee4e-afb7-4444-bb70-490d93408d13" 
DEFAULT_SCHOOL_ID = "b1a2c3d4-e5f6-7890-1234-56789abcdef0"

def monitor_database_writes():
    """Monitor what gets written to the database during processing"""
    
    # Read file path from stdin or use default
    try:
        file_path = input().strip()
        print(f"📁 Using file from stdin: {file_path}")
    except EOFError:
        file_path = "test_images/inquiry_card.jpg"
        print(f"📁 Using default file: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return
    
    print(f"✅ Found file: {file_path}")
    
    # Upload file to Supabase storage
    print("\n📤 Uploading to Supabase storage...")
    supabase_client = get_supabase_client()
    
    storage_path = upload_to_supabase_storage_from_path(
        supabase_client,
        file_path,
        DEFAULT_USER_ID,
        os.path.basename(file_path)
    )
    
    print(f"✅ Uploaded to: {storage_path}")
    
    # Create a new processing job
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    job_data = {
        "id": job_id,
        "status": "queued",
        "school_id": DEFAULT_SCHOOL_ID,
        "user_id": DEFAULT_USER_ID,
        "event_id": DEFAULT_EVENT_ID,
        "file_url": storage_path,
        "created_at": now,
        "updated_at": now
    }
    
    print(f"\n📝 Creating processing job: {job_id}")
    job_response = supabase_client.table("processing_jobs").insert(job_data).execute()
    
    if not job_response.data:
        print("❌ Failed to create job")
        return
    
    print("✅ Job created successfully")
    
    # MONITOR: Check database BEFORE processing
    print(f"\n🔍 BEFORE PROCESSING - Database State:")
    try:
        before_reviewed = supabase_client.table("reviewed_data").select("document_id").eq("document_id", job_id).execute()
        if before_reviewed.data:
            print(f"   Reviewed Data EXISTS")
        else:
            print("   Reviewed Data: NONE")
    except Exception as e:
        print(f"   Reviewed Data: NONE (query error: {e})")
    
    # Call the unified worker
    print(f"\n🚀 Calling unified worker...")
    start_time = time.time()
    
    try:
        process_job_unified(job_data)
        end_time = time.time()
        print(f"✅ Unified worker completed in {end_time - start_time:.2f} seconds")
    except Exception as e:
        print(f"❌ Unified worker failed: {e}")
        return
    
    # MONITOR: Check database AFTER processing
    print(f"\n🔍 AFTER PROCESSING - Database State:")
    
    # Check processing_jobs table
    job_check = supabase_client.table("processing_jobs").select("*").eq("id", job_id).single().execute()
    if job_check.data:
        job = job_check.data
        print(f"   Job Status: {job['status']}")
        if job.get('error_message'):
            print(f"   Job Error: {job['error_message']}")
    
    # Check reviewed_data table  
    try:
        after_reviewed = supabase_client.table("reviewed_data").select("document_id, review_status, fields").eq("document_id", job_id).execute()
        if after_reviewed.data:
            record = after_reviewed.data[0]
            fields = record.get('fields', {})
            print(f"   Reviewed Data: {len(fields)} fields")
            print(f"   Review Status: {record.get('review_status')}")
            print(f"   Has ceeb_code: {'ceeb_code' in fields}")
            print(f"   Has high_school_validation: {'high_school_validation' in fields}")
            
            if 'high_school' in fields:
                hs_field = fields['high_school']
                print(f"   High School: '{hs_field.get('value')}' (source: {hs_field.get('source')})")
            
            if 'ceeb_code' in fields:
                ceeb_field = fields['ceeb_code'] 
                print(f"   CEEB Code: '{ceeb_field.get('value')}' (source: {ceeb_field.get('source')})")
            
            if 'high_school_validation' in fields:
                validation_field = fields['high_school_validation']
                print(f"   Validation: '{validation_field.get('value')}' (source: {validation_field.get('source')})")
                
            # Check if this looks like V2 or V3 data
            v2_indicators = 0
            v3_indicators = 0
            
            for field_name, field_data in fields.items():
                source = field_data.get('source', '')
                if source == 'gemini':
                    v2_indicators += 1
                elif source in ['high_school_directory', 'high_school_directory_verified', 'high_school_matcher']:
                    v3_indicators += 1
            
            print(f"   Pipeline Indicators: V2={v2_indicators}, V3={v3_indicators}")
            if v3_indicators > 0:
                print(f"   🎯 This looks like V3 OUTPUT!")
            elif v2_indicators > 0:
                print(f"   🎯 This looks like V2 OUTPUT!")
            else:
                print(f"   🤔 Unknown pipeline output")
                
        else:
            print("   Reviewed Data: NONE")
    except Exception as e:
        print(f"   Reviewed Data: ERROR - {e}")
    
    print(f"\\n🏁 Monitoring complete for job: {job_id}")

if __name__ == "__main__":
    monitor_database_writes()
