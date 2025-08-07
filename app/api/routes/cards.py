from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any, List, Union
from datetime import datetime, timezone
import traceback
import uuid

from app.models.card import BulkActionPayload, MarkExportedPayload
from app.services.cards_service import (
    mark_as_exported_service,
    archive_cards_service,
    delete_cards_service,
    move_cards_service,
    save_manual_review_service,
    get_cards_service
)
from app.core.clients import get_supabase_client
from app.repositories.reviewed_data_repository import upsert_reviewed_data
# Removed import: canonicalize_fields - no longer using canonicalization
from app.utils.field_utils import filter_combined_fields
from app.utils.retry_utils import log_debug
from app.models.address_suggestions import AddressSuggestionsRequest, AddressSuggestionsResponse
from app.services.address_suggestions_service import get_address_suggestions
from app.services.address_validation_service import validate_address_realtime

router = APIRouter()

# Define required fields that determine review status
REQUIRED_FIELDS = ["address", "cell", "city", "state", "zip_code", "name", "email"]

@router.get("/cards", response_model=List[Dict[str, Any]])
async def get_cards(event_id: Union[str, None] = None):
    return await get_cards_service(event_id)

@router.post("/archive-cards")
async def archive_cards(payload: BulkActionPayload):
    """
    Archive cards - standardized endpoint
    """
    print(f"📁 Archive cards - document_ids: {payload.document_ids}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    return await archive_cards_service(payload.document_ids)

@router.post("/mark-exported")
async def mark_as_exported(payload: BulkActionPayload):
    """
    Mark cards as exported - standardized endpoint
    """
    print(f"📤 Mark as exported - document_ids: {payload.document_ids}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    return await mark_as_exported_service(payload.document_ids)

@router.post("/debug-mark-exported")
async def debug_mark_exported(payload: Dict[str, Any] = Body(...)):
    """Debug endpoint to see what payload is being sent"""
    print(f"🐛 DEBUG: Raw payload received: {payload}")
    print(f"🐛 DEBUG: Payload type: {type(payload)}")
    print(f"🐛 DEBUG: Payload keys: {list(payload.keys()) if isinstance(payload, dict) else 'Not a dict'}")
    
    document_ids = None
    if isinstance(payload, dict):
        document_ids = payload.get('document_ids') or payload.get('documentIds') or payload.get('ids')
    
    print(f"🐛 DEBUG: Extracted document_ids: {document_ids}")
    
    return JSONResponse(status_code=200, content={
        "received_payload": payload,
        "extracted_document_ids": document_ids
    })

@router.post("/delete-cards")
async def delete_cards(payload: BulkActionPayload):
    """
    Delete cards - standardized endpoint
    """
    print(f"🗑️ Delete cards - document_ids: {payload.document_ids}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    return delete_cards_service(payload.document_ids)

@router.post("/move-cards")
async def move_cards(payload: BulkActionPayload):
    """
    Move cards - standardized endpoint
    """
    print(f"📦 Move cards - document_ids: {payload.document_ids}, status: {payload.status}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    status = payload.status or "reviewed"
    return move_cards_service(payload.document_ids, status)

@router.post("/save-review/{document_id}")
async def save_manual_review(document_id: str, payload: Dict[str, Any] = Body(...)):
    """
    Save manual review changes for a card
    """
    try:
        # Get current card data
        supabase_client = get_supabase_client()
        current_card = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
        if not current_card or not current_card.data:
            raise HTTPException(status_code=404, detail="Card not found")

        current_fields_data = current_card.data.get("fields", {})
        updated_fields = payload.get("fields", {})
        frontend_status = payload.get("status")

        # Note: Canonicalization removed - field names from frontend are used directly

        # Update fields based on user input
        for key, field_data in updated_fields.items():
            if key in current_fields_data:
                # Preserve the original review status
                current_fields_data[key].update({
                    **field_data,
                    "value": field_data.get("value", current_fields_data[key].get("value", "")),
                    "reviewed": field_data.get("reviewed", current_fields_data[key].get("reviewed", False)),
                    "requires_human_review": field_data.get("requires_human_review", current_fields_data[key].get("requires_human_review", False)),
                    "review_notes": field_data.get("review_notes", current_fields_data[key].get("review_notes", "")),
                    "source": "human_review"
                })
            else:
                # For new fields, set default values
                current_fields_data[key] = {
                    **field_data,
                    "reviewed": False,
                    "requires_human_review": False,
                    "review_notes": "",
                    "source": "human_review"
                }

        # Check if any required fields still need review
        any_required_field_needs_review = False
        for field_name in REQUIRED_FIELDS:
            field_data = current_fields_data.get(field_name, {})
            if isinstance(field_data, dict):
                # A field needs review if it's marked as requiring review AND hasn't been manually reviewed
                requires_review = field_data.get("requires_human_review", True)
                is_manually_reviewed = field_data.get("reviewed", False)
                
                # If a field requires review but hasn't been manually marked as reviewed, it still needs review
                if requires_review and not is_manually_reviewed:
                    print(f"Field {field_name} needs review (requires_human_review: {requires_review}, manually_reviewed: {is_manually_reviewed})")
                    any_required_field_needs_review = True
                    break

        # Use the frontend status if provided, otherwise determine based on fields
        review_status = frontend_status if frontend_status else ("needs_human_review" if any_required_field_needs_review else "reviewed")

        # Filter out combined fields before saving
        filtered_fields = filter_combined_fields(current_fields_data)

        # Update the card
        update_data = {
            "document_id": document_id,
            "fields": filtered_fields,  # Use filtered fields without combined address fields
            "review_status": review_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "school_id": current_card.data.get("school_id"),  # Preserve school_id
            "event_id": current_card.data.get("event_id"),    # Preserve event_id
            "image_path": current_card.data.get("image_path") # Preserve image_path
        }

        response = upsert_reviewed_data(supabase_client, update_data)
        return response.data[0] if response.data else None

    except Exception as e:
        print(f"Error saving review: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/address-suggestions", response_model=AddressSuggestionsResponse)
async def get_address_suggestions_endpoint(payload: AddressSuggestionsRequest):
    """
    Get real-time address suggestions for review modal
    
    Provides multiple ranked suggestions based on:
    - Google Maps validation
    - ZIP code validation  
    - Smart address correction
    
    Used by frontend to show smart preview suggestions when user edits address fields.
    """
    try:
        result = await get_address_suggestions(payload)
        return result
    except Exception as e:
        log_debug(f"Address suggestions endpoint failed: {str(e)}", service="cards_api")
        return AddressSuggestionsResponse(
            success=False,
            has_suggestions=False,
            suggestions=[],
            original_input=payload.dict(),
            validation_attempted=True,
            error=f"Internal server error: {str(e)}"
        )

@router.post("/address/validate")
async def validate_address_endpoint(payload: Dict[str, Any] = Body(...)):
    """
    New consolidated address validation endpoint
    
    Handles the 4-state validation system:
    - verified: Google Maps confirmed exact match
    - can_be_verified: Google Maps found suggestion but not exact match  
    - no_house_number: Address missing house number
    - not_verified: Could not validate address
    
    Used by the new simplified frontend validation flow.
    """
    try:
        address = payload.get("address", "")
        city = payload.get("city", "")
        state = payload.get("state", "")
        zip_code = payload.get("zip_code", "")
        
        log_debug("Address validation endpoint called", {
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code
        }, service="cards_api")
        
        result = validate_address_realtime(address, city, state, zip_code)
        return JSONResponse(status_code=200, content=result)
        
    except Exception as e:
        log_debug(f"Address validation endpoint failed: {str(e)}", service="cards_api")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "validation": {
                    "state": "not_verified",
                    "is_valid": False,
                    "suggestion": None,
                    "error": f"Internal server error: {str(e)}",
                    "original_query": payload
                }
            }
        )

@router.post("/mark-field-reviewed/{document_id}")
async def mark_field_reviewed(document_id: str, payload: Dict[str, Any] = Body(...)):
    """
    Mark specific fields as manually reviewed
    
    Payload should contain:
    {
        "field_name": "address",  // or other field name
        "reviewed": true,         // mark as reviewed
        "review_notes": "User confirmed address is correct as-is"
    }
    
    This allows users to mark problematic fields (like unverifiable addresses) 
    as reviewed so the card can move to 'ready for export' state.
    """
    try:
        field_name = payload.get("field_name")
        reviewed = payload.get("reviewed", True)
        review_notes = payload.get("review_notes", "Manually marked as reviewed")
        
        if not field_name:
            return JSONResponse(status_code=400, content={"error": "field_name is required"})
        
        # Get current card data
        supabase_client = get_supabase_client()
        current_card = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
        if not current_card or not current_card.data:
            raise HTTPException(status_code=404, detail="Card not found")
        
        current_fields_data = current_card.data.get("fields", {})
        
        # Update the specific field
        if field_name in current_fields_data:
            current_fields_data[field_name]["reviewed"] = reviewed
            current_fields_data[field_name]["review_notes"] = review_notes
            current_fields_data[field_name]["source"] = "human_review"
            
            # If marking as reviewed, also set requires_human_review to False
            if reviewed:
                current_fields_data[field_name]["requires_human_review"] = False
        else:
            return JSONResponse(status_code=404, content={"error": f"Field '{field_name}' not found"})
        
        # Check if any required fields still need review after this update
        any_required_field_needs_review = False
        for req_field_name in REQUIRED_FIELDS:
            field_data = current_fields_data.get(req_field_name, {})
            if isinstance(field_data, dict):
                requires_review = field_data.get("requires_human_review", True)
                is_manually_reviewed = field_data.get("reviewed", False)
                
                if requires_review and not is_manually_reviewed:
                    any_required_field_needs_review = True
                    break
        
        # Update review status
        review_status = "needs_human_review" if any_required_field_needs_review else "reviewed"
        
        # Filter out combined fields before saving
        filtered_fields = filter_combined_fields(current_fields_data)
        
        # Update the card
        update_data = {
            "document_id": document_id,
            "fields": filtered_fields,
            "review_status": review_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "school_id": current_card.data.get("school_id"),
            "event_id": current_card.data.get("event_id"),
            "image_path": current_card.data.get("image_path")
        }
        
        response = upsert_reviewed_data(supabase_client, update_data)
        
        return JSONResponse(status_code=200, content={
            "message": f"Field '{field_name}' marked as reviewed",
            "field_updated": field_name,
            "reviewed": reviewed,
            "card_status": review_status,
            "data": response.data[0] if response.data else None
        })
        
    except Exception as e:
        print(f"Error marking field as reviewed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cards/manual")
async def manual_entry(payload: Dict[str, Any] = Body(...)):
    """
    Create a new manual entry in reviewed_data with review_status='reviewed' and no image.
    Expects: { event_id, school_id, fields: { ... } }
    """
    try:
        supabase_client = get_supabase_client()
        event_id = payload.get("event_id")
        school_id = payload.get("school_id")
        fields = payload.get("fields", {})
        if not event_id or not school_id or not fields:
            return JSONResponse(status_code=400, content={"error": "event_id, school_id, and fields are required."})

        # Generate a new document_id
        document_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Mark all fields as reviewed, not requiring human review, confidence 1.0
        reviewed_fields = {}
        for key, field in fields.items():
            reviewed_fields[key] = {
                **field,
                "reviewed": True,
                "requires_human_review": False,
                "confidence": 1.0,
                "source": "manual_entry",
                "review_notes": "Manually entered"
            }

        # Filter out combined fields before saving
        filtered_fields = filter_combined_fields(reviewed_fields)

        record = {
            "document_id": document_id,
            "fields": filtered_fields,  # Use filtered fields without combined address fields
            "review_status": "reviewed",
            "reviewed_at": now,
            "event_id": event_id,
            "school_id": school_id,
            "image_path": None
        }
        response = supabase_client.table("reviewed_data").insert(record).execute()
        if response.data:
            return JSONResponse(status_code=200, content={"message": "Manual entry created", "document_id": document_id, "record": response.data[0]})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to insert manual entry."})
    except Exception as e:
        print(f"❌ Error creating manual entry: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)}) 