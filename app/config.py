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
MIME_TYPE = "image/png"

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# File Storage Configuration
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "uploads/images"))
TRIMMED_FOLDER = os.environ.get("TRIMMED_FOLDER", os.path.join(os.path.dirname(__file__), "uploads/trimmed"))

# Ensure folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRIMMED_FOLDER, exist_ok=True)

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
    'http://localhost:5173',
    'http://127.0.0.1:5173'
]

GEMINI_MODEL = " gemini-1.5-pro-latest"

# Export for compatibility
PROJECT_ID = GOOGLE_PROJECT_ID