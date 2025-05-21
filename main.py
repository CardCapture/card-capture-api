# main_updated_separate_prompt.py
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException, Form, Depends, Request, Body, status, Path
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi import Body 
import shutil
import os
import json
import uuid
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv
import googlemaps
from google.cloud import documentai_v1 as documentai
import google.generativeai as genai
import io # For file reading
import re
import traceback
from typing import Union, List, Dict, Any, Optional
from pydantic import BaseModel
from jose import jwt, JWTError
import warnings
from urllib3.exceptions import NotOpenSSLWarning
import mimetypes
import tempfile
import stripe
from app.core.gemini_prompt import GEMINI_PROMPT_TEMPLATE
from app.api.routes.cards import router as cards_router

warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

# === CONFIG ===
try:
    if os.path.exists("service_account.json"):
         os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
    elif not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("⚠️ Warning: GOOGLE_APPLICATION_CREDENTIALS environment variable not set and service_account.json not found.")
except Exception as e: print(f"❌ Error setting Google Application Credentials: {e}")

if os.path.exists(".env"): load_dotenv(dotenv_path=".env")
else: print("ℹ️ Info: .env file not found. Relying on system environment variables.")

# Load environment variables
load_dotenv()

# Check for required environment variables
required_vars = {
    'SUPABASE_URL': os.getenv('SUPABASE_URL'),
    'SUPABASE_SERVICE_ROLE_KEY': os.getenv('SUPABASE_SERVICE_ROLE_KEY'),
    'SUPABASE_ANON_KEY': os.getenv('SUPABASE_ANON_KEY'),
    'GOOGLE_PROJECT_ID': os.getenv('GOOGLE_PROJECT_ID'),
    'DOCAI_LOCATION': os.getenv('DOCAI_LOCATION'),
    'DOCAI_PROCESSOR_ID': os.getenv('DOCAI_PROCESSOR_ID'),
    'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY'),
    'GOOGLE_MAPS_API_KEY': os.getenv('GOOGLE_MAPS_API_KEY'),
    'GOOGLE_APPLICATION_CREDENTIALS': os.getenv('GOOGLE_APPLICATION_CREDENTIALS'),
    'SUPABASE_ENV': os.getenv('SUPABASE_ENV'),
    'STRIPE_SECRET_KEY': os.getenv('STRIPE_SECRET_KEY')
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    print(f"⚠️ Warning: Missing required environment variables: {', '.join(missing_vars)}")
else:
    print("✅ All required environment variables are present")

project_id = os.getenv("GOOGLE_PROJECT_ID", "878585200500")
location = os.getenv("DOCAI_LOCATION", "us")
processor_id = os.getenv("DOCAI_PROCESSOR_ID", "894b9758c2215ed6")
mime_type = "image/png" # Keep this for Document AI
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, GOOGLE_MAPS_API_KEY, project_id, processor_id]): 
    print(f"❌ Error: Missing essential configuration variables")
    print(f"SUPABASE_URL: {bool(SUPABASE_URL)}")
    print(f"SUPABASE_KEY: {bool(SUPABASE_KEY)}")
    print(f"GEMINI_API_KEY: {bool(GEMINI_API_KEY)}")
    print(f"GOOGLE_MAPS_API_KEY: {bool(GOOGLE_MAPS_API_KEY)}")
    print(f"project_id: {bool(project_id)}")
    print(f"processor_id: {bool(processor_id)}")

supabase_client: Union[Client, None] = None
# docai_client: Union[documentai.DocumentProcessorServiceClient, None] = None
try:
    docai_client = documentai.DocumentProcessorServiceClient()
    docai_name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
    print("✅ Document AI client initialized successfully")
except Exception as e:
    print(f"❌ Error initializing Document AI client: {str(e)}")
    print(f"❌ Error type: {type(e)}")
    import traceback
    traceback.print_exc()
docai_name: Union[str, None] = None
gmaps_client: Union[googlemaps.Client, None] = None

# Initialize Supabase clients
try:
    # Debug logging for Supabase admin client
    print(f"🔑 Initializing Supabase admin client with URL: {SUPABASE_URL}")
    print(f"🔑 Using service role key (first 10 chars): {SUPABASE_KEY[:10]}...")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Missing Supabase credentials")
        
    supabase_admin = create_client(
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY
    )
    # Set the global supabase_client to use the admin client
    supabase_client = supabase_admin
    print("✅ Successfully initialized Supabase admin client")
except Exception as e:
    print(f"❌ Error initializing Supabase admin client: {e}")
    supabase_admin = None
    supabase_client = None

try:
    # Debug logging for Supabase auth client
    print(f"🔑 Initializing Supabase auth client with URL: {SUPABASE_URL}")
    print(f"🔑 Using service role key (first 10 chars): {SUPABASE_KEY[:10]}...")
    
    supabase_auth = create_client(
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY  # Use service role key for auth operations
    )
    print("✅ Successfully initialized Supabase auth client")
except Exception as e:
    print(f"❌ Error initializing Supabase auth client: {e}")
    supabase_auth = None

try: 
    genai.configure(api_key=GEMINI_API_KEY)
except Exception as e: 
    print(f"❌ Error configuring Google Generative AI: {e}")

try:
    if GOOGLE_MAPS_API_KEY: 
        gmaps_client = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    else: 
        print("⚠️ Warning: GOOGLE_MAPS_API_KEY not set.")
except Exception as e: 
    print(f"❌ Error initializing Google Maps client: {e}")

try:
    docai_client = documentai.DocumentProcessorServiceClient()
    docai_name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
except Exception as e: 
    print(f"❌ Error initializing Document AI client: {e}")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

class MarkExportedPayload(BaseModel):
    document_ids: List[str]

class MarkArchivedPayload(BaseModel):
    document_ids: List[str]

class DeleteCardsPayload(BaseModel):
    document_ids: List[str]

class FieldReviewPayload(BaseModel):
    field_key: str
    value: str
    requires_human_review: bool
    source: str = "human_review"
    review_notes: str = "Manually Reviewed"

class EventCreatePayload(BaseModel):
    name: str
    date: str
    school_id: str

class ArchiveCardsPayload(BaseModel):
    document_ids: List[str]

class ArchiveEventsPayload(BaseModel):
    event_ids: List[str]

class UserUpdateRequest(BaseModel):
    first_name: str
    last_name: str
    role: str

