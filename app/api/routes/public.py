"""
Public API routes for recruiter self-service signup.
No authentication required.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any

from app.models.recruiter_signup import (
    RecruiterSignupRequest,
    RecruiterSignupResponse,
    SchoolListResponse,
    UniversalEventSearchResponse
)
from app.services.recruiter_signup_service import (
    RecruiterSignupService,
    get_public_schools,
    search_universal_events
)


router = APIRouter(prefix="/public", tags=["Public"])


@router.get("/schools", response_model=SchoolListResponse)
async def list_schools(
    q: Optional[str] = Query(None, min_length=1, description="Search query"),
    limit: int = Query(100, ge=1, le=500, description="Max results")
) -> Dict[str, Any]:
    """
    Get list of schools for recruiter signup dropdown.

    This is a public endpoint - no authentication required.
    Virtual schools (auto-created for standalone recruiters) are excluded.
    """
    try:
        result = await get_public_schools(query=q, limit=limit)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch schools: {str(e)}"
        )


@router.get("/universal-events/search", response_model=UniversalEventSearchResponse)
async def search_events(
    q: Optional[str] = Query(None, description="Text search (name, location, city)"),
    state: Optional[str] = Query(None, description="Filter by state (e.g., TX)"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    city: Optional[str] = Query(None, description="Filter by city"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Results per page")
) -> Dict[str, Any]:
    """
    Search universal events catalog.

    This is a public endpoint - no authentication required.
    Returns paginated results with event details.
    """
    try:
        result = await search_universal_events(
            query=q,
            state=state,
            date_from=date_from,
            date_to=date_to,
            city=city,
            page=page,
            limit=limit
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search events: {str(e)}"
        )


@router.get("/universal-events/{event_id}")
async def get_event(event_id: str) -> Dict[str, Any]:
    """
    Get a single universal event by ID.

    This is a public endpoint - no authentication required.
    """
    from app.repositories.universal_events_repository import UniversalEventsRepository

    try:
        repo = UniversalEventsRepository()
        event = repo.get_event_by_id(event_id)

        if not event:
            raise HTTPException(
                status_code=404,
                detail="Event not found"
            )

        return {"event": event}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get event: {str(e)}"
        )


@router.post("/recruiter-signup", response_model=RecruiterSignupResponse)
async def recruiter_signup(request: RecruiterSignupRequest) -> RecruiterSignupResponse:
    """
    Register as a new recruiter and purchase event access.

    This is a public endpoint - no authentication required.

    Flow:
    1. Create user account
    2. Handle school selection (existing or new)
    3. Create Stripe checkout session ($25)
    4. Return checkout URL for payment

    After successful payment, the webhook will:
    - Mark purchase as completed
    - Create the event for the user
    - Send welcome email
    - If linked to existing school, create link request for admin approval
    """
    try:
        service = RecruiterSignupService()
        result = await service.signup_recruiter(request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Signup failed: {str(e)}"
        )


@router.get("/verify-payment/{session_id}")
async def verify_payment(session_id: str) -> Dict[str, Any]:
    """
    Verify Stripe payment status and get the created event ID.

    This is called by the success page after Stripe redirects back.
    If webhook hasn't fired yet but Stripe confirms payment, processes inline.

    Returns:
    - status: 'completed', 'pending', or 'failed'
    - event_id: The created event ID (if completed)
    - message: Human-readable status message
    """
    import os
    import stripe
    from datetime import datetime, timezone
    from app.repositories.event_purchases_repository import EventPurchasesRepository
    from app.repositories.universal_events_repository import UniversalEventsRepository
    from app.core.clients import get_supabase_client

    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret_key:
        raise HTTPException(status_code=500, detail="Payment processing not configured")

    stripe.api_key = stripe_secret_key

    try:
        purchases_repo = EventPurchasesRepository()

        # Check our database first
        purchase = purchases_repo.get_purchase_by_session_id(session_id)

        if not purchase:
            raise HTTPException(status_code=404, detail="Purchase not found")

        # If already completed, return immediately
        if purchase.get("status") == "completed":
            return {
                "status": "completed",
                "event_id": purchase.get("event_id"),
                "message": "Payment successful! Redirecting to your event..."
            }

        if purchase.get("status") == "failed":
            return {
                "status": "failed",
                "event_id": None,
                "message": "Payment failed. Please try again."
            }

        # Still pending - check Stripe directly
        try:
            stripe_session = stripe.checkout.Session.retrieve(session_id)
        except stripe.error.InvalidRequestError:
            raise HTTPException(status_code=404, detail="Invalid session")

        # If Stripe says not paid yet, return pending
        if stripe_session.payment_status != 'paid':
            return {
                "status": "pending",
                "event_id": None,
                "message": "Payment is still processing..."
            }

        # Stripe says paid but webhook hasn't processed yet - do it now!
        # This is the fallback path when webhooks are slow or don't fire

        metadata = stripe_session.metadata or {}
        user_id = metadata.get("user_id")
        universal_event_id = metadata.get("universal_event_id")
        school_id = metadata.get("school_id")

        if not all([user_id, universal_event_id, school_id]):
            return {
                "status": "pending",
                "event_id": None,
                "message": "Processing your payment..."
            }

        # Get universal event details
        events_repo = UniversalEventsRepository()
        universal_event = events_repo.get_event_by_id(universal_event_id)

        if not universal_event:
            return {
                "status": "pending",
                "event_id": None,
                "message": "Processing your payment..."
            }

        # Create the event
        supabase = get_supabase_client()
        timestamp = datetime.now(timezone.utc).isoformat()

        event_data = {
            "name": universal_event.get("name"),
            "date": universal_event.get("event_date"),
            "school_id": school_id,
            "status": "active",
            "universal_event_id": universal_event_id,
            "event_purchase_id": purchase.get("id"),
            "created_at": timestamp,
            "updated_at": timestamp
        }

        event_response = supabase.table("events").insert(event_data).execute()

        if not event_response.data:
            return {
                "status": "pending",
                "event_id": None,
                "message": "Processing your payment..."
            }

        created_event = event_response.data[0]
        event_id = created_event.get("id")

        # Update purchase record
        update_data = {
            "status": "completed",
            "completed_at": timestamp,
            "event_id": event_id
        }
        if stripe_session.payment_intent:
            update_data["stripe_payment_intent_id"] = stripe_session.payment_intent

        supabase.table("event_purchases").update(update_data).eq("id", purchase.get("id")).execute()

        return {
            "status": "completed",
            "event_id": event_id,
            "message": "Payment successful! Redirecting to your event..."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify payment: {str(e)}"
        )
