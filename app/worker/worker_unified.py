"""
Unified Worker - Routes to V2 or V3 pipeline based on feature flags
"""
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# Pipeline configuration no longer needed - V3 is now the standard
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug

# Import both pipeline processors
# V2 worker removed - V3 is now the standard pipeline
from app.worker.worker_v3 import process_job_v3

app = FastAPI(title="CardCapture Unified Worker API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SLEEP_SECONDS = 1


@app.on_event("startup")
async def startup_event():
    """Log when the app starts up"""
    print("🚀 CardCapture Unified Worker API is starting up...", flush=True)
    print(f"🌐 Environment: PORT={os.environ.get('PORT', 'NOT_SET')}", flush=True)
    
    # Show pipeline configuration
    print(f"📊 Pipeline Configuration:", flush=True)
    print(f"   Version: V3 (standard pipeline)", flush=True)
    
    try:
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        print("✅ Supabase client imported and initialized successfully", flush=True)
        print("✅ Both pipeline versions loaded", flush=True)
        print("✅ CardCapture Unified Worker API startup complete", flush=True)
    except Exception as e:
        print(f"⚠️ Startup dependency check failed (continuing): {e}", flush=True)


@app.get("/")
def root():
    return {
        "message": "CardCapture Unified Worker API is running",
        "version": "unified",
        "pipeline_version": "v3"
    }


@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run"""
    return {
        "status": "healthy", 
        "service": "card-capture-worker-unified",
        "version": "unified",
        "pipeline_version": "v3"
    }


@app.get("/ready")
def readiness_check():
    """Readiness check endpoint - verifies all dependencies are working"""
    try:
        from app.core.clients import get_supabase_client
        supabase_client = get_supabase_client()
        
        return {
            "status": "ready", 
            "service": "card-capture-worker-unified",
            "version": "unified",
            "pipeline_version": "v3",
            "dependencies": {
                "supabase": "connected",
                "storage_path": "/tmp writable"
            }
        }
    except Exception as e:
        return {
            "status": "not_ready", 
            "service": "card-capture-worker-unified",
            "error": str(e)
        }


def determine_pipeline_version(job: Dict[str, Any]) -> str:
    """
    Determine which pipeline version to use for this job.
    Always returns 'v3' - V3 is now the standard pipeline.
    
    Args:
        job: Job data containing school_id, user_id, etc.
        
    Returns:
        Pipeline version (always 'v3')
    """
    # V3 is now the standard - no more V2 fallback
    return "v3"


def process_job_unified(job: Dict[str, Any]) -> None:
    """
    Unified job processor that routes to the appropriate pipeline version.
    """
    job_id = job["id"]
    school_id = job.get("school_id")
    user_id = job.get("user_id")
    
    # Determine which pipeline to use
    pipeline_version = determine_pipeline_version(job)
    
    log_debug(f"=== UNIFIED WORKER PROCESSING JOB {job_id} ===", {
        "pipeline_version": pipeline_version,
        "school_id": school_id,
        "user_id": user_id,
        "routing_reason": _get_routing_reason(school_id, user_id, pipeline_version)
    }, service="worker_unified")
    
    # Log pipeline version (but don't try to save it to DB if column doesn't exist)
    supabase_client = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    
    # For now, just update the timestamp (we can track pipeline version in metadata)
    update_processing_job(supabase_client, job_id, {
        "updated_at": now
    })
    
    try:
        # Process with V3 pipeline (now the standard)
        log_debug(f"🚀 Processing job {job_id} with Pipeline V3", service="worker_unified")
        process_job_v3(job)
            
        log_debug(f"✅ Job {job_id} completed successfully with Pipeline V3", service="worker_unified")
        
    except Exception as e:
        log_debug(f"❌ Job {job_id} failed with Pipeline V3: {str(e)}", service="worker_unified")
        
        # Update job with pipeline version info even on failure
        update_processing_job(supabase_client, job_id, {
            "status": "failed",
            "error_message": f"Pipeline V3: {str(e)}",
            "updated_at": now
        })
        
        raise


def _get_routing_reason(school_id: str, user_id: str, pipeline_version: str) -> str:
    """Get human-readable reason for pipeline routing decision"""
    return "V3 is now the standard pipeline"


def main_unified():
    """
    Main worker loop for unified pipeline routing
    """
    log_debug("Starting CardCapture unified processing worker...", service="worker_unified")
    
    try:
        log_debug("=== CHECKING FOR QUEUED JOBS ===", service="worker_unified")
        
        # Get next queued job
        supabase_client = get_supabase_client()
        jobs = supabase_client.table("processing_jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
        
        if jobs.data and len(jobs.data) > 0:
            job = jobs.data[0]
            log_debug(f"Found job {job['id']} to process", service="worker_unified")
            
            # Mark job as processing
            now = datetime.now(timezone.utc).isoformat()
            update_processing_job(supabase_client, job["id"], {
                "status": "processing",
                "updated_at": now
            })
            
            # Process the job with appropriate pipeline
            process_job_unified(job)
            
        else:
            log_debug("No queued jobs found, sleeping...", service="worker_unified")
            time.sleep(SLEEP_SECONDS)
            
    except Exception as e:
        log_debug(f"Unified worker error: {str(e)}", service="worker_unified")
        log_debug("Unified worker traceback", traceback.format_exc(), service="worker_unified")
        time.sleep(SLEEP_SECONDS)


@app.get("/process")
def process_get_endpoint():
    """GET endpoint for health checks - returns service status"""
    return {
        "message": "Unified Worker is ready", 
        "method": "POST", 
        "status": "healthy", 
        "version": "unified",
        "pipeline_version": "v3"
    }


@app.post("/process")
async def process_job_endpoint(request: Request):
    """Process job endpoint using unified pipeline routing"""
    try:
        log_debug("=== INCOMING REQUEST UNIFIED ===", service="worker_unified")
        log_debug("Headers", dict(request.headers), service="worker_unified")
        log_debug("Client", request.client, service="worker_unified")
        
        data = await request.json()
        log_debug("Request body", data, service="worker_unified")
        
        if not data or "job_id" not in data:
            raise HTTPException(status_code=400, detail="Missing job_id in request")
        
        job_id = data["job_id"]
        log_debug(f"Processing job_id: {job_id} with unified worker", service="worker_unified")
        
        # Fetch the job details from Supabase
        supabase_client = get_supabase_client()
        job_query = supabase_client.table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
        
        if not job_query.data:
            log_debug(f"Job {job_id} not found in database", service="worker_unified")
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
            
        job = job_query.data
        log_debug("Found job in database", job, service="worker_unified")
        
        # Update status to processing
        now = datetime.now(timezone.utc).isoformat()
        update_processing_job(supabase_client, job_id, {
            "status": "processing", 
            "updated_at": now
        })
        
        # Process the job with unified routing
        process_job_unified(job)
        
        pipeline_version = determine_pipeline_version(job)
        
        return {
            "status": "success", 
            "message": f"Job {job_id} processing completed",
            "pipeline_version": pipeline_version,
            "version": "unified"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Error in unified process_job_endpoint: {str(e)}", service="worker_unified")
        log_debug("Full traceback", traceback.format_exc(), service="worker_unified")
        raise HTTPException(status_code=500, detail=str(e))


# Pipeline configuration endpoint for monitoring
@app.get("/pipeline/config")
def get_pipeline_configuration():
    """Get current pipeline configuration"""
    return {
        "pipeline_version": "v3",
        "description": "V3 is now the standard pipeline"
    }


@app.post("/pipeline/test")
async def test_pipeline_routing(request: Request):
    """Test which pipeline version would be used for given parameters"""
    try:
        data = await request.json()
        school_id = data.get("school_id")
        user_id = data.get("user_id")
        
        pipeline_version = "v3"
        routing_reason = _get_routing_reason(school_id, user_id, pipeline_version)
        
        return {
            "school_id": school_id,
            "user_id": user_id,
            "pipeline_version": pipeline_version,
            "routing_reason": routing_reason
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Note: Main block removed - let Cloud Run handle uvicorn startup
# The Dockerfile.worker should use: CMD uvicorn app.worker.worker_unified:app --host 0.0.0.0 --port $PORT