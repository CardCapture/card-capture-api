# Card Capture API - Image Pipeline Architecture Summary

## Executive Overview

The card-capture-api is a FastAPI-based backend service for processing student inquiry cards and sign-up sheets using Google Cloud Document AI and Gemini. The system processes images through a **3-stage pipeline**: Extraction → Enhancement → Review, with modular enhancers handling field processing, validation, and enrichment.

---

## 1. Image Pipeline Architecture

### Pipeline Location
**File**: `/Users/kregboyd/Applications/card-capture-api/app/pipeline/`

### 1.1 Main Pipeline Flow

The CardProcessingPipeline class (pipeline.py) orchestrates the complete card processing workflow:

```
Input Image → Stage 1: Extraction → Stage 2: Enhancement → Stage 3: Review Prep → Output Fields
```

**File**: `/Users/kregboyd/Applications/card-capture-api/app/pipeline/pipeline.py` (455 lines)

#### Stage 1: Extraction (Lines 155-265)
- Runs Google Cloud Document AI (DocAI) on the image for OCR
- Extracts serial numbers from universal cards (if present)
- Checks if student already exists by serial number
- If exists: Skips Gemini (cost optimization)
- If new: Runs Gemini v2 for field enhancement
- Converts DocAI and Gemini results to FieldData objects
- Returns ProcessingResult with extracted fields and metadata

#### Stage 2: Enhancement (Lines 327-398)
- Applies 6 sequential field enhancers in order:
  1. CanonicalFieldMapperEnhancer - Maps legacy field names
  2. FieldSplitterEnhancer - Splits combined fields (city_state_zip)
  3. FieldRequirementsEnhancer - Applies school settings
  4. DataCleanerEnhancer - Formats phones, dates, emails
  5. AddressValidationEnhancer - Validates with Google Maps
  6. HighSchoolMatcherEnhancer - Matches high schools + CEEB codes

#### Stage 3: Review Preparation (Lines 400-454)
- Final field validation
- Determines review status based on required fields
- Filters out combined fields that shouldn't be saved
- Prepares for human review or auto-approval

### 1.2 Data Models

**File**: `/Users/kregboyd/Applications/card-capture-api/app/pipeline/models.py` (150 lines)

Key classes:
- **FieldData**: Single field with value, confidence, source, enabled/required flags, review status
- **PipelineContext**: Immutable context carrying school_id, majors list, field requirements
- **ProcessingResult**: Result from each stage with fields dict and metadata
- **ProcessingStage**: Enum (EXTRACTION, ENHANCEMENT, REVIEW)
- **EnhancerResult**: Tracks what changed per enhancer (fields_modified, fields_added, duration)

### 1.3 Enhancers Architecture

**Location**: `/Users/kregboyd/Applications/card-capture-api/app/pipeline/enhancers/`

#### Base Class
**File**: `/Users/kregboyd/Applications/card-capture-api/app/pipeline/enhancers/base.py`
- Abstract FieldEnhancer base class
- Handles execution timing, error handling, change tracking
- Provides helper methods (_create_field, _copy_field_metadata)

#### Enhancers

1. **CanonicalFieldMapperEnhancer** (canonical_field_mapper.py)
   - Maps 25+ legacy field names to canonical format
   - Splits combined name fields into first_name/last_name
   - Examples: "mobile" → "cell", "zip" → "zip_code"

2. **FieldSplitterEnhancer** (field_splitter.py)
   - Splits combined address fields: city_state_zip → city, state, zip_code
   - Handles full address parsing: "123 Main St, Austin TX 78701"
   - Splits academic scores into GPA, ACT, SAT fields
   - Uses smart state/zip detection

3. **FieldRequirementsEnhancer** (field_requirements.py)
   - Applies school settings (enabled/required flags)
   - Special handling for mapped_major
   - Flags fields for human review if required + missing

4. **DataCleanerEnhancer** (data_cleaner.py)
   - Normalizes phone numbers: XXX-XXX-XXXX
   - Standardizes dates: MM/DD/YYYY
   - Cleans email formatting
   - Title-cases names

5. **AddressValidationEnhancer** (address_validator.py)
   - Validates addresses with Google Maps Geocoding API
   - Corrects city/state/zip mismatches
   - Adds suggestions for ambiguous addresses

6. **HighSchoolMatcherEnhancer** (high_school_matcher.py)
   - Matches school names to database
   - Adds CEEB codes for colleges
   - Uses fuzzy matching for common abbreviations

