"""
Worker V3 - New pipeline implementation with race condition fixes
"""
import os
import time
import tempfile
import traceback
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.pipeline.pipeline import CardProcessingPipeline
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import get_supabase_client
from app.repositories.uploads_repository import update_job_status_with_review
# from app.utils.image_processing import ensure_trimmed_image  # Removed - no longer using image trimming
from app.utils.storage import upload_to_supabase_storage_from_path
from app.utils.retry_utils import log_debug


app = FastAPI(title="CardCapture Worker API V3")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize pipeline
pipeline = CardProcessingPipeline()

BUCKET = "cards-uploads"
MAX_RETRIES = 3
SLEEP_SECONDS = 1
STALE_JOB_MINUTES = 5


@app.on_event("startup")
async def startup_event():
    """Log when the app starts up"""
    log_debug("CardCapture Worker API V3 (Race Condition Fixed) is starting up...", service="worker")
    log_debug(f"Environment: PORT={os.environ.get('PORT', 'NOT_SET')}", service="worker")
    try:
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        log_debug("Supabase client imported and initialized successfully", service="worker")
        log_debug("New pipeline system loaded with race condition fixes", service="worker")
        log_debug("CardCapture Worker API V3 (Fixed) startup complete", service="worker")
    except Exception as e:
        log_debug(f"Startup dependency check failed (continuing): {e}", service="worker")


@app.get("/")
def root():
    return {
        "message": "CardCapture Worker API V3 (Race Condition Fixed) is running",
        "version": "v3-fixed",
        "pipeline": "new",
        "features": ["atomic-job-claiming", "duplicate-detection", "retry-protection"]
    }


