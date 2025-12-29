"""
Webhook handlers for external services (Stripe, etc.)
"""

import os
import json
import stripe
from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone

from app.core.clients import get_supabase_client
from app.repositories.event_purchases_repository import EventPurchasesRepository
from app.repositories.universal_events_repository import UniversalEventsRepository
from app.repositories.account_link_requests_repository import AccountLinkRequestsRepository
from app.services.notification_service import NotificationService
from app.utils.retry_utils import log_debug

router = APIRouter(tags=["Webhooks"])


async def send_post_purchase_emails(
    supabase,
    user_id: str,
    events: list,
    total_amount: int,
    checkout_session_id: str,
    purchase_date: str,
    signup_type: str = "recruiter_self_service"
):
    """
    Send post-purchase emails:
    1. Receipt email to all users (welcome message for new users, just receipt for existing)
    2. Invite admins email to users who created a new school (new signups only)
    """
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
            log_debug(f"Profile not found for user {user_id}", service="webhook")
            return

        recipient_email = profile.get("email")
        recipient_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
        if not recipient_name:
            recipient_name = recipient_email

        account_status = profile.get("account_status")
        school_id = profile.get("school_id")

        # Determine if this is a new user signup or existing user purchase
        is_new_user = signup_type == "recruiter_self_service"

        # 1. Send receipt email to everyone
        receipt_result = notification_service.send_purchase_receipt_email(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            events=events,
            total_amount=total_amount,
            checkout_session_id=checkout_session_id,
            purchase_date=purchase_date,
            is_new_user=is_new_user
        )
        log_debug(f"Receipt email result: {receipt_result}", service="webhook")

        # 2. Send invite admins email only for NEW users who created a new school (not standalone)
        # Skip for admin_event_purchase since they already have an account
        if is_new_user and account_status != "standalone" and school_id:
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
            log_debug(f"Invite admins email result: {invite_result}", service="webhook")

    except Exception as e:
        # Don't fail the webhook if emails fail
        log_debug(f"Error sending post-purchase emails: {str(e)}", service="webhook")


# Create notification service instance
notification_service = NotificationService()


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature")
):
    """
    Handle Stripe webhook events.
    Primary handler for checkout.session.completed to finalize purchases.
    """
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if not stripe_secret_key:
        log_debug("Stripe secret key not configured", service="webhook")
        raise HTTPException(status_code=500, detail="Payment processing not configured")

    stripe.api_key = stripe_secret_key

    # Get raw body for signature verification
    payload = await request.body()

    # Verify webhook signature if secret is configured
    if webhook_secret and stripe_signature:
        try:
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, webhook_secret
            )
        except ValueError as e:
            log_debug(f"Invalid payload: {e}", service="webhook")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            log_debug(f"Invalid signature: {e}", service="webhook")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # For development without webhook secret
        import json
        event = json.loads(payload)
        log_debug("Warning: Processing webhook without signature verification", service="webhook")

    event_type = event.get("type") if isinstance(event, dict) else event.type
    log_debug(f"Received Stripe webhook: {event_type}", service="webhook")

    # Handle checkout.session.completed
    if event_type == "checkout.session.completed":
        session = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object
        await handle_checkout_completed(session)

    # Handle payment failures
    elif event_type == "checkout.session.expired":
        session = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object
        await handle_checkout_expired(session)

    return {"received": True}


