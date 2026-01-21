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
from app.models.universal_event_submission import (
    UniversalEventSubmissionRequest,
    UniversalEventSubmissionResponse
)
from app.services.recruiter_signup_service import (
    RecruiterSignupService,
    get_public_schools,
    search_universal_events
)


router = APIRouter(prefix="/public", tags=["Public"])


async def _send_post_purchase_emails(
    supabase,
    user_id: str,
    events: list,
    total_amount: int,
    checkout_session_id: str,
    purchase_date: str
):
    """
    Send post-purchase emails:
    1. Receipt email to all users
    2. Invite admins email to users who created a new school
    """
    from app.services.notification_service import NotificationService

    try:
        # Get user profile
        profile_response = (
            supabase.table("profiles")
            .select("id, email, first_name, last_name, account_status, school_id")
            .eq("id", user_id)
            .single()
            .execute()
        )

        profile = profile_response.data
        if not profile:
            print(f"[post_purchase_emails] Profile not found for user {user_id}")
            return

        recipient_email = profile.get("email")
        recipient_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
        if not recipient_name:
            recipient_name = recipient_email

        account_status = profile.get("account_status")
        school_id = profile.get("school_id")

        notification_service = NotificationService()

        # 1. Send receipt email to everyone
        receipt_result = notification_service.send_purchase_receipt_email(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            events=events,
            total_amount=total_amount,
            checkout_session_id=checkout_session_id,
            purchase_date=purchase_date
        )
        print(f"[post_purchase_emails] Receipt email result: {receipt_result}")

        # 2. Send invite admins email only if user created a new school (not standalone)
        if account_status != "standalone" and school_id:
            # Get school name
            school_response = (
                supabase.table("schools")
                .select("name")
                .eq("id", school_id)
                .single()
                .execute()
            )
            school_name = school_response.data.get("name", "Your School") if school_response.data else "Your School"

            invite_result = notification_service.send_invite_admins_email(
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                school_name=school_name
            )
            print(f"[post_purchase_emails] Invite admins email result: {invite_result}")

    except Exception as e:
        # Don't fail the payment verification if emails fail
        print(f"[post_purchase_emails] Error sending emails: {str(e)}")


async def _handle_account_linking_inline(
    supabase,
    user_id: str,
    purchased_events: list,
    first_purchase_id: str
):
    """
    Check if user wants to link to an existing school and create link request if so.
    Sends notification emails to school admins with all purchased events.
    This is the same logic as in webhooks.py but called inline from verify-payment.
    """
    from app.repositories.account_link_requests_repository import AccountLinkRequestsRepository
    from app.services.notification_service import NotificationService

    try:
        # Get user profile to check for parent_school_id
        profile_response = (
            supabase.table("profiles")
            .select("id, email, first_name, last_name, parent_school_id, account_status")
            .eq("id", user_id)
            .single()
            .execute()
        )

        profile = profile_response.data
        if not profile:
            print(f"[account_linking] Profile not found for user {user_id}")
            return

        parent_school_id = profile.get("parent_school_id")
        account_status = profile.get("account_status")

        # Only create link request if user selected an existing school
        if not parent_school_id or account_status != "standalone":
            print(f"[account_linking] User {user_id} does not need account linking (parent_school_id={parent_school_id}, status={account_status})")
            return

        print(f"[account_linking] Creating account link request for user {user_id} to school {parent_school_id}")

        # Get target school details
        school_response = (
            supabase.table("schools")
            .select("id, name")
            .eq("id", parent_school_id)
            .single()
            .execute()
        )

        school = school_response.data
        if not school:
            print(f"[account_linking] Target school {parent_school_id} not found")
            return

        # Create account link request
        link_repo = AccountLinkRequestsRepository()

        # Check if request already exists
        if link_repo.has_pending_request(user_id, parent_school_id):
            print(f"[account_linking] Link request already exists for user {user_id} to school {parent_school_id}")
            return

        # Use first event for the link request record (the email will show all events)
        first_event = purchased_events[0] if purchased_events else {}
        link_request = link_repo.create_request(
            requester_user_id=user_id,
            target_school_id=parent_school_id,
            universal_event_id=first_event.get("id"),
            event_purchase_id=first_purchase_id
        )

        print(f"[account_linking] Created link request {link_request.get('id')}")

        # Send notification emails to school admins
        notification_service = NotificationService()
        recruiter_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
        if not recruiter_name:
            recruiter_name = profile.get("email", "Unknown")

        # Calculate total amount ($17 per event)
        total_amount = len(purchased_events) * 1700

        email_result = notification_service.send_link_request_to_admins(
            school_id=parent_school_id,
            school_name=school.get("name", "Unknown School"),
            recruiter_name=recruiter_name,
            recruiter_email=profile.get("email", ""),
            events=purchased_events,
            total_amount=total_amount,
            request_id=link_request.get("id")
        )

        print(f"[account_linking] Admin notification result: {email_result}")

    except Exception as e:
        # Don't fail the payment if linking fails - just log it
        print(f"[account_linking] Error handling account linking: {str(e)}")


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


