"""
Unit tests for the authorization module (app/utils/authorization.py).

This module tests the authorization helper functions that enforce multi-tenant
isolation at the application layer. These functions are called in route handlers
BEFORE any database operations to verify that the authenticated user has permission
to access the requested resources.

Test Coverage:
1. is_superadmin() - Check if user has SuperAdmin privileges
2. verify_event_belongs_to_user_school() - Verify event access
3. verify_document_belongs_to_user_school() - Verify single document access
4. verify_documents_belong_to_user_school() - Verify bulk document access
5. verify_school_access() - Verify school-level access
6. get_user_school_id_or_fail() - Extract school_id with proper error handling

Run with: pytest tests/security/test_authorization_module.py -v
Requires: RUN_SECURITY_TESTS=true (for integration tests with real DB)
"""

import asyncio
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

# Mock problematic imports BEFORE importing the authorization module
# This prevents import errors when app.core.clients tries to load Google Cloud
if "app.core.clients" not in sys.modules:
    mock_clients = MagicMock()
    mock_clients.get_supabase_client = MagicMock()
    sys.modules["app.core.clients"] = mock_clients

if "app.utils.retry_utils" not in sys.modules:
    mock_retry = MagicMock()
    mock_retry.log_debug = MagicMock()
    sys.modules["app.utils.retry_utils"] = mock_retry

# Mark module to skip if security tests not enabled
pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_SECURITY_TESTS") != "true",
        reason="Security tests require RUN_SECURITY_TESTS=true"
    ),
    pytest.mark.security,
    pytest.mark.multi_tenant,
]


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def user_school_1():
    """Regular user from school 1."""
    return {
        "id": "user-school-1-uuid",
        "email": "user1@school1.edu",
        "school_id": "school-1-uuid",
        "role": ["recruiter"],
    }


@pytest.fixture
def user_school_2():
    """Regular user from school 2."""
    return {
        "id": "user-school-2-uuid",
        "email": "user2@school2.edu",
        "school_id": "school-2-uuid",
        "role": ["recruiter"],
    }


@pytest.fixture
def superadmin_user():
    """SuperAdmin user with no school_id (NULL)."""
    return {
        "id": "superadmin-uuid",
        "email": "superadmin@cardcapture.io",
        "school_id": None,
        "role": ["admin"],
    }


@pytest.fixture
def user_no_school_not_superadmin():
    """
    Edge case: User with no school_id but NOT a SuperAdmin.
    This could happen with data inconsistency or incomplete profile setup.
    """
    return {
        "id": "orphan-user-uuid",
        "email": "orphan@example.com",
        # Note: school_id key exists but value is empty string (not None)
        "school_id": "",
        "role": ["recruiter"],
    }


@pytest.fixture
def mock_supabase_client():
    """Mock Supabase client for authorization tests."""
    mock = MagicMock()
    mock.table.return_value = mock
    mock.select.return_value = mock
    mock.eq.return_value = mock
    mock.in_.return_value = mock
    mock.maybe_single.return_value = mock
    return mock


# =============================================================================
# Tests for is_superadmin()
# =============================================================================

class TestIsSuperadmin:
    """Tests for the is_superadmin() helper function."""

    def test_user_with_null_school_id_is_superadmin(self, superadmin_user):
        """
        User with school_id=None should be identified as SuperAdmin.

        SuperAdmins are CardCapture platform administrators who can access
        all schools' data. They are identified by having NULL school_id.
        """
        from app.utils.authorization import is_superadmin

        result = is_superadmin(superadmin_user)

        assert result is True

    def test_user_with_valid_school_id_is_not_superadmin(self, user_school_1):
        """
        User with a valid school_id should NOT be identified as SuperAdmin.

        Regular users belong to a specific school and should only access
        that school's data.
        """
        from app.utils.authorization import is_superadmin

        result = is_superadmin(user_school_1)

        assert result is False

    def test_user_dict_without_school_id_key_is_superadmin(self):
        """
        Edge case: User dict without school_id key should return True.

        This handles cases where the user profile might be incomplete
        or the key is missing entirely. user.get("school_id") returns None
        when the key doesn't exist, which matches SuperAdmin condition.
        """
        from app.utils.authorization import is_superadmin

        user_without_key = {
            "id": "user-uuid",
            "email": "user@test.com",
            # Note: school_id key is completely missing
            "role": ["admin"],
        }

        result = is_superadmin(user_without_key)

        # Missing key returns None via .get(), so this is True
        assert result is True

    def test_user_with_empty_string_school_id_is_not_superadmin(self):
        """
        User with empty string school_id should NOT be SuperAdmin.

        Empty string is not the same as None. This represents a data
        inconsistency that should be handled as "not SuperAdmin".
        """
        from app.utils.authorization import is_superadmin

        user_with_empty = {
            "id": "user-uuid",
            "email": "user@test.com",
            "school_id": "",
            "role": ["recruiter"],
        }

        result = is_superadmin(user_with_empty)

        # Empty string != None, so not a SuperAdmin
        assert result is False


