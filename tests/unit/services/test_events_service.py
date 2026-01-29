"""
Unit tests for events_service.py

Tests the security fixes for POST /events endpoint:
1. Authentication required
2. Role-based access control (admin/recruiter only)
3. Multi-tenant isolation (users can only create events for their school)
4. SuperAdmin behavior (can create events for any school)
"""

import asyncio
import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch

# =============================================================================
# Set up test environment BEFORE any app imports
# =============================================================================

# Set environment variables
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

# Mock external dependency modules BEFORE any app imports
sys.modules['google'] = MagicMock()
sys.modules['google.cloud'] = MagicMock()
sys.modules['google.cloud.documentai_v1'] = MagicMock()
sys.modules['google.cloud.vision'] = MagicMock()
sys.modules['google.cloud.storage'] = MagicMock()
sys.modules['googlemaps'] = MagicMock()

# Mock supabase to avoid actual connection attempts
mock_supabase_module = MagicMock()
mock_supabase_module.create_client = MagicMock(return_value=MagicMock())
sys.modules['supabase'] = mock_supabase_module


def run_async(coro):
    """Helper to run async functions synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def admin_user():
    """Admin user with school association."""
    return {
        "id": "admin-user-123",
        "email": "admin@school.edu",
        "school_id": "school-123",
        "role": ["admin"],
    }


@pytest.fixture
def recruiter_user():
    """Recruiter user with school association."""
    return {
        "id": "recruiter-user-456",
        "email": "recruiter@school.edu",
        "school_id": "school-123",
        "role": ["recruiter"],
    }


@pytest.fixture
def reviewer_user():
    """Reviewer user (should NOT be able to create events)."""
    return {
        "id": "reviewer-user-789",
        "email": "reviewer@school.edu",
        "school_id": "school-123",
        "role": ["reviewer"],
    }


@pytest.fixture
def superadmin_user():
    """SuperAdmin user with NO school association."""
    return {
        "id": "superadmin-user-000",
        "email": "superadmin@cardcapture.io",
        "school_id": None,  # SuperAdmins have no school_id
        "role": ["admin"],
    }


@pytest.fixture
def event_payload():
    """Standard event creation payload."""
    class Payload:
        name = "Test Event 2025"
        date = "2025-10-15"
        school_id = "school-123"
        slate_event_id = None
    return Payload()


# =============================================================================
# Permission Tests
# =============================================================================

class TestCreateEventPermissions:
    """Test role-based access control for event creation."""

    def test_admin_can_create_event(self, admin_user, event_payload):
        """Admin users should be able to create events."""
        mock_client = MagicMock()
        mock_insert_result = Mock(data=[{
            "id": "new-event-123",
            "name": "Test Event 2025",
            "date": "2025-10-15",
            "school_id": "school-123",
            "status": "active",
        }])

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.events_service.insert_event_db', return_value=mock_insert_result) as mock_insert:
            from app.services.events_service import create_event_service
            response = run_async(create_event_service(event_payload, admin_user))

        assert response.status_code == 200
        mock_insert.assert_called_once()

    def test_recruiter_can_create_event(self, recruiter_user, event_payload):
        """Recruiter users should be able to create events."""
        mock_client = MagicMock()
        mock_insert_result = Mock(data=[{
            "id": "new-event-123",
            "name": "Test Event 2025",
            "date": "2025-10-15",
            "school_id": "school-123",
            "status": "active",
        }])

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.events_service.insert_event_db', return_value=mock_insert_result) as mock_insert:
            from app.services.events_service import create_event_service
            response = run_async(create_event_service(event_payload, recruiter_user))

        assert response.status_code == 200
        mock_insert.assert_called_once()

    def test_reviewer_can_create_event(self, reviewer_user, event_payload):
        """Reviewer users should be able to create events."""
        mock_client = MagicMock()
        mock_insert_result = Mock(data=[{
            "id": "new-event-123",
            "name": "Test Event 2025",
            "date": "2025-10-15",
            "school_id": "school-123",
            "status": "active",
        }])

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.events_service.insert_event_db', return_value=mock_insert_result) as mock_insert:
            from app.services.events_service import create_event_service
            response = run_async(create_event_service(event_payload, reviewer_user))

        assert response.status_code == 200
        mock_insert.assert_called_once()

    def test_user_with_no_role_cannot_create_event(self, event_payload):
        """Users with no roles should NOT be able to create events."""
        from fastapi import HTTPException

        no_role_user = {
            "id": "no-role-user",
            "email": "norole@test.com",
            "school_id": "school-123",
            "role": [],
        }
        mock_client = MagicMock()

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client):
            from app.services.events_service import create_event_service
            with pytest.raises(HTTPException) as exc_info:
                run_async(create_event_service(event_payload, no_role_user))

        assert exc_info.value.status_code == 403


# =============================================================================
# Multi-Tenant Isolation Tests
# =============================================================================

class TestCreateEventMultiTenantIsolation:
    """Test that users can only create events for their own school."""

    def test_regular_user_event_uses_their_school_id(self, admin_user, event_payload):
        """
        Regular users should have events created for THEIR school,
        regardless of what school_id is in the payload.
        """
        # Try to create event with a DIFFERENT school_id in payload
        event_payload.school_id = "attacker-school-999"

        mock_client = MagicMock()
        mock_insert_result = Mock(data=[{"id": "new-event-123"}])

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.events_service.insert_event_db', return_value=mock_insert_result) as mock_insert:
            from app.services.events_service import create_event_service
            run_async(create_event_service(event_payload, admin_user))

        # Verify the event was created with USER'S school_id, not payload's
        call_args = mock_insert.call_args[0]
        event_data = call_args[1]  # Second argument is the event data

        assert event_data["school_id"] == admin_user["school_id"]
        assert event_data["school_id"] != "attacker-school-999"

    def test_regular_user_cannot_create_event_for_other_school(self, admin_user):
        """
        SECURITY: Verify that payload school_id is IGNORED for regular users.
        This prevents cross-tenant event creation attacks.
        """
        # Create payload with attacker's target school
        class AttackPayload:
            name = "Malicious Event"
            date = "2025-10-15"
            school_id = "victim-school-id"  # Attacker tries to inject this
            slate_event_id = None

        mock_client = MagicMock()
        mock_insert_result = Mock(data=[{"id": "new-event-123"}])

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.events_service.insert_event_db', return_value=mock_insert_result) as mock_insert:
            from app.services.events_service import create_event_service
            run_async(create_event_service(AttackPayload(), admin_user))

        # Verify the attack failed - event created for USER's school, not victim's
        call_args = mock_insert.call_args[0]
        event_data = call_args[1]

        assert event_data["school_id"] == admin_user["school_id"]
        assert event_data["school_id"] != "victim-school-id"


# =============================================================================
# SuperAdmin Tests
# =============================================================================

class TestCreateEventSuperAdmin:
    """Test SuperAdmin event creation behavior."""

    def test_superadmin_can_create_event_for_any_school(self, superadmin_user):
        """SuperAdmins (no school_id) can create events for any school."""
        class SuperAdminPayload:
            name = "SuperAdmin Event"
            date = "2025-10-15"
            school_id = "target-school-456"  # SuperAdmin specifies target school
            slate_event_id = None

        mock_client = MagicMock()
        mock_insert_result = Mock(data=[{"id": "new-event-123"}])

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.events_service.insert_event_db', return_value=mock_insert_result) as mock_insert:
            from app.services.events_service import create_event_service
            run_async(create_event_service(SuperAdminPayload(), superadmin_user))

        # Verify event created for the specified school
        call_args = mock_insert.call_args[0]
        event_data = call_args[1]

        assert event_data["school_id"] == "target-school-456"

    def test_superadmin_requires_school_id_in_payload(self, superadmin_user):
        """SuperAdmins MUST provide school_id in payload."""
        from fastapi import HTTPException

        class MissingSchoolPayload:
            name = "Event Without School"
            date = "2025-10-15"
            school_id = None  # Missing school_id
            slate_event_id = None

        mock_client = MagicMock()

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client):
            from app.services.events_service import create_event_service
            with pytest.raises(HTTPException) as exc_info:
                run_async(create_event_service(MissingSchoolPayload(), superadmin_user))

        assert exc_info.value.status_code == 400
        assert "school_id is required" in str(exc_info.value.detail)

    def test_superadmin_empty_school_id_fails(self, superadmin_user):
        """SuperAdmins with empty string school_id should fail."""
        from fastapi import HTTPException

        class EmptySchoolPayload:
            name = "Event With Empty School"
            date = "2025-10-15"
            school_id = ""  # Empty string
            slate_event_id = None

        mock_client = MagicMock()

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client):
            from app.services.events_service import create_event_service
            with pytest.raises(HTTPException) as exc_info:
                run_async(create_event_service(EmptySchoolPayload(), superadmin_user))

        assert exc_info.value.status_code == 400


# =============================================================================
# Edge Cases
# =============================================================================

class TestCreateEventEdgeCases:
    """Test edge cases and error handling."""

    def test_user_with_null_role_cannot_create_event(self, event_payload):
        """Users with None/null role should not be able to create events."""
        from fastapi import HTTPException

        null_role_user = {
            "id": "null-role-user",
            "email": "nullrole@test.com",
            "school_id": "school-123",
            "role": None,  # None instead of list
        }
        mock_client = MagicMock()

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client):
            from app.services.events_service import create_event_service
            with pytest.raises(HTTPException) as exc_info:
                run_async(create_event_service(event_payload, null_role_user))

        assert exc_info.value.status_code == 403

    def test_event_data_integrity(self, admin_user):
        """Verify all event fields are correctly passed to the database."""
        class DetailedPayload:
            name = "Detailed Test Event"
            date = "2025-12-25"
            school_id = "ignored-school"  # Should be ignored
            slate_event_id = "SLATE-12345"

        mock_client = MagicMock()
        mock_insert_result = Mock(data=[{"id": "new-event-123"}])

        with patch('app.services.events_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.events_service.insert_event_db', return_value=mock_insert_result) as mock_insert:
            from app.services.events_service import create_event_service
            run_async(create_event_service(DetailedPayload(), admin_user))

        call_args = mock_insert.call_args[0]
        event_data = call_args[1]

        assert event_data["name"] == "Detailed Test Event"
        assert event_data["date"] == "2025-12-25"
        assert event_data["school_id"] == admin_user["school_id"]
        assert event_data["slate_event_id"] == "SLATE-12345"
        assert event_data["status"] == "active"


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestCanCreateEvents:
    """Test the can_create_events helper function."""

    def test_admin_can_create(self):
        """Admin role should return True."""
        from app.services.events_service import can_create_events

        user = {"role": ["admin"]}
        assert can_create_events(user) is True

    def test_recruiter_can_create(self):
        """Recruiter role should return True."""
        from app.services.events_service import can_create_events

        user = {"role": ["recruiter"]}
        assert can_create_events(user) is True

    def test_reviewer_can_create(self):
        """Reviewer role should return True."""
        from app.services.events_service import can_create_events

        user = {"role": ["reviewer"]}
        assert can_create_events(user) is True

    def test_multiple_roles_with_admin(self):
        """User with multiple roles including admin should return True."""
        from app.services.events_service import can_create_events

        user = {"role": ["reviewer", "admin"]}
        assert can_create_events(user) is True

    def test_multiple_roles_with_recruiter(self):
        """User with multiple roles including recruiter should return True."""
        from app.services.events_service import can_create_events

        user = {"role": ["reviewer", "recruiter"]}
        assert can_create_events(user) is True

    def test_empty_role_list(self):
        """Empty role list should return False."""
        from app.services.events_service import can_create_events

        user = {"role": []}
        assert can_create_events(user) is False

    def test_missing_role_key(self):
        """Missing role key should return False (not crash)."""
        from app.services.events_service import can_create_events

        user = {}
        assert can_create_events(user) is False
