"""
Service for recruiter self-service signup flow.
"""

import os
import json
from typing import Dict, Any, Optional, List
from fastapi import HTTPException

from app.core.clients import get_supabase_client
from app.repositories.public_schools_repository import PublicSchoolsRepository
from app.repositories.universal_events_repository import UniversalEventsRepository
from app.repositories.event_purchases_repository import EventPurchasesRepository
from app.models.recruiter_signup import (
    RecruiterSignupRequest,
    RecruiterSignupResponse,
    SchoolSelection
)


# Event price in cents ($25.00)
EVENT_PRICE_CENTS = 2500


class RecruiterSignupService:
    """Service for handling recruiter self-signup."""

    def __init__(self):
        self.supabase = get_supabase_client()
        self.schools_repo = PublicSchoolsRepository()
        self.events_repo = UniversalEventsRepository()
        self.purchases_repo = EventPurchasesRepository()

    async def signup_recruiter(
        self,
        request: RecruiterSignupRequest
    ) -> RecruiterSignupResponse:
        """
        Process recruiter signup:
        1. Validate all events exist
        2. Check email isn't already registered
        3. Handle school selection (existing or create new)
        4. Create Supabase Auth user
        5. Create profile with recruiter role
        6. Create Stripe checkout session (with multiple line items)
        7. Create event purchase records for each event
        """
        try:
            import stripe
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Payment processing not available"
            )

        stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe_secret_key:
            raise HTTPException(
                status_code=500,
                detail="Payment processing not configured"
            )
        stripe.api_key = stripe_secret_key

        # 1. Validate all universal events exist
        events: List[Dict[str, Any]] = []
        for event_id in request.universal_event_ids:
            event = self.events_repo.get_event_by_id(event_id)
            if not event:
                raise HTTPException(
                    status_code=404,
                    detail=f"Event not found: {event_id}"
                )
            events.append(event)

        # 2. Check if email is already registered
        existing_user = self._check_email_exists(request.email)
        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="Email already registered. Please login instead."
            )

        # 3. Handle school selection
        school_id, parent_school_id, is_standalone = self._handle_school_selection(
            request.school_selection
        )

        # 4. Create Supabase Auth user
        user_id = self._create_auth_user(
            email=request.email,
            password=request.password,
            first_name=request.first_name,
            last_name=request.last_name,
            school_id=school_id
        )

        # 5. Create/update profile with recruiter role
        self._create_or_update_profile(
            user_id=user_id,
            email=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
            school_id=school_id,
            parent_school_id=parent_school_id,
            is_standalone=is_standalone
        )

        # 6. Create Stripe checkout session with line item per event
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

        # Calculate total amount
        total_amount = EVENT_PRICE_CENTS * len(events)

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=f"{frontend_url}/signup/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/signup/select-event?cancelled=true",
            customer_email=request.email,
            metadata={
                "user_id": user_id,
                "universal_event_ids": json.dumps(request.universal_event_ids),
                "school_id": school_id,
                "signup_type": "recruiter_self_service",
                "event_count": str(len(events))
            }
        )

        # 7. Create event purchase records for each event (before sign-in to keep service role)
        for event_id in request.universal_event_ids:
            self.purchases_repo.create_purchase(
                user_id=user_id,
                universal_event_id=event_id,
                stripe_checkout_session_id=checkout_session.id,
                amount=EVENT_PRICE_CENTS
            )

        # 8. Sign in the user to get session tokens (do this last!)
        session_tokens = self._sign_in_user(request.email, request.password)

        return RecruiterSignupResponse(
            user_id=user_id,
            checkout_session_id=checkout_session.id,
            checkout_url=checkout_session.url,
            access_token=session_tokens["access_token"],
            refresh_token=session_tokens["refresh_token"]
        )

    def _check_email_exists(self, email: str) -> bool:
        """Check if email is already registered."""
        # Check in profiles table
        response = (
            self.supabase.table("profiles")
            .select("id")
            .eq("email", email.lower())
            .limit(1)
            .execute()
        )
        return len(response.data or []) > 0

    def _handle_school_selection(
        self,
        selection: SchoolSelection
    ) -> tuple[str, Optional[str], bool]:
        """
        Handle school selection.
        Returns (school_id, parent_school_id, is_standalone).

        For existing school: user gets virtual school, parent_school_id set for linking
        For new school: user creates and owns the school
        """
        if selection.type == "existing":
            if not selection.school_id:
                raise HTTPException(
                    status_code=400,
                    detail="school_id required for existing school selection"
                )

            # Verify school exists
            if not self.schools_repo.school_exists(selection.school_id):
                raise HTTPException(
                    status_code=404,
                    detail="Selected school not found"
                )

            # Create a virtual school for the standalone recruiter
            # They'll be linked to the main school after admin approval
            virtual_school = self.schools_repo.create_virtual_school(
                name=f"Standalone - Pending Link"
            )

            return virtual_school["id"], selection.school_id, True

        elif selection.type == "new":
            if not selection.school_name:
                raise HTTPException(
                    status_code=400,
                    detail="school_name required for new school creation"
                )

            # Create new real school (will appear in search results)
            new_school = self.schools_repo.create_school(
                name=selection.school_name
            )

            # User owns this school, no parent, not standalone
            return new_school["id"], None, False

        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid school selection type"
            )

    def _create_auth_user(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        school_id: str
    ) -> str:
        """Create Supabase Auth user and return user ID."""
        try:
            # Use admin API to create user
            response = self.supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,  # Auto-confirm since they're paying
                "user_metadata": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "school_id": school_id
                }
            })

            if not response.user:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to create user account"
                )

            return response.user.id

        except Exception as e:
            error_msg = str(e)
            if "already registered" in error_msg.lower():
                raise HTTPException(
                    status_code=409,
                    detail="Email already registered"
                )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create user: {error_msg}"
            )

    def _create_or_update_profile(
        self,
        user_id: str,
        email: str,
        first_name: str,
        last_name: str,
        school_id: str,
        parent_school_id: Optional[str],
        is_standalone: bool
    ) -> Dict[str, Any]:
        """Create or update user profile with appropriate role."""
        # If user created a new school (not standalone), they're the admin
        # If they selected an existing school (standalone), they're a recruiter pending approval
        user_role = ["recruiter"] if is_standalone else ["admin"]

        profile_data = {
            "id": user_id,
            "email": email.lower(),
            "first_name": first_name,
            "last_name": last_name,
            "school_id": school_id,
            "role": user_role,
            "account_status": "standalone" if is_standalone else "linked",
            "parent_school_id": parent_school_id,
            "is_self_registered": True
        }

        response = (
            self.supabase.table("profiles")
            .upsert(profile_data)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=500,
                detail="Failed to create user profile"
            )

        return response.data[0]

    def _sign_in_user(self, email: str, password: str) -> Dict[str, str]:
        """Sign in user and return session tokens using a fresh client."""
        from supabase import create_client

        try:
            # Create a fresh client for sign-in to avoid polluting the service-role client
            # and to avoid sign_out() invalidating the tokens we return
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")

            if not supabase_url or not supabase_anon_key:
                raise HTTPException(
                    status_code=500,
                    detail="Missing Supabase configuration"
                )

            auth_client = create_client(supabase_url, supabase_anon_key)

            response = auth_client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })

            if not response.session:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to create user session"
                )

            return {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to sign in user: {str(e)}"
            )


async def get_public_schools(
    query: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """Get schools for public dropdown."""
    repo = PublicSchoolsRepository()

    if query:
        schools = repo.search_schools(query, limit)
    else:
        schools = repo.get_all_schools(limit)

    return {
        "schools": schools,
        "total": len(schools)
    }


async def search_universal_events(
    query: Optional[str] = None,
    state: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    city: Optional[str] = None,
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
    """Search universal events with filters."""
    from datetime import date as date_type

    repo = UniversalEventsRepository()

    # Parse dates
    parsed_date_from = None
    parsed_date_to = None
    if date_from:
        parsed_date_from = date_type.fromisoformat(date_from)
    if date_to:
        parsed_date_to = date_type.fromisoformat(date_to)

    # Calculate offset
    offset = (page - 1) * limit

    events, total = repo.search_events(
        query=query,
        state=state,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        city=city,
        limit=limit,
        offset=offset
    )

    # Calculate total pages
    pages = (total + limit - 1) // limit if total > 0 else 0

    return {
        "events": events,
        "total": total,
        "page": page,
        "pages": pages
    }