---

## 2. Inquiry Cards vs Sign-Up Sheets Processing

### 2.1 Inquiry Cards (Single Card)

**Processing Flow**:
1. Image uploaded via upload endpoint
2. Worker picks up processing job
3. Runs full pipeline (DocAI → Gemini → Enhancers)
4. Creates single reviewed_data record
5. Record marked for human review or auto-approved

**Upload Type**: "inquiry_card"
**Fields**: Standard (first_name, last_name, email, phone, high_school, major, etc.)

**File**: `/Users/kregboyd/Applications/card-capture-api/app/services/uploads_service.py`

### 2.2 Sign-Up Sheets (Multiple Records)

**Processing Flow**:
1. Sheet image uploaded via upload endpoint
2. Gemini extracts table as JSON array
3. **Creates multiple reviewed_data records** (one per row)
4. Each record linked to same event and upload_type

**Upload Type**: "signup_sheet"
**Key Difference**: Produces many records from single image

**File**: `/Users/kregboyd/Applications/card-capture-api/app/services/signup_service.py` (423 lines)

### 2.3 Major Mapping for Both Types

**Sign-Up Sheet Prompt**:
- Extracts major field as handwritten on sheet
- Creates separate mapped_major field
- Uses intelligent matching: "Comp Sci" → "Computer Science | BS"
- Defaults to "Undecided" if no match found

**Lines 47-150**: Build_signup_sheet_prompt function
- Includes major list context
- Explains pipe character handling
- Shows example mappings

**Key Safeguard** (Lines 305-314):
```python
# Backend safeguard: Ensure mapped_major is set if valid_majors exist
if valid_majors and len(valid_majors) > 0:
    for record in records:
        if 'mapped_major' not in record or not record.get('mapped_major', '').strip():
            record['mapped_major'] = "Undecided"
```

### 2.4 Reviewed Data Structure

Both types create records with this structure:
```python
{
  "document_id": str,
  "fields": {
    "first_name": {"value": "...", "source": "gemini", "confidence": 0.9, ...},
    "mapped_major": {"value": "Business Admin | BSBA", "source": "gemini_signup_mapped", ...}
  },
  "upload_type": "inquiry_card" | "signup_sheet",
  "review_status": "needs_review" | "reviewed",
  "school_id": str,
  "user_id": str,
  "event_id": str
}
```

---

## 3. Mapped Major Implementation and Usage

### 3.1 What is Mapped Major?

**Purpose**: AI-generated mapping of student's written major to school's official major list

**Problem Solved**:
- Students write "psych" or "Psychology" on cards
- Schools maintain official major list: "Psychology | BS"
- Need standardized major for CRM export

### 3.2 Implementation Details

#### Gemini Prompt Configuration

**File**: `/Users/kregboyd/Applications/card-capture-api/app/core/gemini_prompt.py` (Lines 78-80)

Instructions:
1. Preserve original `major` field exactly as written on card
2. Create separate `mapped_major` field with best match
3. Pipe character (|) is part of major name, NOT a delimiter
4. If no match, leave blank (system defaults to "Undecided")
5. If original major empty, default `mapped_major` to "Undecided"

**Critical Note** (From latest fix commit 276241a):
```
The pipe character (|) in major names is part of the major name format 
(e.g., "Business Administration | BSBA") - do NOT split on it or 
treat it as a delimiter. Use intelligent matching (e.g., "Business" → 
"Business Administration | BSBA", "Psych" → "Psychology | BS").
```

#### Gemini Service Processing

**File**: `/Users/kregboyd/Applications/card-capture-api/app/services/gemini_service.py` (Lines 17-250+)

Key logic:
1. Backend safeguard: If mapped_major missing, set to "Undecided" (Lines 304-313)
2. Smart validation: Check if major matches mapped major AND differs from original (Lines 315-330)
3. Unmappable major handling: If blank + valid_majors exist, set to "Undecided" (Lines 331-338)

#### Sign-Up Sheet Handling

**File**: `/Users/kregboyd/Applications/card-capture-api/app/services/signup_service.py` (Lines 304-363)

Special treatment for mapped_major in reviewed_data:
```python
if field_name == "mapped_major":
    fields[field_name] = {
        "value": str(value).strip(),
        "source": "gemini_signup_mapped",
        "confidence": 0.9,
        "requires_human_review": False,  # AI-mapped doesn't need review
        "review_notes": "Automatically mapped to school's major list",
        "reviewed": True,  # AI mapping is considered reviewed
        "original_value": record.get('major', ''),
        "edit_made": True,
        "edit_type": "mapped_value"
    }
```