class EventUpdatePayload(BaseModel):
    name: Optional[str] = None
    date: Optional[str] = None
    school_id: Optional[str] = None
    status: Optional[str] = None

# === FastAPI App Setup ===
app = FastAPI(title="Card Scanner API")
ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084",
    "http://localhost:8085",
    "http://localhost:8086",
    "http://localhost:8087",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "uploads/images"))
TRIMMED_FOLDER = os.environ.get("TRIMMED_FOLDER", os.path.join(os.path.dirname(__file__), "uploads/trimmed"))

# Ensure folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRIMMED_FOLDER, exist_ok=True)

print(f"ℹ️ Using upload folder: {UPLOAD_FOLDER}")

# === HELPERS ===
# Vision API related helpers removed

# --- get_gemini_review ---
def get_gemini_review(all_fields: dict, image_path: str) -> dict:
    global GEMINI_PROMPT_TEMPLATE # Access the template defined above
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
    except Exception as model_e:
        print(f"❌ Gemini model 'gemini-1.5-pro-latest' not accessible: {model_e}")
        return {}

    # Format the prompt using the global template and current fields
    try:
        prompt = GEMINI_PROMPT_TEMPLATE.format(
            all_fields_json=json.dumps(all_fields, indent=2)
        )
    except KeyError as e:
         print(f"❌ Error formatting prompt template: Missing '{{all_fields_json}}' placeholder in GEMINI_PROMPT_TEMPLATE. Check definition. Details: {e}")
         return {}
    except Exception as fmt_e:
        print(f"❌ Unexpected error formatting prompt template: {fmt_e}")
        traceback.print_exc()
        return {}


    response = None; cleaned_json_text = ""
    try:
        print(f"🧠 Sending request to Gemini for image: {os.path.basename(image_path)}")
        # Use io here to open the file
        with io.open(image_path, "rb") as f: image_bytes = f.read()
        current_mime_type = mime_type
        image_part = {"mime_type": current_mime_type, "data": image_bytes}
        # Ensure prompt variable is correctly passed
        response = model.generate_content([prompt, image_part])
        print(f"🧠 Gemini Raw Response Text:\n{response.text}\n--------------------")
        cleaned_json_text = re.sub(r"```json\s*([\s\S]*?)\s*```", r"\1", response.text).strip()
        print(f"🧠 Attempting to parse JSON:\n{cleaned_json_text}\n--------------------")
        gemini_dict = json.loads(cleaned_json_text)
        if isinstance(gemini_dict, dict): print("✅ Gemini review successful, JSON parsed."); return gemini_dict
        else: print(f"❌ Gemini response not a dictionary (type: {type(gemini_dict)})."); return {}
    except json.JSONDecodeError as json_e:
        print(f"❌ Error decoding Gemini JSON response: {json_e}")
        print(f"--- Faulty Text Start ---\n{cleaned_json_text[:1000]}\n--- Faulty Text End ---")
        traceback.print_exc(); return {}
    except Exception as e:
        print(f"❌ Error in get_gemini_review (API call or other): {e}")
        if response:
            if hasattr(response, 'prompt_feedback'): print(f"Prompt Feedback: {response.prompt_feedback}")
            if hasattr(response, 'candidates') and response.candidates:
                 if hasattr(response.candidates[0], 'finish_reason'): print(f"Finish Reason: {response.candidates[0].finish_reason}")
                 if hasattr(response.candidates[0], 'safety_ratings'): print(f"Safety Ratings: {response.candidates[0].safety_ratings}")
        traceback.print_exc(); return {}
# --- END get_gemini_review ---

def validate_address_with_google(address: str, zip_code: str) -> Optional[Dict[str, Any]]:
    """
    Validates an address using Google Maps Geocoding API, with fallback to zip-only query.

    Args:
        address: The street address (can be empty).
        zip_code: The zip code (required).

    Returns:
        A dictionary containing parsed address components and validation metadata,
        or None if validation fails.
        Includes keys: 'street_address', 'city', 'state', 'zip', 'formatted',
                       'location_type', 'partial_match', 'queried_by_zip_only'.
    """
    if not gmaps_client:
        print("ℹ️ Google Maps client not initialized.")
        return None
    if not zip_code:
        print("ℹ️ Zip Code missing for Google Maps validation.")
        return None

    geocode_result = None
    queried_by_zip_only = False
    full_address_query = f"{address}, {zip_code}" if address else zip_code

    # --- Try primary query (address + zip or just zip if address empty) ---
    print(f"🗺️ Validating via Google Maps (Primary): {full_address_query}")
    try:
        geocode_result = gmaps_client.geocode(full_address_query)
    except Exception as e:
        print(f"❌ Error during primary Google Maps query: {e}")
        traceback.print_exc()
        # Allow fallback even if primary query had an error
        geocode_result = None # Ensure it's None so fallback runs

    # --- Fallback Query (Zip Code Only) if primary failed ---
    if not geocode_result and address: # Only fallback if primary failed AND we had an address to begin with
        print(f"ℹ️ Primary validation failed for '{full_address_query}'. Trying fallback with Zip Code only: {zip_code}")
        try:
            geocode_result = gmaps_client.geocode(zip_code)
            if geocode_result:
                queried_by_zip_only = True # Mark that this result is from the zip-only query
                print(f"✅ Google Maps fallback query successful for Zip: {zip_code}")
        except Exception as e:
            print(f"❌ Error during fallback Google Maps query: {e}")
            traceback.print_exc()
            return None # Fail completely if fallback query errors

    # --- Process the result (either primary or fallback) ---
    if geocode_result:
        result = geocode_result[0]
        components = result.get('address_components', [])
        location_type = result.get('geometry', {}).get('location_type', 'UNKNOWN')
        # Partial match is less relevant if we only queried by zip, but capture it anyway
        partial_match_flag = result.get('partial_match', False)

        parsed = {
            "street_number": next((c['long_name'] for c in components if 'street_number' in c['types']), None),
            "route": next((c['long_name'] for c in components if 'route' in c['types']), None),
            "city": next((c['long_name'] for c in components if 'locality' in c['types']), None),
            "state": next((c['short_name'] for c in components if 'administrative_area_level_1' in c['types']), None),
            "zip": next((c['long_name'] for c in components if 'postal_code' in c['types']), None),
            "zip_suffix": next((c['long_name'] for c in components if 'postal_code_suffix' in c['types']), None),
            "formatted": result.get('formatted_address')
        }

        # Combine street parts (will likely be empty if queried_by_zip_only)
        street_address_parts = [parsed["street_number"], parsed["route"]]
        parsed["street_address"] = " ".join(filter(None, street_address_parts))

        if parsed["zip"] and parsed["zip_suffix"]:
            parsed["zip"] = f"{parsed['zip']}-{parsed['zip_suffix']}"

        validation_data = {
            "street_address": str(parsed["street_address"] or ''),
            "city": str(parsed["city"] or ''),
            "state": str(parsed["state"] or ''),
            "zip": str(parsed["zip"] or ''),
            "formatted": str(parsed["formatted"] or ''),
            "location_type": location_type,
            "partial_match": partial_match_flag,
            "queried_by_zip_only": queried_by_zip_only # Add flag indicating how query succeeded
        }

        # Check if essential components were found
        if validation_data["zip"] or (validation_data["city"] and validation_data["state"]):
             print(f"✅ Google Maps validation successful: {validation_data['formatted']} (Type: {location_type}, Partial: {partial_match_flag}, ZipOnlyQuery: {queried_by_zip_only})")
             return validation_data
        else:
             print(f"⚠️ Google Maps result missing essential components (City/State/Zip). Query: {full_address_query}")
             return None

    else:
        # API returned no results from either primary or fallback query
        print(f"⚠️ Address/Zip not found by Google Maps after fallback: {full_address_query}")
        return None

