import os
import mimetypes
import uuid
from datetime import datetime
from app.utils.retry_utils import log_debug, retry_with_exponential_backoff

def upload_to_supabase_storage_from_path(supabase_client, trimmed_path: str, user_id: str, original_filename: str) -> str:
    log_debug(f"[STORAGE DEBUG] === UPLOAD TO SUPABASE STORAGE ===", service="storage")
    log_debug(f"[STORAGE DEBUG] Trimmed path: {trimmed_path}", service="storage")
    log_debug(f"[STORAGE DEBUG] User ID: {user_id}", service="storage")
    log_debug(f"[STORAGE DEBUG] Original filename: {original_filename}", service="storage")
    log_debug(f"[STORAGE DEBUG] File exists: {os.path.exists(trimmed_path) if trimmed_path else 'N/A'}", service="storage")
    
    # Generate unique filename to prevent overwrites
    # Each upload gets its own unique path
    today = datetime.now().strftime('%Y-%m-%d')
    file_extension = os.path.splitext(original_filename)[1] or '.jpg'
    unique_filename = f"{uuid.uuid4().hex}{file_extension}"
    storage_path = f"cards-uploads/{user_id}/{today}/{unique_filename}"

    log_debug(f"[STORAGE DEBUG] Generated storage path: {storage_path}", service="storage")
    
    content_type, _ = mimetypes.guess_type(original_filename)
    if not content_type:
        content_type = 'application/octet-stream'

    log_debug(f"[STORAGE DEBUG] Content type: {content_type}", service="storage")
    
    try:
        with open(trimmed_path, "rb") as f:
            trimmed_bytes = f.read()

        log_debug(f"[STORAGE DEBUG] File size: {len(trimmed_bytes)} bytes", service="storage")
        
        # Upload the file with retry for transient network failures
        def do_upload():
            return supabase_client.storage.from_('cards-uploads').upload(
                storage_path.replace('cards-uploads/', ''),
                trimmed_bytes,
                {"content-type": content_type}
            )

        res = retry_with_exponential_backoff(
            do_upload,
            max_retries=3,
            base_delay=2.0,
            operation_name="Supabase storage upload",
            service="storage"
        )
        
        if hasattr(res, 'error') and res.error:
            log_debug(f"[STORAGE DEBUG] Upload error: {res.error}", service="storage")
            raise Exception(f"Supabase Storage upload error: {res.error}")

        log_debug(f"[STORAGE DEBUG] Upload successful", service="storage")
        log_debug(f"[STORAGE DEBUG] Final storage path: {storage_path}", service="storage")
        return storage_path

    except Exception as e:
        log_debug(f"[STORAGE DEBUG] Exception during upload: {str(e)}", service="storage")
        raise
