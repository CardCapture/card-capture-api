from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
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

@router.get("/events-with-stats")
async def get_events_with_stats(
    school_id: Optional[str] = Query(None),
    user=Depends(get_current_user)
):
    """
    Get events with card statistics calculated server-side for performance.
    This endpoint calculates stats using optimized queries (only 2 DB calls regardless of event count).

    SECURITY: Always filters by user's school_id unless user is SuperAdmin (school_id=null).
    """
    try:
        supabase_client = get_supabase_client()

        # SECURITY FIX: Use user's school_id from auth token, not query parameter
        # Only allow query parameter override for SuperAdmins (who have no school_id)
        user_school_id = user.get("school_id")

        if user_school_id:
            # Regular user - ALWAYS filter by their school_id
            filter_school_id = user_school_id
            log_debug(f"Regular user {user.get('user_id')} requesting events for school {filter_school_id}", service="events")
        else:
            # SuperAdmin with no school_id - allow filtering by query param or return all
            filter_school_id = school_id
            log_debug(f"SuperAdmin {user.get('user_id')} requesting events" + (f" for school {filter_school_id}" if filter_school_id else " (all schools)"), service="events")

        # Fetch events for the school
        events_query = supabase_client.table("events").select("*").order("date", desc=True)
        if filter_school_id:
            events_query = events_query.eq("school_id", filter_school_id)

        events_response = events_query.execute()
        events = events_response.data if events_response.data else []

        if not events:
            return []

        # Get all event IDs
        event_ids = [event["id"] for event in events]
        log_debug(f"Fetched {len(events)} events with IDs: {event_ids[:5]}..." if len(event_ids) > 5 else f"Fetched {len(events)} events with IDs: {event_ids}", service="events")

        # Fetch ALL V1 cards for these events in ONE query
        # IMPORTANT: Supabase client has default 1000 row limit - must use .limit() to get more
        v1_query = supabase_client.table("reviewed_data").select("event_id, review_status")
        v1_query = v1_query.in_("event_id", event_ids).neq("review_status", "deleted").limit(100000)
        v1_response = v1_query.execute()
        v1_cards = v1_response.data if v1_response.data else []
        log_debug(f"Fetched {len(v1_cards)} V1 cards from reviewed_data", service="events")

        # Fetch ALL V2 cards for these events in ONE query
        # IMPORTANT: Supabase client has default 1000 row limit - must use .limit() to get more
        v2_query = supabase_client.table("student_school_interactions").select("event_id, review_status")
        v2_query = v2_query.in_("event_id", event_ids).neq("review_status", "archived").limit(100000)
        v2_response = v2_query.execute()
        v2_cards = v2_response.data if v2_response.data else []
        log_debug(f"Fetched {len(v2_cards)} V2 cards from student_school_interactions", service="events")

        # Combine all cards
        all_cards = v1_cards + v2_cards
        log_debug(f"Total combined cards: {len(all_cards)}", service="events")

        # Group cards by event_id and calculate stats
        event_stats_map: Dict[str, Dict[str, int]] = {}
        for event_id in event_ids:
            event_stats_map[event_id] = {
                "total_cards": 0,
                "needs_review": 0,
                "ready_for_export": 0,
                "exported": 0,
                "archived": 0
            }

        # Aggregate stats
        for card in all_cards:
            event_id = card.get("event_id")
            if event_id not in event_stats_map:
                log_debug(f"WARNING: Card with event_id {event_id} not in event_stats_map", service="events")
                continue

            status = card.get("review_status")
            event_stats_map[event_id]["total_cards"] += 1

            if status == "needs_review":
                event_stats_map[event_id]["needs_review"] += 1
            elif status == "reviewed":
                event_stats_map[event_id]["ready_for_export"] += 1
            elif status == "exported":
                event_stats_map[event_id]["exported"] += 1
            elif status == "archived":
                event_stats_map[event_id]["archived"] += 1

        # Debug logging for Chapin HS event
        chapin_event_id = "fbc214f1-97e0-49a2-87aa-b6ee91d4b230"
        if chapin_event_id in event_stats_map:
            log_debug(f"DEBUG Chapin HS event stats: {event_stats_map[chapin_event_id]}", service="events")
            chapin_cards = [c for c in all_cards if c.get("event_id") == chapin_event_id]
            log_debug(f"DEBUG Chapin HS cards found: {len(chapin_cards)} - statuses: {[c.get('review_status') for c in chapin_cards]}", service="events")

        # Add stats to events
        events_with_stats = []
        for event in events:
            event_id = event["id"]
            stats = event_stats_map.get(event_id, {
                "total_cards": 0,
                "needs_review": 0,
                "ready_for_export": 0,
                "exported": 0,
                "archived": 0
            })
            event_with_stats = {**event, "stats": stats}
            events_with_stats.append(event_with_stats)

        log_debug(f"Fetched {len(events)} events with stats ({len(all_cards)} total cards)", service="events")
        return events_with_stats

    except Exception as e:
        log_debug(f"Get events with stats error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail=f"Failed to get events with stats: {str(e)}")

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