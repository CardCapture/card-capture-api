"""
Repository for account_link_requests table operations.
Handles CRUD operations for recruiter-to-school account linking requests.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from app.core.clients import get_supabase_client


class AccountLinkRequestsRepository:
    """Repository for managing account link requests."""

    def __init__(self):
        self.client = get_supabase_client()
        self.table = "account_link_requests"

    def create_request(
        self,
        requester_user_id: str,
        target_school_id: str,
        universal_event_id: str,
        event_purchase_id: Optional[str] = None,
        requester_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new account link request.
        """
        expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        response = (
            self.client.table(self.table)
            .insert({
                "requester_user_id": requester_user_id,
                "target_school_id": target_school_id,
                "universal_event_id": universal_event_id,
                "event_purchase_id": event_purchase_id,
                "requester_message": requester_message,
                "status": "pending",
                "expires_at": expires_at
            })
            .execute()
        )
        if not response.data:
            raise Exception("Failed to create account link request")
        return response.data[0]

    def get_request_by_id(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get a link request by ID with related data."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("id", request_id)
            .single()
            .execute()
        )
        if not response.data:
            return None

        # Enrich with related data
        enriched = self._enrich_requests([response.data])
        return enriched[0] if enriched else None

    def get_pending_requests_for_school(
        self,
        school_id: str,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all pending link requests for a school.
        By default, excludes expired requests.
        """
        query = (
            self.client.table(self.table)
            .select("*")
            .eq("target_school_id", school_id)
            .eq("status", "pending")
        )

        if not include_expired:
            query = query.gte("expires_at", datetime.now(timezone.utc).isoformat())

        response = query.order("created_at", desc=True).execute()
        requests = response.data or []

        # Enrich with related data
        return self._enrich_requests(requests)

    def get_all_requests_for_school(
        self,
        school_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Get all link requests for a school with optional status filter.
        Returns (requests, total_count).
        """
        # Build base query for count
        count_query = (
            self.client.table(self.table)
            .select("id", count="exact")
            .eq("target_school_id", school_id)
        )
        if status:
            count_query = count_query.eq("status", status)
        count_response = count_query.execute()
        total = count_response.count or 0

        # Build query for data (without embedded relations)
        query = (
            self.client.table(self.table)
            .select("*")
            .eq("target_school_id", school_id)
        )

        if status:
            query = query.eq("status", status)

        response = (
            query
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        requests = response.data or []

        # Enrich with related data
        return self._enrich_requests(requests), total

    def approve_request(
        self,
        request_id: str,
        reviewed_by: str,
        admin_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a link request.
        Returns the updated request.
        """
        response = (
            self.client.table(self.table)
            .update({
                "status": "approved",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "reviewed_by": reviewed_by,
                "admin_notes": admin_notes
            })
            .eq("id", request_id)
            .eq("status", "pending")  # Can only approve pending requests
            .execute()
        )
        if not response.data:
            raise Exception("Failed to approve request or request not found/not pending")
        return response.data[0]

    def reject_request(
        self,
        request_id: str,
        reviewed_by: str,
        admin_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reject a link request.
        Returns the updated request.
        """
        response = (
            self.client.table(self.table)
            .update({
                "status": "rejected",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "reviewed_by": reviewed_by,
                "admin_notes": admin_notes
            })
            .eq("id", request_id)
            .eq("status", "pending")  # Can only reject pending requests
            .execute()
        )
        if not response.data:
            raise Exception("Failed to reject request or request not found/not pending")
        return response.data[0]

    def cancel_request(self, request_id: str, user_id: str) -> Dict[str, Any]:
        """
        Cancel a link request (by the requester).
        """
        response = (
            self.client.table(self.table)
            .update({
                "status": "cancelled"
            })
            .eq("id", request_id)
            .eq("requester_user_id", user_id)  # Only requester can cancel
            .eq("status", "pending")  # Can only cancel pending requests
            .execute()
        )
        if not response.data:
            raise Exception("Failed to cancel request")
        return response.data[0]

    def get_requests_by_user(
        self,
        user_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all link requests made by a user."""
        query = (
            self.client.table(self.table)
            .select("""
                *,
                target_school:schools!target_school_id(
                    id, name
                ),
                universal_event:universal_events!universal_event_id(
                    id, name, event_date, location, city
                )
            """)
            .eq("requester_user_id", user_id)
        )

        if status:
            query = query.eq("status", status)

        response = query.order("created_at", desc=True).execute()
        return response.data or []

    def has_pending_request(
        self,
        user_id: str,
        school_id: str
    ) -> bool:
        """Check if user already has a pending request for this school."""
        response = (
            self.client.table(self.table)
            .select("id")
            .eq("requester_user_id", user_id)
            .eq("target_school_id", school_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        return len(response.data or []) > 0

    def get_pending_count_for_school(self, school_id: str) -> int:
        """Get count of pending requests for a school."""
        response = (
            self.client.table(self.table)
            .select("id", count="exact")
            .eq("target_school_id", school_id)
            .eq("status", "pending")
            .gte("expires_at", datetime.now(timezone.utc).isoformat())
            .execute()
        )
        return response.count or 0

    def expire_old_requests(self) -> int:
        """
        Mark expired pending requests as expired.
        Returns count of expired requests.
        """
        response = (
            self.client.table(self.table)
            .update({"status": "expired"})
            .eq("status", "pending")
            .lt("expires_at", datetime.now(timezone.utc).isoformat())
            .execute()
        )
        return len(response.data or [])

    def _enrich_requests(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich link requests with related data (profiles, events, purchases).
        Fetches related data in batch to avoid N+1 queries.
        """
        if not requests:
            return []

        # Collect unique IDs
        user_ids = set()
        event_ids = set()
        purchase_ids = set()
        school_ids = set()

        for req in requests:
            if req.get("requester_user_id"):
                user_ids.add(req["requester_user_id"])
            if req.get("reviewed_by"):
                user_ids.add(req["reviewed_by"])
            if req.get("universal_event_id"):
                event_ids.add(req["universal_event_id"])
            if req.get("event_purchase_id"):
                purchase_ids.add(req["event_purchase_id"])
            if req.get("target_school_id"):
                school_ids.add(req["target_school_id"])

        # Fetch profiles
        profiles_map = {}
        if user_ids:
            profiles_response = (
                self.client.table("profiles")
                .select("id, email, first_name, last_name, school_id")
                .in_("id", list(user_ids))
                .execute()
            )
            for p in (profiles_response.data or []):
                profiles_map[p["id"]] = p

        # Fetch events
        events_map = {}
        if event_ids:
            events_response = (
                self.client.table("universal_events")
                .select("id, name, event_date, location, city")
                .in_("id", list(event_ids))
                .execute()
            )
            for e in (events_response.data or []):
                events_map[e["id"]] = e

        # Fetch purchases
        purchases_map = {}
        if purchase_ids:
            purchases_response = (
                self.client.table("event_purchases")
                .select("id, amount, status, completed_at")
                .in_("id", list(purchase_ids))
                .execute()
            )
            for p in (purchases_response.data or []):
                purchases_map[p["id"]] = p

        # Fetch schools
        schools_map = {}
        if school_ids:
            schools_response = (
                self.client.table("schools")
                .select("id, name")
                .in_("id", list(school_ids))
                .execute()
            )
            for s in (schools_response.data or []):
                schools_map[s["id"]] = s

        # Fetch ALL event purchases for each requester (to show all events they purchased)
        # This gives us a complete picture of what they bought, not just the event in the link request
        all_purchases_by_user = {}
        if user_ids:
            # Get all completed purchases for these users
            all_purchases_response = (
                self.client.table("event_purchases")
                .select("id, user_id, universal_event_id, amount, status, completed_at")
                .in_("user_id", list(user_ids))
                .eq("status", "completed")
                .execute()
            )
            for purchase in (all_purchases_response.data or []):
                user_id = purchase.get("user_id")
                if user_id not in all_purchases_by_user:
                    all_purchases_by_user[user_id] = []
                all_purchases_by_user[user_id].append(purchase)

            # Collect all unique event IDs from these purchases
            all_event_ids = set()
            for purchases in all_purchases_by_user.values():
                for p in purchases:
                    if p.get("universal_event_id"):
                        all_event_ids.add(p["universal_event_id"])

            # Fetch all events for these purchases
            if all_event_ids:
                all_events_response = (
                    self.client.table("universal_events")
                    .select("id, name, event_date, location, city")
                    .in_("id", list(all_event_ids))
                    .execute()
                )
                for e in (all_events_response.data or []):
                    events_map[e["id"]] = e

        # Enrich requests
        enriched = []
        for req in requests:
            enriched_req = req.copy()

            # Add requester profile
            if req.get("requester_user_id"):
                enriched_req["requester"] = profiles_map.get(req["requester_user_id"])

            # Add reviewer profile
            if req.get("reviewed_by"):
                enriched_req["reviewer"] = profiles_map.get(req["reviewed_by"])

            # Add event (single event from link request - for backwards compatibility)
            if req.get("universal_event_id"):
                enriched_req["universal_event"] = events_map.get(req["universal_event_id"])

            # Add purchase (single purchase from link request - for backwards compatibility)
            if req.get("event_purchase_id"):
                enriched_req["event_purchase"] = purchases_map.get(req["event_purchase_id"])

            # Add target school
            if req.get("target_school_id"):
                enriched_req["target_school"] = schools_map.get(req["target_school_id"])

            # Add ALL purchased events for this requester
            requester_id = req.get("requester_user_id")
            if requester_id and requester_id in all_purchases_by_user:
                user_purchases = all_purchases_by_user[requester_id]
                purchased_events = []
                total_amount = 0
                for purchase in user_purchases:
                    event_id = purchase.get("universal_event_id")
                    event_data = events_map.get(event_id)
                    if event_data:
                        purchased_events.append({
                            "event": event_data,
                            "purchase": {
                                "id": purchase.get("id"),
                                "amount": purchase.get("amount"),
                                "status": purchase.get("status"),
                                "completed_at": purchase.get("completed_at")
                            }
                        })
                        total_amount += purchase.get("amount", 0)

                enriched_req["purchased_events"] = purchased_events
                enriched_req["total_amount"] = total_amount

            enriched.append(enriched_req)

        return enriched