# =============================================================================
# Tests for verify_event_belongs_to_user_school()
# =============================================================================

class TestVerifyEventBelongsToUserSchool:
    """Tests for the verify_event_belongs_to_user_school() function."""

    def test_superadmin_can_access_any_event(self, superadmin_user, mock_supabase_client):
        """
        SuperAdmin (school_id=None) should be able to access any event.

        SuperAdmins bypass school-level access checks because they need
        to manage all schools' data.
        """
        from app.utils.authorization import verify_event_belongs_to_user_school

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_event_belongs_to_user_school(
                    event_id="any-event-uuid",
                    user=superadmin_user
                )

        result = asyncio.run(run_test())

        assert result is True
        # SuperAdmin path should NOT query the database
        mock_supabase_client.table.assert_not_called()

    def test_regular_user_can_access_own_school_event(self, user_school_1, mock_supabase_client):
        """
        Regular user should be able to access events from their own school.

        The function queries the event's school_id and compares it to the
        user's school_id.
        """
        from app.utils.authorization import verify_event_belongs_to_user_school

        # Mock: event belongs to school-1 (same as user)
        mock_response = MagicMock()
        mock_response.data = {"school_id": "school-1-uuid"}
        mock_supabase_client.execute.return_value = mock_response

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_event_belongs_to_user_school(
                    event_id="event-school-1-uuid",
                    user=user_school_1
                )

        result = asyncio.run(run_test())
        assert result is True

    def test_regular_user_gets_403_for_other_school_event(self, user_school_1, mock_supabase_client):
        """
        Regular user should get 403 Forbidden when trying to access
        an event from a different school.

        This is the core multi-tenant isolation check.
        """
        from app.utils.authorization import verify_event_belongs_to_user_school

        # Mock: event belongs to school-2 (different from user's school-1)
        mock_response = MagicMock()
        mock_response.data = {"school_id": "school-2-uuid"}
        mock_supabase_client.execute.return_value = mock_response

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                await verify_event_belongs_to_user_school(
                    event_id="event-school-2-uuid",
                    user=user_school_1
                )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 403
        assert "different school" in exc_info.value.detail.lower()

    def test_nonexistent_event_returns_404(self, user_school_1, mock_supabase_client):
        """
        Accessing a non-existent event should return 404 Not Found.
        """
        from app.utils.authorization import verify_event_belongs_to_user_school

        # Mock: event not found
        mock_response = MagicMock()
        mock_response.data = None
        mock_supabase_client.execute.return_value = mock_response

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                await verify_event_belongs_to_user_school(
                    event_id="nonexistent-event-uuid",
                    user=user_school_1
                )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    def test_user_with_no_school_gets_403(self, user_no_school_not_superadmin, mock_supabase_client):
        """
        User with no school association (but not SuperAdmin) should get 403.

        This handles edge cases where a user profile exists but has no
        valid school_id assigned.
        """
        from app.utils.authorization import verify_event_belongs_to_user_school

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                await verify_event_belongs_to_user_school(
                    event_id="any-event-uuid",
                    user=user_no_school_not_superadmin
                )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 403
        assert "no school association" in exc_info.value.detail.lower()

    def test_raise_on_failure_false_returns_boolean(self, user_school_1, mock_supabase_client):
        """
        When raise_on_failure=False, function should return False instead
        of raising HTTPException.

        This is useful for conditional checks where the caller wants to
        handle the failure case themselves.
        """
        from app.utils.authorization import verify_event_belongs_to_user_school

        # Mock: event belongs to different school
        mock_response = MagicMock()
        mock_response.data = {"school_id": "school-2-uuid"}
        mock_supabase_client.execute.return_value = mock_response

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_event_belongs_to_user_school(
                    event_id="event-school-2-uuid",
                    user=user_school_1,
                    raise_on_failure=False
                )

        result = asyncio.run(run_test())
        assert result is False


