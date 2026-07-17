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
from typing import List, Dict, Any, Tuple
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug
from app.core.signup_enhancement_prompt import build_enhancement_prompt
from app.services.gemini_service import (
    calculate_confidence_from_quality,
    determine_review_from_quality
)

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


def build_first_pass_prompt() -> str:
    """
    Build first-pass prompt focused on table structure and row integrity.
    This is optimized for extracting raw data with correct row boundaries.
    """
    return """You are analyzing a HANDWRITTEN sign-up sheet table to extract its STRUCTURE and RAW DATA.

YOUR TASK: Extract data row-by-row, prioritizing STRUCTURAL ACCURACY over OCR perfection.

🎯 PRIMARY GOAL: Ensure each student's data stays within their own row, and each value stays in its own column, even when some cells are blank.

⛔ THE #1 MISTAKE TO AVOID - COLUMN SHIFTING ON BLANK CELLS:
A row is defined by its VERTICAL POSITION in the table (the physical line the handwriting sits on). Every cell you read belongs to the row it is physically written on.
- A blank cell is a REAL, INTENTIONAL part of the table. It means that student left that field empty.
- When a cell is blank, you MUST output an empty string "" for it and KEEP GOING to the next column of the SAME row.
- NEVER pull a value up from the row below (or down from the row above) to fill a blank cell.
- NEVER let a blank cell cause the values beneath it to shift up. If column "email" is blank on row 2, row 3's email STAYS on row 3 - it does NOT move up into row 2.
- Do NOT "close the gap." Preserve every blank exactly where it appears. The number of rows must equal the number of physical writing lines that have ANY data, blank cells included.

STEP-BY-STEP PROCESS:

1. IDENTIFY TABLE STRUCTURE:
   - Locate the header row (column names)
   - Count the number of body rows that have ANY data written in them (a row counts even if only one cell is filled)
   - Row boundaries are the horizontal ruled lines / the physical line each entry sits on. White space INSIDE a row (a blank cell) is NOT a row boundary and does NOT start a new row.

2. FOR EACH ROW (going top to bottom, one physical line at a time):
   - Assign it a row_number (1, 2, 3, etc.)
   - Scan LEFT TO RIGHT across ALL columns of THAT single row before moving to the next row.
   - For each column, read the cell that is horizontally aligned with this row. If that cell is empty, output "" for it and move to the next column. Do not skip the column and do not borrow another row's value.
   - If text is on the border between rows, assign it to the row where MOST of the text appears
   - Extract exactly what you see - don't worry about OCR errors yet

3. COLUMN MAPPING (expected columns from left to right):
   - Column 1: first_name
   - Column 2: last_name
   - Column 3: date_of_birth (or combined with email)
   - Column 4: email (or combined with date_of_birth)
   - Column 5: address (may include city/state/zip all together)
   - Column 6: high_school
   - Column 7: major
   - Column 8: graduation_year (often labeled "GRAD YEAR")
   Each value must land in the column it is physically written under. If a student skipped column 4 (email), column 4 is "" and columns 5+ keep their own values. Do not slide later columns left to fill the gap.

4. HANDLING MESSY DATA:
   - If multiple fields appear in one cell, extract them all into that field (we'll split later)
   - If a field is completely blank, use empty string "" and continue - do NOT fill it from another row or another column
   - If you can't read handwriting clearly, transcribe your best guess
   - Include the "confidence" field: "high" (clearly readable), "medium" (somewhat unclear), "low" (very messy)

OUTPUT FORMAT - JSON array with one object per row:
[
  {
    "row_number": 1,
    "first_name": "Bianca",
    "last_name": "Johnson",
    "date_of_birth": "7/30/08",
    "email": "bjohnson@email.com",
    "address": "10 county Road 454 Lambert MS",
    "city": "",
    "state": "",
    "zip_code": "",
    "high_school": "LHS",
    "graduation_year": "26",
    "major": "nursing",
    "confidence": "medium"
  }
]

CRITICAL RULES:
- NEVER merge data from multiple rows into one student
- NEVER shift values up to fill a blank cell - a blank cell stays "" and the rows below it stay put
- Blank cells are expected and must be preserved exactly where they occur
- ALWAYS include row_number
- The number of output objects MUST equal the number of physical rows that contain ANY writing (do not drop rows that are mostly blank)
- Extract what you see, don't over-correct OCR errors yet
- If in doubt about which row text belongs to, use visual horizontal alignment (the physical line the text sits on)
- Return ONLY the JSON array, no markdown, no explanations
"""


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

        # Fetch field requirements for this school
        field_requirements = await get_field_requirements(school_id)

        try:
            download_from_supabase(image_path, local_image_path)

            # NEW: Two-pass extraction + pipeline enhancement
            # First pass: Extract table structure and raw data
            raw_records = await extract_signup_data_first_pass(local_image_path)

            if not raw_records:
                log_debug("No records extracted from sign-up sheet", service="signup")
                return {
                    "success": True,
                    "records_created": 0,
                    "document_ids": [],
                    "message": "No filled rows found in sign-up sheet"
                }

            # Second pass: Enhance with quality indicators
            enhanced_records = await enhance_signup_data_second_pass(
                local_image_path,
                raw_records,
                valid_majors
            )

            # Run through pipeline (6 enhancers: canonical mapping, field splitting,
            # requirements, data cleaning, address validation, CEEB matching)
            from app.pipeline.signup_pipeline import SignupSheetPipeline

            pipeline = SignupSheetPipeline()
            results = await pipeline.process_records(
                enhanced_records,
                local_image_path,
                event_id,
                school_id,
                user_id,
                valid_majors,
                field_requirements
            )

        finally:
            # Clean up temporary file
            try:
                os.unlink(local_image_path)
            except Exception:
                pass  # Ignore cleanup errors

        if not results:
            log_debug("No results from pipeline", service="signup")
            return {
                "success": True,
                "records_created": 0,
                "document_ids": [],
                "message": "No records generated from pipeline"
            }

        # Create reviewed_data records from pipeline results
        document_ids = []
        for i, result in enumerate(results):
            try:
                document_id = await create_reviewed_data_from_pipeline_result(
                    result, event_id, school_id, user_id, image_path, i + 1
                )
                document_ids.append(document_id)
                log_debug(f"Created record {i + 1}/{len(results)}", {
                    "document_id": document_id,
                    "review_status": result.metadata.get('review_status')
                }, service="signup")
            except Exception as e:
                log_debug(f"Failed to create record {i + 1}: {str(e)}", {
                    "error": str(e)
                }, service="signup")
                # Continue with other records
                continue
        
        log_debug(f"=== SIGNUP SHEET PROCESSING COMPLETE ===", {
            "records_extracted": len(results),
            "records_created": len(document_ids),
            "document_ids": document_ids
        }, service="signup")

        return {
            "success": True,
            "records_created": len(document_ids),
            "document_ids": document_ids,
            "records_extracted": len(results)
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

        from app.core.clients import get_gemini_client
        from google.genai import types as genai_types
        gemini_client = get_gemini_client()

        # Read image file
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # Build prompt with major mapping if applicable
        prompt = build_signup_sheet_prompt(valid_majors)

        log_debug("Sending image to Gemini for processing with major mapping...", service="signup")

        # Process with Gemini
        response = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
            ]
        )
        
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


