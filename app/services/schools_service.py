import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from fastapi.responses import JSONResponse
from app.repositories.schools_repository import get_school_by_id_db
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug

async def get_school_by_id(school_id: str, user_school_id: str = None) -> Optional[Dict[str, Any]]:
    """
    Fetch a school by its ID from the schools table with tenant isolation
    
    Args:
        school_id: The ID of the school to fetch
        user_school_id: The school_id of the requesting user for tenant isolation
        
    Returns:
        School data if found and user has access, None otherwise
    """
    try:
        log_debug(f"Fetching school with id: {school_id}, user_school_id: {user_school_id}", service="schools")
        
        # TENANT ISOLATION: Ensure user can only access their own school
        if user_school_id and school_id != user_school_id:
            log_debug(f"Tenant isolation violation: user school {user_school_id} trying to access school {school_id}", service="schools")
            return None
            
        supabase_client = get_supabase_client()
        response = supabase_client.table("schools").select("*").eq("id", school_id).execute()
        school = response.data[0] if response.data else None
        log_debug(f"School fetched: {school_id}", service="schools")
        return school
    except Exception as e:
        log_debug(f"Error fetching school: {e}", service="schools")
        return None

async def get_school_service(school_id: str, user_school_id: str = None) -> Dict[str, Any]:
    """
    Service function to get school data with proper error handling and tenant isolation
    
    Args:
        school_id: The ID of the school to fetch
        user_school_id: The school_id of the requesting user for tenant isolation
        
    Returns:
        Dictionary containing school data or error response
    """
    try:
        school = await get_school_by_id(school_id, user_school_id)
        if school:
            return {"school": school}
        else:
            return {"error": "School not found or access denied"}
    except Exception as e:
        log_debug(f"Error in get_school_service: {e}", service="schools")
        return {"error": "Failed to fetch school"} 