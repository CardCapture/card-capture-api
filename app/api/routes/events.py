from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from app.controllers.events_controller import (
    create_event_controller,
    update_event_controller,
    archive_events_controller,
    delete_event_controller
)
from app.models.event import EventCreatePayload, EventUpdatePayload, ArchiveEventsPayload
from app.core.auth import get_current_user
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug

router = APIRouter(tags=["Events"])


class EventCodeCreateRequest(BaseModel):
    event_id: str
    max_uses: Optional[int] = 1000
    valid_days: Optional[int] = 7
    metadata: Optional[dict] = None


class EventCodeUpdateRequest(BaseModel):
    active: Optional[bool] = None
    max_uses: Optional[int] = None
    valid_until: Optional[str] = None

@router.post("/events")
async def create_event(payload: EventCreatePayload):
    return await create_event_controller(payload)

@router.put("/events/{event_id}")
async def update_event(event_id: str, payload: EventUpdatePayload, user=Depends(get_current_user)):
    return await update_event_controller(event_id, payload, user)

@router.post("/archive-events")
async def archive_events(payload: ArchiveEventsPayload):
    return await archive_events_controller(payload)

@router.delete("/events/{event_id}")
async def delete_event(event_id: str, user=Depends(get_current_user)):
    return await delete_event_controller(event_id, user)

@router.post("/events/{event_id}/codes")
async def create_event_code(
    event_id: str,
    body: EventCodeCreateRequest,
    user=Depends(get_current_user)
):
    """Create a new event code for registration"""
    try:
        supabase_client = get_supabase_client()
        
        # Verify user has access to this event
        event_response = supabase_client.table("events").select("*").eq("id", event_id).limit(1).execute()
        if not event_response.data:
            raise HTTPException(status_code=404, detail="Event not found")
        
        event = event_response.data[0]
        if event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Generate unique 6-digit code
        code_response = supabase_client.rpc("generate_event_code").execute()
        code = code_response.data
        
        # Create event code
        valid_until = datetime.utcnow() + timedelta(days=body.valid_days)
        
        data = {
            "code": code,
            "event_id": event_id,
            "max_uses": body.max_uses,
            "valid_until": valid_until.isoformat(),
            "metadata": body.metadata or {}
        }
        
        response = supabase_client.table("event_codes").insert(data).execute()
        
        log_debug(f"Event code created: {code} for event {event_id}", service="events")
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Event code creation error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to create event code")


@router.get("/events/{event_id}/codes")
async def get_event_codes(
    event_id: str,
    user=Depends(get_current_user)
):
    """Get all event codes for an event"""
    try:
        supabase_client = get_supabase_client()
        
        # Verify user has access to this event
        event_response = supabase_client.table("events").select("*").eq("id", event_id).limit(1).execute()
        if not event_response.data:
            raise HTTPException(status_code=404, detail="Event not found")
        
        event = event_response.data[0]
        if event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get event codes
        response = supabase_client.table("event_codes").select("*").eq("event_id", event_id).order("created_at", desc=True).execute()
        
        return response.data
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Get event codes error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to get event codes")


@router.patch("/events/codes/{code_id}")
async def update_event_code(
    code_id: str,
    body: EventCodeUpdateRequest,
    user=Depends(get_current_user)
):
    """Update an event code"""
    try:
        supabase_client = get_supabase_client()
        
        # Get event code with event
        code_response = supabase_client.table("event_codes").select("*, events(*)").eq("id", code_id).limit(1).execute()
        if not code_response.data:
            raise HTTPException(status_code=404, detail="Event code not found")
        
        event_code = code_response.data[0]
        event = event_code.get("events")
        
        # Verify user has access
        if event and event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Update event code
        update_data = {}
        if body.active is not None:
            update_data["active"] = body.active
        if body.max_uses is not None:
            update_data["max_uses"] = body.max_uses
        if body.valid_until is not None:
            update_data["valid_until"] = body.valid_until
        
        response = supabase_client.table("event_codes").update(update_data).eq("id", code_id).execute()
        
        log_debug(f"Event code updated: {code_id}", service="events")
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Update event code error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to update event code")


@router.delete("/events/codes/{code_id}")
async def delete_event_code(
    code_id: str,
    user=Depends(get_current_user)
):
    """Delete (deactivate) an event code"""
    try:
        supabase_client = get_supabase_client()
        
        # Get event code with event
        code_response = supabase_client.table("event_codes").select("*, events(*)").eq("id", code_id).limit(1).execute()
        if not code_response.data:
            raise HTTPException(status_code=404, detail="Event code not found")
        
        event_code = code_response.data[0]
        event = event_code.get("events")
        
        # Verify user has access
        if event and event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Soft delete by deactivating
        response = supabase_client.table("event_codes").update({"active": False}).eq("id", code_id).execute()
        
        log_debug(f"Event code deactivated: {code_id}", service="events")
        return {"success": True, "message": "Event code deactivated"}
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Delete event code error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to delete event code")


@router.get("/debug/auth-user")
async def debug_auth_user(user=Depends(get_current_user)):
    """Debug endpoint to check what's in auth.users for current user"""
    try:
        supabase_client = get_supabase_client()
        
        # Query auth.users directly to see what school_id this user has
        auth_user_query = supabase_client.table("auth.users").select("id, school_id").eq("id", user["user_id"]).execute()
        
        return JSONResponse(status_code=200, content={
            "user_from_token": user,
            "auth_users_record": auth_user_query.data,
            "debug_info": {
                "user_id_from_token": user.get("user_id"),
                "school_id_from_token": user.get("school_id"),
                "roles_from_token": user.get("role", [])
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Debug query failed: {str(e)}"}) 