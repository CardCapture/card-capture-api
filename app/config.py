# app/config.py
import os
from dotenv import load_dotenv

# Load environment variables
if os.path.exists(".env"):
    load_dotenv(dotenv_path=".env")
else:
    print("ℹ️ Info: .env file not found. Relying on system environment variables.")

# Google Cloud Configuration
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "878585200500")
DOCAI_LOCATION = os.getenv("DOCAI_LOCATION", "us")
DOCAI_PROCESSOR_ID = os.getenv("DOCAI_PROCESSOR_ID", "894b9758c2215ed6")
GOOGLE_OCR_PROCESSOR = os.getenv("GOOGLE_OCR_PROCESSOR")  # Enterprise OCR for rotation correction
MIME_TYPE = "image/png"

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_JWT_ALGORITHM = os.getenv("SUPABASE_JWT_ALGORITHM", "HS256")
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# File Storage Configuration
# Use /tmp for Cloud Run compatibility (writable file system)
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/tmp/uploads/images")
TRIMMED_FOLDER = os.environ.get("TRIMMED_FOLDER", "/tmp/uploads/trimmed")

# Ensure folders exist (with error handling for Cloud Run)
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(TRIMMED_FOLDER, exist_ok=True)
except OSError as e:
    print(f"Warning: Could not create upload folders: {e}. Using /tmp as fallback.")
    UPLOAD_FOLDER = "/tmp"
    TRIMMED_FOLDER = "/tmp"

# CORS Configuration
ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084",
    "http://localhost:8085",
    "http://localhost:8086",
    "http://localhost:8087",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
    "http://127.0.0.1:8082",
    "http://127.0.0.1:8083",
    "http://127.0.0.1:8084",
    "http://127.0.0.1:8085",
    "http://127.0.0.1:8086",
    "http://127.0.0.1:8087",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://cardcapture.io",
    "https://gen-lang-client-0493571343.web.app",
    "https://gen-lang-client-0493571343.firebaseapp.com",
    "https://staging.cardcapture.io",
    "https://gen-lang-client-0493571343-staging.web.app"
]

GEMINI_MODEL = " gemini-1.5-pro-latest"

# Frontend URL for invitation links
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Pipeline Configuration - Feature Flags for V3 Rollout
PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "v3")  # Default to new pipeline
PIPELINE_V3_ROLLOUT_PERCENTAGE = int(os.getenv("PIPELINE_V3_ROLLOUT_PERCENTAGE", "0"))  # 0-100
PIPELINE_V3_ENABLED_SCHOOLS = os.getenv("PIPELINE_V3_ENABLED_SCHOOLS", "").split(",") if os.getenv("PIPELINE_V3_ENABLED_SCHOOLS") else []

def should_use_pipeline_v3(school_id: str = None, user_id: str = None) -> bool:
    """
    Determine whether to use pipeline v3 based on feature flags.
    
    Priority order:
    1. If school is explicitly enabled for v3 -> use v3
    2. If PIPELINE_VERSION is set to v3 -> use v3
    3. If rollout percentage covers this request -> use v3
    4. Otherwise -> use v2
    
    Args:
        school_id: School ID for school-specific rollout
        user_id: User ID for percentage-based rollout
        
    Returns:
        True if should use pipeline v3, False for v2
    """
    
    # Check if school is explicitly enabled
    if school_id and school_id in PIPELINE_V3_ENABLED_SCHOOLS:
        return True
    
    # Check if globally set to v3
    if PIPELINE_VERSION == "v3":
        return True
        
    # Check percentage rollout (use school_id or user_id for consistent hash)
    if PIPELINE_V3_ROLLOUT_PERCENTAGE > 0:
        hash_input = school_id or user_id or "default"
        hash_value = hash(hash_input) % 100
        if hash_value < PIPELINE_V3_ROLLOUT_PERCENTAGE:
            return True
    
    return False

def get_pipeline_config() -> dict:
    """Get current pipeline configuration for monitoring/debugging"""
    return {
        "default_version": PIPELINE_VERSION,
        "v3_rollout_percentage": PIPELINE_V3_ROLLOUT_PERCENTAGE,
        "v3_enabled_schools": PIPELINE_V3_ENABLED_SCHOOLS,
        "v3_enabled_school_count": len([s for s in PIPELINE_V3_ENABLED_SCHOOLS if s.strip()])
    }

# Export for compatibility
PROJECT_ID = GOOGLE_PROJECT_ID