def validate_address_components(address: Optional[str], city: Optional[str], state: Optional[str], zip_code: Optional[str]) -> Dict[str, Any]:
    """
    Smart address validation that tries multiple paths and provides detailed validation results.
    First validates zip code to get city/state, then attempts to validate full address.
    """
    if not gmaps_client:
        return {
            "validated": {},
            "confidence": 0.30,
            "requires_review": True,
            "review_notes": "Google Maps client not available",
            "auto_filled": []
        }

    auto_filled = []
    validated_data = {
        "street_address": "",
        "city": "",
        "state": "",
        "zip": ""
    }
    
    # Clean and standardize inputs
    zip_code = str(zip_code).strip() if zip_code else ""
    city = str(city).strip() if city else ""
    state = str(state).strip().upper() if state else ""
    address = str(address).strip() if address else ""

    # Step 1: Validate zip code first to get city/state
    if zip_code and len(zip_code) >= 5:
        print(f"🔍 Validating via zip code: {zip_code}")
        zip_validation = validate_address_with_google("", zip_code)
        
        if zip_validation:
            # Always trust zip validation for city/state
            validated_data["city"] = zip_validation["city"]
            validated_data["state"] = zip_validation["state"]
            validated_data["zip"] = zip_validation["zip"]
            
            if not city: auto_filled.append("city")
            if not state: auto_filled.append("state")

    # Step 2: Now try to validate the full address
    requires_review = False
    review_notes = []
    
    if address:
        print(f"🔍 Validating full address: {address}")
        # Construct full address query using validated city/state from zip
        location_context = f"{validated_data['city']}, {validated_data['state']} {validated_data['zip']}"
        full_validation = validate_address_with_google(address, location_context)
        
        if full_validation and full_validation["street_address"]:
            validated_data["street_address"] = full_validation["street_address"]
            print(f"✅ Full address validated: {full_validation['street_address']}")
        else:
            requires_review = True
            review_notes.append("Could not verify street address")
            validated_data["street_address"] = address  # Keep original for review
            print("⚠️ Could not verify street address")
    else:
        requires_review = True
        review_notes.append("Missing street address")

    return {
        "validated": validated_data,
        "confidence": 0.95 if not requires_review else 0.3,
        "requires_review": requires_review,
        "review_notes": "; ".join(review_notes) if review_notes else "",
        "auto_filled": auto_filled
    }

ALL_EXPECTED_FIELDS = [
    'name', 'preferred_first_name', 'date_of_birth', 'email', 'cell',
    'permission_to_text', 'address', 'city', 'state', 'zip_code',
    'high_school', 'class_rank', 'students_in_class', 'gpa',
    'student_type', 'entry_term', 'major',
    'city_state']
    
