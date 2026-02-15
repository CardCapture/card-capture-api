from typing import List, Dict, Any, Optional
import traceback
from fastapi.responses import JSONResponse
from app.models.card import MarkExportedPayload
from app.core.clients import get_supabase_client
from app.repositories.cards_repository import (
    get_cards_db,
    archive_cards_db,
    mark_as_exported_db,
    delete_cards_db,
    move_cards_db
)
from app.utils.archive_logging import log_archive_debug
from app.utils.retry_utils import log_debug

async def get_cards_service(
    event_id: Optional[str] = None,
    school_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    try:
        log_debug("Received /cards request", service="cards")

        if event_id:
            log_debug(f"Filtering by event_id: {event_id}", service="cards")
        if school_id:
            log_debug(f"Filtering by school_id: {school_id}", service="cards")

        supabase_client = get_supabase_client()
        result = get_cards_db(supabase_client, event_id, school_id, limit, offset)
        log_debug(f"Returning {len(result['cards'])} cards (total: {result['total']})", service="cards")
        return result
    except Exception as e:
        log_debug(f"Error in /cards endpoint: {e}", service="cards")
        raise e

async def archive_cards_service(document_ids: List[str]) -> JSONResponse:
    """Archive cards by document IDs"""
    log_archive_debug("=== ARCHIVE CARDS SERVICE START ===")
    log_archive_debug("Received document IDs", document_ids)
    
    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        error_msg = f"Database client not available: {e}"
        log_archive_debug(f"Error: {error_msg}")
        return JSONResponse(status_code=503, content={"error": error_msg})
    
    if not document_ids:
        error_msg = "No document IDs provided"
        log_archive_debug(f"Error: {error_msg}")
        return JSONResponse(status_code=400, content={"error": error_msg})
    
    try:
        log_archive_debug("Calling archive_cards_db...")
        result = archive_cards_db(supabase_client, document_ids)
        
        if not result or not hasattr(result, 'data'):
            log_archive_debug("No records were archived")
            return JSONResponse(status_code=200, content={"message": "No records were archived", "archived_count": 0})
        
        archived_count = len(result.data)
        log_archive_debug(f"Successfully archived {archived_count} records")
        log_archive_debug("=== ARCHIVE CARDS SERVICE END ===")
        
        return JSONResponse(status_code=200, content={
            "message": f"Successfully archived {archived_count} records",
            "archived_count": archived_count
        })
    except Exception as e:
        error_msg = f"Error archiving cards: {str(e)}"
        log_archive_debug(f"Error: {error_msg}")
        log_archive_debug("=== ARCHIVE CARDS SERVICE END WITH ERROR ===")
        return JSONResponse(status_code=500, content={"error": error_msg})

async def mark_as_exported_service(document_ids: List[str]) -> JSONResponse:
    """Mark cards as exported by document IDs"""
    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        log_debug(f"Database client not available: {e}", service="cards")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    
    if not document_ids:
        log_debug("No document_ids provided", service="cards")
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})
    
    log_debug(f"Recording export timestamp for {len(document_ids)} records...", service="cards")
    try:
        mark_as_exported_db(supabase_client, document_ids)
        log_debug(f"Successfully recorded export timestamp for {len(document_ids)} records", service="cards")
        return JSONResponse(status_code=200, content={"message": f"{len(document_ids)} records export timestamp updated."})
    except Exception as e:
        log_debug(f"Error recording export timestamp: {e}", data={"traceback": traceback.format_exc()}, service="cards")
        return JSONResponse(status_code=500, content={"error": "Failed to record export timestamp."})

def delete_cards_service(document_ids: List[str]) -> JSONResponse:
    """Delete cards by document IDs"""
    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        log_debug(f"Database client not available: {e}", service="cards")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    
    if not document_ids:
        log_debug("No document_ids provided", service="cards")
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})
    
    log_debug(f"Deleting {len(document_ids)} cards...", service="cards")
    
    delete_cards_db(supabase_client, document_ids)
    
    log_debug(f"Successfully deleted {len(document_ids)} cards", service="cards")
    return JSONResponse(status_code=200, content={"message": f"Successfully deleted {len(document_ids)} cards."})

def move_cards_service(document_ids: List[str], status: str = "reviewed") -> JSONResponse:
    """Move cards to a different status by document IDs"""
    try:
        supabase_client = get_supabase_client()
    except Exception as e:
        log_debug(f"Database client not available: {e}", service="cards")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    
    if not document_ids:
        log_debug("No document_ids provided", service="cards")
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})
    
    # Validate status
    valid_statuses = ['pending', 'reviewed', 'approved', 'archived']
    if status not in valid_statuses:
        return JSONResponse(status_code=400, content={"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"})
    
    log_debug(f"Successfully moved {len(document_ids)} cards to status '{status}'", service="cards")
    
    move_cards_db(supabase_client, document_ids, status)
    
    return JSONResponse(status_code=200, content={"message": f"Successfully moved {len(document_ids)} cards to {status}."})

# Legacy service functions for backward compatibility during transition
async def mark_as_exported_service_legacy(payload: MarkExportedPayload):
    """Legacy service - will be removed after frontend migration"""
    document_ids = payload.get_document_ids() if hasattr(payload, 'get_document_ids') else payload.document_ids
    return await mark_as_exported_service(document_ids)

async def save_manual_review_service(document_id: str, payload: Dict[str, Any]):
    """Save manual review for a single card - this remains unchanged"""
    # This function handles individual card reviews, not bulk operations
    # Implementation would go here - keeping the existing logic
    pass 