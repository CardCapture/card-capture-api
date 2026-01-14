"""
Repository for public school listings (for recruiter signup dropdown).
"""

from typing import List, Dict, Any, Optional
from app.core.clients import get_supabase_client


# Default card fields for new schools - standard inquiry card fields
DEFAULT_CARD_FIELDS = [
    {"key": "first_name", "label": "First Name", "enabled": True, "required": True, "field_type": "text"},
    {"key": "last_name", "label": "Last Name", "enabled": True, "required": True, "field_type": "text"},
    {"key": "preferred_first_name", "label": "Preferred Name", "enabled": True, "required": False, "field_type": "text"},
    {"key": "email", "label": "Email", "enabled": True, "required": True, "field_type": "email"},
    {"key": "cell", "label": "Phone Number", "enabled": True, "required": False, "field_type": "phone"},
    {"key": "date_of_birth", "label": "Date of Birth", "enabled": True, "required": False, "field_type": "date"},
    {"key": "address", "label": "Address", "enabled": True, "required": False, "field_type": "text"},
    {"key": "city", "label": "City", "enabled": True, "required": False, "field_type": "text"},
    {"key": "state", "label": "State", "enabled": True, "required": False, "field_type": "text"},
    {"key": "zip_code", "label": "Zip Code", "enabled": True, "required": False, "field_type": "text"},
    {"key": "high_school", "label": "High School", "enabled": True, "required": False, "field_type": "text"},
    {"key": "graduation_year", "label": "Graduation Year", "enabled": True, "required": False, "field_type": "text"},
    {"key": "gpa", "label": "GPA", "enabled": True, "required": False, "field_type": "text"},
    {"key": "major", "label": "Major", "enabled": True, "required": False, "field_type": "text"},
    {"key": "act_score", "label": "ACT Score", "enabled": True, "required": False, "field_type": "text"},
    {"key": "sat_score", "label": "SAT Score", "enabled": True, "required": False, "field_type": "text"},
    {"key": "permission_to_text", "label": "Permission to Text", "enabled": True, "required": False, "field_type": "select", "options": ["Yes", "No"]},
]


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
                "is_legacy_unlimited": False,
                "card_fields": DEFAULT_CARD_FIELDS
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
                "is_legacy_unlimited": False,
                "card_fields": DEFAULT_CARD_FIELDS
            })
            .execute()
        )
        if not response.data:
            raise Exception("Failed to create school")
        return response.data[0]