# =============================================================================
# Tests for verify_document_belongs_to_user_school()
# =============================================================================

class TestVerifyDocumentBelongsToUserSchool:
    """Tests for the verify_document_belongs_to_user_school() function."""

    def test_superadmin_can_access_any_document(self, superadmin_user, mock_supabase_client):
        """
        SuperAdmin should be able to access any document regardless of school.
        """
        from app.utils.authorization import verify_document_belongs_to_user_school

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_document_belongs_to_user_school(
                    document_id="any-document-uuid",
                    user=superadmin_user
                )

        result = asyncio.run(run_test())
        assert result is True
        mock_supabase_client.table.assert_not_called()

    def test_regular_user_can_access_own_school_document_v1(self, user_school_1, mock_supabase_client):
        """
        Regular user should be able to access documents from their school
        in the V1 reviewed_data table.
        """
        from app.utils.authorization import verify_document_belongs_to_user_school

        # Mock: document found in reviewed_data (V1) belonging to user's school
        mock_response = MagicMock()
        mock_response.data = {"school_id": "school-1-uuid"}
        mock_supabase_client.execute.return_value = mock_response

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_document_belongs_to_user_school(
                    document_id="document-v1-uuid",
                    user=user_school_1
                )

        result = asyncio.run(run_test())
        assert result is True

    def test_regular_user_can_access_own_school_document_v2(self, user_school_1, mock_supabase_client):
        """
        Regular user should be able to access documents from their school
        in the V2 student_school_interactions table.

        The function first checks V1 (reviewed_data), and if not found,
        falls back to V2 (student_school_interactions).
        """
        from app.utils.authorization import verify_document_belongs_to_user_school

        # Create separate mocks for each table query
        mock_v1_response = MagicMock()
        mock_v1_response.data = None  # Not found in V1

        mock_v2_response = MagicMock()
        mock_v2_response.data = {"school_id": "school-1-uuid"}  # Found in V2

        # Track which table is being queried
        call_count = [0]

        def mock_execute():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_v1_response  # First call: reviewed_data
            return mock_v2_response  # Second call: student_school_interactions

        mock_supabase_client.execute.side_effect = mock_execute

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_document_belongs_to_user_school(
                    document_id="document-v2-uuid",
                    user=user_school_1
                )

        result = asyncio.run(run_test())
        assert result is True

    def test_regular_user_gets_403_for_other_school_document(self, user_school_1, mock_supabase_client):
        """
        Regular user should get 403 when trying to access a document
        from a different school.
        """
        from app.utils.authorization import verify_document_belongs_to_user_school

        # Mock: document belongs to school-2 (different from user's school-1)
        mock_response = MagicMock()
        mock_response.data = {"school_id": "school-2-uuid"}
        mock_supabase_client.execute.return_value = mock_response

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                await verify_document_belongs_to_user_school(
                    document_id="document-school-2-uuid",
                    user=user_school_1
                )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 403
        assert "different school" in exc_info.value.detail.lower()

    def test_nonexistent_document_returns_404(self, user_school_1, mock_supabase_client):
        """
        Accessing a non-existent document should return 404 Not Found.

        The function checks both V1 and V2 tables before returning 404.
        """
        from app.utils.authorization import verify_document_belongs_to_user_school

        # Mock: document not found in either table
        mock_response = MagicMock()
        mock_response.data = None
        mock_supabase_client.execute.return_value = mock_response

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                await verify_document_belongs_to_user_school(
                    document_id="nonexistent-document-uuid",
                    user=user_school_1
                )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()


