from fastapi import APIRouter, Depends, Body
from app.controllers.schools_controller import get_school_controller
from app.core.auth import get_current_user
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
import json
import re

router = APIRouter(tags=["Schools"])

@router.get("/schools/{school_id}")
async def get_school(school_id: str, user=Depends(get_current_user)):
    return await get_school_controller(school_id, user)

@router.put("/schools/{school_id}/card-fields")
async def update_school_card_fields(school_id: str, payload: Dict[str, Any] = Body(...), user=Depends(get_current_user)):
    """
    Updates the card_fields in the schools table for a given school.
    Expects a payload with a card_fields object containing field settings.
    """
    try:
        # TENANT ISOLATION: Ensure user can only update their own school
        user_school_id = user.get("school_id") if user else None
        if not user_school_id or school_id != user_school_id:
            return JSONResponse(status_code=403, content={"error": "Access denied. You can only update your own school."})
            
        supabase_client = get_supabase_client()
        card_fields = payload.get("card_fields", {})
        if not card_fields:
            return JSONResponse(status_code=400, content={"error": "card_fields is required in payload."})

        # First verify the school exists and user has access
        school_query = supabase_client.table("schools").select("id").eq("id", school_id).maybe_single().execute()
        if not school_query or not school_query.data:
            return JSONResponse(status_code=404, content={"error": "School not found."})

        # Update the school record with new card_fields
        update_payload = {
            "id": school_id,
            "card_fields": card_fields
        }

        log_debug(f"[Card Fields Update] Updating school {school_id} with card_fields:", service="schools")
        log_debug(json.dumps(card_fields, indent=2), service="schools")
        
        response = supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
        
        if response.data:
            log_debug(f"Successfully updated card_fields for school {school_id}", service="schools")
            return JSONResponse(status_code=200, content={
                "message": "Card fields updated successfully",
                "school_id": school_id,
                "card_fields": card_fields
            })
        else:
            log_debug(f"Failed to update card_fields for school {school_id}", service="schools")
            return JSONResponse(status_code=500, content={"error": "Failed to update card fields."})

    except Exception as e:
        log_debug(f"Error updating card fields for school {school_id}: {e}", service="schools")
        return JSONResponse(status_code=500, content={"error": "Failed to update card fields."})

@router.post("/schools/{school_id}/suggested-fields/accept")
async def accept_suggested_field(school_id: str, payload: Dict[str, Any] = Body(...), user=Depends(get_current_user)):
    """
    Accept a discovered field suggestion: promote it from suggested_card_fields
    into card_fields (so it shows for the current card and all future cards) and
    remove it from the suggestions list.
    Expects payload: { "key": "<field key>" }.
    """
    try:
        user_school_id = user.get("school_id") if user else None
        if not user_school_id or school_id != user_school_id:
            return JSONResponse(status_code=403, content={"error": "Access denied. You can only update your own school."})

        key = (payload.get("key") or "").strip()
        if not key:
            return JSONResponse(status_code=400, content={"error": "key is required in payload."})

        supabase_client = get_supabase_client()
        school_query = supabase_client.table("schools").select(
            "card_fields, suggested_card_fields"
        ).eq("id", school_id).maybe_single().execute()
        if not school_query or not school_query.data:
            return JSONResponse(status_code=404, content={"error": "School not found."})

        card_fields = school_query.data.get("card_fields") or []
        if not isinstance(card_fields, list):
            card_fields = []
        suggestions = school_query.data.get("suggested_card_fields") or []
        if not isinstance(suggestions, list):
            suggestions = []

        suggestion = next((s for s in suggestions if isinstance(s, dict) and s.get("key") == key), None)

        # Promote into card_fields if not already present (idempotent).
        if not any(isinstance(f, dict) and f.get("key") == key for f in card_fields):
            from app.utils.field_utils import generate_field_label
            label = (suggestion or {}).get("label") or generate_field_label(key)
            field_type = (suggestion or {}).get("field_type") or "text"
            new_field = {"key": key, "label": label, "enabled": True, "required": False, "field_type": field_type}
            options = (suggestion or {}).get("options")
            if options:
                new_field["options"] = options
            card_fields.append(new_field)

        # Remove from suggestions.
        suggestions = [s for s in suggestions if not (isinstance(s, dict) and s.get("key") == key)]

        response = supabase_client.table("schools").update(
            {"card_fields": card_fields, "suggested_card_fields": suggestions}
        ).eq("id", school_id).execute()

        if response.data:
            log_debug(f"Accepted suggested field '{key}' for school {school_id}", service="schools")
            return JSONResponse(status_code=200, content={
                "message": "Suggested field accepted",
                "school_id": school_id,
                "key": key,
                "card_fields": card_fields,
                "suggested_card_fields": suggestions,
            })
        return JSONResponse(status_code=500, content={"error": "Failed to accept suggested field."})

    except Exception as e:
        log_debug(f"Error accepting suggested field for school {school_id}: {e}", service="schools")
        return JSONResponse(status_code=500, content={"error": "Failed to accept suggested field."})


