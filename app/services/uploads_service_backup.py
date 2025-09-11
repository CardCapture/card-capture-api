import os
import shutil
import tempfile
import uuid
import time
from fastapi.responses import JSONResponse, FileResponse
from app.core.clients import get_supabase_client, docai_client
from app.utils.image_processing import ensure_trimmed_image
from app.utils.storage import upload_to_supabase_storage_from_path
from app.repositories.uploads_repository import (
    insert_processing_job_db,
    insert_extracted_data_db,
    select_extracted_data_image_db,
    update_processing_job_db
)
from PIL import Image
import csv
import io
from google.cloud import documentai_v1 as documentai
from app.config import PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID, TRIMMED_FOLDER
import json
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug
from datetime import datetime, timezone
from typing import Dict, Any

# Try to import SFTP utils, but gracefully handle if not available
try:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sftp_utils import upload_to_slate
    SFTP_AVAILABLE = True
    log_debug("SFTP functionality loaded successfully", service="uploads")
except ImportError as e:
    log_debug(f"SFTP functionality not available: {str(e)}", service="uploads")
    SFTP_AVAILABLE = False
    upload_to_slate = None

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
        log_debug(f"Error splitting PDF {pdf_path}: {e}", service="uploads")
        return []

async def upload_file_service(file, school_id, event_id, user):
    try:
        # Initialize Supabase client
        supabase_client = get_supabase_client()
        
        if not file:
            return JSONResponse(status_code=400, content={"error": "No file uploaded."})
        
        # Reject files that aren't images or PDFs
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/tiff", "application/pdf"]
        if file.content_type not in allowed_types:
            return JSONResponse(
                status_code=400, 
                content={
                    "error": f"File type {file.content_type} not supported. Allowed types: {', '.join(allowed_types)}"
                }
            )
        
        # Create a temporary file path for the uploaded file
        temp_file_path = None
        try:
            # Read file content into memory first
            file_content = await file.read()
            original_size = len(file_content)
            
            log_debug(f"Received upload request for file: {file.filename}", {
                "size": f"{original_size/1024:.1f}KB",
                "type": file.content_type,
                "school_id": school_id,
                "event_id": event_id
            }, service="uploads")
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
                temp_file_path = temp_file.name
                temp_file.write(file_content)
            
            # Handle PDF files
            if file.content_type == "application/pdf":
                return await handle_pdf_upload(temp_file_path, file.filename, school_id, event_id, user)
            
            # Handle image files
            compressed_file_path = None
            try:
                log_debug(f"Compressing image before upload: {file.filename}", service="uploads")
                
                # Open and compress the image
                with Image.open(temp_file_path) as img:
                    # Convert to RGB if necessary
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    
                    # Resize if too large
                    max_size = (2048, 2048)
                    if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                        img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    
                    # Save compressed version
                    compressed_file_path = temp_file_path + "_compressed.jpg"
                    img.save(compressed_file_path, "JPEG", quality=85, optimize=True)
                
                # Get compressed size
                compressed_size = os.path.getsize(compressed_file_path)
                log_debug(f"File sizes - Original: {original_size/1024:.1f}KB, Compressed: {compressed_size/1024:.1f}KB", service="uploads")
                
                # Generate unique filename for storage
                file_extension = ".jpg"  # Always save as JPG after compression
                unique_filename = f"{uuid.uuid4().hex}{file_extension}"
                storage_folder = TRIMMED_FOLDER or "trimmed"
                storage_path = f"{storage_folder}/{unique_filename}"
                
                log_debug(f"File uploaded to storage: {storage_path}", service="uploads")
                
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
                    log_debug(f"Worker notification failed for job {job_id}, but job is queued and worker may pick it up", {
                        "error": str(worker_error),
                        "job_id": job_id
                    }, service="uploads")
                
                return JSONResponse(status_code=200, content={
                    "message": "File uploaded successfully",
                    "job_id": job_id,
                    "document_id": job_id
                })
                
            finally:
                # Clean up compressed file
                if compressed_file_path and os.path.exists(compressed_file_path):
                    os.unlink(compressed_file_path)
                
        finally:
            # Clean up original temp file
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        log_debug(f"Error uploading file: {e}", service="uploads")
        import traceback
        log_debug("Full traceback:", traceback.format_exc(), service="uploads")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def handle_pdf_upload(pdf_path: str, original_filename: str, school_id: str, event_id: str, user):
    """
    Handle PDF upload by splitting into individual PNG files and creating separate jobs
    """
    try:
        # Initialize Supabase client
        supabase_client = get_supabase_client()
        
        log_debug(f"Entering PDF processing block for file: {original_filename}", {
            "pdf_path": pdf_path,
            "original_filename": original_filename
        }, service="uploads")
        
        # Split PDF into PNG files
        png_paths = split_pdf_to_pngs(pdf_path)
        log_debug(f"split_pdf_to_pngs returned {len(png_paths)} images: {png_paths}", service="uploads")
        
        if not png_paths:
            log_debug(f"No PNGs were generated from PDF: {pdf_path}", service="uploads")
            return JSONResponse(status_code=400, content={"error": "Failed to extract images from PDF"})
        
        job_ids = []
        document_ids = []
        
        try:
            for i, png_path in enumerate(png_paths):
                log_debug(f"Processing page {i+1}: {png_path}", service="uploads")
                
                # Convert PNG to JPG
                with Image.open(png_path) as img:
                    # Convert to RGB if necessary
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    
                    # Save as JPG
                    jpg_path = png_path.replace('.png', '.jpg')
                    img.save(jpg_path, "JPEG", quality=85, optimize=True)
                    log_debug(f"Converted PNG to JPG: {jpg_path}", service="uploads")
                
                # Upload to storage with proper JPG filename
                page_filename = f"{os.path.splitext(original_filename)[0]} (Page {i+1}).jpg"
                log_debug(f"Generated page filename: {page_filename}", service="uploads")
                
                storage_path = upload_to_supabase_storage_from_path(
                    supabase_client, 
                    jpg_path, 
                    user.get("id"), 
                    page_filename  # Use filename with .jpg extension
                )
                
                log_debug(f"Storage upload completed. Storage path: {storage_path}", service="uploads")
                
                # Create processing job for this page
                job_data = {
                    "user_id": user.get("id"),
                    "school_id": school_id,
                    "file_url": storage_path,
                    "status": "queued",
                    "event_id": event_id,
                    "image_path": storage_path  # This will be the JPG storage path
                }
                
                log_debug(f"Created job data for page {i+1}", {
                    "job_data": job_data,
                    "file_url": storage_path,
                    "image_path": storage_path
                }, service="uploads")
                
                result = insert_processing_job_db(supabase_client, job_data)
                if not result:
                    raise Exception(f"Failed to create processing job for page {i+1}")
                
                job_id = result[0]["id"]
                job_ids.append(job_id)
                document_ids.append(str(job_id))  # Use job_id as document identifier
                
                log_debug(f"Successfully created job {job_id} for page {i+1} with paths", {
                    "job_id": job_id,
                    "file_url": storage_path,
                    "image_path": storage_path,
                    "page": i+1
                }, service="uploads")
                
                # Clean up temporary files
                os.unlink(png_path)
                os.unlink(jpg_path)
                
                # Notify worker with retry mechanism
                try:
                    await notify_worker_with_retry(job_id, job_data)
                except Exception as worker_error:
                    log_debug(f"Worker notification failed for bulk upload job {job_id}, but job is queued", {
                        "error": str(worker_error),
                        "job_id": job_id,
                        "page": i+1
                    }, service="uploads")
        
        finally:
            # Clean up any remaining PNG files
            for png_path in png_paths:
                if os.path.exists(png_path):
                    os.unlink(png_path)
                jpg_path = png_path.replace('.png', '.jpg')
                if os.path.exists(jpg_path):
                    os.unlink(jpg_path)
        
        return JSONResponse(status_code=200, content={
            "message": f"PDF uploaded successfully. Split into {len(png_paths)} images.",
            "job_ids": job_ids,
            "document_ids": document_ids,
            "total_pages": len(png_paths)
        })
        
    except Exception as e:
        log_debug(f"Error splitting PDF {pdf_path}: {e}", service="uploads")
        import traceback
        log_debug("Full traceback:", traceback.format_exc(), service="uploads")
        return JSONResponse(status_code=500, content={"error": f"Failed to process PDF: {str(e)}"})

