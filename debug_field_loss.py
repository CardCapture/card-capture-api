#!/usr/bin/env python3
"""
Debug script to trace where V3 fields get lost in the process
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.pipeline.pipeline import CardProcessingPipeline
from app.core.clients import get_supabase_client

def debug_field_preservation():
    """Debug where V3 fields are lost"""
    
    print("=== DEBUGGING FIELD PRESERVATION ===")
    
    # Step 1: Run V3 pipeline directly (we know this works)
    pipeline = CardProcessingPipeline()
    
    test_image_path = "test_images/inquiry_card.jpg"
    if not os.path.exists(test_image_path):
        print(f"❌ Test image not found: {test_image_path}")
        return
    
    print("🔄 Running V3 pipeline...")
    result = pipeline.process(
        image_path=test_image_path,
        school_id="b1a2c3d4-e5f6-7890-1234-56789abcdef0",
        user_id="f8714b88-f5c7-404c-b4fa-2304e014a44b",
        event_id="06ecee4e-afb7-4444-bb70-490d93408d13"
    )
    
    print(f"✅ Pipeline completed with {len(result.fields)} fields")
    
    # Step 2: Check critical fields in pipeline result
    critical_fields = ['high_school', 'ceeb_code', 'high_school_validation']
    print(f"\\n🔍 V3 PIPELINE RESULT - CRITICAL FIELDS:")
    
    v3_has_all_fields = True
    for field_name in critical_fields:
        if field_name in result.fields:
            field_data = result.fields[field_name]
            print(f"✅ {field_name}: '{field_data.value}' (source: {field_data.source})")
        else:
            print(f"❌ {field_name}: MISSING")
            v3_has_all_fields = False
    
    if not v3_has_all_fields:
        print("❌ V3 pipeline itself is missing critical fields!")
        return
    
    # Step 3: Test FieldData.to_dict() conversion
    print(f"\\n🔄 Testing FieldData.to_dict() conversion...")
    fields_dict = {}
    for key, field_data in result.fields.items():
        fields_dict[key] = field_data.to_dict()
    
    print(f"✅ Converted to dict format: {len(fields_dict)} fields")
    
    # Check critical fields after conversion
    print(f"\\n🔍 AFTER to_dict() CONVERSION - CRITICAL FIELDS:")
    dict_has_all_fields = True
    for field_name in critical_fields:
        if field_name in fields_dict:
            field_data = fields_dict[field_name]
            print(f"✅ {field_name}: '{field_data.get('value')}' (source: {field_data.get('source')})")
        else:
            print(f"❌ {field_name}: MISSING")
            dict_has_all_fields = False
    
    if not dict_has_all_fields:
        print("❌ Fields lost during to_dict() conversion!")
        return
    
    # Step 4: Test JSON serialization
    print(f"\\n🔄 Testing JSON serialization...")
    try:
        import json
        json_str = json.dumps(fields_dict)
        json_back = json.loads(json_str)
        print(f"✅ JSON serialization successful: {len(json_str)} chars")
        
        # Check critical fields after JSON round-trip
        print(f"\\n🔍 AFTER JSON SERIALIZATION - CRITICAL FIELDS:")
        json_has_all_fields = True
        for field_name in critical_fields:
            if field_name in json_back:
                field_data = json_back[field_name]
                print(f"✅ {field_name}: '{field_data.get('value')}' (source: {field_data.get('source')})")
            else:
                print(f"❌ {field_name}: MISSING")
                json_has_all_fields = False
        
        if not json_has_all_fields:
            print("❌ Fields lost during JSON serialization!")
            return
            
    except Exception as e:
        print(f"❌ JSON serialization failed: {e}")
        return
    
    # Step 5: Test the actual database save structure
    print(f"\\n🔄 Testing database save structure...")
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc).isoformat()
    review_data = {
        "document_id": "test-debug-123",
        "fields": fields_dict,
        "school_id": "b1a2c3d4-e5f6-7890-1234-56789abcdef0",
        "user_id": "f8714b88-f5c7-404c-b4fa-2304e014a44b",
        "event_id": "06ecee4e-afb7-4444-bb70-490d93408d13",
        "image_path": "test_path",
        "trimmed_image_path": None,
        "review_status": result.metadata.get("review_status"),
        "created_at": now,
        "updated_at": now
    }
    
    print(f"✅ Created review_data structure")
    print(f"   Fields count: {len(review_data['fields'])}")
    print(f"   Review status: {review_data['review_status']}")
    
    # Check critical fields in review_data
    print(f"\\n🔍 IN REVIEW_DATA STRUCTURE - CRITICAL FIELDS:")
    review_fields = review_data.get('fields', {})
    for field_name in critical_fields:
        if field_name in review_fields:
            field_data = review_fields[field_name]
            print(f"✅ {field_name}: '{field_data.get('value')}' (source: {field_data.get('source')})")
        else:
            print(f"❌ {field_name}: MISSING")
    
    print(f"\\n🎯 CONCLUSION:")
    print(f"If all checks passed, the issue is NOT in the V3 pipeline or data conversion.")
    print(f"The issue must be in:")
    print(f"1. Race condition (V2 processing overwriting V3 data)")
    print(f"2. Wrong data being passed to update_job_status_with_review")  
    print(f"3. Database transaction issues")
    print(f"4. Frontend data loading issues")

if __name__ == "__main__":
    debug_field_preservation()