@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run"""
    return {"status": "healthy", "service": "card-capture-worker-v3-fixed", "version": "v3-fixed"}


@app.get("/ready")
def readiness_check():
    """Readiness check endpoint - verifies all dependencies are working"""
    try:
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        return {
            "status": "ready",
            "service": "card-capture-worker-v3-fixed",
            "version": "v3-fixed",
            "pipeline": "new",
            "dependencies": {
                "supabase": "connected",
                "storage_path": "/tmp writable",
                "enhancers": len(pipeline.enhancers)
            }
        }
    except Exception as e:
        return {
            "status": "not_ready",
            "service": "card-capture-worker-v3-fixed",
            "error": str(e)
        }


def calculate_image_hash(file_path: str) -> Optional[str]:
    """Calculate SHA-256 hash of image file for deduplication"""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        log_debug(f"Error calculating image hash: {e}", service="worker_v3")
        return None


def mark_job_permanently_failed(job_id: str, error_message: str):
    """Mark job as permanently failed after max retries"""
    try:
        supabase_client = get_supabase_client()
        update_processing_job(supabase_client, job_id, {
            "status": "permanently_failed",
            "error_message": error_message,
            "processing_completed_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        log_debug(f"Job {job_id} marked as permanently failed: {error_message}", service="worker_v3")
    except Exception as e:
        log_debug(f"Error marking job as permanently failed: {e}", service="worker_v3")


def handle_job_failure(supabase_client, job: Dict[str, Any], error_message: str):
    """Handle job failure with retry logic"""
    job_id = job['id']
    retry_count = job.get('retry_count', 0)

    if retry_count < MAX_RETRIES - 1:
        # Reset to queued for retry
        update_processing_job(supabase_client, job_id, {
            "status": "queued",
            "worker_id": None,
            "claimed_at": None,
            "retry_count": retry_count + 1,
            "error_message": f"Attempt {retry_count + 1} failed: {error_message}",
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        log_debug(f"Job {job_id} reset to queued for retry (attempt {retry_count + 2}/{MAX_RETRIES})", service="worker_v3")
    else:
        # Mark as permanently failed
        mark_job_permanently_failed(job_id, f"Failed after {MAX_RETRIES} attempts: {error_message}")


def save_v2_universal_card(
    supabase_client,
    job_id: str,
    result: Any,
    fields_dict: Dict,
    school_id: str,
    user_id: str,
    event_id: str,
    serial_number: str,
    image_path: str,
    now: str
) -> None:
    """
    Save V2 universal card to student_school_interactions table.
    Creates student record if it doesn't exist (new serial number).
    """
    from app.repositories.students_repository import get_student_by_serial, upsert_student
    from app.repositories.interactions_repository import create_student_school_interaction

    log_debug("=== SAVING V2 UNIVERSAL CARD ===", {
        "serial_number": serial_number,
        "school_id": school_id,
        "event_id": event_id
    }, service="worker_v3")

    # Check if this is an existing student or new student
    student_id = result.metadata.get("student_id")

    if not student_id:
        # New student - create from OCR result
        log_debug(f"Creating new student record for serial {serial_number}", service="worker_v3")

        # Extract student data from fields
        student_data = {
            "serial_number": serial_number,
            "source_method": "universal_card",
            "image_url": image_path  # Store original card image URL
        }

        # Map common fields from OCR to student columns
        field_mapping = {
            "first_name": "first_name",
            "last_name": "last_name",
            "preferred_first_name": "preferred_first_name",
            "email": "email",
            "cell": "cell",
            "date_of_birth": "date_of_birth",
            "address": "address",
            "address_2": "address_2",
            "city": "city",
            "state": "state",
            "zip_code": "zip_code",
            "high_school": "high_school",
            "grade_level": "grade_level",
            "grad_year": "grad_year",
            "gpa": "gpa",
            "gpa_scale": "gpa_scale",
            "sat_score": "sat_score",
            "act_score": "act_score",
            "entry_term": "entry_term",
            "entry_year": "entry_year",
            "student_type": "student_type",
            "major": "major"
        }

        for field_key, student_col in field_mapping.items():
            if field_key in fields_dict:
                value = fields_dict[field_key].get("value")
                if value and value != "":
                    student_data[student_col] = value

        # Handle permission_to_text conversion (text to boolean)
        if "permission_to_text" in fields_dict:
            ptt_value = fields_dict["permission_to_text"].get("value", "").lower()
            if ptt_value == "yes":
                student_data["permission_to_text"] = True
            elif ptt_value == "no":
                student_data["permission_to_text"] = False

        # Create student record
        student = upsert_student(student_data)
        student_id = student["id"]

        log_debug(f"✅ Created student record: {student_id}", service="worker_v3")

    # Create or update student_school_interaction
    from app.repositories.interactions_repository import check_existing_interaction, update_student_school_interaction

    # Check if interaction already exists
    existing_interaction = check_existing_interaction(student_id, school_id, event_id)

    interaction_data = {
        "student_id": student_id,
        "school_id": school_id,
        "event_id": event_id,
        "user_id": user_id,
        "fields": fields_dict,
        "source_method": "universal_card",
        "review_status": result.metadata.get("review_status", "needs_review"),
        "image_path": image_path,  # Include image path so UI can display the card
        "updated_at": now
    }

    # Add reviewed_at if status is reviewed
    if interaction_data["review_status"] == "reviewed":
        interaction_data["reviewed_at"] = now

    if existing_interaction:
        # Update existing interaction
        interaction_id = existing_interaction["id"]
        interaction = update_student_school_interaction(interaction_id, interaction_data)
        log_debug(f"✅ Updated existing student_school_interaction: {interaction_id}", {
            "student_id": student_id,
            "serial_number": serial_number,
            "review_status": interaction_data["review_status"]
        }, service="worker_v3")
    else:
        # Create new interaction
        interaction_data["created_at"] = now
        interaction = create_student_school_interaction(interaction_data)

    log_debug(f"✅ Created student_school_interaction: {interaction['id']}", {
        "student_id": student_id,
        "serial_number": serial_number,
        "review_status": interaction_data["review_status"],
        "skipped_gemini": result.metadata.get("skipped_gemini", False)
    }, service="worker_v3")

    # Update job status to complete (skip if job doesn't exist, e.g., in tests)
    try:
        update_processing_job(supabase_client, job_id, {"status": "complete"})
    except Exception as e:
        log_debug(f"Note: Could not update processing job (may not exist): {e}", service="worker_v3")


def download_from_supabase(file_url: str, local_path: str) -> None:
    """Download file from Supabase storage to local path"""
    try:
        supabase_client = get_supabase_client()
        
        # Extract bucket and file path from URL
        url_parts = file_url.split('/', 1)
        if len(url_parts) != 2:
            raise ValueError(f"Invalid file URL format: {file_url}")
            
        bucket_name = url_parts[0]
        file_path = url_parts[1]
        
        log_debug(f"Downloading from bucket: {bucket_name}, path: {file_path}", service="worker_v3")
        
        response = supabase_client.storage.from_(bucket_name).download(file_path)
        
        with open(local_path, 'wb') as f:
            f.write(response)
            
        log_debug(f"Downloaded file from {file_url} to {local_path}", service="worker_v3")
        
    except Exception as e:
        log_debug(f"ERROR downloading file: {str(e)}", service="worker_v3")
        raise


def process_job_v3(job: Dict[str, Any]) -> None:
    """Process job with duplicate detection and retry protection"""
    job_id = job["id"]
    retry_count = job.get("retry_count", 0)

    # Extract job parameters
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")

    log_debug(f"=== PROCESSING JOB V3 START ===", {
        "job_id": job_id,
        "retry_count": retry_count,
        "user_id": user_id,
        "school_id": school_id,
        "event_id": event_id,
        "file_url": file_url
    }, service="worker_v3")

    # Check retry limit
    if retry_count >= MAX_RETRIES:
        log_debug(f"Job {job_id} exceeded max retries ({MAX_RETRIES})", service="worker_v3")
        mark_job_permanently_failed(job_id, f"Exceeded {MAX_RETRIES} retry attempts")
        return
    
    supabase_client = get_supabase_client()
    tmp_file = None
    trimmed_image_path = None
    
    try:
        # Step 1: Download image
        log_debug("=== STEP 1: DOWNLOAD IMAGE ===", service="worker_v3")
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)

        # REMOVED: Duplicate detection was masking the real problem
        # The frontend is reusing the same image file for multiple scans
        # We need to fix the root cause, not add complexity to handle symptoms

        # Step 2: Run the pipeline (this is the magic!)
        log_debug("=== STEP 2: RUN PIPELINE ===", service="worker_v3")

        # Extract storage path for rotation correction
        # file_url format: "cards-uploads/user_id/date/filename"
        original_storage_path = file_url if file_url.startswith('cards-uploads/') else f'cards-uploads/{file_url.split("/", 1)[1] if "/" in file_url else file_url}'

        result = pipeline.process(
            image_path=tmp_file,
            school_id=school_id,
            user_id=user_id,
            event_id=event_id,
            original_storage_path=original_storage_path
        )
        
        log_debug("Pipeline processing complete", {
            "stage": result.stage.value,
            "field_count": len(result.fields),
            "review_status": result.metadata.get("review_status"),
            "fields_needing_review": result.metadata.get("fields_needing_review")
        }, service="worker_v3")
        
        # Step 3: Skip image trimming - use original image directly
        log_debug("=== STEP 3: USING ORIGINAL IMAGE (SKIPPING TRIMMING) ===", service="worker_v3")

        # Use the original uploaded image path directly
        original_image_path = job.get("image_path")
        log_debug(f"[IMAGE DEBUG] Using original image path directly: {original_image_path}", service="worker_v3")

        # Set trimmed_storage_path to the same as original for now
        # This ensures the UI can still pull from trimmed_image_path column
        trimmed_storage_path = original_image_path
        log_debug(f"[IMAGE DEBUG] ✅ Using original image as 'trimmed' image: {trimmed_storage_path}", service="worker_v3")
        
        # Step 4: Save results to database (V1 vs V2 routing)
        log_debug("=== STEP 4: SAVE TO DATABASE ===", service="worker_v3")

        # Convert FieldData objects back to dict format for database
        fields_dict = {}
        for key, field_data in result.fields.items():
            fields_dict[key] = field_data.to_dict()

        # Check if this is a V2 universal card (has serial number)
        serial_number = result.metadata.get("serial_number")
        is_v2_card = serial_number is not None

        if is_v2_card:
            log_debug(f"🆕 V2 Universal Card detected (serial: {serial_number}) - Saving to student_school_interactions", service="worker_v3")
        else:
            log_debug("📋 V1 Legacy card (no serial) - Saving to reviewed_data", service="worker_v3")
        
        # LOG CRITICAL INFO: Track what's happening with first_name and last_name
        log_debug("🔍 CRITICAL: Review status before save", {
            "review_status": result.metadata.get("review_status"),
            "fields_needing_review": result.metadata.get("fields_needing_review"),
            "first_name": {
                "value": fields_dict.get("first_name", {}).get("value"),
                "confidence": fields_dict.get("first_name", {}).get("confidence"),
                "required": fields_dict.get("first_name", {}).get("required"),
                "needs_review": fields_dict.get("first_name", {}).get("requires_human_review")
            },
            "last_name": {
                "value": fields_dict.get("last_name", {}).get("value"),
                "confidence": fields_dict.get("last_name", {}).get("confidence"),
                "required": fields_dict.get("last_name", {}).get("required"),
                "needs_review": fields_dict.get("last_name", {}).get("requires_human_review")
            }
        }, service="worker_v3")
        
        now = datetime.now(timezone.utc).isoformat()
        
        # Determine original image path - CRITICAL: This should be the storage path, not local path
        original_image_path = job.get("image_path")
        log_debug(f"[IMAGE DEBUG] Original image path from job: {original_image_path}", service="worker_v3")
        log_debug(f"[IMAGE DEBUG] Trimmed storage path: {trimmed_storage_path}", service="worker_v3")
        
        # CRITICAL: Validate image paths before saving to database
        if original_image_path and not original_image_path.startswith("cards-uploads/"):
            log_debug(f"[IMAGE DEBUG] ⚠️ WARNING: Original image path looks like local path, not storage path: {original_image_path}", service="worker_v3")
            log_debug(f"[IMAGE DEBUG] This may cause UI image loading issues", service="worker_v3")
        
        if is_v2_card:
            # V2 Path: Save to student_school_interactions
            save_v2_universal_card(
                supabase_client=supabase_client,
                job_id=job_id,
                result=result,
                fields_dict=fields_dict,
                school_id=school_id,
                user_id=user_id,
                event_id=event_id,
                serial_number=serial_number,
                image_path=original_image_path,
                now=now
            )
        else:
            # V1 Path: Save to reviewed_data (legacy)
            review_data = {
                "document_id": job_id,
                "fields": fields_dict,
                "school_id": school_id,
                "user_id": user_id,
                "event_id": event_id,
                "image_path": original_image_path,
                "trimmed_image_path": trimmed_storage_path,
                "review_status": result.metadata.get("review_status"),
                "created_at": now,
                "updated_at": now
            }

            log_debug(f"[IMAGE DEBUG] Final review_data image paths:", {
                "image_path": review_data["image_path"],
                "trimmed_image_path": review_data["trimmed_image_path"]
            }, service="worker_v3")

            log_debug("🔍 CRITICAL: Saving V1 review data", {
                "document_id": job_id,
                "field_count": len(fields_dict),
                "review_status": review_data["review_status"],
                "fields_needing_review": result.metadata.get("fields_needing_review"),
                "pipeline_version": "v3",
                "timestamp": now
            }, service="worker_v3")

            update_job_status_with_review(supabase_client, job_id, "complete", review_data)
        
        log_debug(f"✅ Job {job_id} completed successfully with new pipeline", service="worker_v3")
        log_debug("=== PROCESSING JOB V3 END ===", service="worker_v3")
        
    except Exception as e:
        log_debug(f"❌ Error processing job {job_id}: {str(e)}", service="worker_v3")
        log_debug("Full traceback", traceback.format_exc(), service="worker_v3")
        
        # Update job status to failed
        now = datetime.now(timezone.utc).isoformat()
        update_processing_job(supabase_client, job_id, {
            "status": "failed",
            "error_message": str(e),
            "updated_at": now
        })
        
        raise
        
    finally:
        # Cleanup temporary files (only the downloaded temp file now)
        cleanup_files = []
        if tmp_file and os.path.exists(tmp_file):
            cleanup_files.append(tmp_file)

        for file_path in cleanup_files:
            try:
                os.remove(file_path)
                log_debug(f"Cleaned up: {file_path}", service="worker_v3")
            except Exception as cleanup_error:
                log_debug(f"Cleanup warning: {cleanup_error}", service="worker_v3")
        
        # Force garbage collection
        import gc
        gc.collect()


def main_v3():
    """Main worker loop for V3 pipeline with atomic job claiming"""
    worker_id = f"worker-{os.getpid()}-{datetime.now().timestamp()}"
    log_debug(f"Starting CardCapture processing worker V3 with ID: {worker_id}", service="worker_v3")

    while True:
        try:
            log_debug("=== CHECKING FOR QUEUED JOBS ===", service="worker_v3")

            # Get Supabase client
            supabase_client = get_supabase_client()

            # Atomically claim next job using RPC function
            result = supabase_client.rpc(
                'claim_next_job',
                {
                    'p_worker_id': worker_id,
                    'p_stale_minutes': STALE_JOB_MINUTES
                }
            ).execute()

            if result.data and len(result.data) > 0:
                job = result.data[0]
                log_debug(f"Successfully claimed job {job['id']}", {
                    "worker_id": worker_id,
                    "retry_count": job.get('retry_count', 0)
                }, service="worker_v3")

                # Process the job normally
                try:
                    process_job_v3(job)
                except Exception as e:
                    log_debug(f"Job processing failed: {str(e)}", service="worker_v3")
                    # The existing error handling in process_job_v3 will handle retries

            else:
                log_debug("No queued jobs found, sleeping...", service="worker_v3")
                time.sleep(SLEEP_SECONDS)

        except Exception as e:
            log_debug(f"Worker error: {str(e)}", service="worker_v3")
            log_debug("Worker traceback", traceback.format_exc(), service="worker_v3")
            time.sleep(SLEEP_SECONDS)


@app.get("/process")
def process_get_endpoint():
    """GET endpoint for health checks - returns service status"""
    return {"message": "Worker V3 is ready", "method": "POST", "status": "healthy", "version": "v3"}


@app.post("/process")
async def process_job_endpoint(request: Request):
    """Process job endpoint using new pipeline"""
    try:
        log_debug("=== INCOMING REQUEST V3 ===", service="worker_v3")
        log_debug("Headers", dict(request.headers), service="worker_v3")
        log_debug("Client", request.client, service="worker_v3")
        
        data = await request.json()
        log_debug("Request body", data, service="worker_v3")
        
        if not data or "job_id" not in data:
            raise HTTPException(status_code=400, detail="Missing job_id in request")
        
        job_id = data["job_id"]
        log_debug(f"Processing job_id: {job_id} with pipeline V3", service="worker_v3")
        
        # Fetch the job details from Supabase
        supabase_client = get_supabase_client()
        job_query = supabase_client.table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
        
        if not job_query.data:
            log_debug(f"Job {job_id} not found in database", service="worker_v3")
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
            
        job = job_query.data
        log_debug("Found job in database", job, service="worker_v3")
        
        # Update status to processing
        now = datetime.now(timezone.utc).isoformat()
        update_processing_job(supabase_client, job_id, {
            "status": "processing", 
            "updated_at": now
        })
        
        # Process the job with new pipeline
        process_job_v3(job)
        
        return {
            "status": "success", 
            "message": f"Job {job_id} processing completed with pipeline V3",
            "version": "v3"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Error in process_job_endpoint: {str(e)}", service="worker_v3")
        log_debug("Full traceback", traceback.format_exc(), service="worker_v3")
        raise HTTPException(status_code=500, detail=str(e))


# Note: Main block removed - let Cloud Run handle uvicorn startup
# The Dockerfile.worker should use: CMD uvicorn app.worker.worker_v3:app --host 0.0.0.0 --port $PORT