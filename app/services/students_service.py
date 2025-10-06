from typing import Dict, Any, Optional
import uuid
from fastapi import HTTPException
import os
import resend
from datetime import datetime, timezone

from app.core.clients import get_supabase_client
from app.repositories.students_repository import (
    get_student_by_email,
    upsert_student,
    create_token_for_student,
    get_student_by_token,
)
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.repositories.interactions_repository import (
    create_student_school_interaction,
    check_existing_interaction,
    update_student_school_interaction,
)
from app.utils.qr_utils import qr_png_data_uri
from app.utils.retry_utils import log_debug


FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def _notify_student_email(email: Optional[str], qr_data_uri: str, token: str, is_lookup: bool) -> None:
    """Send the student an email with their QR code using Resend if configured."""
    if not email:
        return
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        # Email service not configured; skip silently for MVP
        log_debug("RESEND_API_KEY not set; skipping email", service="students")
        return

    resend.api_key = api_key
    manage_url = f"{FRONTEND_URL}/student-manage?token={token}"
    subject = "Your CardCapture QR code" if is_lookup else "Welcome to CardCapture – your QR code"
    html = f"""
    <h2>{subject}</h2>
    <p>Show this code at any college booth using CardCapture to share your info.</p>
    <p><img alt=\"QR\" src=\"{qr_data_uri}\" style=\"width:220px;height:220px\" /></p>
    <p><a href=\"{manage_url}\">Manage or update your information</a></p>
    """
    params: resend.Emails.SendParams = {
        "from": "CardCapture <no-reply@cardcapture.io>",
        "to": [email],
        "subject": subject,
        "html": html,
    }
    try:
        resend.Emails.send(params)
    except Exception as e:  # Do not fail registration if email provider rejects the key
        log_debug(f"Resend email send failed (non-fatal): {str(e)}", service="students")


def _parse_date_of_birth(raw: Any) -> Optional[str]:
    """Normalize incoming DOB values to YYYY-MM-DD when possible."""
    if not raw:
        return None
    s = str(raw).strip()
    # Already ISO-like
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    # MM/DD/YYYY
    if '/' in s:
        parts = s.split('/')
        if len(parts) == 3 and all(parts):
            mm, dd, yyyy = parts
            try:
                mm_i = int(mm)
                dd_i = int(dd)
                yyyy_i = int(yyyy)
                return f"{yyyy_i:04d}-{mm_i:02d}-{dd_i:02d}"
            except Exception:
                return None
    # MMDDYYYY (8 digits)
    if s.isdigit() and len(s) == 8:
        try:
            mm_i = int(s[0:2])
            dd_i = int(s[2:4])
            yyyy_i = int(s[4:8])
            return f"{yyyy_i:04d}-{mm_i:02d}-{dd_i:02d}"
        except Exception:
            return None
    return None


