import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
from typing import Dict, Any
import re

# Optional psutil import for memory monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import new services
from app.services.docai_service import process_image_with_docai
from app.services.settings_service import get_field_requirements, apply_field_requirements, sync_field_requirements, sync_field_types_and_options
from app.services.review_service import determine_review_status, validate_field_data
from app.services.address_validation_service import validate_address_for_pipeline
from app.services.gemini_service import process_card_with_gemini_v2

# Import existing infrastructure
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import get_supabase_client
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.config import DOCAI_PROCESSOR_ID

# Import utils
from app.utils.image_processing import ensure_trimmed_image
from app.utils.storage import upload_to_supabase_storage_from_path
from app.utils.field_utils import filter_combined_fields

from app.repositories.uploads_repository import (
    update_job_status_with_review
)

BUCKET = "cards-uploads"
MAX_RETRIES = 3
SLEEP_SECONDS = 1

app = FastAPI(title="CardCapture Worker API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Log when the app starts up"""
    print("🚀 CardCapture Worker API is starting up...", flush=True)
    print(f"🌐 Environment: PORT={os.environ.get('PORT', 'NOT_SET')}", flush=True)
    try:
        # Test basic imports and connections
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        print("✅ Supabase client imported and initialized successfully", flush=True)
        print("✅ CardCapture Worker API startup complete", flush=True)
    except Exception as e:
        # Do not crash container on startup; log and allow health endpoint to reflect readiness
        print(f"⚠️ Startup dependency check failed (continuing): {e}", flush=True)

@app.get("/")
def root():
    return {"message": "CardCapture Worker API is running"}

@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run"""
    return {"status": "healthy", "service": "card-capture-worker-v2"}

@app.get("/ready")
def readiness_check():
    """Readiness check endpoint - verifies all dependencies are working"""
    try:
        # Quick test of critical dependencies
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        return {
            "status": "ready", 
            "service": "card-capture-worker-v2",
            "dependencies": {
                "supabase": "connected",
                "storage_path": "/tmp writable"
            }
        }
    except Exception as e:
        return {
            "status": "not_ready", 
            "service": "card-capture-worker-v2",
            "error": str(e)
        }

def log_worker_debug(message: str, data: Any = None, verbose: bool = False):
    """Write debug message and optional data to worker_v2_debug.log and stdout for Cloud Run."""
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Add memory usage to critical logs
    if PSUTIL_AVAILABLE and any(keyword in message.lower() for keyword in ['start', 'end', 'error', 'timeout']):
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            message = f"{message} [Memory: {memory_mb:.1f}MB]"
        except Exception:
            pass  # Don't fail logging if psutil fails
    
    log_entry = f"\n[{timestamp}] {message}\n"
    if data is not None:
        try:
            import json
            log_entry += json.dumps(data, indent=2, default=str) + "\n"
        except Exception as e:
            log_entry += f"[Could not serialize data: {e}]\n{str(data)}\n"
    # Write to file (in /tmp for Cloud Run compatibility)
    log_file_path = '/tmp/worker_v2_debug.log'
    try:
        with open(log_file_path, 'a') as f:
            f.write(log_entry)
    except Exception as log_error:
        # If file logging fails, just continue with stdout logging
        print(f"Warning: Could not write to log file: {log_error}", flush=True)
    # Also print to stdout for Cloud Run logging
    print(log_entry, flush=True)

def download_from_supabase(file_url: str, local_path: str) -> None:
    """Download file from Supabase storage to local path"""
    try:
        # Initialize Supabase client
        supabase_client = get_supabase_client()
        
        # Extract bucket and file path from URL
        # Format: "bucket-name/path/to/file.ext"
        url_parts = file_url.split('/', 1)  # Split only on first slash
        if len(url_parts) != 2:
            raise ValueError(f"Invalid file URL format: {file_url}")
            
        bucket_name = url_parts[0]  # "cards-uploads"
        file_path = url_parts[1]    # "user-id/date/filename.ext"
        
        log_worker_debug(f"Downloading from bucket: {bucket_name}, path: {file_path}")
        
        # Download file
        response = supabase_client.storage.from_(bucket_name).download(file_path)
        
        with open(local_path, 'wb') as f:
            f.write(response)
            
        log_worker_debug(f"Downloaded file from {file_url} to {local_path}")
        
    except Exception as e:
        log_worker_debug(f"ERROR downloading file: {str(e)}")
        raise

def split_combined_address_fields(fields: dict, school_id: str = None) -> dict:
    """
    Detects and splits combined address/city/state/zip fields into separate fields.
    Enhanced version that tracks split fields for school settings synchronization.
    Handles multiple formats:
    - "City, State, Zip"
    - "City, State Zip"
    - "City State Zip"
    - "City, State"
    - "City State"
    """
    split_fields = set()  # Track which fields were split
    
    for key in ['city_state_zip', 'citystatezip', 'city_state', 'address_line']:
        field = fields.get(key)
        if field and isinstance(field, dict) and field.get('value'):
            value = field['value'].replace('\n', ' ').replace('\r', ' ').strip()
            
            # Pattern 1: City, State, Zip (with optional trailing punctuation)
            match = re.match(r'^([^,]+),\s*([A-Z]{2})(?:,\s*|\s+)(\d{5}(?:-\d{4})?)[.,;:]*?$', value)
            if match:
                fields['city'] = {
                    'value': match.group(1).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                fields['state'] = {
                    'value': match.group(2).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                fields['zip_code'] = {
                    'value': match.group(3).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                split_fields.update(['city', 'state', 'zip_code'])
                log_worker_debug(f"Split {key} into city/state/zip: {match.group(1).strip()}, {match.group(2).strip()}, {match.group(3).strip()}")
                continue

            # Pattern 2: City, State (no zip, with optional trailing punctuation)
            match = re.match(r'^([^,]+),\s*([A-Z]{2})[.,;:]*?$', value)
            if match:
                fields['city'] = {
                    'value': match.group(1).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                fields['state'] = {
                    'value': match.group(2).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                split_fields.update(['city', 'state'])
                log_worker_debug(f"Split {key} into city/state: {match.group(1).strip()}, {match.group(2).strip()}")
                continue

            # Pattern 3: City State Zip (no commas, with optional trailing punctuation)
            match = re.match(r'^([^,]+)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)[.,;:]*?$', value)
            if match:
                fields['city'] = {
                    'value': match.group(1).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                fields['state'] = {
                    'value': match.group(2).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                fields['zip_code'] = {
                    'value': match.group(3).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                split_fields.update(['city', 'state', 'zip_code'])
                log_worker_debug(f"Split {key} into city/state/zip: {match.group(1).strip()}, {match.group(2).strip()}, {match.group(3).strip()}")
                continue

            # Pattern 4: City State (no commas, no zip, with optional trailing punctuation)
            match = re.match(r'^([^,]+)\s+([A-Z]{2})[.,;:]*?$', value)
            if match:
                fields['city'] = {
                    'value': match.group(1).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                fields['state'] = {
                    'value': match.group(2).strip(),
                    'confidence': field.get('confidence', 0.8),
                    'source': 'address_splitting',
                    'enabled': True,
                    'required': False
                }
                split_fields.update(['city', 'state'])
                log_worker_debug(f"Split {key} into city/state: {match.group(1).strip()}, {match.group(2).strip()}")
                continue

            # If no patterns match, try to extract just city and state
            # This is a fallback for less structured formats
            parts = value.split()
            if len(parts) >= 2:
                # Look for a two-letter state code
                for i in range(len(parts) - 1):
                    # Remove punctuation from the potential state part for matching
                    state_part = parts[i + 1].rstrip('.,;:')
                    if re.match(r'^[A-Z]{2}$', state_part):
                        city = ' '.join(parts[:i + 1])
                        state = state_part
                        fields['city'] = {
                            'value': city.strip(),
                            'confidence': field.get('confidence', 0.6),
                            'source': 'address_splitting_fallback',
                            'enabled': True,
                            'required': False
                        }
                        fields['state'] = {
                            'value': state.strip(),
                            'confidence': field.get('confidence', 0.6),
                            'source': 'address_splitting_fallback',
                            'enabled': True,
                            'required': False
                        }
                        split_fields.update(['city', 'state'])
                        
                        # If there's a zip code after the state
                        if i + 2 < len(parts):
                            zip_part = parts[i + 2].rstrip('.,;:')
                            if re.match(r'^\d{5}(?:-\d{4})?$', zip_part):
                                fields['zip_code'] = {
                                    'value': zip_part.strip(),
                                'confidence': field.get('confidence', 0.6),
                                'source': 'address_splitting_fallback',
                                'enabled': True,
                                'required': False
                            }
                            split_fields.add('zip_code')
                        
                        log_worker_debug(f"Split {key} using fallback into: {list(split_fields)}")
                        break

    # If we split any fields and have a school_id, sync with school settings immediately
    if split_fields and school_id:
        log_worker_debug(f"Split address fields detected: {list(split_fields)}, syncing with school settings")
        current_fields = list(fields.keys())
        try:
            sync_field_requirements(school_id, current_fields)
            log_worker_debug("Successfully synced split address fields with school settings")
        except Exception as e:
            log_worker_debug(f"Warning: Failed to sync split fields with school settings: {str(e)}")

    return fields

def prepare_docai_for_review(docai_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare DocAI fields for review system when Gemini fails.
    Add required quality indicators so review system doesn't break.
    """
    prepared_fields = {}
    
    for field_name, field_data in docai_fields.items():
        prepared_fields[field_name] = field_data.copy()
        # Add minimal required indicators for review system compatibility
        prepared_fields[field_name].update({
            "edit_made": False,
            "edit_type": "none",
            "original_value": field_data.get("value", ""),
            "text_clarity": "unclear",
            "certainty": "uncertain", 
            "notes": "AI processing failed - showing raw OCR data",
            "review_confidence": field_data.get("confidence", 0.0),
            "requires_human_review": False,
            "review_notes": ""
        })
    
    return prepared_fields

def detect_field_value_discrepancies(before_fields: dict, after_fields: dict, step_name: str) -> None:
    """
    Helper function to detect and log field value discrepancies between processing steps
    
    Args:
        before_fields: Field data before processing step
        after_fields: Field data after processing step
        step_name: Name of the processing step for logging
    """
    discrepancies = []
    
    # Check for value changes in existing fields
    for field_name in before_fields.keys():
        if field_name in after_fields:
            before_value = before_fields[field_name].get("value", "") if isinstance(before_fields[field_name], dict) else ""
            after_value = after_fields[field_name].get("value", "") if isinstance(after_fields[field_name], dict) else ""
            
            # Check if a non-empty value became empty
            if before_value and not after_value:
                discrepancies.append({
                    "field": field_name,
                    "issue": "value_lost",
                    "before": before_value,
                    "after": after_value
                })
            # Check if value changed unexpectedly
            elif before_value != after_value and before_value and after_value:
                discrepancies.append({
                    "field": field_name,
                    "issue": "value_changed",
                    "before": before_value,
                    "after": after_value
                })
        else:
            # Field disappeared entirely
            before_value = before_fields[field_name].get("value", "") if isinstance(before_fields[field_name], dict) else ""
            if before_value:
                discrepancies.append({
                    "field": field_name,
                    "issue": "field_removed",
                    "before": before_value,
                    "after": "FIELD_MISSING"
                })
    
    if discrepancies:
        log_worker_debug(f"⚠️  FIELD VALUE DISCREPANCIES DETECTED in {step_name}", discrepancies)
    else:
        log_worker_debug(f"✅ No field value discrepancies detected in {step_name}")

def process_job_v2(job: Dict[str, Any]) -> None:
    """
    Simplified, reliable processing flow with atomic database operations
    """
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    
    log_worker_debug("=== PROCESSING JOB V2 START ===")
    log_worker_debug("Job Details", {
        "Job ID": job_id,
        "User ID": user_id,
        "School ID": school_id,
        "Event ID": event_id,
        "File URL": file_url
    })
    
    # Initialize Supabase client
    supabase_client = get_supabase_client()
    
    tmp_file = None
    trimmed_image_path = None
    
    try:
        # Step 1: Get school field requirements
        log_worker_debug("=== STEP 1: GET FIELD REQUIREMENTS ===")
        supabase_client = get_supabase_client()
        school_query = supabase_client.table("schools").select("docai_processor_id").eq("id", school_id).maybe_single().execute()
        processor_id = school_query.data.get("docai_processor_id") if school_query and school_query.data else DOCAI_PROCESSOR_ID
        log_worker_debug(f"Using DocAI processor: {processor_id}")
        
        field_requirements = get_field_requirements(school_id)
        log_worker_debug("Current Field Requirements", field_requirements, verbose=True)
        
        # Step 2: Download image
        log_worker_debug("=== STEP 2: DOWNLOAD IMAGE ===")
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        
        # Step 3: Process with DocAI
        log_worker_debug("=== STEP 3: DOCAI PROCESSING ===")
        docai_fields, cropped_image_path = process_image_with_docai(tmp_file, processor_id)
        log_worker_debug("Original DocAI Response", docai_fields, verbose=True)
        log_worker_debug("DocAI field names extracted", list(docai_fields.keys()))
        
        # Track field values from DocAI
        docai_field_values = {}
        for field_name, field_data in docai_fields.items():
            if isinstance(field_data, dict):
                docai_field_values[field_name] = {
                    "value": field_data.get("value", ""),
                    "confidence": field_data.get("confidence", 0.0)
                }
        log_worker_debug("DocAI field values summary", docai_field_values)
        
        # Step 4: Split address fields
        log_worker_debug("=== STEP 4: SPLIT ADDRESS FIELDS ===")
        pre_split_fields = docai_fields.copy()
        docai_fields = split_combined_address_fields(docai_fields, school_id)
        detect_field_value_discrepancies(pre_split_fields, docai_fields, "Address Splitting")
        log_worker_debug("Fields After Address Splitting", docai_fields, verbose=True)
        log_worker_debug("Field names after address splitting", list(docai_fields.keys()))
        
        # Track field values after address splitting
        split_field_values = {}
        for field_name, field_data in docai_fields.items():
            if isinstance(field_data, dict):
                split_field_values[field_name] = {
                    "value": field_data.get("value", ""),
                    "confidence": field_data.get("confidence", 0.0)
                }
        log_worker_debug("Field values after address splitting", split_field_values)
        
        # Step 5: Sync fields with school settings
        log_worker_debug("=== STEP 5: SYNC WITH SCHOOL SETTINGS ===")
        field_requirements = sync_field_requirements(school_id, list(docai_fields.keys()))
        log_worker_debug("Field Requirements", field_requirements, verbose=True)
        
        # Step 6: Apply requirements to fields
        log_worker_debug("=== STEP 6: APPLY FIELD REQUIREMENTS ===")
        pre_requirements_fields = docai_fields.copy()
        docai_fields = apply_field_requirements(docai_fields, field_requirements)
        detect_field_value_discrepancies(pre_requirements_fields, docai_fields, "Field Requirements Application")
        log_worker_debug("Fields After Requirements", docai_fields, verbose=True)
        
        # Track field values after requirements application
        requirements_field_values = {}
        for field_name, field_data in docai_fields.items():
            if isinstance(field_data, dict):
                requirements_field_values[field_name] = {
                    "value": field_data.get("value", ""),
                    "confidence": field_data.get("confidence", 0.0),
                    "enabled": field_data.get("enabled", True),
                    "required": field_data.get("required", False)
                }
        log_worker_debug("Field values after requirements applied", requirements_field_values)
        
        # Step 7: Fetch valid majors
        log_worker_debug("=== STEP 7: FETCH VALID MAJORS ===")
        supabase_client = get_supabase_client()
        supabase_client = get_supabase_client()
        majors_query = supabase_client.table("schools").select("majors").eq("id", school_id).maybe_single().execute()
        valid_majors = majors_query.data.get("majors") if majors_query and majors_query.data and majors_query.data.get("majors") else []
        log_worker_debug("Valid majors", valid_majors, verbose=True)
        
        # Step 8: Process with Gemini (with failure handling)
        log_worker_debug("=== STEP 8: GEMINI PROCESSING ===")
        ai_processing_failed = False
        ai_error_message = None
        
        log_worker_debug("Fields being sent to Gemini", list(docai_fields.keys()))
        
        # Track field values being sent to Gemini
        gemini_input_values = {}
        for field_name, field_data in docai_fields.items():
            if isinstance(field_data, dict):
                gemini_input_values[field_name] = {
                    "value": field_data.get("value", ""),
                    "confidence": field_data.get("confidence", 0.0),
                    "enabled": field_data.get("enabled", True),
                    "required": field_data.get("required", False)
                }
        log_worker_debug("Field values sent to Gemini", gemini_input_values)
        
        try:
            pre_gemini_fields = docai_fields.copy()
            gemini_fields = process_card_with_gemini_v2(
                cropped_image_path,
                docai_fields,  # Pass DocAI fields directly (not pre-validated)
                valid_majors
            )
            detect_field_value_discrepancies(pre_gemini_fields, gemini_fields, "Gemini Processing")
            log_worker_debug("Gemini Output", gemini_fields, verbose=True)
            log_worker_debug("Gemini output field names", list(gemini_fields.keys()))
            
            # Track field values from Gemini output
            gemini_output_values = {}
            for field_name, field_data in gemini_fields.items():
                if isinstance(field_data, dict):
                    gemini_output_values[field_name] = {
                        "value": field_data.get("value", ""),
                        "confidence": field_data.get("confidence", 0.0),
                        "enabled": field_data.get("enabled", True),
                        "required": field_data.get("required", False)
                    }
            log_worker_debug("Field values from Gemini output", gemini_output_values)
            
            # Sync field types and options detected by Gemini
            log_worker_debug("=== STEP 8.1: SYNC FIELD TYPES AND OPTIONS ===")
            try:
                sync_field_types_and_options(school_id, gemini_fields)
                log_worker_debug("Field types and options synced successfully")
            except Exception as sync_error:
                log_worker_debug(f"Warning: Failed to sync field types: {str(sync_error)}")
                # Don't fail the whole job for this, just log and continue
            
        except Exception as gemini_error:
            log_worker_debug(f"⚠️ Gemini processing failed: {str(gemini_error)}")
            log_worker_debug("Full Gemini error traceback:", traceback.format_exc())
            
            # Use DocAI fields with proper structure for review system
            gemini_fields = prepare_docai_for_review(docai_fields)
            ai_processing_failed = True
            ai_error_message = str(gemini_error)
            
            log_worker_debug("Using DocAI fallback data", gemini_fields, verbose=True)
        
        # Step 9: Address validation on cleaned Gemini data
        log_worker_debug("=== STEP 9: ADDRESS VALIDATION ===")
        if not ai_processing_failed:
            # Only validate addresses if Gemini processing succeeded
            validated_fields, validation_state = validate_address_for_pipeline(gemini_fields)
            
            # Handle validation results based on actual Google Maps API response
            if validation_state == "verified":
                # Perfect match - set google_maps_verified source
                for field_name in ['address', 'city', 'state', 'zip_code']:
                    if field_name in validated_fields:
                        validated_fields[field_name]['source'] = 'google_maps_verified'
                
                log_worker_debug("Address VERIFIED by Google Maps - set google_maps_verified source")
                
            elif validation_state == "can_be_verified":
                log_worker_debug("Address CAN_BE_VERIFIED - Google Maps has suggestions, keeping original sources")
                
            elif validation_state == "no_house_number":
                log_worker_debug("Address NO_HOUSE_NUMBER - missing street number, keeping original sources")
                
            else:  # not_verified
                log_worker_debug("Address NOT_VERIFIED - Google Maps found no match, keeping original sources")
            
            log_worker_debug(f"Address validation result: {validation_state}", {
                "will_set_google_maps_verified": validation_state == "verified"
            })
            log_worker_debug("Fields After Address Validation", validated_fields, verbose=True)
        else:
            # Skip address validation if AI failed
            validated_fields = gemini_fields
            log_worker_debug("Skipping address validation due to AI failure")
        
        # Step 10: Final validation and review determination
        log_worker_debug("=== STEP 10: FINAL VALIDATION ===")
        
        if ai_processing_failed:
            # Set special review status for AI failures
            final_fields = validated_fields  # Use the fallback data (same as gemini_fields in this case)
            review_status = "ai_failed"
            fields_needing_review = []
            log_worker_debug("AI Processing Failed - Setting review_status to ai_failed")
        else:
            # Normal processing path - use address-validated fields
            final_fields = validate_field_data(validated_fields)
            review_status, fields_needing_review = determine_review_status(final_fields)
            
        log_worker_debug("Final Fields", final_fields, verbose=True)
        log_worker_debug("Review Status", {
            "status": review_status,
            "fields_needing_review": fields_needing_review,
            "ai_processing_failed": ai_processing_failed
        }, verbose=True)
        
        # Step 11: Trim and upload image
        log_worker_debug("=== STEP 11: TRIM AND UPLOAD IMAGE ===")
        trimmed_image_path = ensure_trimmed_image(tmp_file)
        trimmed_storage_path = None
        try:
            trimmed_storage_path = upload_to_supabase_storage_from_path(
                supabase_client,
                trimmed_image_path,
                user_id,
                os.path.basename(trimmed_image_path)
            )
            log_worker_debug(f"Trimmed image uploaded to Supabase: {trimmed_storage_path}")
        except Exception as e:
            log_worker_debug(f"Failed to upload trimmed image to Supabase: {e}")
        
        # Clean up trimmed image file immediately after upload
        if trimmed_image_path and os.path.exists(trimmed_image_path):
            try:
                os.remove(trimmed_image_path)
                log_worker_debug(f"Cleaned up trimmed image file: {trimmed_image_path}")
            except Exception as cleanup_error:
                log_worker_debug(f"Warning: Failed to clean up trimmed image: {cleanup_error}")
        
        # Step 12: Update job status and create review data
        log_worker_debug("=== STEP 12: UPDATE JOB STATUS ===")
        
        # Track critical fields before database save
        critical_fields = ["cell", "date_of_birth"]
        log_worker_debug("🔍 CRITICAL FIELDS BEFORE DB SAVE", {
            field: {
                "value": final_fields.get(field, {}).get("value"),
                "original_value": final_fields.get(field, {}).get("original_value"),
                "source": final_fields.get(field, {}).get("source"),
                "enabled": final_fields.get(field, {}).get("enabled"),
                "required": final_fields.get(field, {}).get("required")
            }
            for field in critical_fields
        })
        
        # Filter out combined fields before saving
        final_fields = filter_combined_fields(final_fields)
        
        # Track critical fields after filtering
        log_worker_debug("🔍 CRITICAL FIELDS AFTER FILTERING", {
            field: {
                "value": final_fields.get(field, {}).get("value"),
                "original_value": final_fields.get(field, {}).get("original_value"),
                "source": final_fields.get(field, {}).get("source"),
                "enabled": final_fields.get(field, {}).get("enabled"),
                "required": final_fields.get(field, {}).get("required")
            }
            for field in critical_fields
        })
        
        now = datetime.now(timezone.utc).isoformat()
        review_data = {
            "document_id": job_id,
            "fields": final_fields,
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": job.get("image_path"),
            "trimmed_image_path": trimmed_storage_path,
            "review_status": review_status,
            "created_at": now,
            "updated_at": now
        }
        
        # Add AI error information if processing failed
        if ai_processing_failed:
            review_data["ai_error_message"] = ai_error_message
            
        # 🔍 TRACK CRITICAL FIELDS: Log what's about to be saved to database
        log_worker_debug("🔍 CRITICAL FIELDS BEING SAVED TO DATABASE", {
            field_name: review_data["fields"].get(field_name, "FIELD_NOT_FOUND")
            for field_name in critical_fields
        })
        
        log_worker_debug("Review Data to be Saved", review_data, verbose=True)
        
        update_job_status_with_review(supabase_client, job_id, "complete", review_data)
        
        log_worker_debug(f"✅ Job {job_id} completed successfully")
        log_worker_debug("=== PROCESSING JOB V2 END ===\n")
        
    except Exception as e:
        log_worker_debug(f"❌ Error processing job {job_id}: {str(e)}")
        log_worker_debug("Full traceback", traceback.format_exc())
        
        # Update job status to failed directly  
        now = datetime.now(timezone.utc).isoformat()
        update_processing_job(supabase_client, job_id, {
            "status": "failed",
            "error_message": str(e),
            "updated_at": now
        })
        
        raise
        
    finally:
        # Comprehensive cleanup - always runs whether success or failure
        cleanup_files = []
        if tmp_file and os.path.exists(tmp_file):
            cleanup_files.append(tmp_file)
        if trimmed_image_path and os.path.exists(trimmed_image_path):
            cleanup_files.append(trimmed_image_path)
        
        for file_path in cleanup_files:
            try:
                os.remove(file_path)
                log_worker_debug(f"Cleaned up temporary file: {file_path}")
            except Exception as cleanup_error:
                log_worker_debug(f"Warning: Failed to clean up {file_path}: {cleanup_error}")
        
        # Force garbage collection to free memory
        import gc
        gc.collect()
        log_worker_debug("Forced garbage collection completed")

def main_v2():
    """
    Main worker loop using the new simplified processing pipeline
    """
    log_worker_debug("Starting CardCapture processing worker V2...")
    
    try:
        log_worker_debug("=== CHECKING FOR QUEUED JOBS ===")
        
        # Get next queued job
        supabase_client = get_supabase_client()
        jobs = supabase_client.table("processing_jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
        
        if jobs.data and len(jobs.data) > 0:
            job = jobs.data[0]
            log_worker_debug(f"Found job {job['id']} to process")
            
            # Mark job as processing
            now = datetime.now(timezone.utc).isoformat()
            update_processing_job(supabase_client, job["id"], {
                "status": "processing",
                "updated_at": now
            })
            
            # Process the job
            process_job_v2(job)
            
        else:
            log_worker_debug("No queued jobs found, sleeping...")
            time.sleep(SLEEP_SECONDS)
            
    except Exception as e:
        log_worker_debug(f"Worker error: {str(e)}")
        log_worker_debug("Worker traceback", traceback.format_exc())
        time.sleep(SLEEP_SECONDS)

@app.get("/process")
def process_get_endpoint():
    """GET endpoint for health checks - returns service status"""
    return {"message": "Worker is ready", "method": "POST", "status": "healthy"}

@app.post("/process")
async def process_job_endpoint(request: Request):
    try:
        # Log request details
        log_worker_debug("=== INCOMING REQUEST ===")
        log_worker_debug("Headers", dict(request.headers))
        log_worker_debug("Client", request.client)
        
        data = await request.json()
        log_worker_debug("Request body", data)
        
        # Check if job_id is provided
        if not data or "job_id" not in data:
            raise HTTPException(status_code=400, detail="Missing job_id in request")
        
        job_id = data["job_id"]
        log_worker_debug(f"Processing job_id: {job_id}")
        
        # Fetch the job details from Supabase
        supabase_client = get_supabase_client()
        job_query = supabase_client.table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
        
        if not job_query.data:
            log_worker_debug(f"Job {job_id} not found in database")
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
            
        job = job_query.data
        log_worker_debug("Found job in database", job)
        
        # Update status to processing using direct table update
        now = datetime.now(timezone.utc).isoformat()
        update_processing_job(supabase_client, job_id, {
            "status": "processing", 
            "updated_at": now
        })
        
        # Process the job
        process_job_v2(job)
        return {"status": "success", "message": f"Job {job_id} processing started"}
        
    except HTTPException:
        raise
    except Exception as e:
        log_worker_debug(f"Error in process_job_endpoint: {str(e)}")
        log_worker_debug("Full traceback", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/retry-ai-processing/{document_id}")
async def retry_ai_processing(document_id: str):
    """
    Retry Gemini processing for a card that failed AI processing
    """
    try:
        log_worker_debug(f"=== RETRY AI PROCESSING FOR {document_id} ===")
        
        # Get the reviewed_data record
        supabase_client = get_supabase_client()
        review_query = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
        if not review_query.data:
            log_worker_debug(f"Card {document_id} not found in reviewed_data")
            raise HTTPException(status_code=404, detail="Card not found")
            
        review_data = review_query.data
        log_worker_debug("Found review data", {
            "document_id": document_id,
            "review_status": review_data.get("review_status"),
            "ai_error_message": review_data.get("ai_error_message")
        })
        
        # Check if this card actually failed AI processing
        if review_data.get("review_status") != "ai_failed":
            log_worker_debug(f"Card {document_id} review_status is {review_data.get('review_status')}, not ai_failed")
            raise HTTPException(status_code=400, detail="This card did not fail AI processing")
            
        # Get what we need for retry
        trimmed_image_path = review_data["trimmed_image_path"]  # Cropped image
        docai_fields = review_data["fields"]  # DocAI fields (stored when AI failed)
        school_id = review_data["school_id"]
        
        log_worker_debug("Retry data extracted", {
            "trimmed_image_path": trimmed_image_path,
            "school_id": school_id,
            "field_count": len(docai_fields)
        })
        
        # Get valid majors for school
        majors_query = supabase_client.table("schools").select("majors").eq("id", school_id).maybe_single().execute()
        valid_majors = majors_query.data.get("majors") if majors_query and majors_query.data else []
        log_worker_debug("Valid majors for retry", valid_majors)
        
        # Download the trimmed image to process with Gemini
        # The trimmed_image_path is a storage path, we need to download it
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            temp_image_path = tmp.name
        
        try:
            download_from_supabase(trimmed_image_path, temp_image_path)
            log_worker_debug(f"Downloaded trimmed image for retry: {temp_image_path}")
            
            # Retry Gemini processing
            log_worker_debug("Retrying Gemini processing...")
            gemini_fields = process_card_with_gemini_v2(
                temp_image_path,    # Downloaded cropped image
                docai_fields,       # Original DocAI fields 
                valid_majors
            )
            log_worker_debug("Retry Gemini processing successful", verbose=True)
            
            # Apply address validation to cleaned Gemini data (same as main pipeline)
            log_worker_debug("Applying address validation to retry results...")
            validated_fields, validation_state = validate_address_for_pipeline(gemini_fields)
            
            # Handle validation results based on actual Google Maps API response
            if validation_state == "verified":
                # Perfect match - set google_maps_verified source
                for field_name in ['address', 'city', 'state', 'zip_code']:
                    if field_name in validated_fields:
                        validated_fields[field_name]['source'] = 'google_maps_verified'
                
                log_worker_debug("Retry: Address VERIFIED by Google Maps - set google_maps_verified source")
                
            elif validation_state == "can_be_verified":
                log_worker_debug("Retry: Address CAN_BE_VERIFIED - Google Maps has suggestions, keeping original sources")
                
            elif validation_state == "no_house_number":
                log_worker_debug("Retry: Address NO_HOUSE_NUMBER - missing street number, keeping original sources")
                
            else:  # not_verified
                log_worker_debug("Retry: Address NOT_VERIFIED - Google Maps found no match, keeping original sources")
            
            log_worker_debug(f"Retry address validation result: {validation_state}")
            log_worker_debug("Retry address validation complete", verbose=True)
            
            # Determine new review status with address-validated data
            final_fields = validate_field_data(validated_fields)
            new_review_status, fields_needing_review = determine_review_status(final_fields)
            
            log_worker_debug("New review status after retry", {
                "status": new_review_status,
                "fields_needing_review": fields_needing_review
            })
            
            # Filter out combined fields before saving to reviewed_data
            log_worker_debug("Filtering combined fields before retry save")
            filtered_fields = filter_combined_fields(final_fields)
            log_worker_debug(f"Retry fields before filtering: {len(final_fields)}, after filtering: {len(filtered_fields)}")
            
            # Update reviewed_data with successful results
            now = datetime.now(timezone.utc).isoformat()
            supabase_client = get_supabase_client()
            update_result = supabase_client.table("reviewed_data").update({
                "fields": filtered_fields,            # Now has proper Gemini data without combined fields
                "review_status": new_review_status,   # Proper review status
                "ai_error_message": None,            # Clear the error
                "updated_at": now
            }).eq("document_id", document_id).execute()
            
            log_worker_debug("Updated reviewed_data successfully")
            
            return {
                "status": "success", 
                "message": "AI processing retry completed successfully",
                "new_review_status": new_review_status,
                "fields_updated": len(final_fields)
            }
            
        finally:
            # Clean up temporary image file
            if os.path.exists(temp_image_path):
                os.remove(temp_image_path)
                log_worker_debug(f"Cleaned up temporary retry image: {temp_image_path}")
        
    except HTTPException:
        raise
    except Exception as e:
        log_worker_debug(f"Error retrying AI processing for {document_id}: {str(e)}")
        log_worker_debug("Full retry error traceback:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Retry failed: {str(e)}")


# Remove the main block - let Cloud Run handle uvicorn startup
# The Dockerfile.worker already has: CMD uvicorn app.worker.worker_v2:app --host 0.0.0.0 --port $PORT 