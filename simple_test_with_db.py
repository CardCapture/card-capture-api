#!/usr/bin/env python3
"""
Simple test script to process one card and save to database
"""

import os
import sys
import uuid
from datetime import datetime, timezone

# Set up environment
os.environ['SUPABASE_URL'] = 'https://ftlweumoajawitlszpqx.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ0bHdldW1vYWphd2l0bHN6cHF4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0MzI2NzE2MiwiZXhwIjoyMDU4ODQzMTYyfQ.SEsM-nY72fr_36jAN4Tjj_YL_8T0qOtCyKmV7kxQey8'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = os.environ['SUPABASE_KEY']

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.pipeline.pipeline import CardProcessingPipeline
from app.core.clients import get_supabase_client
from app.repositories.uploads_repository import insert_processing_job_db, insert_extracted_data_db
from app.utils.storage import upload_to_supabase_storage_from_path

def main():
    print("🚀 Simple Pipeline Test with Database Save")

    # Your test parameters
    image_path = "test_images/IMG_0571.JPG"
    school_id = "fbad20ac-810c-43aa-8e71-516c3f89f7c7"
    user_id = "dee097cc-5926-4c1b-acec-b50ccb5313c9"
    event_id = "0052a42d-d2df-4386-864b-0867a94388c9"

    print(f"📸 Image: {image_path}")
    print(f"🏫 School: {school_id}")
    print(f"👤 User: {user_id}")
    print(f"🎯 Event: {event_id}")

    # Check if image exists
    if not os.path.exists(image_path):
        print(f"❌ Image not found: {image_path}")
        return

    try:
        # Process with pipeline
        print(f"\n🔄 Processing with Pipeline V3...")
        pipeline = CardProcessingPipeline()
        result = pipeline.process(
            image_path=image_path,
            school_id=school_id,
            user_id=user_id,
            event_id=event_id
        )

        print(f"✅ Pipeline processing complete!")
        print(f"📝 Fields extracted: {len(result.fields)}")

        # Upload image to storage
        print(f"\n📤 Uploading image to storage...")
        supabase_client = get_supabase_client()
        original_filename = os.path.basename(image_path)
        storage_path = upload_to_supabase_storage_from_path(
            supabase_client,
            image_path,
            user_id,
            original_filename
        )
        print(f"✅ Image uploaded: {storage_path}")

        # Generate IDs
        document_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())

        # Create processing job
        print(f"\n📝 Creating processing job...")
        job_data = {
            'id': job_id,
            'document_id': document_id,
            'event_id': event_id,
            'school_id': school_id,
            'user_id': user_id,
            'status': 'complete',
            'image_path': storage_path,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        insert_processing_job_db(supabase_client, job_data)
        print(f"✅ Job created: {job_id}")

        # Prepare fields data
        fields_data = {}
        for field_name, field_data in result.fields.items():
            fields_data[field_name] = {
                "value": field_data.value or "",
                "confidence": field_data.confidence,
                "source": field_data.source,
                "requires_human_review": field_data.requires_human_review,
                "review_notes": field_data.review_notes or "",
                "reviewed": False,
                "enabled": True,
                "required": False,
                "review_confidence": field_data.confidence,
                "bounding_box": getattr(field_data, 'bounding_box', []),
                "actual_field_name": field_name
            }

        # Create extracted data record
        print(f"\n💾 Saving card data...")
        extracted_data = {
            'id': str(uuid.uuid4()),
            'document_id': document_id,
            'job_id': job_id,
            'event_id': event_id,
            'school_id': school_id,
            'user_id': user_id,
            'image_path': storage_path,
            'review_status': 'needs_human_review',
            'fields': fields_data,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        insert_extracted_data_db(supabase_client, extracted_data)

        print(f"🎉 SUCCESS! Card saved to database")
        print(f"📋 Document ID: {document_id}")
        print(f"🔗 View in UI: /events/{event_id}")

        # Show key extracted fields
        print(f"\n📝 Key fields extracted:")
        key_fields = ['first_name', 'last_name', 'email', 'high_school', 'city', 'state']
        for field in key_fields:
            if field in result.fields:
                value = result.fields[field].value or "(empty)"
                print(f"  {field}: {value}")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()