async def check_upload_status_service(job_id: str):
    try:
        supabase_client = get_supabase_client()
        result = supabase_client.table("processing_jobs").select("*").eq("id", job_id).execute()
        if result.data:
            return JSONResponse(status_code=200, content=result.data[0])
        else:
            return JSONResponse(status_code=404, content={"error": "Job not found"})
    except Exception as e:
        log_debug(f"Error checking upload status: {e}", service="uploads")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def get_image_service(document_id: str):
    try:
        log_debug(f"Image requested for document_id: {document_id}", service="uploads")
        
        # Query the extracted_data table to get the image path
        result = select_extracted_data_image_db(supabase_client, document_id)
        
        if result and result.data:
            image_path = result.data[0].get("image_path")
            log_debug(f"Found image path: {image_path}", service="uploads")
            
            # Download from Supabase storage and return
            try:
                storage_response = supabase_client.storage.from_("cards-uploads").download(image_path)
                return FileResponse(
                    path=io.BytesIO(storage_response),
                    media_type="image/jpeg",
                    filename=f"{document_id}.jpg"
                )
            except Exception as download_error:
                log_debug(f"File not found at path: {image_path}", {"error": str(download_error)}, service="uploads")
                return JSONResponse(status_code=404, content={"error": "Image file not found in storage"})
        else:
            log_debug(f"No database record found for document_id: {document_id}", service="uploads")
            return JSONResponse(status_code=404, content={"error": "Document not found"})
            
    except Exception as e:
        log_debug(f"Error retrieving image for {document_id}: {e}", service="uploads")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def export_to_slate_service(payload: dict):
    try:
        # Initialize Supabase client
        supabase_client = get_supabase_client()
        
        # Check if SFTP functionality is available
        if not SFTP_AVAILABLE:
            return JSONResponse(status_code=503, content={
                "error": "SFTP functionality is not available. Please ensure sftp_utils.py is properly configured."
            })
            
        school_id = payload.get("school_id")
        rows = payload.get("rows")
        if not school_id or not rows or not isinstance(rows, list):
            return JSONResponse(status_code=400, content={"error": "Missing or invalid school_id or rows."})
        
        log_debug(f"SLATE EXPORT: Processing export for school_id: {school_id} with {len(rows)} rows", service="uploads")
        
        # Fetch SFTP configuration from sftp_configs table
        try:
            sftp_config_result = supabase_client.table("sftp_configs").select("*").eq("school_id", school_id).eq("enabled", True).execute()
            
            if sftp_config_result.data:
                sftp_data = sftp_config_result.data[0]
                sftp_config = {
                    "host": sftp_data["host"],
                    "port": sftp_data.get("port", 22),
                    "username": sftp_data["username"],
                    "password": sftp_data["password"],
                    "remote_directory": sftp_data["remote_path"]
                }
                log_debug(f"SLATE EXPORT: Found SFTP config - Host: {sftp_config['host']}, Username: {sftp_config['username']}", service="uploads")
            else:
                log_debug(f"SLATE EXPORT: No enabled SFTP configuration found for school_id: {school_id}", service="uploads")
                return JSONResponse(status_code=400, content={"error": "No enabled SFTP configuration found for this school."})
            
        except Exception as e:
            log_debug(f"SLATE EXPORT: Error fetching SFTP config: {str(e)}", service="uploads")
            return JSONResponse(status_code=500, content={"error": f"Failed to fetch SFTP configuration: {str(e)}"})
        
        # Fetch school's card fields configuration
        try:
            school_result = supabase_client.table("schools").select("card_fields").eq("id", school_id).execute()
            
            if school_result.data and school_result.data[0].get("card_fields"):
                card_fields = school_result.data[0]["card_fields"]
                log_debug(f"SLATE EXPORT: Found card_fields configuration for school_id: {school_id}", service="uploads")
            else:
                log_debug(f"SLATE EXPORT: No card_fields configuration found for school_id: {school_id}, using default fields", service="uploads")
                # Default fallback fields
                card_fields = [
                    {"key": "name", "enabled": True, "required": True},
                    {"key": "email", "enabled": True, "required": True},
                    {"key": "cell", "enabled": True, "required": False},
                    {"key": "address", "enabled": True, "required": False},
                    {"key": "city", "enabled": True, "required": False},
                    {"key": "state", "enabled": True, "required": False},
                    {"key": "zip_code", "enabled": True, "required": False},
                    {"key": "major", "enabled": True, "required": False},
                    {"key": "mapped_major", "enabled": True, "required": False}
                ]
                
        except Exception as e:
            log_debug(f"SLATE EXPORT: Error fetching card fields: {str(e)}", service="uploads")
            return JSONResponse(status_code=500, content={"error": f"Failed to fetch card fields configuration: {str(e)}"})
        
        # Required SFTP fields
        required_fields = ["host", "username", "password", "remote_directory"]
        missing_fields = [field for field in required_fields if not sftp_config.get(field)]
        
        if missing_fields:
            return JSONResponse(status_code=400, content={
                "error": f"SFTP configuration is missing required fields: {', '.join(missing_fields)}"
            })
        
        # Generate CSV content using dynamic card fields with pretty headers
        csv_content = io.StringIO()
        
        # Standard field labels mapping (same as frontend csvExport.ts)
        field_labels_map = {
            'event_name': 'Event Name',
            'slate_event_id': 'Event ID',
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email',
            'cell': 'Cell Phone',
            'phone': 'Phone Number',
            'date_of_birth': 'Birthday',
            'birthday': 'Birthday',
            'permission_to_text': 'Permission to Text',
            'address': 'Address',
            'city': 'City',
            'state': 'State',
            'zip_code': 'Zip Code',
            'zip': 'Zip Code',
            'high_school': 'High School',
            'ceeb_code': 'CEEB Code',
            'class_rank': 'Class Rank',
            'students_in_class': 'Students in Class',
            'gpa': 'GPA',
            'student_type': 'Student Type',
            'entry_term': 'Entry Term',
            'major': 'Major',
            'mapped_major': 'Mapped Major',
            'middle_initial': 'Middle Initial',
            'preferred_name': 'Preferred Name',
            'date_created': 'Date Created'
        }
        
        # Extract enabled field keys from card_fields configuration
        field_keys = []
        for field_config in card_fields:
            if isinstance(field_config, dict) and field_config.get("enabled", False):
                field_key = field_config.get("key")
                if field_key:
                    # Replace 'name' with 'first_name' and 'last_name' for better Slate compatibility
                    if field_key == "name":
                        field_keys.extend(["first_name", "last_name"])
                    else:
                        field_keys.append(field_key)
        
        # Add common fields that might not be in card_fields but are useful for export
        additional_fields = ["event_name", "slate_event_id", "date_created"]
        for field in additional_fields:
            if field not in field_keys:
                field_keys.append(field)
        
        # Convert field keys to pretty headers
        headers = []
        for field_key in field_keys:
            pretty_label = field_labels_map.get(field_key, field_key.replace('_', ' ').title())
            headers.append(pretty_label)
        
        log_debug(f"SLATE EXPORT: Using CSV headers: {headers}", service="uploads")
        log_debug(f"SLATE EXPORT: Field keys mapping: {field_keys}", service="uploads")
        
        def split_name(full_name):
            """Split a full name into first name and last name"""
            if not full_name or not isinstance(full_name, str):
                return {"first_name": "", "last_name": ""}
            
            trimmed_name = full_name.strip()
            if not trimmed_name:
                return {"first_name": "", "last_name": ""}
            
            # Split by spaces and filter out empty strings
            name_parts = [part for part in trimmed_name.split() if part]
            
            if len(name_parts) == 0:
                return {"first_name": "", "last_name": ""}
            elif len(name_parts) == 1:
                # Only one name part - treat as first name
                return {"first_name": name_parts[0], "last_name": ""}
            elif len(name_parts) == 2:
                # Two parts - first and last
                return {"first_name": name_parts[0], "last_name": name_parts[1]}
            else:
                # Three or more parts - first name is first part, last name is everything else
                return {"first_name": name_parts[0], "last_name": " ".join(name_parts[1:])}
        
        writer = csv.DictWriter(csv_content, fieldnames=headers)
        writer.writeheader()
        
        # Track document_ids for marking as exported
        document_ids = []
        
        for row in rows:
            # Extract document_id for tracking
            document_id = row.get("document_id")
            if document_id:
                document_ids.append(document_id)
            
            # Prepare row data for CSV using pretty headers
            csv_row = {}
            for i, header in enumerate(headers):
                # Get the corresponding field key for this header
                field_key = field_keys[i] if i < len(field_keys) else header
                
                # Check if this is a field that should come from the nested fields object
                if field_key in ["event_name", "slate_event_id", "date_created", "document_id"]:
                    # These are top-level fields
                    csv_row[header] = row.get(field_key, "")
                elif field_key in ["first_name", "last_name"]:
                    # Handle name splitting
                    fields_data = row.get("fields", {})
                    if isinstance(fields_data, dict):
                        # Try separate first/last name fields first
                        if field_key == "first_name":
                            first_name_data = fields_data.get("first_name", {})
                            if first_name_data:
                                if isinstance(first_name_data, dict):
                                    csv_row[header] = str(first_name_data.get("value", ""))
                                else:
                                    csv_row[header] = str(first_name_data)
                                continue
                        elif field_key == "last_name":
                            last_name_data = fields_data.get("last_name", {})
                            if last_name_data:
                                if isinstance(last_name_data, dict):
                                    csv_row[header] = str(last_name_data.get("value", ""))
                                else:
                                    csv_row[header] = str(last_name_data)
                                continue
                        
                        # Fallback to splitting full name
                        name_field_data = fields_data.get("name", {})
                        full_name = ""
                        
                        if isinstance(name_field_data, dict):
                            full_name = str(name_field_data.get("value", ""))
                        else:
                            full_name = str(name_field_data) if name_field_data else ""
                        
                        name_parts = split_name(full_name)
                        csv_row[header] = name_parts.get(field_key, "")
                    else:
                        csv_row[header] = ""
                else:
                    # These are card fields - extract from nested fields object
                    fields_data = row.get("fields", {})
                    if isinstance(fields_data, dict):
                        # Try alternative field names for common mappings
                        field_data = fields_data.get(field_key, {})
                        if not field_data:
                            # Try alternative field names
                            alternatives = {
                                'cell': ['phone', 'cell_phone', 'home_phone'],
                                'phone': ['cell', 'cell_phone', 'home_phone'],
                                'date_of_birth': ['birthday', 'birth_date'],
                                'birthday': ['date_of_birth', 'birth_date'],
                                'zip_code': ['zip', 'postal_code'],
                                'zip': ['zip_code', 'postal_code']
                            }
                            if field_key in alternatives:
                                for alt_field in alternatives[field_key]:
                                    field_data = fields_data.get(alt_field, {})
                                    if field_data:
                                        break
                        
                        if isinstance(field_data, dict):
                            csv_row[header] = field_data.get("value", "")
                        else:
                            csv_row[header] = str(field_data) if field_data else ""
                    else:
                        csv_row[header] = ""
            
            writer.writerow(csv_row)
        
        # Generate filename with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        csv_filename = f"slate_export_{school_id}_{timestamp}.csv"
        
        log_debug(f"SLATE EXPORT: Generated CSV file with {len(rows)} records: {csv_filename}", service="uploads")
        
        # Upload to SFTP server
        temp_csv_path = None
        try:
            log_debug(f"SLATE EXPORT: Connecting to SFTP server: {sftp_config['host']}", service="uploads")
            
            # Create temporary CSV file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as temp_csv:
                temp_csv_path = temp_csv.name
                temp_csv.write(csv_content.getvalue())
            
            # Construct remote path
            remote_directory = sftp_config["remote_directory"].rstrip("/")
            remote_path = f"{remote_directory}/{csv_filename}"
            
            # Create SFTPConfig object for upload_to_slate
            from sftp_utils import SFTPConfig
            config = SFTPConfig()
            config.host = sftp_config["host"]
            config.port = sftp_config.get("port", 22)
            config.username = sftp_config["username"]
            config.password = sftp_config["password"]
            config.upload_path = sftp_config["remote_directory"]
            
            # Use the upload_to_slate function
            upload_success = upload_to_slate(temp_csv_path, config)
            
            if upload_success:
                log_debug(f"SLATE EXPORT: Successfully uploaded file to: {remote_path}", service="uploads")
            else:
                raise Exception("SFTP upload returned False")
                
        except Exception as e:
            log_debug(f"SLATE EXPORT: SFTP upload failed: {str(e)}", service="uploads")
            return JSONResponse(status_code=500, content={
                "error": f"Failed to upload to SFTP server: {str(e)}"
            })
        finally:
            # Clean up temporary CSV file
            if temp_csv_path and os.path.exists(temp_csv_path):
                os.unlink(temp_csv_path)
        
        # Mark records as exported in database
        if document_ids:
            try:
                from app.services.cards_service import mark_as_exported_service
                
                result = await mark_as_exported_service(document_ids)
                
                if hasattr(result, 'status_code') and result.status_code == 200:
                    log_debug(f"SLATE EXPORT: Successfully marked {len(document_ids)} records as exported in database", service="uploads")
                else:
                    log_debug(f"SLATE EXPORT: Warning - Failed to mark records as exported: {str(result)}", service="uploads")
                    
            except Exception as e:
                log_debug(f"SLATE EXPORT: Warning - Failed to mark records as exported: {str(e)}", service="uploads")
        
        # Success response
        log_debug(f"SLATE EXPORT SUCCESS: Exported {len(rows)} records to Slate for school_id: {school_id}", {
            "filename": csv_filename,
            "records_exported": len(document_ids) if document_ids else 0
        }, service="uploads")
        
        return JSONResponse(status_code=200, content={
            "message": "Export completed successfully",
            "filename": csv_filename,
            "records_exported": len(rows),
            "remote_path": remote_path
        })
        
    except Exception as e:
        log_debug(f"SLATE EXPORT: Unexpected error: {str(e)}", service="uploads")
        import traceback
        log_debug("Full traceback:", traceback.format_exc(), service="uploads")
        return JSONResponse(status_code=500, content={"error": f"Export failed: {str(e)}"})

async def notify_worker_with_retry(job_id: str, job_data: dict):
    """
    Simplified - just calls notify_worker since database trigger handles everything
    """
    return await notify_worker(job_id, job_data)

async def notify_worker(job_id: str, job_data: dict):
    """
    Database trigger will handle calling the CloudRun worker via edge function.
    This function just logs that the job was created successfully.
    """
    log_debug(f"✅ Job {job_id} created - database trigger will call edge function → CloudRun worker", service="uploads")
    return True

async def notify_processing_complete_service(supabase_client, job_data: Dict[str, Any]):
    """
    Simplified notification service - just updates the job status.
    """
    log_debug("Processing notification", {
        "job_id": job_data.get("id"),
        "status": job_data.get("status")
    }, service="uploads")
    
    try:
        # Just update the job status - removed upload_notifications table usage
        result = update_processing_job_db(supabase_client, job_data["id"], {
            "status": "complete",
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        
        log_debug("Job status updated successfully", {"job_id": job_data["id"]}, service="uploads")
        return result
    except Exception as e:
        log_debug(f"Failed to update job status: {str(e)}", service="uploads")
        raise e 