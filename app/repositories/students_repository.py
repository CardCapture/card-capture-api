from typing import Optional, Dict, Any
import secrets

from app.core.clients import get_supabase_client


def get_student_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Fetch a student by email. Prefer exact match; avoid maybe_single to prevent 406."""
    sb = get_supabase_client()
    response = (
        sb.table("students").select("*").eq("email", email).limit(1).execute()
    )
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def upsert_student(student_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert a student record and return the resulting row.

    Some client versions don't support chaining select() on upsert; rely on
    execute() and then fetch by id or email if data is empty.
    """
    sb = get_supabase_client()
    response = sb.table("students").upsert(student_payload).execute()
    rows = getattr(response, "data", None) or []

    if rows:
        return rows[0]

    # Fallback: try to fetch by id, else by email
    student_id = student_payload.get("id")
    if student_id:
        res = sb.table("students").select("*").eq("id", student_id).limit(1).execute()
        data = getattr(res, "data", None) or []
        if data:
            return data[0]

    email = student_payload.get("email")
    if email:
        res = sb.table("students").select("*").eq("email", email).limit(1).execute()
        data = getattr(res, "data", None) or []
        if data:
            return data[0]

    return student_payload


def create_token_for_student(student_id: str) -> str:
    """Create a new opaque token for the student and persist to student_identifiers."""
    token = secrets.token_urlsafe(16)
    sb = get_supabase_client()
    sb.table("student_identifiers").insert(
        {"token": token, "student_id": student_id, "active": True}
    ).execute()
    return token


def get_student_by_token(token: str) -> Optional[Dict[str, Any]]:
    """Resolve a token to a student row."""
    sb = get_supabase_client()
    response = (
        sb.table("student_identifiers")
        .select("student_id, students(*)")
        .eq("token", token)
        .eq("active", True)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    if not rows:
        return None
    # Supabase join returned nested student under key "students"
    student = rows[0].get("students") or {}
    # Ensure id present
    student["id"] = rows[0]["student_id"]
    return student


