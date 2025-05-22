import os
import tempfile
import traceback
import json
import functions_framework
from datetime import datetime, timezone
from app.services.document_service import parse_card_with_gemini
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import supabase_client
from app.repositories.reviewed_data_repository import upsert_reviewed_data

BUCKET = "cards-uploads"
MAX_RETRIES = 3

def download_from_supabase(storage_path, local_path):
    res = supabase_client.storage.from_(BUCKET).download(storage_path.replace(f"{BUCKET}/", ""))
    if hasattr(res, 'error') and res.error:
        raise Exception(f"Supabase Storage download error: {res.error}")
    with open(local_path, "wb") as f:
        f.write(res)
    return local_path

def sync_card_fields_preferences(supabase_client, user_id, school_id, docai_fields):
    """
    Ensure the settings table for the given user_id and school_id has all fields from docai_fields in preferences.card_fields.
    Adds missing fields with enabled=True and required=False. Inserts row if not present.
    """
    # Collect all unique field names from docai_fields
    field_names = set(docai_fields.keys())
    print(f"[Preferences Sync] Using field names from DocAI: {list(field_names)}")

    settings_query = supabase_client.table("settings").select("id, preferences").eq("user_id", user_id).eq("school_id", school_id).maybe_single().execute()
    settings_row = settings_query.data if settings_query and settings_query.data else None
    if settings_row:
        print(f"[Preferences Sync] Found existing settings row: id={settings_row.get('id')}")
        preferences = settings_row.get("preferences") or {}
        print(f"[Preferences Sync] DB card_fields: {preferences.get('card_fields')}")
        print(f"[Preferences Sync] New card_fields: {preferences.get('card_fields')}")
    else:
        print(f"[Preferences Sync] No settings row found. Will insert new row if needed.")
        preferences = {}
    card_fields = preferences.get("card_fields") if preferences else None

    # When creating new settings, initialize all fields as enabled but not required
    new_fields = {
        field: {
            "enabled": True,
            "required": False  # Default to not required
        } for field in field_names
    }

    if not card_fields or not isinstance(card_fields, dict) or not card_fields:
        print(f"[Preferences Sync] card_fields missing or invalid. Initializing with DocAI fields: {list(new_fields.keys())}")
        card_fields = dict(new_fields)  # ensure new object
        preferences["card_fields"] = card_fields
        print(f"[Preferences Sync] Forcing upsert of card_fields in DB.")
        upsert_payload = {
            "user_id": user_id,
            "school_id": school_id,
            "preferences": preferences
        }
        if settings_row:
            upsert_payload["id"] = settings_row["id"]
        supabase_client.table("settings").upsert(upsert_payload).execute()
        # Fetch again to confirm
        if settings_row:
            updated_row = supabase_client.table("settings").select("id, preferences").eq("id", settings_row["id"]).maybe_single().execute()
        else:
            updated_row = supabase_client.table("settings").select("id, preferences").eq("user_id", user_id).eq("school_id", school_id).maybe_single().execute()
        print(f"[Preferences Sync] After upsert, card_fields in DB: {updated_row.data.get('preferences', {}).get('card_fields') if updated_row and updated_row.data else None}")
        return

    # Add any new fields to existing settings
    updated = False
    for field in new_fields:
        if field not in card_fields:
            print(f"[Preferences Sync] Adding missing field to card_fields: {field}")
            card_fields[field] = {
                "enabled": True,
                "required": False  # New fields start as not required
            }
            updated = True

    if not updated:
        print(f"[Preferences Sync] No new fields to add to card_fields.")
        return

    # Update settings if new fields were added
    preferences["card_fields"] = card_fields
    if not settings_row:
        print(f"[Preferences Sync] Inserting new settings row for user_id={user_id}, school_id={school_id}")
        upsert_payload = {
            "user_id": user_id,
            "school_id": school_id,
            "preferences": preferences
        }
        supabase_client.table("settings").upsert(upsert_payload).execute()
        print(f"[Preferences Sync] Inserted new settings row for user_id={user_id}, school_id={school_id}")
    else:
        print(f"[Preferences Sync] Updating settings preferences.card_fields for user_id={user_id}, school_id={school_id}")
        upsert_payload = {
            "user_id": user_id,
            "school_id": school_id,
            "preferences": preferences
        }
        upsert_payload["id"] = settings_row["id"]
        supabase_client.table("settings").upsert(upsert_payload).execute()
        print(f"[Preferences Sync] Updated settings preferences.card_fields for user_id={user_id}, school_id={school_id}")