# === MAIN DOCUMENT PROCESSING PIPELINE ===
def process_image(image_path: str) -> Dict[str, Any]:
    """
    Processes an image with Document AI and ensures all expected fields
    are present in the output dictionary, adding blanks for missing ones.
    Also attempts to split city_state if city/state are missing and validates address components.
    """
    if not docai_client or not docai_name:
        raise ValueError("Document AI client not available")
    print(f"🔍 Processing image '{os.path.basename(image_path)}' with Document AI...")
    try:
        with io.open(image_path, "rb") as image:
            image_content = image.read()
        current_mime_type = mime_type
        raw_document = documentai.RawDocument(content=image_content, mime_type=current_mime_type)
        request = documentai.ProcessRequest(name=docai_name, raw_document=raw_document)
        result = docai_client.process_document(request=request)
        document = result.document

        print(f"✅ Document AI OCR processing completed.")
        print("-" * 20, "Document AI Raw Response Start", "-" * 20)
        print("Detected Entities:")
        if document.entities:
            for entity in document.entities:
                print(f"  - Type: {entity.type_}\n    Mention Text: '{entity.mention_text}'\n    Confidence: {entity.confidence:.4f}")
        else:
            print("  No entities detected by the processor.")
        print("-" * 20, "Document AI Raw Response End", "-" * 20)

        # --- Process Found Entities ---
        processed_dict = {}
        if document.entities:
            for entity in document.entities:
                key = entity.type_
                value = entity.mention_text.strip()
                docai_confidence = entity.confidence
                # Use placeholder key 'vision_confidence' as Gemini prompt expects it
                # This value will be ignored by Gemini per the prompt instructions
                processed_dict[key] = {"value": value, "vision_confidence": docai_confidence}
            print(f"✅ Formatted {len(processed_dict)} fields found by Document AI.")
        else:
             print("⚠️ No entities found by Document AI.")

        # --- Ensure All Expected Fields Exist ---
        final_extracted_fields = {}
        for field_key in ALL_EXPECTED_FIELDS:
            if field_key in processed_dict:
                final_extracted_fields[field_key] = processed_dict[field_key]
            else:
                # Field was not found by Document AI, add as blank/null entry
                print(f"ℹ️ Field '{field_key}' not found by Document AI, adding as blank.")
                final_extracted_fields[field_key] = {
                    "value": "",  # Use empty string for missing value
                    "vision_confidence": 0.0 # Assign zero confidence
                }

        # --- Validate Address Components ---
        try:
            address = final_extracted_fields.get('address', {}).get('value', '')
            city = final_extracted_fields.get('city', {}).get('value', '')
            state = final_extracted_fields.get('state', {}).get('value', '')
            zip_code = final_extracted_fields.get('zip_code', {}).get('value', '')
            
            print("\n=== Pre-Validation Values ===")
            print(f"Address: '{address}'")
            print(f"City: '{city}'")
            print(f"State: '{state}'")
            print(f"Zip Code: '{zip_code}'")

            validation_result = validate_address_components(
                address=address,
                city=city,
                state=state,
                zip_code=zip_code
            )

            if validation_result:
                print("✅ Address validation completed")
                validated_data = validation_result['validated']
                
                # Always update city/state/zip from validation
                if validated_data['city']:
                    final_extracted_fields['city'] = {
                        "value": validated_data['city'],
                        "vision_confidence": 0.95,
                        "requires_human_review": False,
                        "source": "zip_validation"
                    }
                if validated_data['state']:
                    final_extracted_fields['state'] = {
                        "value": validated_data['state'],
                        "vision_confidence": 0.95,
                        "requires_human_review": False,
                        "source": "zip_validation"
                    }
                if validated_data['zip']:
                    final_extracted_fields['zip_code'] = {
                        "value": validated_data['zip'],
                        "vision_confidence": 0.95,
                        "requires_human_review": False,
                        "source": "zip_validation"
                    }

                # Handle address field
                final_extracted_fields['address'] = {
                    "value": address if validation_result['requires_review'] else validated_data['street_address'],
                    "vision_confidence": validation_result['confidence'],
                    "requires_human_review": validation_result['requires_review'],
                    "review_notes": validation_result['review_notes'],
                    "suggested_value": validated_data['street_address'] if validation_result['requires_review'] and validated_data['street_address'] != address else None,
                    "source": "address_validation"
                }
            else:
                print("⚠️ Address validation failed completely")
                final_extracted_fields['address'] = {
                    "value": address,
                    "vision_confidence": 0.3,
                    "requires_human_review": True,
                    "review_notes": "Address validation failed",
                    "source": "validation_failed"
                }
        except Exception as val_error:
            print(f"⚠️ Error during address validation: {val_error}")
            final_extracted_fields['address'] = {
                "value": address,
                "vision_confidence": 0.3,
                "requires_human_review": True,
                "review_notes": f"Error validating address: {str(val_error)}",
                "source": "validation_error"
            }

        print(f"✅ Final extracted dictionary includes {len(final_extracted_fields)} fields (including added blanks).")
        return final_extracted_fields

    except Exception as e:
        print(f"❌ Error during process_image: {e}")
        traceback.print_exc()
        raise e

