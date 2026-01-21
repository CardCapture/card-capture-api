from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import os
import json
from app.controllers.events_controller import (
    create_event_controller,
    update_event_controller,
    archive_events_controller,
    delete_event_controller
)
from app.models.event import EventCreatePayload, EventUpdatePayload, ArchiveEventsPayload
from app.core.auth import get_current_user
from app.core.clients import get_supabase_client
from app.repositories.universal_events_repository import UniversalEventsRepository
from app.repositories.event_purchases_repository import EventPurchasesRepository
from app.utils.retry_utils import log_debug

router = APIRouter(tags=["Events"])

# Event price in cents ($17.00)
EVENT_PRICE_CENTS = 1700


class AdminEventPurchaseRequest(BaseModel):
    """Request model for admin event purchases."""
    universal_event_ids: List[str] = Field(..., min_length=1, max_length=10, description="List of universal event IDs to purchase")


class AdminEventPurchaseResponse(BaseModel):
    """Response model for admin event purchases."""
    checkout_session_id: str
    checkout_url: str


class EventCodeCreateRequest(BaseModel):
    event_id: str
    max_uses: Optional[int] = 1000
    valid_days: Optional[int] = 7
    metadata: Optional[dict] = None


class EventCodeUpdateRequest(BaseModel):
    active: Optional[bool] = None
    max_uses: Optional[int] = None
    valid_until: Optional[str] = None

@router.post("/events")
async def create_event(payload: EventCreatePayload):
    return await create_event_controller(payload)


@router.post("/events/purchase", response_model=AdminEventPurchaseResponse)
async def purchase_events(request: AdminEventPurchaseRequest, user=Depends(get_current_user)):
    """
    Purchase events for an authenticated admin user.
    Creates a Stripe checkout session for the selected universal events.
    """
    try:
        import stripe
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Payment processing not available"
        )

    # Verify user is an admin
    user_roles = user.get("role", [])
    if "admin" not in user_roles:
        raise HTTPException(
            status_code=403,
            detail="Only admins can purchase events"
        )

    user_id = user.get("id")  # Profile uses 'id' not 'user_id'
    school_id = user.get("school_id")

    if not user_id or not school_id:
        log_debug(f"User profile incomplete: user_id={user_id}, school_id={school_id}", service="events")
        raise HTTPException(
            status_code=400,
            detail="User profile incomplete. Missing user_id or school_id."
        )

    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret_key:
        raise HTTPException(
            status_code=500,
            detail="Payment processing not configured"
        )
    stripe.api_key = stripe_secret_key

    # Initialize repositories
    events_repo = UniversalEventsRepository()
    purchases_repo = EventPurchasesRepository()

    # Validate all universal events exist and check for existing purchases
    events: List[Dict[str, Any]] = []
    already_purchased = []

    for event_id in request.universal_event_ids:
        event = events_repo.get_event_by_id(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event not found: {event_id}"
            )

        # Check if user already has a purchase for this event
        existing_purchase = purchases_repo.get_purchase_by_user_and_event(user_id, event_id)
        if existing_purchase:
            already_purchased.append(event.get("name", event_id))
        else:
            events.append(event)

    # If all events are already purchased, return error
    if not events:
        raise HTTPException(
            status_code=409,
            detail=f"You have already purchased access to: {', '.join(already_purchased)}"
        )

    # If some events are already purchased, warn but continue with the rest
    if already_purchased:
        log_debug(f"User {user_id} already has purchases for: {already_purchased}. Proceeding with remaining events.", service="events")

    # Get user email for Stripe
    supabase = get_supabase_client()
    profile_response = supabase.table("profiles").select("email").eq("id", user_id).single().execute()
    user_email = profile_response.data.get("email") if profile_response.data else None

    # Create Stripe checkout session with line item per event
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

    line_items = []
    for event in events:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Event Access: {event['name']}",
                    "description": f"Access to scan cards at {event['name']} on {event['event_date']}"
                },
                "unit_amount": EVENT_PRICE_CENTS,
            },
            "quantity": 1,
        })

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=f"{frontend_url}/events?purchase=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend_url}/purchase-events?cancelled=true",
        customer_email=user_email,
        allow_promotion_codes=True,
        metadata={
            "user_id": user_id,
            "universal_event_ids": json.dumps(request.universal_event_ids),
            "school_id": school_id,
            "signup_type": "admin_event_purchase",
            "event_count": str(len(events))
        }
    )

    # Create event purchase records for each event
    for event_id in request.universal_event_ids:
        purchases_repo.create_purchase(
            user_id=user_id,
            universal_event_id=event_id,
            stripe_checkout_session_id=checkout_session.id,
            amount=EVENT_PRICE_CENTS
        )

    log_debug(f"Admin {user_id} created checkout session {checkout_session.id} for {len(events)} events", service="events")

    return AdminEventPurchaseResponse(
        checkout_session_id=checkout_session.id,
        checkout_url=checkout_session.url
    )