# =============================================================================
# Tests for verify_documents_belong_to_user_school()
# =============================================================================

class TestVerifyDocumentsBelongToUserSchool:
    """Tests for the verify_documents_belong_to_user_school() function (bulk)."""

    def test_superadmin_can_access_any_documents(self, superadmin_user, mock_supabase_client):
        """
        SuperAdmin should be able to access any documents regardless of school.
        """
        from app.utils.authorization import verify_documents_belong_to_user_school

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_documents_belong_to_user_school(
                    document_ids=["doc-1", "doc-2", "doc-3"],
                    user=superadmin_user
                )

        result = asyncio.run(run_test())
        assert result is True
        mock_supabase_client.table.assert_not_called()

    def test_all_documents_from_own_school_passes(self, user_school_1, mock_supabase_client):
        """
        When all documents belong to user's school, access should be granted.
        """
        from app.utils.authorization import verify_documents_belong_to_user_school

        # Mock: all documents from user's school
        mock_v1_response = MagicMock()
        mock_v1_response.data = [
            {"document_id": "doc-1", "school_id": "school-1-uuid"},
            {"document_id": "doc-2", "school_id": "school-1-uuid"},
        ]

        mock_v2_response = MagicMock()
        mock_v2_response.data = [
            {"id": "doc-3", "school_id": "school-1-uuid"},
        ]

        call_count = [0]

        def mock_execute():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_v1_response
            return mock_v2_response

        mock_supabase_client.execute.side_effect = mock_execute

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_documents_belong_to_user_school(
                    document_ids=["doc-1", "doc-2", "doc-3"],
                    user=user_school_1
                )

        result = asyncio.run(run_test())
        assert result is True

    def test_one_document_from_other_school_fails_entire_batch(self, user_school_1, mock_supabase_client):
        """
        If even ONE document belongs to another school, the entire batch
        should fail with 403.

        This is critical for bulk operations (archive, delete, move) to
        prevent partial cross-tenant access.
        """
        from app.utils.authorization import verify_documents_belong_to_user_school

        # Mock: 2 docs from user's school, 1 from different school
        mock_v1_response = MagicMock()
        mock_v1_response.data = [
            {"document_id": "doc-1", "school_id": "school-1-uuid"},
            {"document_id": "doc-2", "school_id": "school-1-uuid"},
            {"document_id": "doc-bad", "school_id": "school-2-uuid"},  # Different school!
        ]

        mock_v2_response = MagicMock()
        mock_v2_response.data = []

        call_count = [0]

        def mock_execute():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_v1_response
            return mock_v2_response

        mock_supabase_client.execute.side_effect = mock_execute

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                await verify_documents_belong_to_user_school(
                    document_ids=["doc-1", "doc-2", "doc-bad"],
                    user=user_school_1
                )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 403
        assert "different school" in exc_info.value.detail.lower()

    def test_empty_list_passes(self, user_school_1, mock_supabase_client):
        """
        Empty document_ids list should pass (nothing to verify).
        """
        from app.utils.authorization import verify_documents_belong_to_user_school

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                return await verify_documents_belong_to_user_school(
                    document_ids=[],
                    user=user_school_1
                )

        result = asyncio.run(run_test())
        assert result is True
        mock_supabase_client.table.assert_not_called()

    def test_nonexistent_document_returns_404(self, user_school_1, mock_supabase_client):
        """
        If any document in the list doesn't exist, return 404.
        """
        from app.utils.authorization import verify_documents_belong_to_user_school

        # Mock: only one of two documents found
        mock_v1_response = MagicMock()
        mock_v1_response.data = [
            {"document_id": "doc-1", "school_id": "school-1-uuid"},
            # doc-missing is NOT in the response
        ]

        mock_v2_response = MagicMock()
        mock_v2_response.data = []

        call_count = [0]

        def mock_execute():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_v1_response
            return mock_v2_response

        mock_supabase_client.execute.side_effect = mock_execute

        async def run_test():
            with patch("app.utils.authorization.get_supabase_client", return_value=mock_supabase_client):
                await verify_documents_belong_to_user_school(
                    document_ids=["doc-1", "doc-missing"],
                    user=user_school_1
                )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()


