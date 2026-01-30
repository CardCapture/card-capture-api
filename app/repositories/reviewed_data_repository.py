from fastapi import HTTPException
import json
from datetime import datetime, timezone
from app.utils.retry_utils import log_debug

def upsert_reviewed_data(supabase_client, data):
    """
    Upsert reviewed data to the database
    """
    log_debug(f"[REVIEWED DATA DEBUG] === UPSERT OPERATION START ===", service="reviewed_data")

    # Track critical fields being saved
    critical_fields = ["cell", "date_of_birth"]
    log_debug(f"[REVIEWED DATA DEBUG] CRITICAL FIELDS BEING SAVED:", service="reviewed_data")
    for field in critical_fields:
        field_data = data.get("fields", {}).get(field, {})
        log_debug(f"[REVIEWED DATA DEBUG] {field}:", service="reviewed_data")
        log_debug(f"  - value: {field_data.get('value')}", service="reviewed_data")
        log_debug(f"  - original_value: {field_data.get('original_value')}", service="reviewed_data")
        log_debug(f"  - source: {field_data.get('source')}", service="reviewed_data")
        log_debug(f"  - enabled: {field_data.get('enabled')}", service="reviewed_data")
        log_debug(f"  - required: {field_data.get('required')}", service="reviewed_data")
    
    try:
        result = supabase_client.table("reviewed_data").upsert(data, on_conflict="document_id").execute()
        log_debug(f"[REVIEWED DATA DEBUG] === UPSERT OPERATION COMPLETE ===", service="reviewed_data")
        return result
    except Exception as e:
        log_debug(f"[REVIEWED DATA DEBUG] Error during upsert: {str(e)}", service="reviewed_data")
        raise

def get_reviewed_data_by_document_id(supabase_client, document_id):
    response = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Reviewed data not found")
    return response.data
