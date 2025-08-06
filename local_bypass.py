#!/usr/bin/env python3
"""
Local Processing Bypass
Add this to your upload flow to process locally instead of cloud worker.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.worker.worker_v2 import process_job_v2

def process_locally_if_enabled(job_data):
    """
    If LOCAL_PROCESSING=true, process the job immediately instead of sending to cloud worker
    """
    if os.getenv("LOCAL_PROCESSING", "false").lower() == "true":
        print(f"🏠 Processing job {job_data['id']} LOCALLY")
        try:
            process_job_v2(job_data)
            print(f"✅ Local processing completed for job {job_data['id']}")
            return True
        except Exception as e:
            print(f"❌ Local processing failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    return False

# You can add this to your upload service:
def add_to_upload_service():
    """
    Example of how to integrate this into your upload flow
    """
    return """
    # In your upload service, after creating the job:
    
    from local_bypass import process_locally_if_enabled
    
    # Create job normally
    job_data = {...}
    job_response = supabase_client.table("processing_jobs").insert(job_data).execute()
    
    # Check if we should process locally
    if process_locally_if_enabled(job_data):
        # Processed locally, don't trigger cloud worker
        return {"status": "processed_locally", "job_id": job_data["id"]}
    else:
        # Trigger cloud worker as normal
        # ... existing cloud worker trigger code
    """

if __name__ == "__main__":
    print("💡 To enable local processing:")
    print("   export LOCAL_PROCESSING=true")
    print()
    print("📝 Add this to your upload service:")
    print(add_to_upload_service())