# =============================================================================
# Tests for verify_school_access()
# =============================================================================

class TestVerifySchoolAccess:
    """Tests for the verify_school_access() function."""

    def test_superadmin_can_access_any_school(self, superadmin_user):
        """
        SuperAdmin should be able to access any school_id.
        """
        from app.utils.authorization import verify_school_access

        async def run_test():
            return await verify_school_access(
                school_id="any-school-uuid",
                user=superadmin_user
            )

        result = asyncio.run(run_test())
        assert result is True

    def test_user_can_access_own_school(self, user_school_1):
        """
        User should be able to access their own school_id.
        """
        from app.utils.authorization import verify_school_access

        async def run_test():
            return await verify_school_access(
                school_id="school-1-uuid",
                user=user_school_1
            )

        result = asyncio.run(run_test())
        assert result is True

    def test_user_gets_403_for_different_school(self, user_school_1):
        """
        User should get 403 when trying to access a different school_id.
        """
        from app.utils.authorization import verify_school_access

        async def run_test():
            await verify_school_access(
                school_id="school-2-uuid",  # Different from user's school-1
                user=user_school_1
            )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())

        assert exc_info.value.status_code == 403
        assert "different school" in exc_info.value.detail.lower()

    def test_raise_on_failure_false_returns_boolean(self, user_school_1):
        """
        When raise_on_failure=False, should return False instead of raising.
        """
        from app.utils.authorization import verify_school_access

        async def run_test():
            return await verify_school_access(
                school_id="school-2-uuid",
                user=user_school_1,
                raise_on_failure=False
            )

        result = asyncio.run(run_test())
        assert result is False


# =============================================================================
# Tests for get_user_school_id_or_fail()
# =============================================================================

class TestGetUserSchoolIdOrFail:
    """Tests for the get_user_school_id_or_fail() function."""

    def test_returns_school_id_for_regular_user(self, user_school_1):
        """
        Should return the user's school_id as a string.
        """
        from app.utils.authorization import get_user_school_id_or_fail

        result = get_user_school_id_or_fail(user_school_1)

        assert result == "school-1-uuid"
        assert isinstance(result, str)

    def test_returns_none_for_superadmin(self, superadmin_user):
        """
        Should return None for SuperAdmin users.

        SuperAdmins legitimately have NULL school_id and this is valid.
        """
        from app.utils.authorization import get_user_school_id_or_fail

        result = get_user_school_id_or_fail(superadmin_user)

        assert result is None

    def test_returns_none_when_school_id_key_missing(self):
        """
        When school_id key is missing, should return None (like SuperAdmin).
        """
        from app.utils.authorization import get_user_school_id_or_fail

        user_without_key = {
            "id": "user-uuid",
            "email": "user@test.com",
            "role": ["admin"],
        }

        result = get_user_school_id_or_fail(user_without_key)

        assert result is None


# =============================================================================
# Integration Tests (with real DB - skip if not configured)
# =============================================================================

@pytest.mark.skipif(
    os.getenv("RUN_SECURITY_TESTS") != "true",
    reason="Integration tests require RUN_SECURITY_TESTS=true and real DB"
)
class TestAuthorizationIntegration:
    """
    Integration tests that verify authorization against real database.

    These tests use the fixtures from security/conftest.py to create
    real test data in Supabase.

    NOTE: These tests require pytest-asyncio and real database connection.
    They are skipped by default and only run in CI with full setup.
    """

    def test_verify_event_with_real_data(
        self,
        test_event_school_1,
        test_user_school_1,
        test_user_school_2,
    ):
        """
        Integration test: Verify event access with real database data.
        """
        from app.utils.authorization import verify_event_belongs_to_user_school

        async def run_access_test():
            # User from school 1 should access school 1's event
            return await verify_event_belongs_to_user_school(
                event_id=test_event_school_1["id"],
                user=test_user_school_1
            )

        async def run_denial_test():
            # User from school 2 should NOT access school 1's event
            await verify_event_belongs_to_user_school(
                event_id=test_event_school_1["id"],
                user=test_user_school_2
            )

        result = asyncio.run(run_access_test())
        assert result is True

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_denial_test())
        assert exc_info.value.status_code == 403
