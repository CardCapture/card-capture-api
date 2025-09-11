"""
Enhanced Uploads Service with PhotoRoom and HEIC Support
"""

import os
import shutil
import tempfile
import uuid
import time
from fastapi.responses import JSONResponse, FileResponse
from app.core.clients import get_supabase_client, docai_client
from app.utils.image_processing_integrated import ensure_trimmed_image
from app.utils.storage import upload_to_supabase_storage_from_path
from app.repositories.uploads_repository import (
    insert_processing_job_db,
    insert_extracted_data_db,
    select_extracted_data_image_db,
    update_processing_job_db
)
from PIL import Image
import pillow_heif
import csv
import io
from google.cloud import documentai_v1 as documentai
from app.config import PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID, TRIMMED_FOLDER
import json
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug
from datetime import datetime, timezone
from typing import Dict, Any
from pathlib import Path

# Register HEIF opener for HEIC support
try:
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
    log_debug("HEIC support enabled", service="uploads_v2")
except:
    HEIC_SUPPORT = False
    log_debug("HEIC support not available", service="uploads_v2")

# Try to import SFTP utils
try:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sftp_utils import upload_to_slate
    SFTP_AVAILABLE = True
    log_debug("SFTP functionality loaded successfully", service="uploads_v2")
except ImportError as e:
    log_debug(f"SFTP functionality not available: {str(e)}", service="uploads_v2")
    SFTP_AVAILABLE = False
    upload_to_slate = None


def convert_heic_to_jpeg(heic_path: str) -> str:
    """
    Convert HEIC/HEIF file to JPEG
    Returns path to converted file
    """
    try:
        log_debug(f"Converting HEIC file: {heic_path}", service="uploads_v2")
        
        # Open HEIC image
        img = Image.open(heic_path)
        
        # Convert to RGB if necessary
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Save as JPEG
        jpeg_path = heic_path.replace('.heic', '.jpg').replace('.HEIC', '.jpg').replace('.heif', '.jpg').replace('.HEIF', '.jpg')
        img.save(jpeg_path, 'JPEG', quality=95, optimize=True)
        
        log_debug(f"HEIC converted to JPEG: {jpeg_path}", service="uploads_v2")
        return jpeg_path
        
    except Exception as e:
        log_debug(f"Error converting HEIC: {e}", service="uploads_v2")
        raise


def split_pdf_to_pngs(pdf_path, output_dir=None):
    """
    Split PDF into PNG files and return list of PNG file paths
    """
    try:
        import fitz  # PyMuPDF
        
        if output_dir is None:
            output_dir = tempfile.mkdtemp()
        
        pdf_document = fitz.open(pdf_path)
        png_paths = []
        
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better quality
            
            png_filename = f"page_{page_num + 1}.png"
            png_path = os.path.join(output_dir, png_filename)
            pix.save(png_path)
            png_paths.append(png_path)
        
        pdf_document.close()
        return png_paths
        
    except Exception as e:
        log_debug(f"Error splitting PDF {pdf_path}: {e}", service="uploads_v2")
        return []


