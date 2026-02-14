from typing import List, Dict, Any, Union
from datetime import datetime, timezone
from app.utils.db_utils import (
    safe_db_operation,
    validate_db_response,
)

@safe_db_operation("Get cards")
def get_cards_db(supabase_client, event_id: Union[str, None] = None, school_id: Union[str, None] = None) -> List[Dict[str, Any]]:
    """Get cards from reviewed_data (V1), student_school_interactions (V2), and in-progress processing_jobs.

    Args:
        supabase_client: The Supabase client
        event_id: Optional event ID to filter by
        school_id: Optional school ID to filter by (for multi-tenant isolation)
    """
    all_cards = []

    # Fetch V1 cards from reviewed_data
    query_v1 = supabase_client.table("reviewed_data").select("*")
    if event_id:
        query_v1 = query_v1.eq("event_id", event_id)
    if school_id:
        query_v1 = query_v1.eq("school_id", school_id)
    response_v1 = query_v1.execute()

    # Track document IDs from reviewed_data so we don't duplicate with processing_jobs
    reviewed_doc_ids = set()

    if validate_db_response(response_v1, "Get cards from reviewed_data"):
        v1_cards = [card for card in response_v1.data if card.get("review_status") != "deleted"]
        for card in v1_cards:
            reviewed_doc_ids.add(card.get("document_id"))
        all_cards.extend(v1_cards)

    # Fetch V2 interactions from student_school_interactions
    query_v2 = supabase_client.table("student_school_interactions").select("*")
    if event_id:
        query_v2 = query_v2.eq("event_id", event_id)
    if school_id:
        query_v2 = query_v2.eq("school_id", school_id)
    response_v2 = query_v2.execute()

    if validate_db_response(response_v2, "Get cards from student_school_interactions"):
        # Transform V2 interactions to match V1 card format
        for interaction in response_v2.data:
            if interaction.get("review_status") != "archived":
                # Map interaction to card format
                card = {
                    "document_id": interaction.get("id"),  # Use interaction id as document_id
                    "id": interaction.get("id"),
                    "fields": interaction.get("fields", {}),
                    "review_status": interaction.get("review_status"),
                    "event_id": interaction.get("event_id"),
                    "school_id": interaction.get("school_id"),
                    "user_id": interaction.get("user_id"),
                    "created_at": interaction.get("created_at"),
                    "updated_at": interaction.get("updated_at"),
                    "reviewed_at": interaction.get("reviewed_at"),
                    "exported_at": interaction.get("exported_at"),
                    "upload_type": interaction.get("source_method", "qr_code"),  # Map source_method to upload_type
                    "image_path": interaction.get("image_path"),  # Universal cards have images, QR codes will be None
                    "trimmed_image_path": interaction.get("image_path"),  # Use same path for trimmed (no trimming for V2)
                }
                all_cards.append(card)

    # Fetch in-progress processing jobs (queued/processing) that don't yet have reviewed_data
    query_jobs = supabase_client.table("processing_jobs").select("*").in_("status", ["queued", "processing"])
    if event_id:
        query_jobs = query_jobs.eq("event_id", event_id)
    if school_id:
        query_jobs = query_jobs.eq("school_id", school_id)
    response_jobs = query_jobs.execute()

    if validate_db_response(response_jobs, "Get cards from processing_jobs"):
        for job in response_jobs.data:
            # Skip jobs that already have a reviewed_data entry
            if job.get("id") in reviewed_doc_ids:
                continue
            card = {
                "document_id": job.get("id"),
                "id": job.get("id"),
                "fields": {},
                "review_status": "processing",
                "event_id": job.get("event_id"),
                "school_id": job.get("school_id"),
                "user_id": str(job.get("user_id")) if job.get("user_id") else None,
                "created_at": job.get("created_at"),
                "updated_at": job.get("updated_at"),
                "image_path": job.get("image_path"),
                "upload_type": "inquiry_card",
            }
            all_cards.append(card)

    return all_cards

@safe_db_operation("Mark cards as exported")
def mark_as_exported_db(supabase_client, document_ids: List[str]):
    """
    Mark cards as exported - handles both V1 (reviewed_data) and V2 (student_school_interactions).
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Update V1 cards in reviewed_data
    supabase_client.table("reviewed_data").update({
        "exported_at": timestamp,
        "review_status": "exported",
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

    # Update V2 interactions in student_school_interactions
    return supabase_client.table("student_school_interactions").update({
        "exported_at": timestamp,
        "review_status": "exported",
        "updated_at": timestamp
    }).in_("id", document_ids).execute()

@safe_db_operation("Archive cards")
def archive_cards_db(supabase_client, document_ids: List[str]):
    """
    Archive cards - handles both V1 (reviewed_data) and V2 (student_school_interactions).
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Update V1 cards in reviewed_data
    supabase_client.table("reviewed_data").update({
        "review_status": "archived",
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

    # Update V2 interactions in student_school_interactions
    return supabase_client.table("student_school_interactions").update({
        "review_status": "archived",
        "updated_at": timestamp
    }).in_("id", document_ids).execute()

@safe_db_operation("Delete cards")
def delete_cards_db(supabase_client, document_ids: List[str]):
    """
    Delete cards (mark as deleted) - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data status - removed deleted_at as it doesn't exist
    return supabase_client.table("reviewed_data").update({
        "review_status": "deleted",
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

@safe_db_operation("Move cards")
def move_cards_db(supabase_client, document_ids: List[str], status: str):
    """
    Move cards to a different status - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data status
    return supabase_client.table("reviewed_data").update({
        "review_status": status,
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

@safe_db_operation("Save manual review")
def save_manual_review_db(supabase_client, document_id: str, review_data: Dict[str, Any]):
    """
    Save manual review changes - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data - removed last_reviewed_by as it doesn't exist
    return supabase_client.table("reviewed_data").update({
        **review_data,
        "updated_at": timestamp
    }).eq("document_id", document_id).execute() 