"""
API routes for account linking functionality.
Handles admin approval/rejection of recruiter link requests.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.clients import get_supabase_client
from app.repositories.account_link_requests_repository import AccountLinkRequestsRepository
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/account-link-requests", tags=["Account Linking"])


# Request/Response Models
class ApproveRejectRequest(BaseModel):
    admin_notes: Optional[str] = None


class LinkRequestResponse(BaseModel):
    id: str
    requester_user_id: str
    target_school_id: str
    universal_event_id: str
    status: str
    created_at: str
    requester: Optional[dict] = None
    universal_event: Optional[dict] = None
    event_purchase: Optional[dict] = None


class PendingCountResponse(BaseModel):
    count: int


# Helper to verify user is admin of target school
def verify_admin_access(profile: dict, school_id: str):
    """Verify the current user is an admin of the specified school."""
    user_school_id = profile.get("school_id")
    user_roles = profile.get("role", [])

    if isinstance(user_roles, str):
        user_roles = [user_roles]

    if user_school_id != school_id:
        raise HTTPException(
            status_code=403,
            detail="You don't have access to this school's link requests"
        )

    if "admin" not in user_roles:
        raise HTTPException(
            status_code=403,
            detail="Only admins can manage link requests"
        )


@router.get("")
async def list_link_requests(
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    profile: dict = Depends(get_current_user)
):
    """
    List all link requests for the current user's school.
    Requires admin role.
    """
    school_id = profile.get("school_id")
    user_roles = profile.get("role", [])

    if isinstance(user_roles, str):
        user_roles = [user_roles]

    if "admin" not in user_roles:
        raise HTTPException(
            status_code=403,
            detail="Only admins can view link requests"
        )

    if not school_id:
        raise HTTPException(
            status_code=400,
            detail="User does not belong to a school"
        )

    repo = AccountLinkRequestsRepository()
    offset = (page - 1) * limit

    requests, total = repo.get_all_requests_for_school(
        school_id=school_id,
        status=status,
        limit=limit,
        offset=offset
    )

    pages = (total + limit - 1) // limit if total > 0 else 0

    return {
        "requests": requests,
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit
    }


@router.get("/pending/count")
async def get_pending_count(
    profile: dict = Depends(get_current_user)
):
    """
    Get count of pending link requests for the current user's school.
    Used for displaying badges/alerts.
    """
    school_id = profile.get("school_id")
    user_roles = profile.get("role", [])

    if isinstance(user_roles, str):
        user_roles = [user_roles]

    if "admin" not in user_roles:
        return {"count": 0}

    if not school_id:
        return {"count": 0}

    repo = AccountLinkRequestsRepository()
    count = repo.get_pending_count_for_school(school_id)

    return {"count": count}


@router.get("/{request_id}")
async def get_link_request(
    request_id: str,
    profile: dict = Depends(get_current_user)
):
    """
    Get details of a specific link request.
    """
    repo = AccountLinkRequestsRepository()
    request = repo.get_request_by_id(request_id)

    if not request:
        raise HTTPException(
            status_code=404,
            detail="Link request not found"
        )

    # Verify access
    verify_admin_access(profile, request.get("target_school_id"))

    return request


@router.post("/{request_id}/approve")
async def approve_link_request(
    request_id: str,
    body: Optional[ApproveRejectRequest] = None,
    profile: dict = Depends(get_current_user)
):
    """
    Approve a link request and merge the recruiter into the school.
    This will:
    1. Update the request status to 'approved'
    2. Update the recruiter's school_id to the target school
    3. Transfer ownership of their events to the target school
    4. Send confirmation email to the recruiter
    """
    repo = AccountLinkRequestsRepository()
    supabase = get_supabase_client()
    notification_service = NotificationService()

    # Get the request
    request = repo.get_request_by_id(request_id)
    if not request:
        raise HTTPException(
            status_code=404,
            detail="Link request not found"
        )

    # Verify access
    verify_admin_access(profile, request.get("target_school_id"))

    # Verify request is pending
    if request.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Request is already {request.get('status')}"
        )

    admin_notes = body.admin_notes if body else None
    admin_id = profile.get("id")

    # Approve the request
    repo.approve_request(
        request_id=request_id,
        reviewed_by=admin_id,
        admin_notes=admin_notes
    )

    # Get requester info
    requester = request.get("requester", {})
    requester_id = request.get("requester_user_id")
    target_school_id = request.get("target_school_id")

    # Get the requester's current (virtual) school_id to update their events
    requester_profile = (
        supabase.table("profiles")
        .select("school_id")
        .eq("id", requester_id)
        .single()
        .execute()
    )
    old_school_id = requester_profile.data.get("school_id") if requester_profile.data else None

    # Update recruiter's profile
    supabase.table("profiles").update({
        "school_id": target_school_id,
        "account_status": "linked",
        "parent_school_id": None  # Clear the pending link reference
    }).eq("id", requester_id).execute()

    # Transfer events from old school to target school
    if old_school_id and old_school_id != target_school_id:
        supabase.table("events").update({
            "school_id": target_school_id
        }).eq("school_id", old_school_id).execute()

        # Also transfer any reviewed_data (scanned cards)
        supabase.table("reviewed_data").update({
            "school_id": target_school_id
        }).eq("school_id", old_school_id).execute()

        # Delete the virtual school if it's empty
        supabase.table("schools").delete().eq("id", old_school_id).eq("is_virtual_school", True).execute()

    # Get school name and event info for email
    target_school = request.get("target_school", {})
    universal_event = request.get("universal_event", {})

    # Send approval email to recruiter
    recruiter_name = f"{requester.get('first_name', '')} {requester.get('last_name', '')}".strip()
    if not recruiter_name:
        recruiter_name = requester.get("email", "Recruiter")

    notification_service.send_link_approval_email(
        recruiter_email=requester.get("email", ""),
        recruiter_name=recruiter_name,
        school_name=target_school.get("name", "Your school"),
        event_name=universal_event.get("name", "your event")
    )

    return {
        "success": True,
        "message": "Link request approved successfully",
        "request_id": request_id
    }


@router.post("/{request_id}/reject")
async def reject_link_request(
    request_id: str,
    body: Optional[ApproveRejectRequest] = None,
    profile: dict = Depends(get_current_user)
):
    """
    Reject a link request.
    The recruiter will stay standalone and receive a notification email.
    """
    repo = AccountLinkRequestsRepository()
    notification_service = NotificationService()

    # Get the request
    request = repo.get_request_by_id(request_id)
    if not request:
        raise HTTPException(
            status_code=404,
            detail="Link request not found"
        )

    # Verify access
    verify_admin_access(profile, request.get("target_school_id"))

    # Verify request is pending
    if request.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Request is already {request.get('status')}"
        )

    admin_notes = body.admin_notes if body else None
    admin_id = profile.get("id")

    # Reject the request
    repo.reject_request(
        request_id=request_id,
        reviewed_by=admin_id,
        admin_notes=admin_notes
    )

    # Get requester and school info for email
    requester = request.get("requester", {})
    target_school = request.get("target_school", {})

    # Send rejection email to recruiter
    recruiter_name = f"{requester.get('first_name', '')} {requester.get('last_name', '')}".strip()
    if not recruiter_name:
        recruiter_name = requester.get("email", "Recruiter")

    notification_service.send_link_rejection_email(
        recruiter_email=requester.get("email", ""),
        recruiter_name=recruiter_name,
        school_name=target_school.get("name", "The school")
    )

    return {
        "success": True,
        "message": "Link request rejected",
        "request_id": request_id
    }
