from fastapi import HTTPException
from typing import Optional, Dict, Any, List

def insert_processing_job(supabase_client, job_data):
    response = supabase_client.table("processing_jobs").insert(job_data).execute()
    if hasattr(response, 'error') and response.error:
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    return response

def update_processing_job(supabase_client, job_id, update_data):
    response = supabase_client.table("processing_jobs").update(update_data).eq("id", job_id).execute()
    if hasattr(response, 'error') and response.error:
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    return response

def claim_next_job(supabase_client, worker_id: str, stale_minutes: int = 5) -> Optional[Dict[str, Any]]:
    """Atomically claim the next available job for processing"""
    try:
        result = supabase_client.rpc(
            'claim_next_job',
            {
                'p_worker_id': worker_id,
                'p_stale_minutes': stale_minutes
            }
        ).execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to claim job: {str(e)}")

def check_for_duplicate(supabase_client, image_hash: str, event_id: str, window_minutes: int = 5) -> Optional[Dict[str, Any]]:
    """Check if this image has already been processed recently"""
    try:
        result = supabase_client.rpc(
            'check_duplicate_job',
            {
                'p_image_hash': image_hash,
                'p_event_id': event_id,
                'p_window_minutes': window_minutes
            }
        ).execute()

        if result.data and len(result.data) > 0 and result.data[0].get('is_duplicate'):
            return result.data[0]
        return None

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check for duplicates: {str(e)}")

def get_job_statistics(supabase_client, hours: int = 1) -> List[Dict[str, Any]]:
    """Get job processing statistics for monitoring"""
    try:
        result = supabase_client.rpc(
            'get_job_statistics',
            {'p_hours': hours}
        ).execute()

        return result.data if result.data else []

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get job statistics: {str(e)}")

def find_stuck_jobs(supabase_client, minutes: int = 5) -> List[Dict[str, Any]]:
    """Find jobs that have been processing for too long"""
    try:
        result = supabase_client.rpc(
            'find_stuck_jobs',
            {'p_minutes': minutes}
        ).execute()

        return result.data if result.data else []

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find stuck jobs: {str(e)}") 