def _normalize_student_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Map legacy FE keys to canonical columns and drop unknowns.

    Unknown keys are placed into `extras` JSONB so no data is lost.
    """
    mapping = {
        "mobile": "cell",
        "address1": "address",
        "address2": "address_2",
        "zip": "zip_code",
        "dob": "date_of_birth",
        "start_term": "entry_term",
        "start_year": "entry_year",
        "sms_opt_in": "permission_to_text",
    }

    normalized: Dict[str, Any] = {}
    extras: Dict[str, Any] = {}

    # Allowed canonical keys in students table
    allowed = {
        "id",
        # identity
        "first_name",
        "last_name",
        "preferred_first_name",
        # contact/consent
        "email",
        "cell",
        "email_opt_in",
        "permission_to_text",
        # address
        "address",
        "address_2",
        "city",
        "state",
        "zip_code",
        # demographic
        "date_of_birth",
        "high_school",
        "grade_level",
        "grad_year",
        # academics
        "gpa",
        "gpa_scale",
        "sat_score",
        "act_score",
        # enrollment
        "student_type",
        "entry_term",
        "entry_year",
        # interests
        "major",
        "academic_interests",
        "intended_majors",
        # misc
        "extras",
        "created_at",
        "updated_at",
    }

    for key, value in (payload or {}).items():
        target = mapping.get(key, key)
        if target == "date_of_birth":
            parsed = _parse_date_of_birth(value)
            value = parsed if parsed else value
        if target in allowed:
            normalized[target] = value
        else:
            # Keep unknowns in extras to avoid hard failures (e.g., academic_interests_text)
            extras[target] = value

    # If academic_interests_text present and academic_interests missing, carry it over as a single string entry
    if "academic_interests" not in normalized and "academic_interests_text" in extras:
        ait = str(extras.get("academic_interests_text") or "").strip()
        if ait:
            normalized["academic_interests"] = [ait]

    # Merge any provided extras
    existing_extras = normalized.get("extras") or {}
    if isinstance(existing_extras, dict):
        normalized["extras"] = {**existing_extras, **extras}
    else:
        normalized["extras"] = extras

    return normalized


async def register_student(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a student, generate a fresh QR token, email it, and return QR."""
    log_debug("Register student called", payload, service="students")
    email = (payload.get("email") or "").strip()
    existing = get_student_by_email(email) if email else None

    # If existing, preserve its id on upsert; map incoming keys to canonical columns
    normalized_payload = _normalize_student_payload(payload)
    student_in = {**(existing or {}), **normalized_payload}
    student = upsert_student(student_in)

    token = create_token_for_student(student["id"])
    qr_data_uri = qr_png_data_uri(token)

    _notify_student_email(student.get("email"), qr_data_uri, token, is_lookup=False)

    return {"student_id": student["id"], "token": token, "qrDataUri": qr_data_uri}


async def lookup_student(email: str) -> Dict[str, Any]:
    """Re-issue a student QR via email if the student exists."""
    s = get_student_by_email(email)
    if not s:
        return {"sent": False}
    token = create_token_for_student(s["id"])
    qr_data_uri = qr_png_data_uri(token)
    _notify_student_email(email, qr_data_uri, token, is_lookup=True)
    return {"sent": True}


