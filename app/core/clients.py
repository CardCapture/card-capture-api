import os
from dotenv import load_dotenv
from supabase import create_client
from google.cloud import documentai_v1 as documentai
import googlemaps

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Lazy initialization of Supabase clients
supabase_client = None
supabase_auth = None

def get_supabase_client():
    global supabase_client
    if supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("Missing required Supabase environment variables")
        try:
            supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            raise RuntimeError(f"Failed to create Supabase client: {e}")
    return supabase_client

def get_supabase_auth():
    global supabase_auth
    if supabase_auth is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("Missing required Supabase environment variables")
        try:
            supabase_auth = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            raise RuntimeError(f"Failed to create Supabase auth client: {e}")
    return supabase_auth

# For backwards compatibility, create clients on first access
def __getattr__(name):
    if name == 'supabase_client':
        return get_supabase_client()
    elif name == 'supabase_auth':
        return get_supabase_auth()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

# Document AI
try:
    docai_client = documentai.DocumentProcessorServiceClient()
    project_id = os.getenv("GOOGLE_PROJECT_ID")
    location = os.getenv("DOCAI_LOCATION")
    processor_id = os.getenv("DOCAI_PROCESSOR_ID")
    docai_name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
except Exception:
    docai_client = None
    docai_name = None

# Google Maps
try:
    gmaps_client = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))
except Exception:
    gmaps_client = None

mime_type = "image/png"

# Gemini (new google-genai SDK)
_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client 