### 3.3 Settings Service Integration

**File**: `/Users/kregboyd/Applications/card-capture-api/app/services/settings_service.py` (Lines 91-104)

Smart review logic for mapped_major:
- If has value: No review needed (successfully mapped)
- If empty AND required: Flagged for review
- If empty AND optional: No review needed

### 3.4 Mississippi College Case Study

**Git Commit**: `e6600f7` - "added major_mapping to sign up sheets"
**Date**: Oct 18, 2025 12:47:39

**What was fixed** (Commit 276241a):
- Clarified pipe character handling in major names
- Added intelligent matching examples
- Ensured system doesn't split "Business Administration | BSBA" on the pipe

**MC's Major List**: ~60 majors with pipe format (e.g., "Marketing | BSBA")

**Test Setup**:
- School ID: `72892a66-df27-4731-9770-d19000244830`
- Event ID: `506fbd1c-56ca-4f24-b514-6a9c2f269927`
- Test sheet: `/Users/kregboyd/Applications/card-capture-api/MC/sign-up-sheet.jpg`

**Expected Mappings**:
- "marketing" → "Marketing | BSBA"
- "psych" → "Psychology | BS"
- "entrepreneur" → "Entrepreneurship | BSBA"
- "Business" → "Business Administration | BSBA"
- "Nursing" → "Pre-Nursing: Traditional | BS"
- "Sports Management" → "Sports Management | BS"

---

## 4. Local Pipeline Setup and Execution

### 4.1 Environment Configuration

**File**: `/Users/kregboyd/Applications/card-capture-api/.env` (copy from .env.example)

Required variables:
```
SUPABASE_URL=<production_url>
SUPABASE_SERVICE_ROLE_KEY=<service_key>
GOOGLE_PROJECT_ID=gen-lang-client-0493571343
DOCAI_PROCESSOR_ID=<processor_id>
GEMINI_API_KEY=<api_key>
GOOGLE_MAPS_API_KEY=<maps_api_key>
GOOGLE_APPLICATION_CREDENTIALS=service_account.json
```

**File**: `/Users/kregboyd/Applications/card-capture-api/app/config.py` (Lines 1-100+)

Configuration loads:
- Google Cloud: Project ID, DocAI processor, location
- Supabase: URL, keys, JWT settings
- Pipeline: Feature flags for V2/V3 rollout
- CORS: Allowed origins for local dev (localhost:8080-8087, localhost:3000)

### 4.2 Local Development Setup

**File**: `/Users/kregboyd/Applications/card-capture-api/README.md`

Setup steps:
```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure .env
cp .env.example .env
# Edit .env with your credentials

# 4. Run development server
uvicorn app.main:app --reload

# 5. Run worker (separate terminal)
uvicorn app.worker.worker_v3:app --host 0.0.0.0 --port 8001
```

### 4.3 Database Setup for Local Dev

**File**: `/Users/kregboyd/Applications/card-capture-api/DB_SETUP_README.md` (80 lines)

Local database connection helper:
```bash
# Connect to staging or production database
cd /Users/kregboyd/Applications/card-capture-api
./db-connect.sh

# Or use helper functions
source db-helpers.sh
list-tables staging
describe-table cards staging
count-rows profiles staging
```

### 4.4 Processing Workers

**V3 Worker** (NEW - Production):
**File**: `/Users/kregboyd/Applications/card-capture-api/app/worker/worker_v3.py`
- Uses new 3-stage pipeline
- Race condition fixes (atomic job claiming)
- Duplicate detection
- Endpoints: GET /, GET /health, GET /ready
- Main endpoint: Polls processing_jobs, claims, processes, updates status

**Unified Worker** (Router):
**File**: `/Users/kregboyd/Applications/card-capture-api/app/worker/worker_unified.py`
- Routes between V2 and V3 based on feature flags
- Uses should_use_pipeline_v3() from config.py

**Feature Flags** (config.py Lines 82-99):
```python
PIPELINE_VERSION = "v3"  # Default version
PIPELINE_V3_ROLLOUT_PERCENTAGE = 0-100  # Percentage rollout
PIPELINE_V3_ENABLED_SCHOOLS = ""  # Comma-separated school IDs
```

Priority: School-specific > Global > Percentage > Default

### 4.5 Local Testing Scripts