# === ASYNCHRONOUS GEMINI REVIEW TASK ===
# === ASYNCHRONOUS GEMINI REVIEW TASK ===
async def run_gemini_review(document_id: str, extracted_fields_dict: dict, image_path: str):
    if not supabase_client: 
        print("❌ Supabase client not available")
        return
        
    print(f"⏳ Background Task: Starting Gemini review for document_id: {document_id}")
    try:
        # Get the event_id from extracted_data with more robust error handling
        try:
            extracted_response = supabase_client.table("extracted_data") \
                .select("*") \
                .eq("document_id", document_id) \
                .execute()
            
            if not extracted_response.data:
                print(f"❌ No extracted data found for document_id: {document_id}")
                return
                
            event_id = extracted_response.data[0].get("event_id")
            print(f"📝 Found event_id: {event_id} for document: {document_id}")
        except Exception as db_e:
            print(f"❌ Error fetching extracted data: {db_e}")
            return

        gemini_reviewed_data = get_gemini_review(extracted_fields_dict, image_path)
        if not gemini_reviewed_data:
            print(f"⚠️ Gemini review failed or returned empty for {document_id}. Saving original data with error status.")
            insert_data = {
                "document_id": document_id,
                "fields": extracted_fields_dict,
                "review_status": "review_error",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "event_id": event_id
            }
            try:
                if supabase_client: 
                    supabase_client.table("reviewed_data").upsert(insert_data, on_conflict="document_id").execute()
                    print(f"✅ Saved original data with 'review_error' status for {document_id}.")
                else: 
                    print("❌ Cannot save error status: Supabase client not available.")
            except Exception as db_e: 
                print(f"❌ Supabase error saving error status for {document_id}: {db_e}")
            return

        print(f"✅ Background Task: Gemini review completed for {document_id}")
        final_reviewed_fields = {}
        any_field_needs_review = False
        
        for field_name, review_data in gemini_reviewed_data.items():
            if isinstance(review_data, dict):
                final_reviewed_fields[field_name] = {
                    "value": review_data.get("value"),
                    "confidence": review_data.get("review_confidence", 0.0),
                    "requires_human_review": review_data.get("requires_human_review", False),
                    "review_notes": review_data.get("review_notes", ""),
                    "source": "gemini"
                }
                if review_data.get("requires_human_review"):
                    any_field_needs_review = True
            else:
                print(f"⚠️ Unexpected format for field '{field_name}': {review_data}")
                original_data = extracted_fields_dict.get(field_name, {})
                final_reviewed_fields[field_name] = {
                    "value": review_data if isinstance(review_data, str) else None,
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "review_notes": "Unexpected data format from Gemini review",
                    "source": "gemini_error"
                }
                any_field_needs_review = True

        # Save the reviewed data
        try:
            update_data = {
                "document_id": document_id,
                "fields": final_reviewed_fields,
                "review_status": "needs_human_review" if any_field_needs_review else "reviewed",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "event_id": event_id
            }
            
            supabase_client.table("reviewed_data").upsert(update_data, on_conflict="document_id").execute()
            print(f"✅ Background Task: Saved reviewed data for {document_id}")
            
            # Send notification about review completion
            try:
                notification_data = {
                    "document_id": document_id,
                    "event": "review_completed",
                    "status": "needs_human_review" if any_field_needs_review else "reviewed",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                supabase_client.table("upload_notifications").insert(notification_data).execute()
                print(f"✅ Notification sent for review completed: {document_id}")
            except Exception as notif_error:
                print(f"⚠️ Failed to send notification: {notif_error}")
                
        except Exception as db_e: 
            print(f"❌ Background Task: Supabase error saving reviewed data for {document_id}: {db_e}")
            raise db_e
    except Exception as e:
        print(f"❌ Background Task: Error during run_gemini_review for {document_id}: {e}")
        traceback.print_exc()
        try:
            if supabase_client: 
                supabase_client.table("reviewed_data").upsert({
                    "document_id": document_id, 
                    "review_status": "review_error", 
                    "fields": extracted_fields_dict,
                    "event_id": event_id
                }, on_conflict="document_id").execute()
        except Exception as db_err: 
            print(f"❌ Failed to update review status to error for {document_id}: {db_err}")
    finally:
        try:
            if os.path.exists(image_path):
                print(f"✅ Background Task: File cleanup SKIPPED for: {image_path}")
        except Exception as e: 
            print(f"⚠️ Background Task: Error checking/skipping cleanup for file {image_path}: {e}")

# === API ENDPOINTS ===
# Helper to upload to Supabase Storage
async def upload_to_supabase_storage_from_path(trimmed_path: str, user_id: str, original_filename: str) -> str:
    import uuid
    from datetime import datetime
    file_extension = os.path.splitext(original_filename)[1] if original_filename else '.png'
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    today = datetime.now().strftime('%Y-%m-%d')
    storage_path = f"cards-uploads/{user_id}/{today}/{unique_filename}"
    content_type, _ = mimetypes.guess_type(original_filename)
    if not content_type:
        content_type = 'application/octet-stream'
    with open(trimmed_path, "rb") as f:
        trimmed_bytes = f.read()
    res = supabase_client.storage.from_('cards-uploads').upload(
        storage_path.replace('cards-uploads/', ''),
        trimmed_bytes,
        {"content-type": content_type}
    )
    if hasattr(res, 'error') and res.error:
        raise Exception(f"Supabase Storage upload error: {res.error}")
    return storage_path

# Dependency to extract and verify JWT from Authorization header
async def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, os.getenv("SUPABASE_JWT_SECRET"), algorithms=[os.getenv("SUPABASE_JWT_ALGORITHM")], audience=os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated"))
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found in token")
        # Fetch the user's profile from the profiles table
        response = supabase_client.table("profiles").select("id, email, first_name, last_name, role").eq("id", user_id).maybe_single().execute()
        if not response or not response.data:
            raise HTTPException(status_code=404, detail="User profile not found")
        profile = response.data
        return profile
    except JWTError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

@app.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    event_id: str = Form(None),
    school_id: str = Form(...),
    user=Depends(get_current_user)
):
    print(f"📤 Received upload request for file: {file.filename}")
    print(f"📤 File content type: {file.content_type}")
    print(f"📤 File size: {file.size if hasattr(file, 'size') else 'unknown'}")
    print(f"📤 Event ID: {event_id}")
    user_id = user['id']
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    if not docai_client:
        print("❌ Document processing client not available")
        return JSONResponse(status_code=503, content={"error": "Document processing client not available."})
    try:
        # Check if the file is a PDF and reject it
        if file.content_type == "application/pdf" or file.filename.lower().endswith('.pdf'):
            print(f"⚠️ PDF detected in /upload endpoint. Rejecting and suggesting /bulk-upload.")
            return JSONResponse(status_code=400, content={"error": "PDFs must be uploaded via the /bulk-upload endpoint."})
        # 1. Save uploaded file to a temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1] or '.png') as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name
        print(f"📄 File saved temporarily to: {temp_path}")
        # 2. Trim the image
        trimmed_path = ensure_trimmed_image(temp_path)
        print(f"✂️ Trimmed image saved to: {trimmed_path}")
        # 3. Upload trimmed image to Supabase Storage
        storage_path = await upload_to_supabase_storage_from_path(trimmed_path, user_id, file.filename)
        print(f"✅ Uploaded trimmed image to Supabase Storage: {storage_path}")
        # 4. Delete temp files
        try:
            os.remove(temp_path)
            if trimmed_path != temp_path:
                os.remove(trimmed_path)
            print(f"🗑️ Temp files deleted.")
        except Exception as cleanup_e:
            print(f"⚠️ Error deleting temp files: {cleanup_e}")
        # 5. Insert a processing job
        from datetime import datetime
        import uuid
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        # Remove 'cards-uploads/' prefix for image_path
        image_path_for_db = storage_path.replace('cards-uploads/', '') if storage_path.startswith('cards-uploads/') else storage_path
        job_data = {
            "id": job_id,
            "user_id": user_id,
            "school_id": school_id,
            "file_url": storage_path,
            "image_path": image_path_for_db,
            "status": "queued",
            "result_json": None,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
            "event_id": event_id
        }
        supabase_client.table("processing_jobs").insert(job_data).execute()
        # 6. Continue pipeline using trimmed image path
        document_id = str(uuid.uuid4())
        print(f"🆔 Generated Document ID: {document_id}")
        insert_data = {
            "document_id": document_id,
            "fields": {},  # Will be filled after processing
            "image_path": storage_path,
            "event_id": event_id,
            "school_id": school_id
        }
        try:
            response = supabase_client.table("extracted_data").insert(insert_data).execute()
            print(f"✅ Saved initial data for {document_id}.")
            try:
                notification_data = {
                    "document_id": document_id,
                    "event_type": "initial_data_saved",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                supabase_client.table("upload_notifications").insert(notification_data).execute()
                print(f"✅ Notification sent for initial data saved: {document_id}")
            except Exception as notif_error:
                print(f"⚠️ Failed to send notification: {notif_error}")
        except Exception as db_error:
            print(f"⚠️ Database error: {db_error}")
        response_data = {
            "status": "success",
            "message": "File uploaded and trimmed successfully",
            "document_id": document_id,
            "storage_path": storage_path
        }
        return JSONResponse(status_code=200, content=response_data)
    except Exception as e:
        print(f"❌ Error uploading or processing file: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to upload or process file."})

