from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.controllers.events_controller import (
    create_event_controller,
    update_event_controller,
    archive_events_controller,
    delete_event_controller
)
from app.models.event import EventCreatePayload, EventUpdatePayload, ArchiveEventsPayload
from app.core.auth import get_current_user
from app.core.clients import get_supabase_client

router = APIRouter(tags=["Events"])

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