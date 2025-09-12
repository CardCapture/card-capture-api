from fastapi import HTTPException
from typing import Dict, Any, List
from datetime import datetime, timezone
from app.utils.db_utils import (
    ensure_atomic_updates,
    safe_db_operation,
    validate_db_response,
    handle_db_error
)

def get_school_by_id_db(supabase_client, school_id: str, user_school_id: str = None):
    # TENANT ISOLATION: Ensure user can only access their own school
    if user_school_id and school_id != user_school_id:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your own school.")
        
    response = supabase_client.table("schools") \
        .select("*") \
        .eq("id", school_id) \
        .maybe_single() \
        .execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="School not found.")
    return response.data 

@safe_db_operation("Get school settings")
def get_school_settings_db(supabase_client, school_id: str, user_school_id: str = None):
    """Get school settings with proper error handling and tenant isolation."""
    # TENANT ISOLATION: Ensure user can only access their own school
    if user_school_id and school_id != user_school_id:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your own school settings.")
        
    return supabase_client.table("schools").select("*").eq("id", school_id).single().execute()

@ensure_atomic_updates(["schools", "field_requirements"])
def update_school_settings_db(supabase_client, school_id: str, settings: Dict[str, Any], user_school_id: str = None):
    """
    Update school settings and field requirements atomically with tenant isolation.
    If either operation fails, both are rolled back.
    """
    try:
        # TENANT ISOLATION: Ensure user can only update their own school
        if user_school_id and school_id != user_school_id:
            raise HTTPException(status_code=403, detail="Access denied. You can only update your own school settings.")
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Extract field requirements from settings
        field_requirements = settings.pop("field_requirements", {})
        
        # Update school settings
        settings_response = supabase_client.table("schools").update({
            **settings,
            "updated_at": timestamp
        }).eq("id", school_id).execute()
        
        if not validate_db_response(settings_response, "Update school settings"):
            raise HTTPException(status_code=500, detail="Failed to update school settings")
            
        # Update field requirements if provided
        if field_requirements:
            # Create/update field requirement records
            requirement_records = [{
                "school_id": school_id,
                "field_name": field_name,
                **field_data,
                "updated_at": timestamp
            } for field_name, field_data in field_requirements.items()]
            
            requirements_response = supabase_client.table("field_requirements").upsert(
                requirement_records,
                on_conflict="school_id,field_name"
            ).execute()
            
            if not validate_db_response(requirements_response, "Update field requirements"):
                raise HTTPException(status_code=500, detail="Failed to update field requirements")
        
        return {
            "settings": settings_response.data[0] if settings_response.data else None,
            "requirements": requirements_response.data if field_requirements else None
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Update school settings")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["schools", "field_requirements", "field_mappings"])
def update_school_field_config_db(
    supabase_client,
    school_id: str,
    field_requirements: Dict[str, Any],
    field_mappings: Dict[str, Any],
    user_school_id: str = None
):
    """
    Update school field configuration atomically across all related tables with tenant isolation.
    If any operation fails, all are rolled back.
    """
    try:
        # TENANT ISOLATION: Ensure user can only update their own school
        if user_school_id and school_id != user_school_id:
            raise HTTPException(status_code=403, detail="Access denied. You can only update your own school field configuration.")
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Update field requirements
        requirement_records = [{
            "school_id": school_id,
            "field_name": field_name,
            **field_data,
            "updated_at": timestamp
        } for field_name, field_data in field_requirements.items()]
        
        requirements_response = supabase_client.table("field_requirements").upsert(
            requirement_records,
            on_conflict="school_id,field_name"
        ).execute()
        
        if not validate_db_response(requirements_response, "Update field requirements"):
            raise HTTPException(status_code=500, detail="Failed to update field requirements")
            
        # Update field mappings
        mapping_records = [{
            "school_id": school_id,
            "source_field": source,
            "target_field": target,
            "updated_at": timestamp
        } for source, target in field_mappings.items()]
        
        mappings_response = supabase_client.table("field_mappings").upsert(
            mapping_records,
            on_conflict="school_id,source_field"
        ).execute()
        
        if not validate_db_response(mappings_response, "Update field mappings"):
            raise HTTPException(status_code=500, detail="Failed to update field mappings")
            
        # Update school's last_config_update
        school_response = supabase_client.table("schools").update({
            "last_field_config_update": timestamp
        }).eq("id", school_id).execute()
        
        if not validate_db_response(school_response, "Update school config timestamp"):
            raise HTTPException(status_code=500, detail="Failed to update school config timestamp")
            
        return {
            "requirements": requirements_response.data,
            "mappings": mappings_response.data,
            "school": school_response.data[0] if school_response.data else None
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Update school field configuration")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["schools", "docai_processors"])
def update_school_processor_db(supabase_client, school_id: str, processor_config: Dict[str, Any], user_school_id: str = None):
    """
    Update school's DocAI processor configuration atomically with tenant isolation.
    If either operation fails, both are rolled back.
    """
    try:
        # TENANT ISOLATION: Ensure user can only update their own school
        if user_school_id and school_id != user_school_id:
            raise HTTPException(status_code=403, detail="Access denied. You can only update your own school processor configuration.")
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create/update processor record
        processor_response = supabase_client.table("docai_processors").upsert({
            **processor_config,
            "updated_at": timestamp
        }).execute()
        
        if not validate_db_response(processor_response, "Update DocAI processor"):
            raise HTTPException(status_code=500, detail="Failed to update DocAI processor")
            
        # Update school's processor reference
        school_response = supabase_client.table("schools").update({
            "docai_processor_id": processor_config["processor_id"],
            "updated_at": timestamp
        }).eq("id", school_id).execute()
        
        if not validate_db_response(school_response, "Update school processor reference"):
            raise HTTPException(status_code=500, detail="Failed to update school processor reference")
            
        return {
            "processor": processor_response.data[0] if processor_response.data else None,
            "school": school_response.data[0] if school_response.data else None
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Update school processor")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["schools", "export_configs"])
def update_school_export_config_db(supabase_client, school_id: str, export_config: Dict[str, Any], user_school_id: str = None):
    """
    Update school's export configuration atomically with tenant isolation.
    If either operation fails, both are rolled back.
    """
    try:
        # TENANT ISOLATION: Ensure user can only update their own school
        if user_school_id and school_id != user_school_id:
            raise HTTPException(status_code=403, detail="Access denied. You can only update your own school export configuration.")
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create/update export config
        config_response = supabase_client.table("export_configs").upsert({
            "school_id": school_id,
            **export_config,
            "updated_at": timestamp
        }).execute()
        
        if not validate_db_response(config_response, "Update export config"):
            raise HTTPException(status_code=500, detail="Failed to update export configuration")
            
        # Update school's export_config_id
        school_response = supabase_client.table("schools").update({
            "export_config_id": config_response.data[0]["id"] if config_response.data else None,
            "updated_at": timestamp
        }).eq("id", school_id).execute()
        
        if not validate_db_response(school_response, "Update school export config reference"):
            raise HTTPException(status_code=500, detail="Failed to update school export config reference")
            
        return {
            "config": config_response.data[0] if config_response.data else None,
            "school": school_response.data[0] if school_response.data else None
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Update school export configuration")
        raise HTTPException(status_code=500, detail=error_details) 