@app.get("/cards", response_model=List[Dict[str, Any]])
async def get_cards(event_id: Union[str, None] = None):
    """
    Fetches card data from reviewed_data table.
    Optionally filters by event_id if provided.
    Filters out cards with deleted=true or review_status='archived'.
    """
    try:
        print(" Rcvd /cards request")
        if event_id:
            print(f" Filtering by event_id: {event_id}")
        # Query reviewed_data table with event_id filter if provided
        reviewed_query = supabase_client.table("reviewed_data").select("*")
        if event_id:
            reviewed_query = reviewed_query.eq("event_id", event_id)
        reviewed_response = reviewed_query.execute()
        reviewed_data = reviewed_response.data
        print(f" Found {len(reviewed_data)} reviewed records.")
        # Filter out deleted cards only (do not filter out archived)
        filtered_data = [card for card in reviewed_data if not card.get("deleted")]
        print(f" Returning {len(filtered_data)} non-deleted records.")
        return filtered_data
    except Exception as e:
        print(f"❌ Error in /cards endpoint: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/review/{document_id}")
async def review_document_manually(document_id: str, background_tasks: BackgroundTasks):
    # (Implementation remains the same - reads extracted_data which has changed slightly)
    if not supabase_client: return JSONResponse(status_code=503, content={"error": "Database client not available."})
    print(f"🔄 Manual review requested for {document_id}")
    try:
        response = supabase_client.table("extracted_data").select("fields, image_path").eq("document_id", document_id).maybe_single().execute()
        if not response.data: return JSONResponse(status_code=404, content={"error": "Document not found."})
        extracted_fields_dict = response.data.get("fields", {}) # This dict now uses docai confidence
        image_path = response.data.get("image_path")
        if not image_path or not os.path.exists(image_path): return JSONResponse(status_code=404, content={"error": "Image file not found."})
        if not extracted_fields_dict: return JSONResponse(status_code=400, content={"error": "No extracted data found."})
        # Pass the modified extracted_fields_dict to the background task
        background_tasks.add_task(run_gemini_review, document_id, extracted_fields_dict, image_path)
        print(f"✅ Scheduled manual review for {document_id}")
        return JSONResponse(content={"message": f"Review task scheduled for {document_id}."})
    except Exception as e: print(f"❌ Error triggering manual review: {e}"); traceback.print_exc(); return JSONResponse(status_code=500, content={"error": "Failed to trigger review."})

def get_trimmed_image_path(original_path: str) -> str:
    """
    Generates a path for the trimmed version of an image.
    
    Args:
        original_path: Path to the original image
        
    Returns:
        Path where the trimmed image should be stored
    """
    # Extract filename from original path and add '_trimmed' suffix
    filename = os.path.basename(original_path)
    name, ext = os.path.splitext(filename)
    trimmed_filename = f"{name}_trimmed{ext}"
    return os.path.join(TRIMMED_FOLDER, trimmed_filename)

def ensure_trimmed_image(original_image_path: str) -> str:
    """
    Processes the image using trim_card and overwrites the original image with the trimmed version.
    Returns the path to the processed image.
    """
    print(f"🔄 Processing image: {original_image_path}")
    try:
        # Process the image and get the path where it was saved
        trimmed_path = ensure_trimmed_image(original_image_path)
        
        # Verify the trimmed image exists
        if not os.path.exists(trimmed_path):
            print(f"⚠️ Trimmed image not found at: {trimmed_path}")
            return original_image_path
            
        print(f"✅ Image processed and saved at: {trimmed_path}")
        return trimmed_path
        
    except Exception as e:
        print(f"❌ Error processing image: {e}")
        # If processing fails, return the original image path
        return original_image_path

@app.get("/images/{document_id}")
async def get_image(document_id: str):
    """
    Serves the trimmed image file associated with a given document ID.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    print(f"🖼️ Image requested for document_id: {document_id}")
    try:
        # Query the database to find the image paths using the document_id
        response = supabase_client.table("extracted_data") \
                                  .select("image_path, trimmed_image_path") \
                                  .eq("document_id", document_id) \
                                  .maybe_single() \
                                  .execute()

        if response.data:
            # Try to use trimmed image first, fall back to original if not available
            image_path = response.data.get("trimmed_image_path") or response.data.get("image_path")
            print(f"  -> Found image path: {image_path}")

            if image_path and os.path.exists(image_path):
                # Use FileResponse to send the image file back with CORS headers
                headers = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                }
                return FileResponse(image_path, headers=headers)
            else:
                print(f"  -> File not found at path: {image_path}")
                return JSONResponse(status_code=404, content={"error": "Image file not found on server."})
        else:
            print(f"  -> No database record found for document_id: {document_id}")
            return JSONResponse(status_code=404, content={"error": "Image record not found."})

    except Exception as e:
        print(f"❌ Error retrieving image for {document_id}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve image."})
    
@app.post("/save-review/{document_id}")
async def save_manual_review(document_id: str, payload: Dict[str, Any] = Body(...)):
    """
    Updates a record in reviewed_data based on manual user edits.
    Only required fields determine if a card needs review.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    print(f"💾 Saving manual review for document_id: {document_id}")
    print(f"   Payload received: {payload}")
    
    updated_fields = payload.get("fields", {})
    frontend_status = payload.get("status")

    try:
        # 1. Fetch the current record from reviewed_data
        fetch_response = supabase_client.table("reviewed_data") \
                                        .select("fields, event_id, school_id") \
                                        .eq("document_id", document_id) \
                                        .maybe_single() \
                                        .execute()

        if not fetch_response.data:
            # If no reviewed data exists yet, get event_id and school_id from extracted_data
            extracted_response = supabase_client.table("extracted_data") \
                .select("event_id, school_id, fields") \
                .eq("document_id", document_id) \
                .maybe_single() \
                .execute()
            
            if not extracted_response.data:
                print(f"  -> Error: No existing data found for {document_id}")
                return JSONResponse(status_code=404, content={"error": "Record not found."})
                
            event_id = extracted_response.data.get("event_id")
            school_id = extracted_response.data.get("school_id")
            current_fields_data = extracted_response.data.get("fields", {})
        else:
            event_id = fetch_response.data.get("event_id")
            school_id = fetch_response.data.get("school_id")
            current_fields_data = fetch_response.data.get("fields", {})

        # Define required fields that determine review status
        REQUIRED_FIELDS = ["address", "cell", "city", "state", "zip_code", "name", "email"]

        # 2. Update fields based on user input
        for key, field_data in updated_fields.items():
            if key in current_fields_data:
                # Update value and metadata for the edited field
                current_fields_data[key].update({
                    **field_data,
                    "reviewed": True,  # Mark as reviewed since it's a manual edit
                    "requires_human_review": False,  # No longer needs review
                    "confidence": 1.0,  # High confidence for manual edits
                    "source": "human_review",
                    "review_notes": "Manually reviewed"
                })
            else:
                # If the field doesn't exist, add it with full metadata
                current_fields_data[key] = {
                    **field_data,
                    "reviewed": True,
                    "requires_human_review": False,
                    "confidence": 1.0,
                    "source": "human_review",
                    "review_notes": "Manually reviewed"
                }

        # 3. Check if any required fields still need review
        any_required_field_needs_review = False
        for field_name in REQUIRED_FIELDS:
            field_data = current_fields_data.get(field_name, {})
            if isinstance(field_data, dict):
                # A field needs review if it's marked as requiring review
                requires_review = field_data.get("requires_human_review", True)
                if requires_review:
                    print(f"Field {field_name} needs review")
                    any_required_field_needs_review = True
                    break

        # 4. Prepare data for update
        # Use the frontend status if provided, otherwise determine based on fields
        review_status = frontend_status if frontend_status else ("needs_human_review" if any_required_field_needs_review else "reviewed")
        
        update_payload = {
            "document_id": document_id,
            "fields": current_fields_data,
            "review_status": review_status,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "school_id": school_id
        }

        # 5. Update the record in Supabase
        update_response = supabase_client.table("reviewed_data") \
                                         .upsert(update_payload, on_conflict="document_id") \
                                         .execute()

        print(f"✅ Successfully saved manual review for {document_id}")
        return JSONResponse(status_code=200, content={
            "message": "Review saved successfully",
            "status": update_payload["review_status"],
            "any_field_needs_review": any_required_field_needs_review
        })

    except Exception as e:
        print(f"❌ Error saving manual review for {document_id}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to save review."})