@router.get("/events/verify-purchase/{session_id}")
async def verify_admin_purchase(session_id: str, user=Depends(get_current_user)):
    """
    Verify Stripe payment status for admin event purchases and send receipt email.
    Called by frontend after returning from Stripe checkout.
    """
    try:
        import stripe
    except ImportError:
        raise HTTPException(status_code=500, detail="Payment processing not available")

    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret_key:
        raise HTTPException(status_code=500, detail="Payment processing not configured")

    stripe.api_key = stripe_secret_key

    user_id = user.get("id")
    school_id = user.get("school_id")

    try:
        from datetime import datetime, timezone
        from app.services.notification_service import NotificationService

        purchases_repo = EventPurchasesRepository()
        events_repo = UniversalEventsRepository()
        supabase = get_supabase_client()

        # Get all purchases for this session
        purchases = purchases_repo.get_purchases_by_session_id(session_id)

        if not purchases:
            raise HTTPException(status_code=404, detail="Purchase not found")

        # Verify the purchase belongs to this user
        if purchases[0].get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Purchase does not belong to this user")

        # Check if already completed
        all_completed = all(p.get("status") == "completed" for p in purchases)

        if all_completed:
            event_ids = [p.get("event_id") for p in purchases if p.get("event_id")]
            return {
                "status": "completed",
                "event_ids": event_ids,
                "message": "Payment already processed."
            }

        # Check Stripe directly
        try:
            stripe_session = stripe.checkout.Session.retrieve(session_id)
        except stripe.error.InvalidRequestError:
            raise HTTPException(status_code=404, detail="Invalid session")

        if stripe_session.payment_status != 'paid':
            return {
                "status": "pending",
                "event_ids": [],
                "message": "Payment is still processing..."
            }

        # Stripe says paid - process the purchases
        timestamp = datetime.now(timezone.utc).isoformat()
        payment_intent = stripe_session.payment_intent
        created_event_ids = []
        purchased_events = []

        for purchase in purchases:
            if purchase.get("status") == "completed":
                if purchase.get("event_id"):
                    created_event_ids.append(purchase.get("event_id"))
                continue

            universal_event_id = purchase.get("universal_event_id")
            universal_event = events_repo.get_event_by_id(universal_event_id)

            if not universal_event:
                log_debug(f"Universal event not found: {universal_event_id}", service="events")
                continue

            purchased_events.append(universal_event)

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
                log_debug(f"Failed to create event for purchase: {purchase.get('id')}", service="events")
                continue

            created_event = event_response.data[0]
            event_id = created_event.get("id")
            created_event_ids.append(event_id)

            # Update purchase record
            update_data = {
                "status": "completed",
                "completed_at": timestamp,
                "event_id": event_id
            }
            if payment_intent:
                update_data["stripe_payment_intent_id"] = payment_intent

            supabase.table("event_purchases").update(update_data).eq("id", purchase.get("id")).execute()
            log_debug(f"Purchase completed: {purchase.get('id')} -> event {event_id}", service="events")

        # Send receipt email (is_new_user=False for admin purchases)
        if purchased_events:
            notification_service = NotificationService()

            # Get user profile for email
            profile_response = (
                supabase.table("profiles")
                .select("email, first_name, last_name")
                .eq("id", user_id)
                .single()
                .execute()
            )
            profile = profile_response.data

            if profile:
                recipient_email = profile.get("email")
                recipient_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
                if not recipient_name:
                    recipient_name = recipient_email

                total_amount = len(purchased_events) * EVENT_PRICE_CENTS

                receipt_result = notification_service.send_purchase_receipt_email(
                    recipient_email=recipient_email,
                    recipient_name=recipient_name,
                    events=purchased_events,
                    total_amount=total_amount,
                    checkout_session_id=session_id,
                    purchase_date=timestamp,
                    is_new_user=False  # Admin purchase, not new signup
                )
                log_debug(f"Receipt email result: {receipt_result}", service="events")

        return {
            "status": "completed",
            "event_ids": created_event_ids,
            "message": f"Payment successful! {len(created_event_ids)} event(s) added to your account."
        }

    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Error verifying admin purchase: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail=f"Failed to verify payment: {str(e)}")


