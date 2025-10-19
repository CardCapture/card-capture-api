"""
Sign-up Sheet Processing Service

Handles processing of sign-up sheet table images using Gemini,
creating multiple reviewed_data records from a single upload.
"""

import os
import json
import uuid
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Any
import google.generativeai as genai
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug

def download_from_supabase(file_url: str, local_path: str) -> None:
    """Download file from Supabase storage to local path"""
    try:
        # Get Supabase client
        supabase_client = get_supabase_client()
        
        # Extract bucket and file path from URL
        # Format: "bucket-name/path/to/file.ext"
        url_parts = file_url.split('/', 1)  # Split only on first slash
        if len(url_parts) != 2:
            raise ValueError(f"Invalid file URL format: {file_url}")
            
        bucket_name = url_parts[0]  # "cards-uploads"
        file_path = url_parts[1]    # "user-id/date/filename.ext"
        
        log_debug(f"Downloading from bucket: {bucket_name}, path: {file_path}", service="signup")
        
        # Download file
        response = supabase_client.storage.from_(bucket_name).download(file_path)
        
        with open(local_path, 'wb') as f:
            f.write(response)
            
        log_debug(f"Downloaded file from {file_url} to {local_path}", service="signup")
        
    except Exception as e:
        log_debug(f"ERROR downloading file: {str(e)}", service="signup")
        raise

def build_signup_sheet_prompt(valid_majors: List[str] = None) -> str:
    """Build sign-up sheet extraction prompt with optional major mapping"""

    base_prompt = """You are extracting data from a sign-up sheet table image.

CRITICAL INSTRUCTIONS:
- Extract ONLY filled rows (skip completely empty rows)
- Return a JSON array with one object per completed row
- Standardize all dates to MM/DD/YYYY format
- Clean up handwriting OCR errors
- If a field is blank/unclear, use empty string
- Look for these field patterns in the table columns:

Expected fields (in order they typically appear):
1. first_name (First Name)
2. last_name (Last Name)
3. date_of_birth (Date of Birth, Birthday, DOB - convert to MM/DD/YYYY)
4. email (Email, Email Address)
5. address (Street Address - ONLY the street number and name, no city/state/zip)
6. city (City)
7. state (State - use 2-letter abbreviation like TX, CA, etc.)
8. zip_code (ZIP Code, Postal Code)
9. high_school (Current School, High School)
10. graduation_year (Graduation Year, Grad Year)
11. major (Major, Intended Major, Program of Study - extract exactly as written)
"""

    # Add major mapping instructions if valid_majors provided
    if valid_majors and len(valid_majors) > 0:
        major_list_str = json.dumps(valid_majors, indent=2)
        base_prompt += f"""
12. mapped_major - Map the extracted major to the closest match from this list:
{major_list_str}

MAJOR MAPPING INSTRUCTIONS:
- Always preserve the original 'major' field exactly as written on the sheet
- Create a separate 'mapped_major' field with the best match from the valid majors list
- Use intelligent matching (e.g., "Comp Sci" → "Computer Science | BS", "Business" → "Business Administration | BSBA")
- If no reasonable match exists, set mapped_major to "Undecided" or leave it as the closest general match
- IMPORTANT: The pipe character (|) in major names is part of the major name - do NOT split on it
- Example: If student writes "Computer Science", map to "Computer Science | BS" from the list
"""

    base_prompt += """
CRITICAL ADDRESS HANDLING:
- If address appears as one line like "123 Main St, Austin TX 78701", split it:
  - address: "123 Main St"
  - city: "Austin"
  - state: "TX"
  - zip_code: "78701"
- Always separate address components into distinct fields
"""

    # Add example output
    if valid_majors and len(valid_majors) > 0:
        base_prompt += """
Output format - respond ONLY with this JSON array:
[
  {
    "first_name": "John",
    "last_name": "Smith",
    "date_of_birth": "03/15/2006",
    "email": "john.smith@email.com",
    "address": "123 Main St",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701",
    "high_school": "Roosevelt High School",
    "graduation_year": "2024",
    "major": "Computer Science",
    "mapped_major": "Computer Science | BS"
  }
]
"""
    else:
        base_prompt += """
Output format - respond ONLY with this JSON array:
[
  {
    "first_name": "John",
    "last_name": "Smith",
    "date_of_birth": "03/15/2006",
    "email": "john.smith@email.com",
    "address": "123 Main St",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701",
    "high_school": "Roosevelt High School",
    "graduation_year": "2024",
    "major": "Computer Science"
  }
]
"""

    base_prompt += """
IMPORTANT:
- Skip rows that are completely empty
- If only some fields are filled in a row, still include that row
- Clean up obvious OCR errors in names and addresses
- Standardize phone numbers to XXX-XXX-XXXX if present
- No markdown formatting, no explanations, just the JSON array
"""

    return base_prompt

