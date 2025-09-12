"""
Worker V3 - New pipeline implementation
"""
import os
import time
import tempfile
import traceback
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.pipeline.pipeline import CardProcessingPipeline
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import get_supabase_client
from app.repositories.uploads_repository import update_job_status_with_review
from app.utils.image_processing import ensure_trimmed_image
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


@app.on_event("startup")
async def startup_event():
    """Log when the app starts up"""
    print("🚀 CardCapture Worker API V3 is starting up...", flush=True)
    print(f"🌐 Environment: PORT={os.environ.get('PORT', 'NOT_SET')}", flush=True)
    try:
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        print("✅ Supabase client imported and initialized successfully", flush=True)
        print("✅ New pipeline system loaded", flush=True)
        print("✅ CardCapture Worker API V3 startup complete", flush=True)
    except Exception as e:
        print(f"⚠️ Startup dependency check failed (continuing): {e}", flush=True)


@app.get("/")
def root():
    return {"message": "CardCapture Worker API V3 is running", "version": "v3", "pipeline": "new"}


@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run"""
    return {"status": "healthy", "service": "card-capture-worker-v3", "version": "v3"}


@app.get("/ready")
def readiness_check():
    """Readiness check endpoint - verifies all dependencies are working"""
    try:
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        return {
            "status": "ready", 
            "service": "card-capture-worker-v3",
            "version": "v3",
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
            "service": "card-capture-worker-v3",
            "error": str(e)
        }


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
    """
    New simplified job processor using the pipeline system.
    
    Much cleaner than the old 12-step process!
    """
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    
    log_debug("🔍🔍🔍 CRITICAL: PROCESS_JOB_V3 CALLED 🔍🔍🔍", {
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "caller": "Check stack trace to see who called this"
    }, service="worker_v3")
    
    log_debug("=== PROCESSING JOB V3 START ===", {
        "job_id": job_id,
        "user_id": user_id,
        "school_id": school_id,
        "event_id": event_id,
        "file_url": file_url
    }, service="worker_v3")
    
    supabase_client = get_supabase_client()
    tmp_file = None
    trimmed_image_path = None
    
    try:
        # Step 1: Download image
        log_debug("=== STEP 1: DOWNLOAD IMAGE ===", service="worker_v3")
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        
        # Step 2: Run the pipeline (this is the magic!)
        log_debug("=== STEP 2: RUN PIPELINE ===", service="worker_v3")
        result = pipeline.process(
            image_path=tmp_file,
            school_id=school_id,
            user_id=user_id,
            event_id=event_id
        )
        
        log_debug("Pipeline processing complete", {
            "stage": result.stage.value,
            "field_count": len(result.fields),
            "review_status": result.metadata.get("review_status"),
            "fields_needing_review": result.metadata.get("fields_needing_review")
        }, service="worker_v3")
        
        # Step 3: Handle image trimming and upload
        log_debug("=== STEP 3: TRIM AND UPLOAD IMAGE ===", service="worker_v3")
        cropped_image_path = result.metadata.get("cropped_image_path")
        trimmed_storage_path = None
        
        log_debug(f"[IMAGE DEBUG] Cropped image path from pipeline: {cropped_image_path}", service="worker_v3")
        log_debug(f"[IMAGE DEBUG] Cropped image exists: {os.path.exists(cropped_image_path) if cropped_image_path else 'N/A'}", service="worker_v3")
        log_debug(f"[IMAGE DEBUG] Original tmp file: {tmp_file}", service="worker_v3")
        log_debug(f"[IMAGE DEBUG] Original tmp file exists: {os.path.exists(tmp_file) if tmp_file else 'N/A'}", service="worker_v3")
        
        if cropped_image_path and os.path.exists(cropped_image_path):
            # Use the cropped image from DocAI processing
            trimmed_image_path = cropped_image_path
            log_debug(f"[IMAGE DEBUG] Using cropped image from DocAI: {trimmed_image_path}", service="worker_v3")
        else:
            # Fall back to trimming the original
            trimmed_image_path = ensure_trimmed_image(tmp_file)
            log_debug(f"[IMAGE DEBUG] Using fallback trimmed image: {trimmed_image_path}", service="worker_v3")
        
        log_debug(f"[IMAGE DEBUG] Final trimmed image path: {trimmed_image_path}", service="worker_v3")
        log_debug(f"[IMAGE DEBUG] Final trimmed image exists: {os.path.exists(trimmed_image_path) if trimmed_image_path else 'N/A'}", service="worker_v3")
        
        try:
            trimmed_storage_path = upload_to_supabase_storage_from_path(
                supabase_client,
                trimmed_image_path,
                user_id,
                os.path.basename(trimmed_image_path)
            )
            log_debug(f"[IMAGE DEBUG] ✅ Trimmed image uploaded to storage: {trimmed_storage_path}", service="worker_v3")
        except Exception as e:
            log_debug(f"[IMAGE DEBUG] ❌ Failed to upload trimmed image: {e}", service="worker_v3")
        
        # Step 4: Save results to database
        log_debug("=== STEP 4: SAVE TO DATABASE ===", service="worker_v3")
        
        # Convert FieldData objects back to dict format for database
        fields_dict = {}
        for key, field_data in result.fields.items():
            fields_dict[key] = field_data.to_dict()
        
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
        
        log_debug("🔍 CRITICAL: Saving review data", {
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
        # Cleanup temporary files
        cleanup_files = []
        if tmp_file and os.path.exists(tmp_file):
            cleanup_files.append(tmp_file)
        if trimmed_image_path and os.path.exists(trimmed_image_path) and trimmed_image_path != tmp_file:
            cleanup_files.append(trimmed_image_path)
        
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
    """
    Main worker loop for V3 pipeline
    """
    log_debug("Starting CardCapture processing worker V3...", service="worker_v3")
    
    try:
        log_debug("=== CHECKING FOR QUEUED JOBS ===", service="worker_v3")
        
        # Get next queued job
        supabase_client = get_supabase_client()
        jobs = supabase_client.table("processing_jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
        
        if jobs.data and len(jobs.data) > 0:
            job = jobs.data[0]
            log_debug(f"Found job {job['id']} to process", service="worker_v3")
            
            # Mark job as processing
            now = datetime.now(timezone.utc).isoformat()
            update_processing_job(supabase_client, job["id"], {
                "status": "processing",
                "updated_at": now
            })
            
            # Process the job
            process_job_v3(job)
            
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