**Sign-Up Sheet Testing**:
**File**: `/Users/kregboyd/Applications/card-capture-api/test_signup_sheet_local.py`

**Inquiry Card Testing**:
Various test files in root:
- test_local_pipeline_v3_with_db.py
- test_universal_card.py
- test_local_worker.py

### 4.6 Image Processing Pipeline

**File**: `/Users/kregboyd/Applications/card-capture-api/app/utils/image_processing_v2.py` (272 lines)

Processing steps:
1. **HEIC Conversion**: Convert HEIC/HEIF to JPEG
2. **EXIF Orientation**: Apply correct rotation
3. **PhotoRoom Background Removal** (optional)
4. **Card Boundary Detection** (fallback)
5. **Image Optimization**: Resize + compress

Functions:
- convert_heic_to_jpeg()
- process_uploaded_image()
- validate_image_format()
- optimize_image_for_storage()
- ensure_trimmed_image_v2()

---

## 5. Mississippi College (MC) Configuration

### 5.1 School Settings

**School ID**: `72892a66-df27-4731-9770-d19000244830`

Stored in `schools` table:
- `majors`: Array of ~60 majors with pipe format
- `card_fields`: Field configuration
- `docai_processor_id`: Custom processor (if different from default)

### 5.2 Event Configuration

**Primary Test Event**: `506fbd1c-56ca-4f24-b514-6a9c2f269927`

### 5.3 Tenant-Specific Settings

Schools can customize:
1. **Card Fields**: Which fields enabled/required
2. **Major List**: School's official majors list
3. **DocAI Processor**: School-specific processor (for different card layouts)
4. **Field Requirements**: Validation rules per field

### 5.4 Recent MC-Related Changes

**Commit 276241a** (Oct 18, 13:13):
- Bug fix for mapped_majors for MC
- Updated Gemini prompt to clarify pipe character handling
- Added detailed major matching instructions

**Commit e6600f7** (Oct 18, 12:47):
- Added major_mapping to sign-up sheets
- Implemented intelligent major matching
- Created TEST_SIGNUP_SHEET_README.md with MC setup

**Test Data**:
- `/Users/kregboyd/Applications/card-capture-api/MC/sign-up-sheet.jpg`: Sample MC sign-up sheet

---

## 6. File Organization Summary

```
app/
├── api/routes/              # API endpoints
│   ├── uploads.py          # Upload handling
│   ├── cards.py            # Card endpoints
│   └── ...
├── controllers/            # Request handlers
│   ├── uploads_controller.py
│   └── ...
├── services/               # Business logic
│   ├── uploads_service.py       # Inquiry card processing
│   ├── signup_service.py        # Sign-up sheet processing
│   ├── gemini_service.py        # Gemini API integration
│   ├── docai_service.py         # Document AI integration
│   ├── settings_service.py      # School settings/field requirements
│   └── ...
├── repositories/           # Database access
│   ├── uploads_repository.py
│   ├── cards_repository.py
│   └── ...
├── pipeline/               # NEW: V3 processing pipeline
│   ├── pipeline.py         # Main pipeline orchestrator
│   ├── models.py           # Data structures
│   ├── enhancers/
│   │   ├── base.py        # Base enhancer class
│   │   ├── canonical_field_mapper.py
│   │   ├── field_splitter.py
│   │   ├── field_requirements.py
│   │   ├── data_cleaner.py
│   │   ├── address_validator.py
│   │   └── high_school_matcher.py
│   └── tests/
│       ├── test_pipeline.py
│       └── test_enhancers.py
├── worker/                 # Background task processing
│   ├── worker_v3.py        # New pipeline worker
│   ├── worker_unified.py   # Router between v2/v3
│   └── ...
├── utils/                  # Utilities
│   ├── image_processing_v2.py    # Image handling
│   ├── field_utils.py            # Field operations
│   ├── retry_utils.py            # Retry logic
│   └── ...
├── core/                   # Core components
│   ├── clients.py         # Supabase, Google clients
│   ├── gemini_prompt.py   # Gemini prompt template
│   └── ...
└── config.py              # Configuration
```

---

## 7. Processing Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    UPLOAD ENDPOINT                              │
│  POST /api/uploads (inquiry card or sign-up sheet)              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ├─→ Save to Supabase Storage
                       ├─→ Create processing_job record
                       └─→ Return to client
                       