@router.post("/universal-events", response_model=UniversalEventSubmissionResponse)
async def submit_universal_event(request: UniversalEventSubmissionRequest) -> Dict[str, Any]:
    """
    Submit a new universal event.

    This is a public endpoint - no authentication required.
    Events are created immediately with 'active' status.
    Sends confirmation email to the organizer.
    """
    from app.repositories.universal_events_repository import UniversalEventsRepository
    from app.services.notification_service import NotificationService

    try:
        repo = UniversalEventsRepository()

        # Prepare event data
        event_data = {
            "name": request.name,
            "event_date": request.event_date.isoformat(),
            "contact_name": request.contact_name,
            "contact_email": request.contact_email,
            "contact_phone": request.contact_phone,
            "start_time": request.start_time.isoformat() if request.start_time else None,
            "end_time": request.end_time.isoformat() if request.end_time else None,
            "location": request.location,
            "address": request.address,
            "city": request.city,
            "state": request.state or "TX",
            "zip": request.zip,
            "description": request.description,
            "needs_inquiry_cards": request.needs_inquiry_cards or False,
            "expected_students": request.expected_students,
            "status": "active"
        }

        # Create event
        created_event = repo.create_event(event_data)

        # Send confirmation email
        notification_service = NotificationService()
        notification_service.send_event_submission_confirmation(
            recipient_email=request.contact_email,
            recipient_name=request.contact_name,
            event_name=request.name,
            event_date=request.event_date.isoformat(),
            event_id=created_event.get("id")
        )

        return {
            "success": True,
            "event_id": created_event.get("id"),
            "message": "Event submitted successfully! A confirmation email has been sent."
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit event: {str(e)}"
        )