async def process_signup_sheet(
    image_path: str, 
    event_id: str, 
    school_id: str, 
    user_id: str
) -> Dict[str, Any]:
    """
    Process sign-up sheet and create reviewed_data records
    
    Args:
        image_path: Path to uploaded image file
        event_id: Event ID to associate records with
        school_id: School ID for the records
        user_id: User ID who uploaded the sheet
        
    Returns:
        Dict with success status, record count, and document IDs
    """
    log_debug("=== SIGNUP SHEET PROCESSING START ===", {
        "image_path": image_path,
        "event_id": event_id,
        "school_id": school_id,
        "user_id": user_id
    }, service="signup")

    try:
        # Fetch school's major list for mapping
        supabase_client = get_supabase_client()
        school_query = supabase_client.table("schools").select("majors").eq("id", school_id).maybe_single().execute()
        valid_majors = school_query.data.get("majors", []) if school_query.data else []

        log_debug(f"Fetched {len(valid_majors)} valid majors for school", service="signup")

        # Download image from storage to temporary local file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            local_image_path = tmp_file.name

        try:
            download_from_supabase(image_path, local_image_path)

            # Extract data with Gemini using local file
            records = await extract_signup_data_with_gemini(local_image_path, valid_majors)
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(local_image_path)
            except Exception:
                pass  # Ignore cleanup errors
        
        if not records:
            log_debug("No records extracted from sign-up sheet", service="signup")
            return {
                "success": True,
                "records_created": 0,
                "document_ids": [],
                "message": "No filled rows found in sign-up sheet"
            }
        
        # Create reviewed_data records
        document_ids = []
        for i, record in enumerate(records):
            try:
                document_id = await create_reviewed_data_record(
                    record, event_id, school_id, user_id, image_path, i + 1
                )
                document_ids.append(document_id)
                log_debug(f"Created record {i + 1}/{len(records)}", {
                    "document_id": document_id,
                    "record": record
                }, service="signup")
            except Exception as e:
                log_debug(f"Failed to create record {i + 1}: {str(e)}", {
                    "record": record,
                    "error": str(e)
                }, service="signup")
                # Continue with other records
                continue
        
        log_debug(f"=== SIGNUP SHEET PROCESSING COMPLETE ===", {
            "records_extracted": len(records),
            "records_created": len(document_ids),
            "document_ids": document_ids
        }, service="signup")
        
        return {
            "success": True,
            "records_created": len(document_ids),
            "document_ids": document_ids,
            "records_extracted": len(records)
        }
        
    except Exception as e:
        log_debug(f"Signup sheet processing failed: {str(e)}", service="signup")
        raise

