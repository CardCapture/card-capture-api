import os
import mimetypes
import uuid
from datetime import datetime

def upload_to_supabase_storage_from_path(supabase_client, trimmed_path: str, user_id: str, original_filename: str) -> str:
    print(f"[STORAGE DEBUG] === UPLOAD TO SUPABASE STORAGE ===")
    print(f"[STORAGE DEBUG] Trimmed path: {trimmed_path}")
    print(f"[STORAGE DEBUG] User ID: {user_id}")
    print(f"[STORAGE DEBUG] Original filename: {original_filename}")
    print(f"[STORAGE DEBUG] File exists: {os.path.exists(trimmed_path) if trimmed_path else 'N/A'}")
    
    # Generate unique filename to prevent overwrites
    # Each upload gets its own unique path
    today = datetime.now().strftime('%Y-%m-%d')
    file_extension = os.path.splitext(original_filename)[1] or '.jpg'
    unique_filename = f"{uuid.uuid4().hex}{file_extension}"
    storage_path = f"cards-uploads/{user_id}/{today}/{unique_filename}"
    
    print(f"[STORAGE DEBUG] Generated storage path: {storage_path}")
    
    content_type, _ = mimetypes.guess_type(original_filename)
    if not content_type:
        content_type = 'application/octet-stream'
    
    print(f"[STORAGE DEBUG] Content type: {content_type}")
    
    try:
        with open(trimmed_path, "rb") as f:
            trimmed_bytes = f.read()
        
        print(f"[STORAGE DEBUG] File size: {len(trimmed_bytes)} bytes")
        
        # Upload the file with unique path
        res = supabase_client.storage.from_('cards-uploads').upload(
            storage_path.replace('cards-uploads/', ''),
            trimmed_bytes,
            {"content-type": content_type}
        )
        
        if hasattr(res, 'error') and res.error:
            print(f"[STORAGE DEBUG] ❌ Upload error: {res.error}")
            raise Exception(f"Supabase Storage upload error: {res.error}")
        
        print(f"[STORAGE DEBUG] ✅ Upload successful")
        print(f"[STORAGE DEBUG] Final storage path: {storage_path}")
        return storage_path
        
    except Exception as e:
        print(f"[STORAGE DEBUG] ❌ Exception during upload: {str(e)}")
        raise