async def upload_file_service(file, school_id, event_id, user):
    """
    Enhanced upload service with HEIC and PhotoRoom support
    """
    try:
        # Initialize Supabase client
        supabase_client = get_supabase_client()
        
        if not file:
            return JSONResponse(status_code=400, content={"error": "No file uploaded."})
        
        # Enhanced allowed types including HEIC
        allowed_types = [
            "image/jpeg", "image/jpg", "image/png", "image/gif", 
            "image/bmp", "image/tiff", "image/webp",
            "image/heic", "image/heif",  # Add HEIC support
            "application/pdf"
        ]
        
        # Check file extension if content type is not properly set (common with HEIC)
        file_ext = Path(file.filename).suffix.lower() if file.filename else ""
        
        # Handle HEIC files that might have generic content type
        if file_ext in ['.heic', '.heif'] and file.content_type not in allowed_types:
            file.content_type = "image/heic"
            log_debug(f"Detected HEIC file by extension: {file.filename}", service="uploads_v2")
        
        if file.content_type not in allowed_types and file_ext not in ['.heic', '.heif']:
            return JSONResponse(
                status_code=400, 
                content={
                    "error": f"File type {file.content_type} not supported. Allowed types: {', '.join(allowed_types)}"
                }
            )
        
        # Create a temporary file path for the uploaded file
        temp_file_path = None
        converted_file_path = None
        
        try:
            # Read file content into memory first
            file_content = await file.read()
            original_size = len(file_content)
            
            log_debug(f"Received upload request for file: {file.filename}", {
                "size": f"{original_size/1024:.1f}KB",
                "type": file.content_type,
                "extension": file_ext,
                "school_id": school_id,
                "event_id": event_id
            }, service="uploads_v2")
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext or os.path.splitext(file.filename)[1]) as temp_file:
                temp_file_path = temp_file.name
                temp_file.write(file_content)
            
            # Handle HEIC files - convert to JPEG first
            if file.content_type in ["image/heic", "image/heif"] or file_ext in ['.heic', '.heif']:
                log_debug("Processing HEIC file...", service="uploads_v2")
                
                if not HEIC_SUPPORT:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "HEIC files are not supported on this server. Please convert to JPEG first."}
                    )
                
                converted_file_path = convert_heic_to_jpeg(temp_file_path)
                working_file_path = converted_file_path
                file.content_type = "image/jpeg"  # Update content type
            else:
                working_file_path = temp_file_path
            
            # Handle PDF files
            if file.content_type == "application/pdf":
                return await handle_pdf_upload(working_file_path, file.filename, school_id, event_id, user)
            
            # Handle image files (including converted HEIC)
            compressed_file_path = None
            processed_file_path = None
            
            try:
                log_debug(f"Processing image: {file.filename}", service="uploads_v2")
                
                # Apply PhotoRoom background removal via ensure_trimmed_image
                # This will use PhotoRoom if enabled, otherwise fall back to boundary detection
                processed_file_path = ensure_trimmed_image(working_file_path)
                
                log_debug(f"Image processing complete: {processed_file_path}", service="uploads_v2")
                
                # Open the processed image for final optimization
                with Image.open(processed_file_path) as img:
                    # Convert to RGB if necessary
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    
                    # Resize if too large (but keep good quality for card reading)
                    max_size = (2048, 2048)
                    if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                        img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    
                    # Save compressed version
                    compressed_file_path = processed_file_path + "_final.jpg"
                    img.save(compressed_file_path, "JPEG", quality=90, optimize=True)
                
                # Get compressed size
                compressed_size = os.path.getsize(compressed_file_path)
                log_debug(f"File sizes - Original: {original_size/1024:.1f}KB, Final: {compressed_size/1024:.1f}KB", service="uploads_v2")
                
                # Generate unique filename for storage
                file_extension = ".jpg"
                unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                storage_folder = TRIMMED_FOLDER or "trimmed"
                storage_path = f"{storage_folder}/{unique_filename}"
                
                log_debug(f"Uploading to storage: {storage_path}", service="uploads_v2")
                
                # Upload to storage using the compressed file
                storage_path = upload_to_supabase_storage_from_path(
                    supabase_client,
                    compressed_file_path, 
                    user.get("id"),
                    file.filename
                )
                
                # Create processing job
                job_data = {
                    "user_id": user.get("id"),
                    "school_id": school_id,
                    "file_url": storage_path,
                    "status": "queued",
                    "event_id": event_id,
                    "image_path": storage_path
                }
                
                result = insert_processing_job_db(supabase_client, job_data)
                if not result:
                    raise Exception("Failed to create processing job")
                
                job_id = result[0]["id"]
                
                # Notify worker with retry mechanism
                try:
                    await notify_worker_with_retry(job_id, job_data)
                except Exception as worker_error:
                    log_debug(f"Worker notification failed for job {job_id}, but job is queued", {
                        "error": str(worker_error),
                        "job_id": job_id
                    }, service="uploads_v2")
                
                return JSONResponse(status_code=200, content={
                    "message": "File uploaded successfully",
                    "job_id": job_id,
                    "document_id": job_id,
                    "processed_with": "photoroom" if os.getenv('USE_PHOTOROOM', 'true').lower() == 'true' else "boundary_detection"
                })
                
            finally:
                # Clean up temporary files
                if compressed_file_path and os.path.exists(compressed_file_path):
                    os.unlink(compressed_file_path)
                if processed_file_path and os.path.exists(processed_file_path):
                    os.unlink(processed_file_path)
                
        finally:
            # Clean up original temp files
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            if converted_file_path and os.path.exists(converted_file_path):
                os.unlink(converted_file_path)
                
    except Exception as e:
        log_debug(f"Error uploading file: {e}", service="uploads_v2")
        import traceback
        log_debug("Full traceback:", traceback.format_exc(), service="uploads_v2")
        return JSONResponse(status_code=500, content={"error": str(e)})


async def handle_pdf_upload(pdf_path: str, original_filename: str, school_id: str, event_id: str, user):
    """
    Handle PDF upload by splitting into individual PNG files and creating separate jobs
    """
    try:
        log_debug(f"Processing PDF: {original_filename}", service="uploads_v2")
        
        # Split PDF into PNGs
        png_paths = split_pdf_to_pngs(pdf_path)
        
        if not png_paths:
            return JSONResponse(status_code=400, content={"error": "Failed to process PDF"})
        
        log_debug(f"PDF split into {len(png_paths)} pages", service="uploads_v2")
        
        # Process each page
        job_ids = []
        for i, png_path in enumerate(png_paths):
            try:
                # Process with PhotoRoom/boundary detection
                processed_path = ensure_trimmed_image(png_path)
                
                # Upload to storage
                supabase_client = get_supabase_client()
                storage_path = upload_to_supabase_storage_from_path(
                    supabase_client,
                    processed_path,
                    user.get("id"),
                    f"{original_filename}_page_{i+1}.png"
                )
                
                # Create processing job for this page
                job_data = {
                    "user_id": user.get("id"),
                    "school_id": school_id,
                    "file_url": storage_path,
                    "status": "queued",
                    "event_id": event_id,
                    "image_path": storage_path
                }
                
                result = insert_processing_job_db(supabase_client, job_data)
                if result:
                    job_ids.append(result[0]["id"])
                
            except Exception as e:
                log_debug(f"Error processing PDF page {i+1}: {e}", service="uploads_v2")
            finally:
                # Clean up temp files
                if os.path.exists(png_path):
                    os.unlink(png_path)
                if 'processed_path' in locals() and os.path.exists(processed_path):
                    os.unlink(processed_path)
        
        return JSONResponse(status_code=200, content={
            "message": f"PDF processed into {len(job_ids)} cards",
            "job_ids": job_ids,
            "page_count": len(png_paths)
        })
        
    except Exception as e:
        log_debug(f"Error handling PDF upload: {e}", service="uploads_v2")
        return JSONResponse(status_code=500, content={"error": str(e)})


async def notify_worker_with_retry(job_id: str, job_data: dict):
    """
    Notify worker about new job (stub for actual implementation)
    """
    # This would contain your actual worker notification logic
    pass


# Export the main service functions
async def check_upload_status_service(document_id: str):
    """Check upload status"""
    # Implementation from original
    pass


async def get_image_service(document_id: str):
    """Get image"""
    # Implementation from original
    pass


async def export_to_slate_service(payload: dict):
    """Export to Slate"""
    # Implementation from original
    pass