async def extract_signup_data_with_gemini(image_path: str, valid_majors: List[str] = None) -> List[Dict]:
    """Extract sign-up sheet data using Gemini with optional major mapping"""
    log_debug("=== GEMINI EXTRACTION START ===", {
        "image_path": image_path,
        "valid_majors_count": len(valid_majors) if valid_majors else 0
    }, service="signup")

    try:
        # Configure Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-pro")

        # Read image file
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # Build prompt with major mapping if applicable
        prompt = build_signup_sheet_prompt(valid_majors)

        log_debug("Sending image to Gemini for processing with major mapping...", service="signup")

        # Process with Gemini
        response = model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        
        log_debug("Received response from Gemini", {
            "response_text": response.text[:200] + "..." if len(response.text) > 200 else response.text
        }, service="signup")
        
        # Parse JSON response (handle markdown code blocks)
        try:
            response_text = response.text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith('```json'):
                response_text = response_text.split('```json')[1]
            if response_text.endswith('```'):
                response_text = response_text.split('```')[0]
            
            response_text = response_text.strip()
            records = json.loads(response_text)
        except json.JSONDecodeError as e:
            log_debug(f"Failed to parse Gemini response as JSON: {str(e)}", {
                "response_text": response.text
            }, service="signup")
            raise ValueError(f"Invalid JSON response from Gemini: {str(e)}")
        
        if not isinstance(records, list):
            raise ValueError("Expected JSON array from Gemini")

        # Backend safeguard: Ensure mapped_major is set if valid_majors exist
        if valid_majors and len(valid_majors) > 0:
            for record in records:
                # If mapped_major is missing or empty, default to "Undecided"
                if 'mapped_major' not in record or not record.get('mapped_major', '').strip():
                    record['mapped_major'] = "Undecided"
                    log_debug("Set mapped_major to 'Undecided' for unmappable/missing major", {
                        "original_major": record.get('major', ''),
                        "row": records.index(record) + 1
                    }, service="signup")

        log_debug(f"=== GEMINI EXTRACTION COMPLETE ===", {
            "records_count": len(records),
            "records": records
        }, service="signup")

        return records
        
    except Exception as e:
        log_debug(f"Gemini sign-up sheet processing failed: {str(e)}", service="signup")
        raise

async def create_reviewed_data_record(
    record: Dict, 
    event_id: str, 
    school_id: str, 
    user_id: str,
    image_path: str,
    row_number: int
) -> str:
    """Create a reviewed_data record from sign-up sheet data"""
    
    # Generate unique document_id for this record
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    log_debug(f"Creating reviewed_data record for row {row_number}", {
        "document_id": document_id,
        "record": record
    }, service="signup")
    
    # Format fields for reviewed_data structure
    fields = {}
    for field_name, value in record.items():
        if value is not None and str(value).strip():  # Only include non-empty fields
            # Special handling for mapped_major - it's AI-mapped, not handwritten
            if field_name == "mapped_major":
                fields[field_name] = {
                    "value": str(value).strip(),
                    "source": "gemini_signup_mapped",
                    "confidence": 0.9,
                    "enabled": True,
                    "required": False,
                    "requires_human_review": False,  # AI-mapped major doesn't need review
                    "review_notes": "Automatically mapped to school's major list",
                    "reviewed": True,  # AI mapping is considered reviewed
                    "original_value": record.get('major', ''),  # Link to original major
                    "edit_made": True,
                    "edit_type": "mapped_value"
                }
            else:
                fields[field_name] = {
                    "value": str(value).strip(),
                    "source": "gemini_signup",
                    "confidence": 0.85,
                    "enabled": True,
                    "required": False,
                    "requires_human_review": True,  # Handwriting OCR needs human review
                    "review_notes": "Extracted from handwritten signup sheet - please verify accuracy",
                    "reviewed": False,  # Not yet reviewed by human
                    "original_value": str(value).strip(),
                    "edit_made": False,
                    "edit_type": "none"
                }
    
    # Create reviewed_data record
    review_data = {
        "document_id": document_id,
        "fields": fields,
        "school_id": school_id,
        "user_id": user_id,
        "event_id": event_id,
        "image_path": image_path,
        "review_status": "needs_review",  # Require human review for handwriting OCR
        "upload_type": "signup_sheet",  # New field to distinguish from inquiry cards
        "created_at": now,
        "updated_at": now
    }
    
    try:
        # Insert into reviewed_data table
        supabase_client = get_supabase_client()
        response = supabase_client.table("reviewed_data").insert(review_data).execute()
        
        if not response.data:
            raise Exception("Failed to insert reviewed_data record - no data returned")
        
        log_debug(f"Successfully created reviewed_data record", {
            "document_id": document_id,
            "fields_count": len(fields)
        }, service="signup")
        
        return document_id
        
    except Exception as e:
        log_debug(f"Failed to create reviewed_data record: {str(e)}", {
            "document_id": document_id,
            "review_data": review_data
        }, service="signup")
        raise

def validate_signup_record(record: Dict) -> bool:
    """Validate that a signup record has minimum required data"""
    # At minimum, we need first_name OR last_name
    has_name = (
        (record.get("first_name") and str(record["first_name"]).strip()) or
        (record.get("last_name") and str(record["last_name"]).strip())
    )
    
    return has_name