@app.post("/archive-cards")
async def archive_cards(payload: ArchiveCardsPayload):
    """
    Archives one or more cards by setting their status to 'archived'.
    This unified endpoint handles both single and multiple card archival.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        update_payload = {
            "review_status": "archived",
            "reviewed_at": timestamp
        }

        # Update all cards in the list to archived status
        result = supabase_client.table('reviewed_data') \
            .update(update_payload) \
            .in_("document_id", payload.document_ids) \
            .execute()

        print(f"✅ Successfully archived {len(payload.document_ids)} cards")
        return JSONResponse(
            status_code=200,
            content={"message": f"Successfully archived {len(payload.document_ids)} cards"}
        )

    except Exception as e:
        print(f"❌ Error archiving cards: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/mark-exported")
async def mark_as_exported(payload: MarkExportedPayload):
    """
    Updates only the exported_at timestamp for a list of document IDs.
    Expects a JSON body like: {"document_ids": ["id1", "id2", ...]}
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    document_ids_to_update = payload.document_ids
    if not document_ids_to_update:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})

    print(f"📤 Recording export timestamp for {len(document_ids_to_update)} records...")

    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        update_payload = {
            "exported_at": timestamp  # Only update the exported_at timestamp
        }

        # Update rows where document_id is in the provided list
        update_response = supabase_client.table("reviewed_data") \
                                         .update(update_payload) \
                                         .in_("document_id", document_ids_to_update) \
                                         .execute()

        print(f"✅ Successfully recorded export timestamp for {len(document_ids_to_update)} records.")
        return JSONResponse(status_code=200, content={"message": f"{len(document_ids_to_update)} records export timestamp updated."})

    except Exception as e:
        print(f"❌ Error recording export timestamp: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to record export timestamp."})

@app.post("/delete-cards")
async def delete_cards(payload: DeleteCardsPayload):
    """
    Deletes multiple cards from both extracted_data and reviewed_data tables.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    document_ids = payload.document_ids
    if not document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})

    print(f"🗑️ Deleting {len(document_ids)} cards...")

    try:
        # Delete from reviewed_data
        reviewed_response = supabase_client.table("reviewed_data") \
                                         .delete() \
                                         .in_("document_id", document_ids) \
                                         .execute()

        # Delete from extracted_data
        extracted_response = supabase_client.table("extracted_data") \
                                          .delete() \
                                          .in_("document_id", document_ids) \
                                          .execute()

        print(f"✅ Successfully deleted {len(document_ids)} cards.")
        return JSONResponse(status_code=200, content={"message": f"{len(document_ids)} cards deleted successfully."})

    except Exception as e:
        print(f"❌ Error deleting cards: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to delete cards."})

@app.get("/health")
def health_check():
    # (Implementation remains the same)
    db_ok = False
    if supabase_client:
        try:
            # Check connection by trying a small query
            supabase_client.table('extracted_data').select('document_id', head=True).limit(1).execute()
            db_ok = True # If it didn't raise an exception, connection is likely ok
        except Exception as db_e:
            print(f"DB health check failed: {db_e}")
            db_ok = False
    return {"status": "ok", "database_connection": "ok" if db_ok else "error"}

@app.get("/test-connection")
async def test_connection():
    print("🔍 Test connection endpoint called")
    return {"status": "ok", "message": "Backend is reachable"}

@app.post("/auth/login")
async def login(credentials: dict):
    try:
        print("🔐 Login attempt for:", credentials.get("email"))
        response = supabase_auth.auth.sign_in_with_password({
            "email": credentials.get("email"),
            "password": credentials.get("password")
        })
        print("✅ Login successful")
        return response
    except Exception as e:
        print("❌ Login error:", str(e))
        raise HTTPException(status_code=401, detail=str(e))

# Add a new endpoint to check upload status
@app.get("/upload-status/{document_id}")
async def check_upload_status(document_id: str):
    """
    Check the status of an upload by document_id.
    Returns the latest notification for this document.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    
    try:
        # Query the notifications table for this document_id
        response = supabase_client.table("upload_notifications") \
            .select("*") \
            .eq("document_id", document_id) \
            .order("timestamp", desc=True) \
            .limit(1) \
            .execute()
        
        if response.data and len(response.data) > 0:
            return JSONResponse(content=response.data[0])
        else:
            return JSONResponse(content={"status": "not_found"})
    except Exception as e:
        print(f"❌ Error checking upload status: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to check upload status."})

