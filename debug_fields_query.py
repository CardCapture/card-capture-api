#!/usr/bin/env python3
"""
Debug script to check what fields are actually saved in the database
"""
import json
from app.core.clients import get_supabase_client

def main():
    print("=== CHECKING SAVED FIELDS IN DATABASE ===")
    
    supabase_client = get_supabase_client()
    
    # Look for recent records and examine the most recent one
    recent_response = supabase_client.table("reviewed_data").select("*").order("created_at", desc=True).limit(1).execute()
    
    if not recent_response.data:
        print("No records found in reviewed_data table")
        return
    
    # Get the most recent record
    record = recent_response.data[0]
    document_id = record['document_id']
    print(f"Examining most recent record: {document_id}")
    print(f"Created: {record['created_at']}")
    print(f"Review status: {record['review_status']}")
    print()
    
    fields = record.get('fields', {})
    
    print(f"Record found with {len(fields)} fields:")
    print(f"Review status: {record.get('review_status')}")
    print()
    
    # Print all fields with their details
    for field_name, field_data in fields.items():
        if isinstance(field_data, dict):
            value = field_data.get('value', '')
            source = field_data.get('source', '')
            confidence = field_data.get('confidence', 0)
            print(f"{field_name}: '{value}' (source: {source}, conf: {confidence:.2f})")
        else:
            print(f"{field_name}: {field_data} (raw value)")
    
    print()
    print("=== CHECKING FOR SPECIFIC FIELDS ===")
    target_fields = ['first_name', 'last_name', 'ceeb_code', 'high_school', 'name']
    
    for field_name in target_fields:
        if field_name in fields:
            field_data = fields[field_name]
            if isinstance(field_data, dict):
                print(f"✅ {field_name}: '{field_data.get('value')}' (source: {field_data.get('source')}, conf: {field_data.get('confidence'):.2f})")
            else:
                print(f"✅ {field_name}: {field_data} (raw)")
        else:
            print(f"❌ {field_name}: NOT FOUND")

if __name__ == "__main__":
    main()