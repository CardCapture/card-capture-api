from typing import Dict, Any, Optional
import uuid
from fastapi import HTTPException
import os
import resend

from app.core.clients import get_supabase_client
from app.repositories.students_repository import (
    get_student_by_email,
    upsert_student,
    create_token_for_student,
    get_student_by_token,
)
from app.repositories.reviewed_data_repository import upsert_reviewed_data
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


async def register_student(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a student, generate a fresh QR token, email it, and return QR."""
    log_debug("Register student called", payload, service="students")
    email = (payload.get("email") or "").strip()
    existing = get_student_by_email(email) if email else None

    # If existing, preserve its id on upsert
    student_in = {**(existing or {}), **payload}
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
    """Resolve token and upsert a reviewed_data row for the event with student fields."""
    # Basic guardrails to prevent massive data URIs or junk from being sent to PostgREST
    token = (token or "").strip()
    if not token or len(token) > 128 or token.startswith("data:") or "base64," in token:
        raise HTTPException(status_code=400, detail="Invalid token format")
    s = get_student_by_token(token)
    if not s:
        raise HTTPException(status_code=400, detail="Invalid token")

    fields = _student_to_reviewed_fields(s)
    if rating is not None:
        fields["rating"] = _field(str(rating), source="rep")
    if notes:
        fields["notes"] = _field(notes, source="rep")

    # Use a deterministic UUID so rescans of the same student/event upsert the same row
    deterministic_name = f"cardcapture/student/{s['id']}/event/{event_id}"
    document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, deterministic_name))
    data = {
        "document_id": document_id,
        "fields": fields,
        "school_id": school_id,
        "user_id": user_id,
        "event_id": event_id,
        "review_status": "reviewed",
        "upload_type": "student_qr",
    }

    upsert_reviewed_data(get_supabase_client(), data)
    return {"success": True, "document_id": document_id, "student_id": s["id"]}


def _field(value: Any, source: str = "student_self") -> Dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "confidence": 0.99 if source == "student_self" else 1.0,
        "enabled": True,
        "required": False,
        "reviewed": True,
    }


def _student_to_reviewed_fields(s: Dict[str, Any]) -> Dict[str, Any]:
    def f(v):
        return _field(v) if v not in (None, "") else None

    mapping = {
        "first_name": f(s.get("first_name")),
        "last_name": f(s.get("last_name")),
        "email": f(s.get("email")),
        "cell": f(s.get("mobile")),
        "date_of_birth": f(s.get("dob")),
        "address": f(s.get("address1")),
        "address_2": f(s.get("address2")),
        "city": f(s.get("city")),
        "state": f(s.get("state")),
        "zip_code": f(s.get("zip")),
        "current_school": f(s.get("high_school")),
        "grade": f(s.get("grade_level")),
        "grad_year": f(s.get("grad_year")),
        "gpa": f(s.get("gpa")),
        "gpa_scale": f(s.get("gpa_scale")),
        "sat_score": f(s.get("sat_score")),
        "act_score": f(s.get("act_score")),
        "academic_interests": f(
            ", ".join(s.get("academic_interests") or s.get("intended_majors") or [])
        ),
        "start_college_term": f(
            f"{s.get('start_term', '')} {s.get('start_year', '')}".strip()
        ),
    }

    return {k: v for k, v in mapping.items() if v is not None}


