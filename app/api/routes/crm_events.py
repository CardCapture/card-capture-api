from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from app.core.auth import get_current_user
from app.controllers.crm_events_controller import (
    list_crm_events_controller,
    create_crm_event_controller,
    update_crm_event_controller,
    delete_crm_event_controller,
    bulk_delete_crm_events_controller,
    upload_csv_controller,
    search_crm_events_controller
)
from typing import List, Optional
import json

router = APIRouter(tags=["CRM Events"])

# Temporary mock user for development
def get_mock_user():
    return {
        "id": "f8714b88-f5c7-404c-b4fa-2304e014a44b",
        "school_id": "b1a2c3d4-e5f6-7890-1234-56789abcdef0",
        "role": ["admin"],
        "email": "kreg@cardcapture.io"
    }

@router.get("/crm-events")
async def list_crm_events(user=Depends(get_mock_user)):
    """List all CRM events for the user's school"""
    return await list_crm_events_controller(user)

@router.post("/crm-events")
async def create_crm_event(
    payload: dict,
    user=Depends(get_mock_user)
):
    """Create a single CRM event"""
    return await create_crm_event_controller(user, payload)

@router.put("/crm-events/{event_id}")
async def update_crm_event(
    event_id: str,
    payload: dict,
    user=Depends(get_mock_user)
):
    """Update a CRM event"""
    return await update_crm_event_controller(user, event_id, payload)

@router.delete("/crm-events/bulk")
async def bulk_delete_crm_events(
    event_ids: List[str],
    user=Depends(get_mock_user)
):
    """Bulk delete CRM events"""
    return await bulk_delete_crm_events_controller(user, event_ids)

@router.delete("/crm-events/{event_id}")
async def delete_crm_event(
    event_id: str,
    user=Depends(get_mock_user)
):
    """Delete a single CRM event"""
    return await delete_crm_event_controller(user, event_id)

@router.post("/crm-events/upload")
async def upload_csv(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    user=Depends(get_mock_user)
):
    """Upload and process CSV file with column mapping"""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    # Parse the mapping JSON string
    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid mapping format")
    
    return await upload_csv_controller(user, file, mapping_dict)

@router.get("/crm-events/search")
async def search_crm_events(
    q: str,
    user=Depends(get_mock_user)
):
    """Search CRM events for type-ahead functionality"""
    if len(q) < 2:
        return {"results": []}
    
    return await search_crm_events_controller(user, q)