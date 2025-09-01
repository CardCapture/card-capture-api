#!/usr/bin/env python3
"""
Process a card through Pipeline V3 and save to database for UI viewing
"""

import os
import sys
import json
import tempfile
import shutil
from datetime import datetime, timezone
import uuid

# Add the app directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up environment for testing
os.environ['SUPABASE_URL'] = 'https://ftlweumoajawitlszpqx.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ0bHdldW1vYWphd2l0bHN6cHF4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0MzI2NzE2MiwiZXhwIjoyMDU4ODQzMTYyfQ.SEsM-nY72fr_36jAN4Tjj_YL_8T0qOtCyKmV7kxQey8'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = os.environ['SUPABASE_KEY']

from app.pipeline.pipeline import CardProcessingPipeline
from app.core.clients import get_supabase_client
from app.repositories.processing_jobs_repository import insert_processing_job
from app.repositories.uploads_repository import update_job_status_with_review
from app.services.uploads_service import upload_to_supabase_storage_from_path

def process_card_for_ui():
    """Process a card through Pipeline V3 and save to database for UI viewing"""
    print("🚀 Processing Card Through Pipeline V3 for UI")
    print("=" * 60)
    
    # Select a test card
    test_image = "test_images/page_19.png"  # Alina's card - testing high confidence Google Maps
    
    if not os.path.exists(test_image):
        print(f"❌ Test image not found: {test_image}")
        return None
    
    print(f"📸 Using test image: {test_image}")
    
    # Generate test parameters
    school_id = "b1a2c3d4-e5f6-7890-1234-56789abcdef0"  # Your test school
    user_id = "f8714b88-f5c7-404c-b4fa-2304e014a44b"  # Use existing valid user ID
    event_id = "06ecee4e-afb7-4444-bb70-490d93408d13"  # Use the correct event ID for UI visibility
    
    print(f"🎯 Processing with:")
    print(f"   School ID: {school_id}")
    print(f"   User ID: {user_id}")
    print(f"   Event ID: {event_id}")
    
    # Create job in database
    supabase_client = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    
    # Actually upload the image to Supabase storage
    print(f"\n📤 Uploading image to Supabase storage...")
    try:
        storage_path = upload_to_supabase_storage_from_path(
            supabase_client,
            test_image,
            user_id,
            os.path.basename(test_image)
        )
        print(f"✅ Image uploaded to storage: {storage_path}")
    except Exception as e:
        print(f"❌ Failed to upload image: {str(e)}")
        return None
    
    print(f"\n📋 Creating processing job in database...")
    job_data = {
        "file_url": storage_path,  # Use the actual storage path
        "user_id": user_id,
        "school_id": school_id,
        "event_id": event_id,
        "status": "complete",  # Set to complete to prevent trigger from firing
        "created_at": now,
        "updated_at": now
    }
    
    job_response = insert_processing_job(supabase_client, job_data)
    job = job_response.data[0]
    job_id = job["id"]
    
    print(f"✅ Created job: {job_id}")
    
    # Process through Pipeline V3
    print(f"\n🔄 Processing through Pipeline V3...")
    pipeline = CardProcessingPipeline()
    
    try:
        result = pipeline.process(
            image_path=test_image,
            school_id=school_id,
            user_id=user_id,
            event_id=event_id
        )
        
        print(f"✅ Pipeline processing completed!")
        print(f"   Fields extracted: {len(result.fields)}")
        print(f"   Review status: {result.metadata.get('review_status', 'unknown')}")
        

        
        # Convert result to database format (same as worker_v3)
        fields_dict = {}
        for key, field_data in result.fields.items():
            fields_dict[key] = field_data.to_dict()
        
        # Create review data in the same format as worker_v3
        print(f"\n💾 Saving results to database...")
        now = datetime.now(timezone.utc).isoformat()
        review_data = {
            "document_id": job_id,
            "fields": fields_dict,
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": storage_path,  # Use the actual storage path where image was uploaded
            "review_status": result.metadata.get("review_status"),
            "created_at": now,
            "updated_at": now
        }
        
        # Save using the same method as worker_v3
        update_job_status_with_review(supabase_client, job_id, "complete", review_data)
        
        print(f"✅ Results saved to database!")
        print(f"\n🎉 SUCCESS! Card processed through Pipeline V3")
        print(f"\n📋 Job Details:")
        print(f"   Job ID: {job_id}")
        print(f"   User ID: {user_id}")
        print(f"   School ID: {school_id}")
        print(f"   Status: complete")
        print(f"   Fields: {len(fields_dict)}")
        print(f"   Review Status: {result.metadata.get('review_status')}")
        
        # Show some key fields
        print(f"\n📝 Sample Extracted Fields:")
        key_fields = ['first_name', 'last_name', 'email', 'high_school', 'ceeb_code', 'address']
        for field_name in key_fields:
            if field_name in fields_dict:
                field_data = fields_dict[field_name]
                print(f"   {field_name}: '{field_data.get('value')}' (confidence: {field_data.get('confidence', 0):.2f})")
        
        print(f"\n🌐 You should now be able to view this card in your UI!")
        print(f"   Look for job ID: {job_id}")
        print(f"   Or user ID: {user_id}")
        print(f"   Data is in both 'processing_jobs' and 'reviewed_data' tables")
        
        return {
            "job_id": job_id,
            "user_id": user_id,
            "school_id": school_id,
            "status": "complete",
            "pipeline_version": "v3",
            "fields_count": len(fields_dict),
            "review_status": result.metadata.get('review_status')
        }
        
    except Exception as e:
        print(f"\n❌ Pipeline processing failed: {str(e)}")
        
        # Update job with error using correct repository function
        from app.repositories.processing_jobs_repository import update_processing_job
        update_processing_job(supabase_client, job_id, {
            "status": "failed",
            "error_message": str(e),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    result = process_card_for_ui()
    
    if result:
        print(f"\n✨ Card successfully processed and saved to database!")
        print(f"   Check your UI for job: {result['job_id']}")
    else:
        print(f"\n💥 Processing failed - check the logs above")