async def extract_signup_data_first_pass(image_path: str) -> List[Dict]:
    """
    First pass: Extract table structure and raw data with row integrity focus.

    Args:
        image_path: Path to sign-up sheet image

    Returns:
        List of raw student records with row_number tracking
    """
    log_debug("=== FIRST PASS: STRUCTURE EXTRACTION ===", {
        "image_path": image_path
    }, service="signup")

    try:
        # Configure Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")

        from app.core.clients import get_gemini_client
        from google.genai import types as genai_types
        gemini_client = get_gemini_client()

        # Read image file
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # Build first-pass prompt
        prompt = build_first_pass_prompt()

        log_debug("Sending image to Gemini for first-pass extraction...", service="signup")

        # Process with Gemini
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
            ],
            # Allow a modest thinking budget: aligning rows/columns around blank
            # cells is spatial reasoning that benefits from some deliberation.
            config=genai_types.GenerateContentConfig(thinking_config=genai_types.ThinkingConfig(thinking_budget=512))
        )

        log_debug("Received first-pass response from Gemini", {
            "response_text": response.text[:200] + "..." if len(response.text) > 200 else response.text
        }, service="signup")

        # Parse JSON response (handle markdown code blocks)
        try:
            response_text = response.text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith('```json'):
                response_text = response_text.split('```json')[1]
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
            if response_text.endswith('```'):
                response_text = response_text.rsplit('```', 1)[0]

            response_text = response_text.strip()
            records = json.loads(response_text)
        except json.JSONDecodeError as e:
            log_debug(f"Failed to parse first-pass response as JSON: {str(e)}", {
                "response_text": response.text
            }, service="signup")
            raise ValueError(f"Invalid JSON response from Gemini: {str(e)}")

        if not isinstance(records, list):
            raise ValueError("Expected JSON array from Gemini")

        # Sanity-check row integrity so a recurrence of the "blank cell shifts
        # rows up" bug is visible in logs. Non-sequential or duplicate
        # row_numbers are a signal that Gemini collapsed a blank cell.
        row_numbers = [r.get("row_number") for r in records if isinstance(r, dict)]
        expected_sequence = list(range(1, len(records) + 1))
        if row_numbers != expected_sequence:
            log_debug("⚠️ First-pass row_numbers are not sequential - possible row shift", {
                "row_numbers": row_numbers,
                "expected": expected_sequence
            }, service="signup")

        log_debug(f"=== FIRST PASS COMPLETE ===", {
            "records_count": len(records)
        }, service="signup")

        return records

    except Exception as e:
        log_debug(f"First-pass extraction failed: {str(e)}", service="signup")
        raise


