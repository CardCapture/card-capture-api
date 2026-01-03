"""
Repository for public school listings (for recruiter signup dropdown).
"""

from typing import List, Dict, Any, Optional
from app.core.clients import get_supabase_client


class PublicSchoolsRepository:
    """Repository for accessing schools for public display."""

    def __init__(self):
        self.client = get_supabase_client()
        self.table = "schools"

    def get_all_schools(self, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Get all schools for dropdown selection.
        Excludes virtual schools (auto-created for standalone recruiters).
        """
        response = (
            self.client.table(self.table)
            .select("id, name")
            .eq("is_virtual_school", False)
            .order("name", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data or []

    def search_schools(
        self,
        query: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search schools by name.
        Excludes virtual schools.
        """
        response = (
            self.client.table(self.table)
            .select("id, name")
            .eq("is_virtual_school", False)
            .ilike("name", f"%{query}%")
            .order("name", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data or []

    def get_school_by_id(self, school_id: str) -> Optional[Dict[str, Any]]:
        """Get a school by ID."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("id", school_id)
            .single()
            .execute()
        )
        return response.data

    def school_exists(self, school_id: str) -> bool:
        """Check if a school exists."""
        response = (
            self.client.table(self.table)
            .select("id")
            .eq("id", school_id)
            .limit(1)
            .execute()
        )
        return len(response.data or []) > 0

    def create_virtual_school(self, name: str) -> Dict[str, Any]:
        """
        Create a virtual school for a standalone recruiter.
        Used when a user selects an existing school but needs a temporary
        school until their account is merged.
        """
        response = (
            self.client.table(self.table)
            .insert({
                "name": name,
                "is_virtual_school": True,
                "credits_balance": 0,
                "is_legacy_unlimited": False
            })
            .execute()
        )
        if not response.data:
            raise Exception("Failed to create virtual school")
        return response.data[0]

    def create_school(self, name: str) -> Dict[str, Any]:
        """
        Create a real school that will appear in search results.
        Used when a user creates a new school that doesn't exist yet.
        """
        response = (
            self.client.table(self.table)
            .insert({
                "name": name,
                "is_virtual_school": False,
                "credits_balance": 0,
                "is_legacy_unlimited": False
            })
            .execute()
        )
        if not response.data:
            raise Exception("Failed to create school")
        return response.data[0]
