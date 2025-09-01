#!/usr/bin/env python3
"""
Debug script to test pipeline processing and examine what fields are created vs saved
"""
import os
import tempfile
from datetime import datetime, timezone

from app.pipeline.pipeline import CardProcessingPipeline
from app.repositories.uploads_repository import update_job_status_with_review
from app.core.clients import get_supabase_client

def main():
    print("=== TESTING PIPELINE FIELD CREATION AND SAVE ===")
    
    # First, get a valid school ID from the database
    supabase_client = get_supabase_client()
    schools_response = supabase_client.table("schools").select("id, name").limit(1).execute()
    
    if not schools_response.data:
        print("No schools found in database")
        return
    
    school_id = schools_response.data[0]['id']
    school_name = schools_response.data[0]['name']
    print(f"Using school: {school_name} ({school_id})")
    
    # Initialize pipeline
    pipeline = CardProcessingPipeline()
    
    # Test image path  
    image_path = "/Users/kregboyd/Applications/card-capture-api/test_images/page_31.png"
    
    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return
    
    print(f"Processing image: {image_path}")
    
    # Process through pipeline
    result = pipeline.process(
        image_path=image_path,
        school_id=school_id,
        user_id="f8714b88-f5c7-404c-b4fa-2304e014a44b",
        event_id=str(uuid.uuid4())
    )
    
    print(f"\n=== PIPELINE RESULT ===")
    print(f"Stage: {result.stage.value}")
    print(f"Field count: {len(result.fields)}")
    print(f"Review status: {result.metadata.get('review_status')}")
    
    print(f"\n=== PIPELINE FIELDS ===")
    target_fields = ['name', 'first_name', 'last_name', 'high_school', 'ceeb_code']
    
    for field_name in target_fields:
        if field_name in result.fields:
            field_data = result.fields[field_name]
            print(f"✅ {field_name}: '{field_data.value}' (source: {field_data.source}, conf: {field_data.confidence:.2f})")
        else:
            print(f"❌ {field_name}: NOT FOUND")
    
    print(f"\n=== ALL PIPELINE FIELDS ===")
    for field_name, field_data in result.fields.items():
        print(f"{field_name}: '{field_data.value}' (source: {field_data.source})")
    
    # Convert to dict format (what gets saved)
    fields_dict = {}
    for key, field_data in result.fields.items():
        fields_dict[key] = field_data.to_dict()
    
    print(f"\n=== CONVERTED FIELDS DICT ===")
    for field_name in target_fields:
        if field_name in fields_dict:
            field_data = fields_dict[field_name]
            print(f"✅ {field_name}: '{field_data['value']}' (source: {field_data['source']}, conf: {field_data['confidence']:.2f})")
        else:
            print(f"❌ {field_name}: NOT FOUND")
    
    print(f"\n=== DICT KEYS ===")
    print(f"Fields dict has {len(fields_dict)} keys: {list(fields_dict.keys())}")
    
    # Test what would be saved (without actually saving)
    import uuid
    test_document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    review_data = {
        "document_id": test_document_id,
        "fields": fields_dict,
        "school_id": "test-school",
        "user_id": "f8714b88-f5c7-404c-b4fa-2304e014a44b",
        "event_id": "test-event",
        "image_path": image_path,
        "trimmed_image_path": None,
        "review_status": result.metadata.get("review_status"),
        "created_at": now,
        "updated_at": now
    }
    
    print(f"\n=== REVIEW DATA TO SAVE ===")
    print(f"Document ID: {review_data['document_id']}")
    print(f"Fields count: {len(review_data['fields'])}")
    print(f"Review status: {review_data['review_status']}")
    
    print(f"\n=== TARGET FIELDS IN REVIEW DATA ===")
    for field_name in target_fields:
        if field_name in review_data['fields']:
            field_data = review_data['fields'][field_name]
            print(f"✅ {field_name}: '{field_data['value']}'")
        else:
            print(f"❌ {field_name}: NOT IN REVIEW DATA")
    
    # Actually save to database to test the full flow
    print(f"\n=== TESTING ACTUAL DATABASE SAVE ===")
    try:
        supabase_client = get_supabase_client()
        save_result = update_job_status_with_review(supabase_client, test_document_id, "complete", review_data)
        print("✅ Successfully saved to database")
        
        # Query back to verify
        verification = supabase_client.table("reviewed_data").select("*").eq("document_id", test_document_id).single().execute()
        if verification.data:
            saved_fields = verification.data['fields']
            print(f"\n=== VERIFICATION: FIELDS SAVED TO DATABASE ===")
            for field_name in target_fields:
                if field_name in saved_fields:
                    field_data = saved_fields[field_name]
                    print(f"✅ {field_name}: '{field_data['value']}' (source: {field_data.get('source')})")
                else:
                    print(f"❌ {field_name}: NOT SAVED TO DATABASE")
        else:
            print("❌ Failed to retrieve saved record for verification")
            
    except Exception as e:
        print(f"❌ Database save failed: {str(e)}")
        
    # Clean up test record
    try:
        supabase_client.table("reviewed_data").delete().eq("document_id", test_document_id).execute()
        print(f"\n✅ Cleaned up test record: {test_document_id}")
    except:
        pass

if __name__ == "__main__":
    main()