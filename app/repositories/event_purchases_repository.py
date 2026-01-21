"""
Repository for event_purchases table operations.
"""

from typing import List, Dict, Any, Optional
from app.core.clients import get_supabase_client


class EventPurchasesRepository:
    """Repository for managing event purchases."""

    def __init__(self):
        self.client = get_supabase_client()
        self.table = "event_purchases"

    def create_purchase(
        self,
        user_id: str,
        universal_event_id: str,
        stripe_checkout_session_id: str,
        amount: int = 1700,
        currency: str = "usd"
    ) -> Dict[str, Any]:
        """
        Create a new event purchase record (pending status).
        """
        response = (
            self.client.table(self.table)
            .insert({
                "user_id": user_id,
                "universal_event_id": universal_event_id,
                "stripe_checkout_session_id": stripe_checkout_session_id,
                "amount": amount,
                "currency": currency,
                "status": "pending"
            })
            .execute()
        )
        if not response.data:
            raise Exception("Failed to create event purchase")
        return response.data[0]

    def get_purchase_by_session_id(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get first purchase by Stripe checkout session ID (for backward compatibility)."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("stripe_checkout_session_id", session_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def get_purchases_by_session_id(
        self,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """Get all purchases by Stripe checkout session ID."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("stripe_checkout_session_id", session_id)
            .execute()
        )
        return response.data or []

    def get_purchase_by_id(self, purchase_id: str) -> Optional[Dict[str, Any]]:
        """Get a purchase by ID."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("id", purchase_id)
            .single()
            .execute()
        )
        return response.data

    def complete_purchase(
        self,
        purchase_id: str,
        stripe_payment_intent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Mark a purchase as completed.
        """
        update_data = {
            "status": "completed",
            "completed_at": "now()"
        }
        if stripe_payment_intent_id:
            update_data["stripe_payment_intent_id"] = stripe_payment_intent_id

        response = (
            self.client.table(self.table)
            .update(update_data)
            .eq("id", purchase_id)
            .execute()
        )
        if not response.data:
            raise Exception("Failed to complete purchase")
        return response.data[0]

    def fail_purchase(self, purchase_id: str) -> Dict[str, Any]:
        """Mark a purchase as failed."""
        response = (
            self.client.table(self.table)
            .update({"status": "failed"})
            .eq("id", purchase_id)
            .execute()
        )
        if not response.data:
            raise Exception("Failed to update purchase status")
        return response.data[0]

    def get_user_purchases(
        self,
        user_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all purchases for a user."""
        query = (
            self.client.table(self.table)
            .select("*, universal_events(*)")
            .eq("user_id", user_id)
        )
        if status:
            query = query.eq("status", status)

        response = query.order("created_at", desc=True).execute()
        return response.data or []

    def user_has_purchased_event(
        self,
        user_id: str,
        universal_event_id: str
    ) -> bool:
        """Check if a user has already purchased an event."""
        response = (
            self.client.table(self.table)
            .select("id")
            .eq("user_id", user_id)
            .eq("universal_event_id", universal_event_id)
            .eq("status", "completed")
            .limit(1)
            .execute()
        )
        return len(response.data or []) > 0

    def get_pending_purchase(
        self,
        user_id: str,
        universal_event_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a pending purchase for a user and event."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("universal_event_id", universal_event_id)
            .eq("status", "pending")
            .single()
            .execute()
        )
        return response.data

    def get_purchase_by_user_and_event(
        self,
        user_id: str,
        universal_event_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get any purchase (pending or completed) for a user and event."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("universal_event_id", universal_event_id)
            .neq("status", "failed")  # Ignore failed purchases
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None
