"""
Authorization helpers for multi-tenant isolation.

These helpers verify that the authenticated user has permission to access
or modify resources. They should be called at the route level BEFORE
any business logic is executed.

SuperAdmin Note: Users with school_id=NULL are SuperAdmins and can access
all resources across all schools.
"""

from typing import List, Optional
from fastapi import HTTPException, status
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug


def is_superadmin(user: dict) -> bool:
    """
    Check if user is a SuperAdmin (school_id is NULL).

    SuperAdmins can access all resources across all schools.

    Args:
        user: The authenticated user profile (from get_current_user)

    Returns:
        True if user is a SuperAdmin, False otherwise
    """
    return user.get("school_id") is None


async def verify_event_belongs_to_user_school(
    event_id: str,
    user: dict,
    raise_on_failure: bool = True
) -> bool:
    """
    Verify that an event belongs to the user's school.

    Args:
        event_id: The event ID to check
        user: The authenticated user profile (from get_current_user)
        raise_on_failure: If True, raises HTTPException on failure

    Returns:
        True if user has access, False otherwise

    Raises:
        HTTPException 404: Event not found
        HTTPException 403: Event belongs to different school
    """
    # SuperAdmin can access any event
    if is_superadmin(user):
        log_debug(f"SuperAdmin accessing event {event_id}", service="auth")
        return True

    user_school_id = user.get("school_id")
    if not user_school_id:
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no school association"
            )
        return False

    supabase = get_supabase_client()
    event = supabase.table("events").select("school_id").eq("id", event_id).maybe_single().execute()

    if not event.data:
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found"
            )
        return False

    event_school_id = event.data.get("school_id")

    if str(event_school_id) != str(user_school_id):
        log_debug(
            f"Access denied: User school {user_school_id} != Event school {event_school_id}",
            service="auth"
        )
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Event belongs to different school"
            )
        return False

    return True


async def verify_document_belongs_to_user_school(
    document_id: str,
    user: dict,
    raise_on_failure: bool = True
) -> bool:
    """
    Verify that a document (card) belongs to the user's school.

    Checks both reviewed_data (V1) and student_school_interactions (V2) tables.

    Args:
        document_id: The document_id to check
        user: The authenticated user profile
        raise_on_failure: If True, raises HTTPException on failure

    Returns:
        True if user has access, False otherwise

    Raises:
        HTTPException 404: Document not found
        HTTPException 403: Document belongs to different school
    """
    # SuperAdmin can access any document
    if is_superadmin(user):
        log_debug(f"SuperAdmin accessing document {document_id}", service="auth")
        return True

    user_school_id = user.get("school_id")
    if not user_school_id:
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no school association"
            )
        return False

    supabase = get_supabase_client()

    # Try V1 table first (reviewed_data)
    doc = supabase.table("reviewed_data").select("school_id").eq("document_id", document_id).maybe_single().execute()

    if not doc.data:
        # Try V2 table (student_school_interactions)
        doc = supabase.table("student_school_interactions").select("school_id").eq("id", document_id).maybe_single().execute()

    if not doc.data:
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        return False

    doc_school_id = doc.data.get("school_id")

    if str(doc_school_id) != str(user_school_id):
        log_debug(
            f"Access denied: User school {user_school_id} != Document school {doc_school_id}",
            service="auth"
        )
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Document belongs to different school"
            )
        return False

    return True


async def verify_documents_belong_to_user_school(
    document_ids: List[str],
    user: dict,
    raise_on_failure: bool = True
) -> bool:
    """
    Verify that ALL documents belong to the user's school.

    Used for bulk operations (archive, delete, move, export).

    Args:
        document_ids: List of document IDs to check
        user: The authenticated user profile
        raise_on_failure: If True, raises HTTPException on failure

    Returns:
        True if user has access to ALL documents, False otherwise

    Raises:
        HTTPException 404: One or more documents not found
        HTTPException 403: One or more documents belong to different school
    """
    # SuperAdmin can access any documents
    if is_superadmin(user):
        log_debug(f"SuperAdmin accessing {len(document_ids)} documents", service="auth")
        return True

    user_school_id = user.get("school_id")
    if not user_school_id:
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no school association"
            )
        return False

    if not document_ids:
        return True  # No documents to check

    supabase = get_supabase_client()

    # Check V1 table (reviewed_data)
    v1_docs = supabase.table("reviewed_data")\
        .select("document_id, school_id")\
        .in_("document_id", document_ids)\
        .execute()

    # Check V2 table (student_school_interactions)
    v2_docs = supabase.table("student_school_interactions")\
        .select("id, school_id")\
        .in_("id", document_ids)\
        .execute()

    # Combine results
    found_docs = {}
    for doc in (v1_docs.data or []):
        found_docs[doc["document_id"]] = doc["school_id"]
    for doc in (v2_docs.data or []):
        found_docs[doc["id"]] = doc["school_id"]

    # Verify all documents found and belong to user's school
    for doc_id in document_ids:
        if doc_id not in found_docs:
            log_debug(f"Document {doc_id} not found", service="auth")
            if raise_on_failure:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document not found: {doc_id}"
                )
            return False

        doc_school_id = found_docs[doc_id]
        if str(doc_school_id) != str(user_school_id):
            log_debug(
                f"Access denied: Document {doc_id} belongs to school {doc_school_id}",
                service="auth"
            )
            if raise_on_failure:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: One or more documents belong to different school"
                )
            return False

    return True


async def verify_school_access(
    school_id: str,
    user: dict,
    raise_on_failure: bool = True
) -> bool:
    """
    Verify that user has access to the specified school.

    Used when school_id is provided in request body/params.

    Args:
        school_id: The school ID to verify access to
        user: The authenticated user profile
        raise_on_failure: If True, raises HTTPException on failure

    Returns:
        True if user has access, False otherwise

    Raises:
        HTTPException 403: User does not have access to the school
    """
    # SuperAdmin can access any school
    if is_superadmin(user):
        log_debug(f"SuperAdmin accessing school {school_id}", service="auth")
        return True

    user_school_id = user.get("school_id")

    if str(school_id) != str(user_school_id):
        log_debug(
            f"Access denied: User school {user_school_id} != Requested school {school_id}",
            service="auth"
        )
        if raise_on_failure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Cannot access resources from different school"
            )
        return False

    return True


def get_user_school_id_or_fail(user: dict) -> Optional[str]:
    """
    Get the user's school_id, allowing None for SuperAdmins.

    This function is used when you need to extract the school_id from
    the user profile, with proper handling for SuperAdmin users.

    Args:
        user: The authenticated user profile

    Returns:
        school_id string, or None for SuperAdmins

    Raises:
        HTTPException 403 if user has no school and is not SuperAdmin
    """
    school_id = user.get("school_id")

    # SuperAdmins have NULL school_id - this is valid
    if school_id is None:
        # SuperAdmin users legitimately have no school_id
        log_debug(f"SuperAdmin user {user.get('id')} (no school_id)", service="auth")
        return None

    return str(school_id)