@router.put("/events/{event_id}")
async def update_event(event_id: str, payload: EventUpdatePayload, user=Depends(get_current_user)):
    return await update_event_controller(event_id, payload, user)

@router.post("/archive-events")
async def archive_events(payload: ArchiveEventsPayload):
    return await archive_events_controller(payload)

@router.delete("/events/{event_id}")
async def delete_event(event_id: str, user=Depends(get_current_user)):
    return await delete_event_controller(event_id, user)

@router.get("/events-with-stats")
async def get_events_with_stats(
    school_id: Optional[str] = Query(None),
    user=Depends(get_current_user)
):
    """
    Get events with card statistics calculated server-side for performance.
    This endpoint calculates stats using optimized queries (only 2 DB calls regardless of event count).

    SECURITY: Always filters by user's school_id unless user is SuperAdmin (school_id=null).
    """
    try:
        supabase_client = get_supabase_client()

        # SECURITY FIX: Use user's school_id from auth token, not query parameter
        # Only allow query parameter override for SuperAdmins (who have no school_id)
        user_school_id = user.get("school_id")

        if user_school_id:
            # Regular user - ALWAYS filter by their school_id
            filter_school_id = user_school_id
            log_debug(f"Regular user {user.get('user_id')} requesting events for school {filter_school_id}", service="events")
        else:
            # SuperAdmin with no school_id - allow filtering by query param or return all
            filter_school_id = school_id
            log_debug(f"SuperAdmin {user.get('user_id')} requesting events" + (f" for school {filter_school_id}" if filter_school_id else " (all schools)"), service="events")

        # Fetch events for the school
        events_query = supabase_client.table("events").select("*").order("date", desc=True)
        if filter_school_id:
            events_query = events_query.eq("school_id", filter_school_id)

        events_response = events_query.execute()
        events = events_response.data if events_response.data else []

        if not events:
            return []

        # Get all event IDs
        event_ids = [event["id"] for event in events]

        # Use database function to get card stats aggregated in SQL
        # This avoids PostgREST's 1000 row limit and is much more efficient
        stats_response = supabase_client.rpc('get_event_card_stats', {'event_ids': event_ids}).execute()
        stats_data = stats_response.data if stats_response.data else []

        # Initialize stats map for all events (so events with 0 cards still show up)
        event_stats_map: Dict[str, Dict[str, int]] = {}
        for event_id in event_ids:
            event_stats_map[event_id] = {
                "total_cards": 0,
                "needs_review": 0,
                "ready_for_export": 0,
                "exported": 0,
                "archived": 0
            }

        # Populate stats from database aggregation
        for row in stats_data:
            event_id = row.get("event_id")
            status = row.get("review_status")
            count = row.get("card_count", 0)

            if event_id not in event_stats_map:
                continue

            event_stats_map[event_id]["total_cards"] += count

            if status == "needs_review":
                event_stats_map[event_id]["needs_review"] += count
            elif status == "reviewed":
                event_stats_map[event_id]["ready_for_export"] += count
            elif status == "exported":
                event_stats_map[event_id]["exported"] += count
            elif status == "archived":
                event_stats_map[event_id]["archived"] += count

        # Add stats to events
        events_with_stats = []
        for event in events:
            event_id = event["id"]
            stats = event_stats_map.get(event_id, {
                "total_cards": 0,
                "needs_review": 0,
                "ready_for_export": 0,
                "exported": 0,
                "archived": 0
            })
            event_with_stats = {**event, "stats": stats}
            events_with_stats.append(event_with_stats)

        total_cards = sum(stats["total_cards"] for stats in event_stats_map.values())
        log_debug(f"Fetched {len(events)} events with stats ({total_cards} total cards aggregated in DB)", service="events")
        return events_with_stats

    except Exception as e:
        log_debug(f"Get events with stats error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail=f"Failed to get events with stats: {str(e)}")

@router.post("/events/{event_id}/codes")
async def create_event_code(
    event_id: str,
    body: EventCodeCreateRequest,
    user=Depends(get_current_user)
):
    """Create a new event code for registration"""
    try:
        supabase_client = get_supabase_client()
        
        # Verify user has access to this event
        event_response = supabase_client.table("events").select("*").eq("id", event_id).limit(1).execute()
        if not event_response.data:
            raise HTTPException(status_code=404, detail="Event not found")
        
        event = event_response.data[0]
        if event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Generate unique 6-digit code
        code_response = supabase_client.rpc("generate_event_code").execute()
        code = code_response.data
        
        # Create event code
        valid_until = datetime.utcnow() + timedelta(days=body.valid_days)
        
        data = {
            "code": code,
            "event_id": event_id,
            "max_uses": body.max_uses,
            "valid_until": valid_until.isoformat(),
            "metadata": body.metadata or {}
        }
        
        response = supabase_client.table("event_codes").insert(data).execute()
        
        log_debug(f"Event code created: {code} for event {event_id}", service="events")
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Event code creation error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to create event code")


@router.get("/events/{event_id}/codes")
async def get_event_codes(
    event_id: str,
    user=Depends(get_current_user)
):
    """Get all event codes for an event"""
    try:
        supabase_client = get_supabase_client()
        
        # Verify user has access to this event
        event_response = supabase_client.table("events").select("*").eq("id", event_id).limit(1).execute()
        if not event_response.data:
            raise HTTPException(status_code=404, detail="Event not found")
        
        event = event_response.data[0]
        if event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get event codes
        response = supabase_client.table("event_codes").select("*").eq("event_id", event_id).order("created_at", desc=True).execute()
        
        return response.data
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Get event codes error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to get event codes")


@router.patch("/events/codes/{code_id}")
async def update_event_code(
    code_id: str,
    body: EventCodeUpdateRequest,
    user=Depends(get_current_user)
):
    """Update an event code"""
    try:
        supabase_client = get_supabase_client()
        
        # Get event code with event
        code_response = supabase_client.table("event_codes").select("*, events(*)").eq("id", code_id).limit(1).execute()
        if not code_response.data:
            raise HTTPException(status_code=404, detail="Event code not found")
        
        event_code = code_response.data[0]
        event = event_code.get("events")
        
        # Verify user has access
        if event and event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Update event code
        update_data = {}
        if body.active is not None:
            update_data["active"] = body.active
        if body.max_uses is not None:
            update_data["max_uses"] = body.max_uses
        if body.valid_until is not None:
            update_data["valid_until"] = body.valid_until
        
        response = supabase_client.table("event_codes").update(update_data).eq("id", code_id).execute()
        
        log_debug(f"Event code updated: {code_id}", service="events")
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Update event code error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to update event code")


@router.delete("/events/codes/{code_id}")
async def delete_event_code(
    code_id: str,
    user=Depends(get_current_user)
):
    """Delete (deactivate) an event code"""
    try:
        supabase_client = get_supabase_client()
        
        # Get event code with event
        code_response = supabase_client.table("event_codes").select("*, events(*)").eq("id", code_id).limit(1).execute()
        if not code_response.data:
            raise HTTPException(status_code=404, detail="Event code not found")
        
        event_code = code_response.data[0]
        event = event_code.get("events")
        
        # Verify user has access
        if event and event.get("school_id") != user.get("school_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Soft delete by deactivating
        response = supabase_client.table("event_codes").update({"active": False}).eq("id", code_id).execute()
        
        log_debug(f"Event code deactivated: {code_id}", service="events")
        return {"success": True, "message": "Event code deactivated"}
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Delete event code error: {str(e)}", service="events")
        raise HTTPException(status_code=500, detail="Failed to delete event code")


@router.get("/debug/auth-user")
async def debug_auth_user(user=Depends(get_current_user)):
    """Debug endpoint to check what's in auth.users for current user"""
    try:
        supabase_client = get_supabase_client()
        
        # Query auth.users directly to see what school_id this user has
        auth_user_query = supabase_client.table("auth.users").select("id, school_id").eq("id", user["user_id"]).execute()
        
        return JSONResponse(status_code=200, content={
            "user_from_token": user,
            "auth_users_record": auth_user_query.data,
            "debug_info": {
                "user_id_from_token": user.get("user_id"),
                "school_id_from_token": user.get("school_id"),
                "roles_from_token": user.get("role", [])
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Debug query failed: {str(e)}"}) 