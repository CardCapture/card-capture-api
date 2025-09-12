from fastapi import APIRouter, File, UploadFile, BackgroundTasks, Form, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from app.controllers.uploads_controller import (
    upload_file_controller,
    check_upload_status_controller,
    get_image_controller,
    export_to_slate_controller
)
from app.core.auth import get_current_user
from app.services.signup_service import process_signup_sheet
from app.utils.storage import upload_to_supabase_storage_from_path
from app.core.clients import get_supabase_client
import tempfile
import os
import uuid

print("UPLOAD ROUTER FILE:", __file__)
print("MODULE NAME:", __name__)

router = APIRouter(tags=["Uploads"])

@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    event_id: str = Form(None),
    school_id: str = Form(...),
    user=Depends(get_current_user)
):
    return await upload_file_controller(background_tasks, file, event_id, school_id, user)

@router.post("/test-upload")
async def test_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    event_id: str = Form(None),
    school_id: str = Form(...)
):
    # Create a test user object with the valid user ID
    test_user = {
        "id": "f8714b88-f5c7-404c-b4fa-2304e014a44b",
        "email": "test@example.com",
        "role": "admin"
    }
    return await upload_file_controller(background_tasks, file, event_id, school_id, test_user)

@router.get("/upload-status/{document_id}")
async def check_upload_status(document_id: str):
    return await check_upload_status_controller(document_id)

@router.get("/images/{document_id}")
async def get_image(document_id: str):
    return await get_image_controller(document_id)

@router.post("/export-to-slate")
async def export_to_slate(payload: dict):
    return await export_to_slate_controller(payload)

@router.post("/upload-signup-sheet")
async def upload_signup_sheet(
    file: UploadFile = File(...),
    event_id: str = Form(...),
    school_id: str = Form(...),
    user=Depends(get_current_user)
):
    """
    Upload and process sign-up sheet (bypasses DocAI, goes directly to Gemini)
    Creates multiple reviewed_data records from a single table image
    """
    try:
        # Validate file type (including HEIC support)
        valid_content_types = [
            'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
            'image/bmp', 'image/tiff', 'image/webp',
            'image/heic', 'image/heif'
        ]
        
        # Check file extension for HEIC files (content type might be generic)
        file_ext = os.path.splitext(file.filename or "")[1].lower() if file.filename else ""
        is_heic = file_ext in ['.heic', '.heif']
        
        if not file.content_type or (not file.content_type.startswith('image/') and not is_heic):
            if not (file.content_type in valid_content_types or is_heic):
                raise HTTPException(
                    status_code=400, 
                    detail="Only image files (including HEIC) are supported for sign-up sheets"
                )
        
        # Validate required fields
        if not event_id or not school_id:
            raise HTTPException(
                status_code=400,
                detail="event_id and school_id are required"
            )
        
        # Save uploaded file to temporary location first
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename or "")[1] or '.jpg') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Upload to permanent storage (similar to regular card uploads)
            supabase_client = get_supabase_client()
            permanent_storage_path = upload_to_supabase_storage_from_path(
                supabase_client,
                tmp_file_path,
                user["id"], 
                f"signup_sheet_{uuid.uuid4().hex}.jpg"
            )
            
            # Process with signup service using permanent storage path
            result = await process_signup_sheet(
                image_path=permanent_storage_path,
                event_id=event_id,
                school_id=school_id,
                user_id=user["id"]
            )
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": f"Successfully processed sign-up sheet. Created {result['records_created']} records.",
                    "records_created": result["records_created"],
                    "records_extracted": result.get("records_extracted", 0),
                    "document_ids": result["document_ids"]
                }
            )
            
        finally:
            # Clean up temporary file (permanent file is now in Supabase storage)
            try:
                os.unlink(tmp_file_path)
            except Exception:
                pass  # Ignore cleanup errors
                
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Sign-up sheet processing failed: {str(e)}"
        ) 