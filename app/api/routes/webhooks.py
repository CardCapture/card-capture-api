"""
Webhook handlers for external services (Stripe, etc.)
"""

import os
import stripe
from fastapi import APIRouter, Request, HTTPException, Header
from datetime import datetime, timezone

from app.core.clients import get_supabase_client
from app.repositories.event_purchases_repository import EventPurchasesRepository
from app.repositories.universal_events_repository import UniversalEventsRepository
from app.utils.retry_utils import log_debug

router = APIRouter(tags=["Webhooks"])


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
    1. Mark purchase as completed
    2. Create event in user's events table
    3. Link event to purchase
    """
    session_id = session.get("id")
    payment_intent = session.get("payment_intent")
    metadata = session.get("metadata", {})

    user_id = metadata.get("user_id")
    universal_event_id = metadata.get("universal_event_id")
    school_id = metadata.get("school_id")

    log_debug(f"Processing completed checkout: {session_id}", service="webhook")
    log_debug(f"Metadata: user_id={user_id}, event_id={universal_event_id}, school_id={school_id}", service="webhook")

    if not all([user_id, universal_event_id, school_id]):
        log_debug(f"Missing metadata in checkout session: {session_id}", service="webhook")
        return

    try:
        supabase = get_supabase_client()
        purchases_repo = EventPurchasesRepository()
        events_repo = UniversalEventsRepository()

        # Get the purchase record
        purchase = purchases_repo.get_purchase_by_session_id(session_id)
        if not purchase:
            log_debug(f"Purchase not found for session: {session_id}", service="webhook")
            return

        # Check if already processed
        if purchase.get("status") == "completed":
            log_debug(f"Purchase already completed: {session_id}", service="webhook")
            return

        # Get universal event details
        universal_event = events_repo.get_event_by_id(universal_event_id)
        if not universal_event:
            log_debug(f"Universal event not found: {universal_event_id}", service="webhook")
            return

        # Create event in user's events table
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
            log_debug(f"Failed to create event for purchase: {session_id}", service="webhook")
            return

        created_event = event_response.data[0]
        event_id = created_event.get("id")
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

        log_debug(f"Purchase completed successfully: {session_id} -> event {event_id}", service="webhook")

    except Exception as e:
        log_debug(f"Error processing checkout completion: {str(e)}", service="webhook")
        raise


async def handle_checkout_expired(session: dict):
    """Handle expired/cancelled checkout sessions."""
    session_id = session.get("id")
    log_debug(f"Checkout session expired: {session_id}", service="webhook")

    try:
        purchases_repo = EventPurchasesRepository()
        purchase = purchases_repo.get_purchase_by_session_id(session_id)

        if purchase and purchase.get("status") == "pending":
            purchases_repo.fail_purchase(purchase.get("id"))
            log_debug(f"Marked purchase as failed: {session_id}", service="webhook")

    except Exception as e:
        log_debug(f"Error handling expired checkout: {str(e)}", service="webhook")
