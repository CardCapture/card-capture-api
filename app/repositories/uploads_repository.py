from datetime import datetime, timezone
from typing import Dict, Any
from fastapi import HTTPException
from app.utils.db_utils import (
    db_transaction,
    ensure_atomic_updates,
    safe_db_operation,
    validate_db_response,
    handle_db_error
)

@safe_db_operation("Insert processing job")
def insert_processing_job_db(supabase_client, job_data: Dict[str, Any]):
    """Insert a new processing job with proper error handling."""
    return supabase_client.table("processing_jobs").insert(job_data).execute()

@safe_db_operation("Insert extracted data")
def insert_extracted_data_db(supabase_client, data: Dict[str, Any]):
    """Insert extracted data with proper error handling."""
    return supabase_client.table("extracted_data").insert(data).execute()

@safe_db_operation("Get extracted data image")
def select_extracted_data_image_db(supabase_client, document_id: str):
    """Get extracted data image path with proper error handling."""
    return supabase_client.table("extracted_data").select("image_path, trimmed_image_path").eq("document_id", document_id).single().execute()

@ensure_atomic_updates(["processing_jobs", "extracted_data"])
def create_processing_job_with_data(supabase_client, job_data: Dict[str, Any], extracted_data: Dict[str, Any]):
    """
    Atomically create a processing job and its associated extracted data.
    If either operation fails, both are rolled back.
    """
    # Insert processing job
    job_response = supabase_client.table("processing_jobs").insert(job_data).execute()
    if not validate_db_response(job_response, "Insert processing job"):
        raise HTTPException(status_code=500, detail="Failed to create processing job")
        
    # Insert extracted data
    data_response = supabase_client.table("extracted_data").insert(extracted_data).execute()
    if not validate_db_response(data_response, "Insert extracted data"):
        raise HTTPException(status_code=500, detail="Failed to create extracted data")
        
    return {
        "job": job_response.data[0] if job_response.data else None,
        "data": data_response.data[0] if data_response.data else None
    }

@ensure_atomic_updates(["processing_jobs", "reviewed_data"])
def update_job_status_with_review(
    supabase_client,
    job_id: str,
    status: str,
    review_data: Dict[str, Any]
):
    """
    Update job status and create/update reviewed data in a transaction
    """
    print(f"[DATABASE DEBUG] === UPDATE JOB STATUS WITH REVIEW ===")
    print(f"[DATABASE DEBUG] Job ID: {job_id}")
    print(f"[DATABASE DEBUG] Status: {status}")
    
    # 🔍 JSON VALIDATION: Check for corruption before database operations
    critical_fields = ["cell", "date_of_birth"]
    print(f"[DATABASE DEBUG] 🔍 JSON VALIDATION - CRITICAL FIELDS:")
    
    try:
        # Serialize and deserialize to check for JSON corruption
        import json
        serialized = json.dumps(review_data)
        deserialized = json.loads(serialized)
        
        # Check for critical fields in the JSON
        fields_data = review_data.get('fields', {})
        for field_name in critical_fields:
            if field_name in fields_data:
                field_data = fields_data[field_name]
                print(f"[DATABASE DEBUG]   - {field_name}: value='{field_data.get('value')}', type={type(field_data.get('value'))}")
                
                # Check for JSON corruption indicators
                field_str = json.dumps(field_data)
                if '{{' in field_str or '}}' in field_str:
                    print(f"[DATABASE DEBUG] 🚨 JSON CORRUPTION DETECTED in {field_name}: {field_str[:200]}...")
                if field_str.count('{') != field_str.count('}'):
                    print(f"[DATABASE DEBUG] 🚨 BRACE MISMATCH in {field_name}: {field_str.count('{')} opening vs {field_str.count('}')} closing")
            else:
                print(f"[DATABASE DEBUG]   - {field_name}: FIELD_NOT_FOUND")
                
        print(f"[DATABASE DEBUG] JSON validation passed - serialized length: {len(serialized)}")
        
    except Exception as e:
        print(f"[DATABASE DEBUG] 🚨 JSON VALIDATION FAILED: {str(e)}")
        # Log the raw data that's causing issues
        print(f"[DATABASE DEBUG] Raw review_data type: {type(review_data)}")
        print(f"[DATABASE DEBUG] Raw fields keys: {list(review_data.get('fields', {}).keys()) if isinstance(review_data.get('fields'), dict) else 'NOT_DICT'}")
    
    # Update job status first
    job_response = supabase_client.table("processing_jobs").update({
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", job_id).execute()
    
    # Then upsert review data 
    print(f"[DATABASE DEBUG] About to upsert reviewed_data...")
    print(f"[DATABASE DEBUG] 🔍 CRITICAL: Upserting with review_status = {review_data.get('review_status')}")
    print(f"[DATABASE DEBUG] 🔍 CRITICAL: Document ID = {review_data.get('document_id')}")
    
    # Check if this is an UPDATE or INSERT
    existing = supabase_client.table("reviewed_data").select("review_status").eq("document_id", review_data.get("document_id")).maybe_single().execute()
    if existing and existing.data:
        print(f"[DATABASE DEBUG] 🔍 CRITICAL: This is an UPDATE! Previous status = {existing.data.get('review_status')}")
    else:
        print(f"[DATABASE DEBUG] 🔍 CRITICAL: This is a NEW INSERT")
    
    review_response = supabase_client.table("reviewed_data").upsert(review_data, on_conflict="document_id").execute()
    
    print(f"[DATABASE DEBUG] Database operations completed successfully")
    return {
        "job": job_response,
        "review": review_response
    }

@safe_db_operation("Update processing job")
def update_processing_job_db(supabase_client, job_id: str, updates: Dict[str, Any]):
    """
    Update a processing job - simplified to only use existing tables.
    """
    return supabase_client.table("processing_jobs").update(updates).eq("id", job_id).execute() 