@app.post("/events")
async def create_event(payload: EventCreatePayload):
    """
    Creates a new event with the given name, date, and school_id.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    try:
        # Insert the new event into the events table
        response = supabase_client.table("events").insert({
            "name": payload.name,
            "date": payload.date,
            "school_id": payload.school_id,
            "status": "active"  # Default status for new events
        }).execute()

        if not response.data:
            return JSONResponse(status_code=500, content={"error": "Failed to create event."})

        return JSONResponse(status_code=200, content=response.data[0])

    except Exception as e:
        print(f"❌ Error creating event: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to create event."})

@app.put("/events/{event_id}")
async def update_event(event_id: str, payload: EventUpdatePayload, user=Depends(get_current_user)):
    """
    Updates the name of an event. Only admins can update event names.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update event names.")
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        result = supabase_client.table("events").update({"name": payload.name}).eq("id", event_id).execute()
        if hasattr(result, 'error') and result.error:
            raise Exception(result.error)
        return {"success": True}
    except Exception as e:
        print(f"❌ Error updating event {event_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/archive-events")
async def archive_events(payload: ArchiveEventsPayload):
    """
    Archives one or more events by setting their status to 'archived'.
    This unified endpoint handles both single and multiple event archival.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        update_payload = {
            "status": "archived",
            "updated_at": timestamp
        }

        # Update all events in the list to archived status
        result = supabase_client.table('events') \
            .update(update_payload) \
            .in_("id", payload.event_ids) \
            .execute()

        print(f"✅ Successfully archived {len(payload.event_ids)} events")
        return JSONResponse(
            status_code=200,
            content={"message": f"Successfully archived {len(payload.event_ids)} events"}
        )

    except Exception as e:
        print(f"❌ Error archiving events: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.delete("/events/{event_id}")
async def delete_event(event_id: str, user=Depends(get_current_user)):
    """
    Deletes an event and all cards associated with it (from reviewed_data and extracted_data).
    Only admins can delete events.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete events.")
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        # Delete cards from reviewed_data
        supabase_client.table("reviewed_data").delete().eq("event_id", event_id).execute()
        # Delete cards from extracted_data
        supabase_client.table("extracted_data").delete().eq("event_id", event_id).execute()
        # Delete the event itself
        supabase_client.table("events").delete().eq("id", event_id).execute()
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content={"success": True})
    except Exception as e:
        print(f"❌ Error deleting event {event_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# Test endpoint to return current user info
@app.get("/me")
async def read_current_user(user=Depends(get_current_user)):
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found in token")
    # Query the profiles table for this user
    try:
        response = supabase_client.table("profiles").select("id, email, first_name, last_name, role").eq("id", user_id).maybe_single().execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="User profile not found")
        return {"profile": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user profile: {e}")

@app.get("/users")
async def list_users(user=Depends(get_current_user)):
    try:
        response = supabase_client.table("profiles").select("id, email, first_name, last_name, role").execute()
        return {"users": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching users: {e}")

@app.post("/invite-user")
async def invite_user(
    user=Depends(get_current_user),
    payload: dict = Body(...)
):
    # Only allow admins
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can invite users.")
    first_name = payload.get("first_name")
    last_name = payload.get("last_name")
    email = payload.get("email")
    role = payload.get("role", "user")
    school_id = payload.get("school_id")
    if not all([first_name, last_name, email, school_id]):
        raise HTTPException(status_code=400, detail="Missing required fields.")
    try:
        print(f"🔑 Attempting to invite user: {email}")
        print(f"📝 User metadata being sent:")
        print(f"  - first_name: {first_name}")
        print(f"  - last_name: {last_name}")
        print(f"  - role: {role}")
        print(f"  - school_id: {school_id}")
        
        # Invite user in Supabase Auth (sends invite email)
        result = supabase_auth.auth.admin.invite_user_by_email(
            email,
            {
                "user_metadata": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "school_id": school_id
                },
                "data": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "school_id": school_id
                },
                "redirectTo": "http://localhost:3000/accept-invite"
            }
        )
        print(f"✅ Successfully invited user: {email}")
        print(f"📝 Created user metadata:")
        print(f"  User metadata: {result.user.user_metadata}")
        print(f"  App metadata: {result.user.app_metadata}")
        return {"success": True, "user_id": result.user.id}
    except Exception as e:
        print(f"❌ Error inviting user: {str(e)}")
        print(f"❌ Error type: {type(e)}")
        print(f"❌ Error details: {e.__dict__ if hasattr(e, '__dict__') else 'No details available'}")
        raise HTTPException(status_code=500, detail=f"Error inviting user: {str(e)}")

@app.put("/users/{user_id}")
async def update_user(user_id: str, update: UserUpdateRequest):
    """
    Updates a user's first name, last name, and role in the profiles table.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        result = supabase_client.table("profiles").update({
            "first_name": update.first_name,
            "last_name": update.last_name,
            "role": update.role
        }).eq("id", user_id).execute()
        if hasattr(result, 'error') and result.error:
            raise Exception(result.error)
        return {"success": True}
    except Exception as e:
        print(f"❌ Error updating user {user_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    data = await request.json()
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": data["price_id"],
                "quantity": 1,
            }],
            mode="subscription",  # or "payment" for one-time
            success_url=data["success_url"],
            cancel_url=data["cancel_url"],
            customer_email=data.get("customer_email"),
        )
        return {"url": session.url}
    except Exception as e:
        return {"error": str(e)}

@app.get("/schools/{school_id}")
async def get_school(school_id: str, user=Depends(get_current_user)):
    """
    Fetches a school record by ID.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    try:
        # Fetch the school record
        response = supabase_client.table("schools") \
            .select("*") \
            .eq("id", school_id) \
            .maybe_single() \
            .execute()

        if not response.data:
            return JSONResponse(status_code=404, content={"error": "School not found."})

        return {"school": response.data}

    except Exception as e:
        print(f"❌ Error fetching school: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to fetch school."})

# Ensure modular routers are included after CORS setup
app.include_router(cards_router)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"🚀 Starting FastAPI server on {host}:{port}...")
    # Use reload=False for production typically, True for development
    uvicorn.run("main:app", host=host, port=port, reload=True)