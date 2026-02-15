from typing import List, Dict, Any, Union
from datetime import datetime, timezone
from app.utils.db_utils import (
    safe_db_operation,
    validate_db_response,
)


def get_cards_db(
    supabase_client,
    event_id: Union[str, None] = None,
    school_id: Union[str, None] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Get paginated cards from reviewed_data (V1), student_school_interactions (V2),
    and in-progress processing_jobs.

    Returns a dict with "cards", "total", "limit", and "offset".
    """
    all_cards: List[Dict[str, Any]] = []
    total_count = 0

    # --- V1: reviewed_data (with count) ---
    query_v1 = (
        supabase_client.table("reviewed_data")
        .select("*", count="exact")
        .neq("review_status", "deleted")
    )
    if event_id:
        query_v1 = query_v1.eq("event_id", event_id)
    if school_id:
        query_v1 = query_v1.eq("school_id", school_id)
    query_v1 = query_v1.range(offset, offset + limit - 1)
    response_v1 = query_v1.execute()

    v1_count = response_v1.count if response_v1.count is not None else 0
    reviewed_doc_ids: set = set()

    if validate_db_response(response_v1, "Get cards from reviewed_data"):
        for card in response_v1.data:
            reviewed_doc_ids.add(card.get("document_id"))
        all_cards.extend(response_v1.data)

    # --- V2: student_school_interactions (with count) ---
    query_v2 = (
        supabase_client.table("student_school_interactions")
        .select("*", count="exact")
        .neq("review_status", "archived")
    )
    if event_id:
        query_v2 = query_v2.eq("event_id", event_id)
    if school_id:
        query_v2 = query_v2.eq("school_id", school_id)
    query_v2 = query_v2.range(offset, offset + limit - 1)
    response_v2 = query_v2.execute()

    v2_count = response_v2.count if response_v2.count is not None else 0

    if validate_db_response(response_v2, "Get cards from student_school_interactions"):
        for interaction in response_v2.data:
            card = {
                "document_id": interaction.get("id"),
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
                "upload_type": interaction.get("source_method", "qr_code"),
                "image_path": interaction.get("image_path"),
                "trimmed_image_path": interaction.get("image_path"),
            }
            all_cards.append(card)

    # --- Processing jobs (always small, not paginated) ---
    query_jobs = (
        supabase_client.table("processing_jobs")
        .select("*", count="exact")
        .in_("status", ["queued", "processing"])
    )
    if event_id:
        query_jobs = query_jobs.eq("event_id", event_id)
    if school_id:
        query_jobs = query_jobs.eq("school_id", school_id)
    response_jobs = query_jobs.execute()

    jobs_count = 0
    if validate_db_response(response_jobs, "Get cards from processing_jobs"):
        for job in response_jobs.data:
            if job.get("id") in reviewed_doc_ids:
                continue
            jobs_count += 1
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

    total_count = v1_count + v2_count + jobs_count

    return {
        "cards": all_cards,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }

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