from fastapi import APIRouter, Depends, Body
from app.controllers.schools_controller import get_school_controller
from app.core.auth import get_current_user
from app.core.clients import get_supabase_client
from fastapi.responses import JSONResponse
from typing import Dict, Any
import json

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
        
        print(f"[Card Fields Update] Updating school {school_id} with card_fields:")
        print(json.dumps(card_fields, indent=2))
        
        response = supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
        
        if response.data:
            print(f"✅ Successfully updated card_fields for school {school_id}")
            return JSONResponse(status_code=200, content={
                "message": "Card fields updated successfully",
                "school_id": school_id,
                "card_fields": card_fields
            })
        else:
            print(f"❌ Failed to update card_fields for school {school_id}")
            return JSONResponse(status_code=500, content={"error": "Failed to update card fields."})

    except Exception as e:
        print(f"❌ Error updating card fields for school {school_id}: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to update card fields."}) 