from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from app.core.clients import get_supabase_client
from app.repositories.events_repository import (
    insert_event_db,
    update_event_db,
    archive_event_db,
    delete_event_and_cards_db
)
from datetime import datetime, timezone
from app.utils.retry_utils import log_debug

def is_admin(user):
    # Updated to check roles array for admin permission
    user_roles = user.get("role", [])
    return "admin" in user_roles

def has_role(user, role_name):
    """Helper function to check if user has a specific role"""
    user_roles = user.get("role", [])
    return role_name in user_roles

def can_create_events(user):
    """Check if user can create events (admin, recruiter, or reviewer)"""
    user_roles = user.get("role") or []
    return any(role in user_roles for role in ["admin", "recruiter", "reviewer"])

def can_archive_events(user):
    """Check if user can archive events (admin or recruiter)"""
    user_roles = user.get("role", [])
    return any(role in user_roles for role in ["admin", "recruiter"])

async def create_event_service(payload, user):
    """Create an event for the authenticated user's school.

    SECURITY:
    - Requires authentication (enforced at route level)
    - Only admins and recruiters can create events
    - Regular users: school_id is taken from their authenticated profile (payload ignored)
    - SuperAdmins (school_id=NULL): school_id is taken from payload (required)

    Args:
        payload: EventCreatePayload with name, date, school_id, slate_event_id
        user: Authenticated user profile from get_current_user

    Returns:
        JSONResponse with created event data or error

    Raises:
        HTTPException 403: If user lacks permission or school association
        HTTPException 400: If SuperAdmin doesn't provide school_id
    """
    # SECURITY: Verify user has permission to create events
    if not can_create_events(user):
        log_debug(f"SECURITY: User {user.get('id')} denied event creation - insufficient role", service="events")
        raise HTTPException(status_code=403, detail="Only admins, recruiters, and reviewers can create events")

    # SECURITY: Determine school_id based on user type
    user_school_id = user.get("school_id")

    if user_school_id:
        # Regular user - MUST use their own school_id (ignore payload)
        target_school_id = user_school_id
        if payload.school_id and payload.school_id != user_school_id:
            log_debug(
                f"SECURITY: Regular user {user.get('id')} payload school_id={payload.school_id} ignored, using {user_school_id}",
                service="events"
            )
    else:
        # SuperAdmin (school_id=NULL) - use payload school_id (required)
        if not payload.school_id:
            log_debug(f"SECURITY: SuperAdmin {user.get('id')} missing school_id in payload", service="events")
            raise HTTPException(status_code=400, detail="school_id is required for SuperAdmin event creation")
        target_school_id = payload.school_id
        log_debug(f"SuperAdmin {user.get('id')} creating event for school {target_school_id}", service="events")

    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        log_debug(f"Database client not available: {e}", service="events")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    try:
        event_data = {
            "name": payload.name,
            "date": payload.date,
            "school_id": target_school_id,  # SECURITY: Uses validated school_id
            "status": "active",
            "slate_event_id": payload.slate_event_id
        }

        log_debug(f"Creating event: {event_data}", service="events")

        response = insert_event_db(supabase_client, event_data)

        if not response.data:
            log_debug("Failed to create event", service="events")
            return JSONResponse(status_code=500, content={"error": "Failed to create event."})

        log_debug(f"Event created: {response.data[0]}", service="events")
        return JSONResponse(status_code=200, content=response.data[0])

    except Exception as e:
        import traceback
        log_debug(f"Error creating event: {e}", data={"traceback": traceback.format_exc()}, service="events")
        return JSONResponse(status_code=500, content={"error": "Failed to create event."})

async def update_event_service(event_id: str, payload, user):
    # Allow admins, recruiters, and reviewers to update events
    # RLS policies ensure users can only update events from their school
    user_roles = user.get("role", [])
    if not any(role in user_roles for role in ["admin", "recruiter", "reviewer"]):
        log_debug("Only admins, recruiters, and reviewers can update events", service="events")
        raise HTTPException(status_code=403, detail="Only admins, recruiters, and reviewers can update events.")
    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        log_debug(f"Database client not available: {e}", service="events")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        # Build update dict with only provided fields
        update_data = {}
        if payload.name is not None:
            update_data["name"] = payload.name
        if payload.date is not None:
            update_data["date"] = payload.date
        if hasattr(payload, 'slate_event_id'):
            update_data["slate_event_id"] = payload.slate_event_id

        log_debug(f"UPDATE EVENT DEBUG - Updating event {event_id} with data: {update_data}", service="events")

        result = update_event_db(supabase_client, event_id, update_data)
        if hasattr(result, 'error') and result.error:
            log_debug(f"Error updating event {event_id}: {result.error}", service="events")
            raise Exception(result.error)
        log_debug(f"Event updated: {event_id}", service="events")
        return {"success": True}
    except Exception as e:
        log_debug(f"Error updating event {event_id}: {e}", service="events")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def archive_events_service(payload):
    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        log_debug(f"Database client not available: {e}", service="events")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        archived_count = 0
        errors = []
        
        # Archive each event
        archived_events = []
        for event_id in payload.event_ids:
            try:
                result = archive_event_db(supabase_client, event_id)
                if result.get("event"):
                    archived_events.append(result["event"])
                    log_debug(f"Successfully archived event {event_id}", service="events")
                    archived_count += 1
                else:
                    log_debug(f"Failed to archive event {event_id} - no result", service="events")
            except Exception as e:
                error_msg = f"Failed to archive event {event_id}: {str(e)}"
                errors.append(error_msg)
                log_debug(f"{error_msg}", service="events")
        
        if archived_count == len(payload.event_ids):
            return JSONResponse(
                status_code=200,
                content={"message": f"Successfully archived {archived_count} events"}
            )
        elif archived_count > 0:
            return JSONResponse(
                status_code=207,  # Multi-status
                content={
                    "message": f"Archived {archived_count} out of {len(payload.event_ids)} events",
                    "errors": errors
                }
            )
        else:
            return JSONResponse(
                status_code=500,
                content={
                    "message": "Failed to archive any events",
                    "errors": errors
                }
            )
    except Exception as e:
        import traceback
        log_debug(f"Error archiving events: {e}", data={"traceback": traceback.format_exc()}, service="events")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

async def delete_event_service(event_id: str, user):
    if not is_admin(user):
        log_debug("Only admins can delete events", service="events")
        raise HTTPException(status_code=403, detail="Only admins can delete events.")
    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        log_debug(f"Database client not available: {e}", service="events")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        reviewed, extracted, event = delete_event_and_cards_db(supabase_client, event_id)
        log_debug(f"Deleted event {event_id} and associated cards", service="events")
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content={"success": True})
    except Exception as e:
        log_debug(f"Error deleting event {event_id}: {e}", service="events")
        return JSONResponse(status_code=500, content={"error": str(e)}) 