async def enhance_signup_data_second_pass(
    image_path: str,
    raw_records: List[Dict],
    valid_majors: List[str] = None,
    batch_size: int = 5
) -> List[Dict]:
    """
    Second pass: Enhance extracted data with quality indicators.
    Reuses inquiry card quality system for consistency.

    Processes records in batches to avoid Gemini token limits.
    Can handle 20+ students per sheet.

    Args:
        image_path: Path to sign-up sheet image
        raw_records: List of raw student records from first pass
        valid_majors: List of valid majors for mapping
        batch_size: Number of students to process per Gemini call (default: 5)

    Returns:
        List of enhanced student records with quality indicators
    """
    log_debug("=== SECOND PASS: DATA ENHANCEMENT (BATCHED) ===", {
        "image_path": image_path,
        "total_records": len(raw_records),
        "batch_size": batch_size,
        "num_batches": (len(raw_records) + batch_size - 1) // batch_size,
        "valid_majors_count": len(valid_majors) if valid_majors else 0
    }, service="signup")

    if not raw_records:
        return []

    # Process records in batches
    all_enhanced_records = []
    total_batches = (len(raw_records) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(raw_records))
        batch = raw_records[start_idx:end_idx]

        log_debug(f"Processing batch {batch_num + 1}/{total_batches}", {
            "students_in_batch": len(batch),
            "row_numbers": [r.get('row_number', i+start_idx+1) for i, r in enumerate(batch)]
        }, service="signup")

        try:
            # Process this batch
            enhanced_batch = await _enhance_single_batch(
                image_path,
                batch,
                valid_majors
            )

            all_enhanced_records.extend(enhanced_batch)

            log_debug(f"✅ Batch {batch_num + 1}/{total_batches} complete", {
                "records_enhanced": len(enhanced_batch)
            }, service="signup")

        except Exception as e:
            log_debug(f"❌ Batch {batch_num + 1}/{total_batches} failed: {str(e)}", {
                "batch_size": len(batch),
                "error": str(e)
            }, service="signup")
            # Continue with other batches - don't fail entire sheet
            # Add placeholders for failed batch
            for record in batch:
                all_enhanced_records.append(record)  # Use raw record as fallback

    log_debug(f"=== SECOND PASS COMPLETE (ALL BATCHES) ===", {
        "total_records_enhanced": len(all_enhanced_records),
        "batches_processed": total_batches
    }, service="signup")

    return all_enhanced_records


async def _enhance_single_batch(
    image_path: str,
    batch_records: List[Dict],
    valid_majors: List[str] = None
) -> List[Dict]:
    """
    Enhance a single batch of student records.
    Internal helper for batch processing.

    Args:
        image_path: Path to sign-up sheet image
        batch_records: Batch of raw student records
        valid_majors: List of valid majors for mapping

    Returns:
        List of enhanced student records for this batch
    """
    try:
        # Configure Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")

        from app.core.clients import get_gemini_client
        from google.genai import types as genai_types
        gemini_client = get_gemini_client()

        # Read image file
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # Build enhancement prompt with batch records
        prompt = build_enhancement_prompt(batch_records, valid_majors)

        # Process with Gemini
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
            ],
            config=genai_types.GenerateContentConfig(thinking_config=genai_types.ThinkingConfig(thinking_budget=0))
        )

        # Parse JSON response
        response_text = response.text.strip()

        # Remove markdown code blocks if present
        if response_text.startswith('```json'):
            response_text = response_text.split('```json')[1]
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
        if response_text.endswith('```'):
            response_text = response_text.rsplit('```', 1)[0]

        response_text = response_text.strip()
        enhanced_records = json.loads(response_text)

        if not isinstance(enhanced_records, list):
            raise ValueError("Expected JSON array from Gemini")

        # Apply confidence calculation and review determination to each field
        for record in enhanced_records:
            for field_name, field_value in record.items():
                # Skip row_number (it's not an enhanced field object)
                if field_name == 'row_number':
                    continue

                # Only process enhanced field objects (dicts with quality indicators)
                if isinstance(field_value, dict) and 'text_clarity' in field_value:
                    # Calculate confidence from quality indicators
                    confidence = calculate_confidence_from_quality(field_value)
                    field_value['confidence'] = confidence

                    # Determine if review is needed
                    field_data = {
                        'required': False,  # Sign-up sheets don't have required fields by default
                        'value': field_value.get('value', '')
                    }

                    needs_review, review_notes = determine_review_from_quality(field_value, field_data)
                    field_value['requires_human_review'] = needs_review

                    # Add review notes if generated
                    if review_notes and not field_value.get('notes'):
                        field_value['review_notes'] = review_notes

        return enhanced_records

    except Exception as e:
        log_debug(f"Batch enhancement failed: {str(e)}", service="signup")
        raise