async def handle_checkout_completed(session: dict):
    """
    Handle successful checkout completion.
    1. Mark all purchases as completed
    2. Create events in user's events table for each purchase
    3. Link events to purchases
    4. Handle account linking for first event
    """
    session_id = session.get("id")
    payment_intent = session.get("payment_intent")
    metadata = session.get("metadata", {})

    user_id = metadata.get("user_id")
    school_id = metadata.get("school_id")
    signup_type = metadata.get("signup_type", "recruiter_self_service")

    # Handle both old (single) and new (multiple) event ID formats
    universal_event_ids_json = metadata.get("universal_event_ids")
    if universal_event_ids_json:
        universal_event_ids = json.loads(universal_event_ids_json)
    else:
        # Backward compatibility: single event ID
        single_id = metadata.get("universal_event_id")
        universal_event_ids = [single_id] if single_id else []

    log_debug(f"Processing completed checkout: {session_id}", service="webhook")
    log_debug(f"Metadata: user_id={user_id}, event_ids={universal_event_ids}, school_id={school_id}", service="webhook")

    if not user_id or not school_id or not universal_event_ids:
        log_debug(f"Missing metadata in checkout session: {session_id}", service="webhook")
        return

    try:
        supabase = get_supabase_client()
        purchases_repo = EventPurchasesRepository()
        events_repo = UniversalEventsRepository()

        # Get all purchase records for this session
        purchases = purchases_repo.get_purchases_by_session_id(session_id)
        if not purchases:
            log_debug(f"No purchases found for session: {session_id}", service="webhook")
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        first_universal_event = None
        first_purchase_id = None
        purchased_events = []  # Collect events for receipt email

        # Process each purchase
        for purchase in purchases:
            # Check if already processed
            if purchase.get("status") == "completed":
                log_debug(f"Purchase {purchase.get('id')} already completed", service="webhook")
                # Still collect the event for receipt
                ue = events_repo.get_event_by_id(purchase.get("universal_event_id"))
                if ue:
                    purchased_events.append(ue)
                continue

            universal_event_id = purchase.get("universal_event_id")

            # Get universal event details
            universal_event = events_repo.get_event_by_id(universal_event_id)
            if not universal_event:
                log_debug(f"Universal event not found: {universal_event_id}", service="webhook")
                continue

            # Store first event for account linking
            if first_universal_event is None:
                first_universal_event = universal_event
                first_purchase_id = purchase.get("id")

            # Create event in user's events table
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
                log_debug(f"Failed to create event for purchase: {purchase.get('id')}", service="webhook")
                continue

            created_event = event_response.data[0]
            event_id = created_event.get("id")
            purchased_events.append(universal_event)  # Add to receipt list
            log_debug(f"Created event {event_id} for user {user_id}", service="webhook")

            # Update purchase record with completion status and event_id
            update_data = {
                "status": "completed",
                "completed_at": timestamp,
                "event_id": event_id
            }
            if payment_intent:
                update_data["stripe_payment_intent_id"] = payment_intent

            supabase.table("event_purchases").update(update_data).eq("id", purchase.get("id")).execute()
            log_debug(f"Purchase completed successfully: {purchase.get('id')} -> event {event_id}", service="webhook")

        # Handle account linking for first event only
        if first_universal_event and first_purchase_id:
            await handle_account_linking(
                supabase=supabase,
                user_id=user_id,
                universal_event_id=first_universal_event.get("id"),
                purchase_id=first_purchase_id,
                universal_event=first_universal_event
            )

        # Send post-purchase emails (receipt + invite admins if applicable)
        if purchased_events:
            total_amount = len(purchased_events) * 2500  # $25 per event
            await send_post_purchase_emails(
                supabase=supabase,
                user_id=user_id,
                events=purchased_events,
                total_amount=total_amount,
                checkout_session_id=session_id,
                purchase_date=timestamp,
                signup_type=signup_type
            )

    except Exception as e:
        log_debug(f"Error processing checkout completion: {str(e)}", service="webhook")
        raise


async def handle_account_linking(
    supabase,
    user_id: str,
    universal_event_id: str,
    purchase_id: str,
    universal_event: dict
):
    """
    Check if user wants to link to an existing school and create link request if so.
    Sends notification emails to school admins.
    """
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
            log_debug(f"Profile not found for user {user_id}", service="webhook")
            return

        parent_school_id = profile.get("parent_school_id")
        account_status = profile.get("account_status")

        # Only create link request if user selected an existing school
        if not parent_school_id or account_status != "standalone":
            log_debug(f"User {user_id} does not need account linking", service="webhook")
            return

        log_debug(f"Creating account link request for user {user_id} to school {parent_school_id}", service="webhook")

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
            log_debug(f"Target school {parent_school_id} not found", service="webhook")
            return

        # Create account link request
        link_repo = AccountLinkRequestsRepository()

        # Check if request already exists
        if link_repo.has_pending_request(user_id, parent_school_id):
            log_debug(f"Link request already exists for user {user_id} to school {parent_school_id}", service="webhook")
            return

        link_request = link_repo.create_request(
            requester_user_id=user_id,
            target_school_id=parent_school_id,
            universal_event_id=universal_event_id,
            event_purchase_id=purchase_id
        )

        log_debug(f"Created link request {link_request.get('id')}", service="webhook")

        # Send notification emails to school admins
        notification_service = NotificationService()
        recruiter_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
        if not recruiter_name:
            recruiter_name = profile.get("email", "Unknown")

        # Get purchase amount
        purchase_response = (
            supabase.table("event_purchases")
            .select("amount")
            .eq("id", purchase_id)
            .single()
            .execute()
        )
        amount_paid = purchase_response.data.get("amount", 2500) if purchase_response.data else 2500

        email_result = notification_service.send_link_request_to_admins(
            school_id=parent_school_id,
            school_name=school.get("name", "Unknown School"),
            recruiter_name=recruiter_name,
            recruiter_email=profile.get("email", ""),
            event_name=universal_event.get("name", "Unknown Event"),
            event_date=universal_event.get("event_date", "TBD"),
            amount_paid=amount_paid,
            request_id=link_request.get("id")
        )

        log_debug(f"Admin notification result: {email_result}", service="webhook")

    except Exception as e:
        # Don't fail the purchase if linking fails - just log it
        log_debug(f"Error handling account linking: {str(e)}", service="webhook")


async def handle_checkout_expired(session: dict):
    """Handle expired/cancelled checkout sessions."""
    session_id = session.get("id")
    log_debug(f"Checkout session expired: {session_id}", service="webhook")

    try:
        purchases_repo = EventPurchasesRepository()
        # Get all purchases for this session
        purchases = purchases_repo.get_purchases_by_session_id(session_id)

        for purchase in purchases:
            if purchase.get("status") == "pending":
                purchases_repo.fail_purchase(purchase.get("id"))
                log_debug(f"Marked purchase {purchase.get('id')} as failed", service="webhook")

    except Exception as e:
        log_debug(f"Error handling expired checkout: {str(e)}", service="webhook")