@router.post("/recruiter-signup", response_model=RecruiterSignupResponse)
async def recruiter_signup(request: RecruiterSignupRequest) -> RecruiterSignupResponse:
    """
    Register as a new recruiter and purchase event access.

    This is a public endpoint - no authentication required.

    Flow:
    1. Create user account
    2. Handle school selection (existing or new)
    3. Create Stripe checkout session ($17)
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
    Verify Stripe payment status and get the created event IDs.

    This is called by the success page after Stripe redirects back.
    If webhook hasn't fired yet but Stripe confirms payment, processes inline.

    Returns:
    - status: 'completed', 'pending', or 'failed'
    - event_ids: List of created event IDs (if completed)
    - event_id: First created event ID for backward compatibility
    - message: Human-readable status message
    """
    import os
    import json
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
        events_repo = UniversalEventsRepository()
        supabase = get_supabase_client()

        # Get all purchases for this session
        purchases = purchases_repo.get_purchases_by_session_id(session_id)

        if not purchases:
            raise HTTPException(status_code=404, detail="Purchase not found")

        # Check if all are already completed
        all_completed = all(p.get("status") == "completed" for p in purchases)
        any_failed = any(p.get("status") == "failed" for p in purchases)

        if all_completed:
            event_ids = [p.get("event_id") for p in purchases if p.get("event_id")]
            return {
                "status": "completed",
                "event_ids": event_ids,
                "event_id": event_ids[0] if event_ids else None,
                "message": "Payment successful! Redirecting to your events..."
            }

        if any_failed:
            return {
                "status": "failed",
                "event_ids": [],
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
                "event_ids": [],
                "event_id": None,
                "message": "Payment is still processing..."
            }

        # Stripe says paid but webhook hasn't processed yet - do it now!
        # This is the fallback path when webhooks are slow or don't fire

        metadata = stripe_session.metadata or {}
        user_id = metadata.get("user_id")
        school_id = metadata.get("school_id")

        # Handle both old (single) and new (multiple) event ID formats
        universal_event_ids_json = metadata.get("universal_event_ids")
        if universal_event_ids_json:
            universal_event_ids = json.loads(universal_event_ids_json)
        else:
            # Backward compatibility: single event ID
            single_id = metadata.get("universal_event_id")
            universal_event_ids = [single_id] if single_id else []

        if not user_id or not school_id or not universal_event_ids:
            return {
                "status": "pending",
                "event_ids": [],
                "event_id": None,
                "message": "Processing your payment..."
            }

        timestamp = datetime.now(timezone.utc).isoformat()
        created_event_ids = []
        purchased_events = []  # Collect events for receipt email
        first_universal_event = None
        first_purchase_id = None

        # Process each purchase/event
        for purchase in purchases:
            # Skip if already completed
            if purchase.get("status") == "completed":
                if purchase.get("event_id"):
                    created_event_ids.append(purchase.get("event_id"))
                # Still collect the event for receipt
                ue = events_repo.get_event_by_id(purchase.get("universal_event_id"))
                if ue:
                    purchased_events.append(ue)
                continue

            universal_event_id = purchase.get("universal_event_id")
            universal_event = events_repo.get_event_by_id(universal_event_id)

            if not universal_event:
                continue

            # Store first event for account linking
            if first_universal_event is None:
                first_universal_event = universal_event
                first_purchase_id = purchase.get("id")

            # Create the event
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

            if event_response.data:
                created_event = event_response.data[0]
                event_id = created_event.get("id")
                created_event_ids.append(event_id)
                purchased_events.append(universal_event)  # Add to receipt list

                # Update purchase record
                update_data = {
                    "status": "completed",
                    "completed_at": timestamp,
                    "event_id": event_id
                }
                if stripe_session.payment_intent:
                    update_data["stripe_payment_intent_id"] = stripe_session.payment_intent

                supabase.table("event_purchases").update(update_data).eq("id", purchase.get("id")).execute()

        # Handle account linking with all purchased events (same logic as webhook)
        if purchased_events and first_purchase_id:
            await _handle_account_linking_inline(
                supabase=supabase,
                user_id=user_id,
                purchased_events=purchased_events,
                first_purchase_id=first_purchase_id
            )

        if created_event_ids:
            # Calculate total amount (number of events * price per event)
            total_amount = len(purchased_events) * 1700  # $17 per event

            # Send post-purchase emails (receipt + invite admins if applicable)
            await _send_post_purchase_emails(
                supabase=supabase,
                user_id=user_id,
                events=purchased_events,
                total_amount=total_amount,
                checkout_session_id=session_id,
                purchase_date=timestamp
            )

            return {
                "status": "completed",
                "event_ids": created_event_ids,
                "event_id": created_event_ids[0],
                "message": "Payment successful! Redirecting to your events..."
            }

        return {
            "status": "pending",
            "event_ids": [],
            "event_id": None,
            "message": "Processing your payment..."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify payment: {str(e)}"
        )