async def get_field_requirements(school_id: str) -> Dict[str, Any]:
    """
    Fetch field requirements for a school.

    Args:
        school_id: School ID

    Returns:
        Dictionary of field requirements
    """
    try:
        supabase_client = get_supabase_client()

        # Query settings table for this school's field requirements
        settings_query = supabase_client.table("settings").select("field_requirements").eq("school_id", school_id).maybe_single().execute()

        if settings_query.data and settings_query.data.get("field_requirements"):
            return settings_query.data.get("field_requirements", {})

        # Default empty requirements if not configured
        return {}

    except Exception as e:
        log_debug(f"Failed to fetch field requirements: {str(e)}", service="signup")
        # Return empty dict on error - pipeline will use defaults
        return {}


async def create_reviewed_data_from_pipeline_result(
    result: 'ProcessingResult',
    event_id: str,
    school_id: str,
    user_id: str,
    image_path: str,
    row_number: int
) -> str:
    """
    Create reviewed_data record from pipeline ProcessingResult.
    Converts FieldData objects to reviewed_data format.

    Args:
        result: ProcessingResult from pipeline
        event_id: Event ID
        school_id: School ID
        user_id: User ID
        image_path: Original image path
        row_number: Row number from sheet

    Returns:
        Document ID of created record
    """
    from app.pipeline.models import ProcessingResult

    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Convert FieldData objects to reviewed_data format
    fields = {}
    for field_name, field_data in result.fields.items():
        fields[field_name] = {
            "value": field_data.value,
            "source": field_data.source,
            "confidence": field_data.confidence,
            "enabled": field_data.enabled,
            "required": field_data.required,
            "requires_human_review": field_data.requires_human_review,
            "review_notes": field_data.review_notes,
            "reviewed": False,
            "original_value": field_data.original_value or field_data.value,
            "edit_made": field_data.metadata.get('edit_made', False),
            "edit_type": field_data.metadata.get('edit_type', 'none'),
            "validation_status": field_data.validation_status,
            "suggestions": field_data.suggestions or [],
            "text_clarity": field_data.metadata.get('text_clarity', 'clear'),
            "certainty": field_data.metadata.get('certainty', 'certain'),
            "notes": field_data.metadata.get('notes', '')
        }

    # Get review status from pipeline result
    review_status = result.metadata.get("review_status", "needs_review")

    review_data = {
        "document_id": document_id,
        "fields": fields,
        "school_id": school_id,
        "user_id": user_id,
        "event_id": event_id,
        "image_path": image_path,
        "review_status": review_status,
        "upload_type": "signup_sheet",
        "created_at": now,
        "updated_at": now
    }

    try:
        supabase_client = get_supabase_client()
        response = supabase_client.table("reviewed_data").insert(review_data).execute()

        if not response.data:
            raise Exception("Failed to insert reviewed_data record")

        log_debug(f"Created reviewed_data record from pipeline", {
            "document_id": document_id,
            "review_status": review_status,
            "fields_count": len(fields),
            "row_number": row_number
        }, service="signup")

        return document_id

    except Exception as e:
        log_debug(f"Failed to create reviewed_data record: {str(e)}", {
            "document_id": document_id,
            "review_data": review_data
        }, service="signup")
        raise


async def create_reviewed_data_record(
    record: Dict,
    event_id: str,
    school_id: str,
    user_id: str,
    image_path: str,
    row_number: int
) -> str:
    """
    LEGACY: Create a reviewed_data record from sign-up sheet data.
    This is kept for backwards compatibility with old single-pass approach.
    New code should use create_reviewed_data_from_pipeline_result() instead.
    """
    
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