┌──────────────────────────────────────────────────────────────────┐
│                    WORKER POLLING                                │
│  Queries processing_jobs table for "queued" status              │
└──────────────────────┬───────────────────────────────────────────┘
                       │
        ┌──────────────┴─────────────┐
        │                            │
        ▼                            ▼
  INQUIRY CARD              SIGN-UP SHEET
        │                            │
        └─→ Download image           └─→ Download image
        │                            │
        └─→ Run full pipeline:       └─→ Extract table with Gemini:
            │                            │
            ├─ Stage 1: Extraction      ├─ Extract rows as JSON array
            │   ├─ DocAI OCR            ├─ Parse field names
            │   ├─ Check serial         ├─ Handle major mapping
            │   └─ Gemini enhancement   └─ Create records for each row
            │                            
            ├─ Stage 2: Enhancement    For each row:
            │   ├─ Field mapping          │
            │   ├─ Field splitting        ├─ Create reviewed_data record
            │   ├─ Address validation     ├─ Set upload_type="signup_sheet"
            │   └─ School matching        ├─ Set mapped_major + original major
            │                             └─ Link to event
            └─ Stage 3: Review           
                ├─ Final validation
                └─ Determine review status
                       │
                       └─→ Create single reviewed_data record
                           Set upload_type="inquiry_card"

┌─────────────────────────────────────────────────────────────────┐
│              SAVE RESULTS TO reviewed_data TABLE                │
│  document_id | fields | review_status | upload_type | event_id  │
└─────────────────────────────────────────────────────────────────┘
                       │
                       └─→ Update processing_job: status="completed"
                           Return to client UI
```

---

## 8. Key Configuration Files and Line Numbers

| File | Purpose | Key Lines |
|------|---------|-----------|
| pipeline.py | Main orchestrator | 30-126 |
| models.py | Data structures | 10-150 |
| base.py | Enhancer framework | 11-145 |
| canonical_field_mapper.py | Legacy field mapping | 41-160 |
| field_splitter.py | Address/field splitting | 27-150+ |
| field_requirements.py | School settings | 8-150+ |
| data_cleaner.py | Format normalization | - |
| address_validator.py | Address validation | - |
| high_school_matcher.py | School + CEEB matching | - |
| signup_service.py | Sign-up sheet processing | 47-423 |
| gemini_service.py | Gemini integration | 17-250+ |
| docai_service.py | DocAI/OCR | 55-250+ |
| settings_service.py | Field requirements | 8-150+ |
| gemini_prompt.py | Prompt template | Lines 1-134 |
| worker_v3.py | Processing worker | 100+ |
| config.py | Configuration | 77-120 |
| image_processing_v2.py | Image handling | 67-159 |

---

## 9. Quick Start: Running Pipeline Locally

```bash
# 1. Setup environment
cd /Users/kregboyd/Applications/card-capture-api
cp .env.example .env
# Edit .env with credentials

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run API server (Terminal 1)
uvicorn app.main:app --reload --port 8000

# 4. Run worker (Terminal 2)
uvicorn app.worker.worker_v3:app --host 0.0.0.0 --port 8001

# 5. Test sign-up sheet processing (Terminal 3)
python3 test_signup_sheet_local.py

# 6. Check results
# - Navigate to UI at localhost:3000
# - Go to events page
# - Look for upload_type="signup_sheet" records
# - Verify mapped_major field
```

---

## 10. Critical Notes for Developers

### mapped_major Processing
- **ALWAYS preserve original `major` field** - never null it out
- **Pipe character (|) is NOT a delimiter** - "Business | BSBA" is one major
- **Default to "Undecided"** if no match found
- **Intelligent matching**: "Comp Sci" → "Computer Science | BS"
- **Backend safeguard**: System ensures mapped_major is set even if Gemini misses it

### Pipeline Execution
- Enhancers run in strict order (mapper → splitter → requirements → cleaner → validator → school matcher)
- Each enhancer is isolated and has error handling
- If enhancer fails, pipeline continues with next one (fail-safe)
- All field changes are tracked for logging

### Sign-Up Sheets
- Creates **multiple records** (one per row) from single image
- Each record has upload_type="signup_sheet"
- mapped_major marked as reviewed (AI-mapped is trusted)
- Handwritten text marked for human review

### Mississippi College Specifics
- School ID: `72892a66-df27-4731-9770-d19000244830`
- ~60 majors with "| Degree" format
- Recent fix: Clarified pipe character handling in Gemini prompt
- Test sheet available in `/Users/kregboyd/Applications/card-capture-api/MC/sign-up-sheet.jpg`