@router.post("/schools/{school_id}/suggested-fields/dismiss")
async def dismiss_suggested_field(school_id: str, payload: Dict[str, Any] = Body(...), user=Depends(get_current_user)):
    """
    Dismiss a discovered field suggestion: remove it from suggested_card_fields
    without adding it to card_fields.
    Expects payload: { "key": "<field key>" }.
    """
    try:
        user_school_id = user.get("school_id") if user else None
        if not user_school_id or school_id != user_school_id:
            return JSONResponse(status_code=403, content={"error": "Access denied. You can only update your own school."})

        key = (payload.get("key") or "").strip()
        if not key:
            return JSONResponse(status_code=400, content={"error": "key is required in payload."})

        supabase_client = get_supabase_client()
        school_query = supabase_client.table("schools").select(
            "suggested_card_fields"
        ).eq("id", school_id).maybe_single().execute()
        if not school_query or not school_query.data:
            return JSONResponse(status_code=404, content={"error": "School not found."})

        suggestions = school_query.data.get("suggested_card_fields") or []
        if not isinstance(suggestions, list):
            suggestions = []
        suggestions = [s for s in suggestions if not (isinstance(s, dict) and s.get("key") == key)]

        response = supabase_client.table("schools").update(
            {"suggested_card_fields": suggestions}
        ).eq("id", school_id).execute()

        if response.data:
            log_debug(f"Dismissed suggested field '{key}' for school {school_id}", service="schools")
            return JSONResponse(status_code=200, content={
                "message": "Suggested field dismissed",
                "school_id": school_id,
                "key": key,
                "suggested_card_fields": suggestions,
            })
        return JSONResponse(status_code=500, content={"error": "Failed to dismiss suggested field."})

    except Exception as e:
        log_debug(f"Error dismissing suggested field for school {school_id}: {e}", service="schools")
        return JSONResponse(status_code=500, content={"error": "Failed to dismiss suggested field."})


@router.get("/schools/{school_id}/notification-settings")
async def get_notification_settings(school_id: str, user=Depends(get_current_user)):
    """
    Get notification settings for a school.
    Returns notification_email and notifications_enabled fields.
    """
    try:
        # TENANT ISOLATION: Ensure user can only access their own school
        user_school_id = user.get("school_id") if user else None
        if not user_school_id or school_id != user_school_id:
            return JSONResponse(status_code=403, content={"error": "Access denied. You can only access your own school settings."})

        supabase_client = get_supabase_client()

        # Get notification settings from school record
        response = supabase_client.table("schools").select(
            "notification_email, notifications_enabled"
        ).eq("id", school_id).maybe_single().execute()

        if not response or not response.data:
            return JSONResponse(status_code=404, content={"error": "School not found."})

        return JSONResponse(status_code=200, content={
            "notification_email": response.data.get("notification_email"),
            "notifications_enabled": response.data.get("notifications_enabled", False)
        })

    except Exception as e:
        log_debug(f"Error getting notification settings for school {school_id}: {e}", service="schools")
        return JSONResponse(status_code=500, content={"error": "Failed to get notification settings."})

@router.put("/schools/{school_id}/notification-settings")
async def update_notification_settings(
    school_id: str,
    payload: Dict[str, Any] = Body(...),
    user=Depends(get_current_user)
):
    """
    Update notification settings for a school.
    Expects payload with notification_email and/or notifications_enabled.

    Example payload:
    {
        "notification_email": "admissions@school.edu",
        "notifications_enabled": true
    }
    """
    try:
        # TENANT ISOLATION: Ensure user can only update their own school
        user_school_id = user.get("school_id") if user else None
        if not user_school_id or school_id != user_school_id:
            return JSONResponse(status_code=403, content={"error": "Access denied. You can only update your own school settings."})

        supabase_client = get_supabase_client()

        # First verify the school exists and user has access
        school_query = supabase_client.table("schools").select("id").eq("id", school_id).maybe_single().execute()
        if not school_query or not school_query.data:
            return JSONResponse(status_code=404, content={"error": "School not found."})

        # Extract and validate notification settings from payload
        notification_email = payload.get("notification_email")
        notifications_enabled = payload.get("notifications_enabled")

        # Validate email if provided
        if notification_email is not None:
            # Allow None/empty to clear the email
            if notification_email and notification_email.strip():
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, notification_email):
                    return JSONResponse(status_code=400, content={"error": "Invalid email format."})

        # Build update payload with only provided fields
        update_payload = {}
        if notification_email is not None:
            # Store None if empty string, otherwise store the email
            update_payload["notification_email"] = notification_email if notification_email and notification_email.strip() else None

        if notifications_enabled is not None:
            update_payload["notifications_enabled"] = bool(notifications_enabled)

        if not update_payload:
            return JSONResponse(status_code=400, content={"error": "No valid fields to update."})

        log_debug(f"[Notification Settings Update] Updating school {school_id} with settings:", service="schools")
        log_debug(json.dumps(update_payload, indent=2), service="schools")

        # Update the school record
        response = supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()

        if response.data:
            log_debug(f"Successfully updated notification settings for school {school_id}", service="schools")
            return JSONResponse(status_code=200, content={
                "message": "Notification settings updated successfully",
                "school_id": school_id,
                **update_payload
            })
        else:
            log_debug(f"Failed to update notification settings for school {school_id}", service="schools")
            return JSONResponse(status_code=500, content={"error": "Failed to update notification settings."})

    except Exception as e:
        log_debug(f"Error updating notification settings for school {school_id}: {e}", service="schools")
        return JSONResponse(status_code=500, content={"error": "Failed to update notification settings."}) 