from typing import Optional, Dict, Any
from fastapi import HTTPException

from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug


def create_student_school_interaction(interaction_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a student_school_interaction record.

    This replaces reviewed_data for V2 universal cards and QR codes.
    Each school gets their own editable version of student data.
    """
    sb = get_supabase_client()

    try:
        response = sb.table("student_school_interactions").insert(interaction_data).execute()
        rows = getattr(response, "data", None) or []

        if rows:
            return rows[0]

        # Fallback in case data is not returned
        return interaction_data
    except Exception as e:
        import json
        error_msg = str(e)

        # Log the full error and payload for debugging
        log_debug(f"[INTERACTION ERROR] Failed to create interaction", service="interactions")
        log_debug(f"[INTERACTION ERROR] Error: {error_msg}", service="interactions")
        log_debug(f"[INTERACTION ERROR] Payload: {json.dumps(interaction_data, indent=2, default=str)}", service="interactions")

        # Check for duplicate scan (UNIQUE constraint violation)
        if "duplicate key value violates unique constraint" in error_msg.lower():
            raise HTTPException(
                status_code=409,
                detail="This student has already been scanned for this event"
            )

        # Re-raise other errors
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create interaction: {error_msg}"
        )


def get_interaction_by_id(interaction_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single interaction by ID."""
    sb = get_supabase_client()
    response = (
        sb.table("student_school_interactions")
        .select("*")
        .eq("id", interaction_id)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def check_existing_interaction(
    student_id: str,
    school_id: str,
    event_id: str
) -> Optional[Dict[str, Any]]:
    """Check if an interaction already exists for this student/school/event combo."""
    sb = get_supabase_client()
    response = (
        sb.table("student_school_interactions")
        .select("*")
        .eq("student_id", student_id)
        .eq("school_id", school_id)
        .eq("event_id", event_id)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def update_student_school_interaction(interaction_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing student_school_interaction record."""
    sb = get_supabase_client()

    try:
        response = (
            sb.table("student_school_interactions")
            .update(update_data)
            .eq("id", interaction_id)
            .execute()
        )
        rows = getattr(response, "data", None) or []

        if rows:
            return rows[0]

        # Fallback
        return update_data
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update interaction: {str(e)}"
        )