async def scan_student(
    token: str,
    event_id: str,
    school_id: str,
    user_id: Optional[str],
    rating: Optional[int],
    notes: Optional[str],
) -> Dict[str, Any]:
    """Resolve token and create a student_school_interaction for the event (V2)."""
    # Basic guardrails to prevent massive data URIs or junk from being sent to PostgREST
    token = (token or "").strip()
    if not token or len(token) > 128 or token.startswith("data:") or "base64," in token:
        raise HTTPException(status_code=400, detail="Invalid token format")
    s = get_student_by_token(token)
    if not s:
        raise HTTPException(status_code=400, detail="Invalid token")

    # Convert student columns to V2 field structure
    fields = _student_to_reviewed_fields(s)

    # Check if this student has already been scanned for this event
    existing = check_existing_interaction(s['id'], school_id, event_id)

    # Create or update student_school_interaction (V2)
    interaction_data = {
        "student_id": s['id'],
        "school_id": school_id,
        "event_id": event_id,
        "fields": fields,
        "source_method": "qr_code",
        "review_status": "reviewed",  # QR codes are auto-approved (student entered data)
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Add optional fields only if provided
    if user_id:
        interaction_data["user_id"] = user_id
    if rating is not None:
        interaction_data["rating"] = rating
    if notes:
        interaction_data["notes"] = notes

    if existing:
        # Update existing interaction
        interaction = update_student_school_interaction(existing["id"], interaction_data)
        log_debug(f"Updated existing QR scan interaction: {existing['id']}", service="students")
    else:
        # Create new interaction
        interaction_data["created_at"] = datetime.now(timezone.utc).isoformat()
        interaction = create_student_school_interaction(interaction_data)
        log_debug(f"Created new QR scan interaction: {interaction['id']}", service="students")
    return {
        "success": True,
        "interaction_id": interaction["id"],
        "student_id": s["id"]
    }


def _field(value: Any, source: str = "student_self") -> Dict[str, Any]:
    """Create a V2 field structure for student_school_interactions."""
    return {
        "value": value,
        "confidence": 1.0,  # Student entered data = high confidence
        "source": source,
        "enabled": True,     # Will be set by school-specific settings
        "required": False,   # Will be set by school-specific settings
        "requires_review": False,  # QR codes don't need review (student entered data)
        "original_value": value,
    }


def _student_to_reviewed_fields(s: Dict[str, Any]) -> Dict[str, Any]:
    """Convert student table columns to V2 interaction field structure.

    This creates the JSONB fields structure for student_school_interactions,
    converting from structured columns to the school's working copy format.
    """
    def f(v):
        return _field(v) if v not in (None, "") else None

    # Handle special cases
    # 1. Academic interests - join array into comma-separated string
    academic_list = s.get("academic_interests") or s.get("intended_majors")
    if isinstance(academic_list, list):
        academic_joined = ", ".join([
            str(x)
            for x in academic_list
            if str(x).strip() != ""
        ])
    else:
        academic_joined = str(academic_list) if academic_list not in (None, "") else None

    # 2. Permission to text - convert boolean to text
    permission_text = None
    if s.get("permission_to_text") is True:
        permission_text = "Yes"
    elif s.get("permission_to_text") is False:
        permission_text = "No"

    # 3. Date of birth - convert to string if date object
    dob = s.get("date_of_birth")
    if dob and not isinstance(dob, str):
        dob = str(dob)

    # 4. High school validation - look up CEEB code if high school exists
    high_school_name = s.get("high_school")
    student_state = s.get("state")
    ceeb_code = None
    high_school_validation_status = "not_verified"

    if high_school_name and high_school_name.strip():
        try:
            # Try to find exact match in high schools directory
            sb = get_supabase_client()

            # If we have a state, prioritize schools in that state
            if student_state:
                hs_result = sb.table("high_schools_directory").select("ceeb_code, name, city, state").ilike("name", high_school_name).eq("state", student_state).limit(1).execute()

                if not hs_result.data or len(hs_result.data) == 0:
                    # Fall back to any state if no match in student's state
                    hs_result = sb.table("high_schools_directory").select("ceeb_code, name, city, state").ilike("name", high_school_name).limit(1).execute()
            else:
                # No state info, just search by name
                hs_result = sb.table("high_schools_directory").select("ceeb_code, name, city, state").ilike("name", high_school_name).limit(1).execute()

            if hs_result.data and len(hs_result.data) > 0:
                school_match = hs_result.data[0]
                # Check if it's an exact match (case insensitive)
                if school_match["name"].lower() == high_school_name.lower():
                    ceeb_code = school_match.get("ceeb_code")
                    high_school_validation_status = "verified"
                    log_debug(f"High school verified: {high_school_name} ({school_match['state']}) -> CEEB: {ceeb_code}", service="students")
        except Exception as e:
            log_debug(f"Error looking up high school: {e}", service="students")

    # Map all student columns to V2 field structure
    mapping = {
        "first_name": f(s.get("first_name")),
        "last_name": f(s.get("last_name")),
        "preferred_first_name": f(s.get("preferred_first_name")),
        "email": f(s.get("email")),
        "cell": f(s.get("cell")),
        "permission_to_text": f(permission_text),
        "date_of_birth": f(dob),
        "address": f(s.get("address")),
        "address_2": f(s.get("address_2")),
        "city": f(s.get("city")),
        "state": f(s.get("state")),
        "zip_code": f(s.get("zip_code")),
        "high_school": f(high_school_name),
        "high_school_validation": f(high_school_validation_status),  # Add validation status
        "ceeb_code": f(ceeb_code) if ceeb_code else None,  # Add CEEB code if found
        "grade_level": f(s.get("grade_level")),
        "grad_year": f(s.get("grad_year")),
        "gpa": f(s.get("gpa")),
        "gpa_scale": f(s.get("gpa_scale")),
        "sat_score": f(s.get("sat_score")),
        "act_score": f(s.get("act_score")),
        "academic_interests": f(academic_joined),
        "entry_term": f(s.get("entry_term")),
        "entry_year": f(s.get("entry_year")),
        "student_type": f(s.get("student_type")),
        "major": f(s.get("major")),
    }

    return {k: v for k, v in mapping.items() if v is not None}


