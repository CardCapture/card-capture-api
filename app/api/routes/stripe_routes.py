from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import os
from app.core.auth import get_current_user
from app.core.clients import supabase_client
from app.utils.retry_utils import log_debug

router = APIRouter(prefix="/stripe", tags=["Stripe"])

@router.post("/create-portal-session")
async def create_portal_session(user=Depends(get_current_user)):
    """
    Create a Stripe customer portal session for the user's school
    """
    try:
        # Check if Stripe is available
        try:
            import stripe
        except ImportError as e:
            log_debug(f"Stripe import error: {e}", service="stripe")
            raise HTTPException(status_code=500, detail="Stripe library not installed")

        # Configure Stripe
        stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")

        if not stripe_secret_key:
            log_debug("STRIPE_SECRET_KEY environment variable not found", service="stripe")
            raise HTTPException(status_code=500, detail="Stripe not configured")

        stripe.api_key = stripe_secret_key

        # Get the user's school information
        if not user or not user.get("school_id"):
            log_debug("User school not found", service="stripe")
            raise HTTPException(status_code=400, detail="User school not found")

        school_id = user.get("school_id")
        log_debug(f"Creating portal session for school_id: {school_id}", service="stripe")

        # Fetch school record to get stripe_customer_id
        school_response = supabase_client.table("schools").select("stripe_customer_id, name").eq("id", school_id).single().execute()

        if not school_response.data:
            raise HTTPException(status_code=404, detail="School not found")

        school = school_response.data
        stripe_customer_id = school.get("stripe_customer_id")

        if not stripe_customer_id:
            raise HTTPException(status_code=400, detail="No Stripe customer ID found for this school. Please contact support.")

        # Create the portal session
        log_debug("Creating Stripe portal session...", service="stripe")

        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=os.getenv("FRONTEND_URL", "http://localhost:3000") + "/settings/subscription",
        )

        log_debug("Portal session created successfully", service="stripe")
        return JSONResponse(status_code=200, content={"url": session.url})

    except stripe.error.StripeError as e:
        log_debug(f"Stripe error: {e}", service="stripe")
        raise HTTPException(status_code=400, detail="Stripe billing error")
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        log_debug(f"Error creating portal session: {e}", service="stripe")
        raise HTTPException(status_code=500, detail="Failed to create billing portal session")