def process_job(job):
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    print(f"Processing job {job_id} for user {user_id}, file {file_url}")
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        print(f"Downloaded to {tmp_file}")
        # Use DocAI fields from processing_jobs.result_json
        docai_fields = job.get("result_json")
        if not docai_fields:
            raise Exception("No DocAI fields found in processing_jobs.result_json")
        # Run Gemini enhancement with DocAI fields
        gemini_fields = parse_card_with_gemini(tmp_file, docai_fields)
        print(f"Extracted fields: {json.dumps(gemini_fields)[:200]}...")
        # --- Preferences sync logic ---
        sync_card_fields_preferences(supabase_client, user_id, school_id, docai_fields)
        # --- End preferences sync logic ---
        now = datetime.now(timezone.utc).isoformat()
        reviewed_data = {
            "document_id": job_id,
            "fields": gemini_fields,
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": job.get("image_path"),
            "review_status": "reviewed",
            "created_at": now,
            "updated_at": now
        }
        upsert_reviewed_data(supabase_client, reviewed_data)
        print(f"✅ Upserted reviewed_data for job {job_id}")
        update_processing_job(supabase_client, job_id, {
            "status": "complete",
            "updated_at": now,
            "error_message": None
        })
        print(f"Job {job_id} complete.")
        return {"status": "success", "job_id": job_id}
    except Exception as e:
        print(f"Error processing job {job_id}: {e}")
        traceback.print_exc()
        retries = job.get("retries", 0) + 1
        now = datetime.now(timezone.utc).isoformat()
        if retries < MAX_RETRIES:
            update_processing_job(supabase_client, job_id, {
                "status": "queued",
                "error_message": str(e),
                "updated_at": now,
                "retries": retries
            })
            print(f"Job {job_id} re-queued (retry {retries}).")
            return {"status": "retrying", "job_id": job_id, "retry": retries}
        else:
            update_processing_job(supabase_client, job_id, {
                "status": "failed",
                "error_message": str(e),
                "updated_at": now
            })
            print(f"Job {job_id} failed after {MAX_RETRIES} retries.")
            return {"status": "failed", "job_id": job_id, "error": str(e)}
    finally:
        if tmp_file and os.path.exists(tmp_file):
            os.remove(tmp_file)

# HTTP Trigger for Cloud Functions Gen1
@functions_framework.http
def process_card_http(request):
    """HTTP Cloud Function that processes a card image.
    Args:
        request (flask.Request): The request object.
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`.
    """
    request_json = request.get_json(silent=True)
    
    if not request_json or 'job_id' not in request_json:
        return {"error": "Missing job_id in request"}, 400
    
    job_id = request_json['job_id']
    
    # Fetch the job details from Supabase
    job_query = supabase_client.table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
    
    if not job_query.data:
        return {"error": f"Job {job_id} not found"}, 404
        
    job = job_query.data
    
    # Update status to processing
    now = datetime.now(timezone.utc).isoformat()
    update_processing_job(supabase_client, job_id, {
        "status": "processing",
        "updated_at": now
    })
    
    # Process the job
    result = process_job(job)
    return result

# Pub/Sub Trigger
@functions_framework.cloud_event
def process_card_pubsub(cloud_event):
    """Cloud Function that processes a card when triggered by Pub/Sub.
    Args:
        cloud_event (CloudEvent): The CloudEvent that triggered this function.
    Returns:
        None; the output is written to Stackdriver Logging.
    """
    import base64
    
    # Get Pub/Sub message
    pubsub_message = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    message_json = json.loads(pubsub_message)
    
    if 'job_id' not in message_json:
        print("Error: Missing job_id in Pub/Sub message")
        return
    
    job_id = message_json['job_id']
    
    # Fetch the job details from Supabase
    job_query = supabase_client.table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
    
    if not job_query.data:
        print(f"Error: Job {job_id} not found")
        return
        
    job = job_query.data
    
    # Update status to processing
    now = datetime.now(timezone.utc).isoformat()
    update_processing_job(supabase_client, job_id, {
        "status": "processing",
        "updated_at": now
    })
    
    # Process the job
    result = process_job(job)
    print(f"Processing result: {result}")

# This is only used when running locally
if __name__ == "__main__":
    # This is used when running locally. Gunicorn is used to run the
    # application on Cloud Run. See entrypoint in Dockerfile.
    import os
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app(target=process_card_http, debug=True)
    app.run(host="0.0.0.0", port=port) 