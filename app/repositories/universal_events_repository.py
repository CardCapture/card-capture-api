"""
Repository for universal_events table operations.
"""

import re
from typing import List, Dict, Any, Optional
from datetime import date
from app.core.clients import get_supabase_client


def _sanitize_search_input(value: str) -> str:
    """Sanitize search input to prevent XSS and PostgREST filter injection.

    Strips HTML tags, SQL metacharacters, and PostgREST operators
    that could be used for injection via the .or_() filter string.
    """
    # Strip HTML tags
    value = re.sub(r"<[^>]*>", "", value)
    # Remove characters that could break PostgREST filter syntax or enable injection
    value = re.sub(r"[;\"'\\()\-]{2}", "", value)
    # Remove remaining dangerous single chars used in PostgREST operators
    value = re.sub(r"[<>]", "", value)
    # Collapse whitespace and trim
    value = re.sub(r"\s+", " ", value).strip()
    # Limit length to prevent abuse
    return value[:200]


class UniversalEventsRepository:
    """Repository for accessing universal events catalog."""

    def __init__(self):
        self.client = get_supabase_client()
        self.table = "universal_events"

    def search_events(
        self,
        query: Optional[str] = None,
        state: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        city: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Search universal events with filters.
        Returns (events, total_count).
        Sorted by date ascending (closest to today first).
        """
        # Sanitize text inputs
        if query:
            query = _sanitize_search_input(query)
        if city:
            city = _sanitize_search_input(city)

        # Build count query with filters
        count_query = self.client.table(self.table).select("*", count="exact")
        count_query = count_query.eq("status", "active")
        if state:
            count_query = count_query.eq("state", state.upper())
        if city:
            count_query = count_query.ilike("city", f"%{city}%")
        if date_from:
            count_query = count_query.gte("event_date", date_from.isoformat())
        if date_to:
            count_query = count_query.lte("event_date", date_to.isoformat())
        if query:
            count_query = count_query.or_(f"name.ilike.%{query}%,location.ilike.%{query}%,city.ilike.%{query}%,state.ilike.%{query}%,venue.ilike.%{query}%")

        # Build data query with same filters
        data_query = self.client.table(self.table).select("*")
        data_query = data_query.eq("status", "active")
        if state:
            data_query = data_query.eq("state", state.upper())
        if city:
            data_query = data_query.ilike("city", f"%{city}%")
        if date_from:
            data_query = data_query.gte("event_date", date_from.isoformat())
        if date_to:
            data_query = data_query.lte("event_date", date_to.isoformat())
        if query:
            data_query = data_query.or_(f"name.ilike.%{query}%,location.ilike.%{query}%,city.ilike.%{query}%,state.ilike.%{query}%,venue.ilike.%{query}%")

        # Get total count
        count_response = count_query.limit(1).execute()
        total = count_response.count or 0

        # Get paginated data - sorted by date ascending (closest events first)
        data_response = (
            data_query
            .order("event_date", desc=False)
            .range(offset, offset + limit - 1)
            .execute()
        )

        return data_response.data or [], total

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get a single universal event by ID."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("id", event_id)
            .single()
            .execute()
        )
        return response.data

    def get_upcoming_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get upcoming events ordered by date."""
        today = date.today().isoformat()
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("status", "active")
            .gte("event_date", today)
            .order("event_date", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data or []

    def get_events_by_region(self, region: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get events for a specific region."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("status", "active")
            .eq("region", region)
            .order("event_date", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data or []

    def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new universal event.

        Required fields: name, event_date
        Optional fields: start_time, end_time, location, address, city, state, zip,
                        description, contact_name, contact_email, contact_phone, etc.
        Defaults: state='TX', status='active'
        """
        # Set defaults
        event_data.setdefault("state", "TX")
        event_data.setdefault("status", "active")

        # Remove None values to let DB defaults apply
        event_data = {k: v for k, v in event_data.items() if v is not None}

        response = (
            self.client.table(self.table)
            .insert(event_data)
            .execute()
        )

        if response.data:
            return response.data[0]
        raise Exception("Failed to create event")
