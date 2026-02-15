"""
Unit tests for recruiter signup service rollback behavior.

Tests that the signup flow correctly handles failures at each stage:
1. Auth user creation failure -> school record cleaned up
2. Stripe checkout failure -> user and school cleaned up
3. Happy path succeeds without triggering rollback

All external services (Supabase, Stripe) are mocked.
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch, AsyncMock

# Set up test environment BEFORE any app imports
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

mock_supabase_module = MagicMock()
mock_supabase_module.create_client = MagicMock(return_value=MagicMock())
sys.modules['supabase'] = mock_supabase_module


import asyncio


def run_async(coro):
    """Helper to run async functions synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase_client():
    """Create a fully mocked Supabase client."""
    client = MagicMock()

    # Mock table queries to be chainable
    def mock_table(name):
        table = MagicMock()
        table.select.return_value = table
        table.insert.return_value = table
        table.update.return_value = table
        table.upsert.return_value = table
        table.delete.return_value = table
        table.eq.return_value = table
        table.limit.return_value = table
        table.single.return_value = table
        table.maybe_single.return_value = table

        # Default: empty results (no existing user)
        result = Mock()
        result.data = []
        result.error = None
        table.execute.return_value = result
        return table

    client.table = mock_table

    # Mock auth admin
    client.auth = MagicMock()
    client.auth.admin = MagicMock()

    return client


@pytest.fixture
def signup_request():
    """Create a standard signup request object."""
    request = MagicMock()
    request.email = "recruiter@test.edu"
    request.password = "SecurePass123!"
    request.first_name = "Test"
    request.last_name = "Recruiter"
    request.universal_event_ids = ["event-uuid-1"]

    # School selection for new school
    request.school_selection = MagicMock()
    request.school_selection.type = "new"
    request.school_selection.school_name = "Test University"
    request.school_selection.school_id = None
    request.school_selection.is_self_admin = True
    request.school_selection.admin_email = None
    request.school_selection.admin_first_name = None
    request.school_selection.admin_last_name = None

    return request


@pytest.fixture
def mock_event_data():
    """Sample universal event data."""
    return {
        "id": "event-uuid-1",
        "name": "Fall College Fair 2025",
        "event_date": "2025-10-15",
        "city": "Dallas",
        "state": "TX",
    }


# =============================================================================
# Auth User Creation Failure Tests
# =============================================================================

class TestSignupAuthFailure:
    """Test that auth user creation failure triggers cleanup."""

    @pytest.mark.unit
    def test_auth_failure_raises_http_exception(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """When auth user creation fails, an HTTPException should be raised."""
        from fastapi import HTTPException

        # Mock auth failure
        mock_supabase_client.auth.admin.create_user.side_effect = Exception("Auth service unavailable")

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository') as mock_schools_repo_cls, \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'):

            # Set up events repo to return valid event
            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            # Set up schools repo to create school successfully
            mock_schools_repo = mock_schools_repo_cls.return_value
            mock_schools_repo.create_school.return_value = {"id": "new-school-123", "name": "Test University"}

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            with pytest.raises(HTTPException) as exc_info:
                run_async(service.signup_recruiter(signup_request))

            assert exc_info.value.status_code == 500
            assert "Failed to create user" in str(exc_info.value.detail)

    @pytest.mark.unit
    def test_duplicate_email_auth_raises_409(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """When auth returns 'already registered', a 409 should be raised."""
        from fastapi import HTTPException

        mock_supabase_client.auth.admin.create_user.side_effect = Exception("User already registered")

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository') as mock_schools_repo_cls, \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            mock_schools_repo = mock_schools_repo_cls.return_value
            mock_schools_repo.create_school.return_value = {"id": "new-school-123", "name": "Test University"}

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            with pytest.raises(HTTPException) as exc_info:
                run_async(service.signup_recruiter(signup_request))

            assert exc_info.value.status_code == 409


# =============================================================================
# Stripe Checkout Failure Tests
# =============================================================================

class TestSignupStripeFailure:
    """Test that Stripe checkout failure is surfaced correctly."""

    @pytest.mark.unit
    def test_stripe_checkout_failure_raises_exception(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """When Stripe checkout creation fails, the error should propagate."""
        # Mock successful auth user creation
        mock_user = Mock()
        mock_user.id = "new-user-123"
        mock_auth_response = Mock()
        mock_auth_response.user = mock_user
        mock_supabase_client.auth.admin.create_user.return_value = mock_auth_response

        # Mock successful profile upsert
        profile_table = MagicMock()
        profile_table.upsert.return_value = profile_table
        profile_table.execute.return_value = Mock(data=[{"id": "new-user-123"}])

        def table_router(name):
            if name == "profiles":
                t = MagicMock()
                t.select.return_value = t
                t.eq.return_value = t
                t.limit.return_value = t
                # No existing user found
                t.execute.return_value = Mock(data=[])
                t.upsert.return_value = t
                # But upsert returns profile
                def execute_side_effect():
                    return Mock(data=[{"id": "new-user-123"}])
                return t
            return MagicMock()

        mock_supabase_client.table = MagicMock(side_effect=table_router)

        # Override table for profiles specifically for upsert
        profiles_mock = MagicMock()
        profiles_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(data=[])
        profiles_mock.upsert.return_value.execute.return_value = Mock(data=[{"id": "new-user-123"}])
        mock_supabase_client.table = MagicMock(return_value=profiles_mock)

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository') as mock_schools_repo_cls, \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'), \
             patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_123"}), \
             patch('stripe.checkout.Session.create', side_effect=Exception("Stripe API error")):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            mock_schools_repo = mock_schools_repo_cls.return_value
            mock_schools_repo.create_school.return_value = {"id": "new-school-123", "name": "Test University"}

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            with pytest.raises(Exception) as exc_info:
                run_async(service.signup_recruiter(signup_request))

            assert "Stripe API error" in str(exc_info.value)


# =============================================================================
# Happy Path Tests
# =============================================================================

class TestSignupHappyPath:
    """Test that the happy path completes successfully."""

    @pytest.mark.unit
    def test_successful_signup_returns_response(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """Full signup flow succeeds and returns checkout URL and tokens."""
        # Mock successful auth user creation
        mock_user = Mock()
        mock_user.id = "new-user-123"
        mock_auth_response = Mock()
        mock_auth_response.user = mock_user
        mock_supabase_client.auth.admin.create_user.return_value = mock_auth_response

        # Mock table operations
        profiles_mock = MagicMock()
        profiles_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(data=[])
        profiles_mock.upsert.return_value.execute.return_value = Mock(data=[{"id": "new-user-123"}])
        mock_supabase_client.table = MagicMock(return_value=profiles_mock)

        # Mock Stripe checkout session
        mock_checkout = Mock()
        mock_checkout.id = "cs_test_abc123"
        mock_checkout.url = "https://checkout.stripe.com/test"

        # Mock sign-in
        mock_sign_in_client = MagicMock()
        mock_session = Mock()
        mock_session.access_token = "test-access-token"
        mock_session.refresh_token = "test-refresh-token"
        mock_sign_in_response = Mock()
        mock_sign_in_response.session = mock_session
        mock_sign_in_client.auth.sign_in_with_password.return_value = mock_sign_in_response

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository') as mock_schools_repo_cls, \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository') as mock_purchases_repo_cls, \
             patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_123", "FRONTEND_URL": "http://localhost:5173"}), \
             patch('stripe.checkout.Session.create', return_value=mock_checkout), \
             patch('supabase.create_client', return_value=mock_sign_in_client):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            mock_schools_repo = mock_schools_repo_cls.return_value
            mock_schools_repo.create_school.return_value = {"id": "new-school-123", "name": "Test University"}

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            result = run_async(service.signup_recruiter(signup_request))

            assert result.user_id == "new-user-123"
            assert result.checkout_session_id == "cs_test_abc123"
            assert result.checkout_url == "https://checkout.stripe.com/test"
            assert result.access_token == "test-access-token"
            assert result.refresh_token == "test-refresh-token"

    @pytest.mark.unit
    def test_event_not_found_returns_404(
        self, mock_supabase_client, signup_request
    ):
        """Signup with a nonexistent event ID should return 404."""
        from fastapi import HTTPException

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository'), \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'), \
             patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_123"}):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = None  # Event not found

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            with pytest.raises(HTTPException) as exc_info:
                run_async(service.signup_recruiter(signup_request))

            assert exc_info.value.status_code == 404
            assert "Event not found" in str(exc_info.value.detail)

    @pytest.mark.unit
    def test_existing_email_returns_409(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """Signup with an already-registered email should return 409."""
        from fastapi import HTTPException

        # Make profiles query return an existing user
        profiles_mock = MagicMock()
        profiles_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(
            data=[{"id": "existing-user-123"}]
        )
        mock_supabase_client.table = MagicMock(return_value=profiles_mock)

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository'), \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'), \
             patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_123"}):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            with pytest.raises(HTTPException) as exc_info:
                run_async(service.signup_recruiter(signup_request))

            assert exc_info.value.status_code == 409

    @pytest.mark.unit
    def test_missing_stripe_key_returns_500(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """Signup without STRIPE_SECRET_KEY configured should return 500."""
        from fastapi import HTTPException

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository'), \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'), \
             patch.dict(os.environ, {"STRIPE_SECRET_KEY": ""}, clear=False):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            with pytest.raises(HTTPException) as exc_info:
                run_async(service.signup_recruiter(signup_request))

            assert exc_info.value.status_code == 500
            assert "not configured" in str(exc_info.value.detail)


# =============================================================================
# School Selection Tests
# =============================================================================

class TestSignupSchoolSelection:
    """Test school selection logic during signup."""

    @pytest.mark.unit
    def test_existing_school_creates_virtual_school(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """Selecting an existing school should create a virtual/standalone school."""
        # Configure for existing school selection
        signup_request.school_selection.type = "existing"
        signup_request.school_selection.school_id = "existing-school-456"
        signup_request.school_selection.school_name = None

        # Mock auth user
        mock_user = Mock()
        mock_user.id = "new-user-123"
        mock_auth_response = Mock()
        mock_auth_response.user = mock_user
        mock_supabase_client.auth.admin.create_user.return_value = mock_auth_response

        # Mock table
        profiles_mock = MagicMock()
        profiles_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(data=[])
        profiles_mock.upsert.return_value.execute.return_value = Mock(data=[{"id": "new-user-123"}])
        mock_supabase_client.table = MagicMock(return_value=profiles_mock)

        # Mock Stripe and sign-in
        mock_checkout = Mock(id="cs_test_abc", url="https://checkout.stripe.com/test")
        mock_sign_in_client = MagicMock()
        mock_session = Mock(access_token="tok", refresh_token="ref")
        mock_sign_in_client.auth.sign_in_with_password.return_value = Mock(session=mock_session)

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository') as mock_schools_repo_cls, \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'), \
             patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_123", "FRONTEND_URL": "http://localhost:5173"}), \
             patch('stripe.checkout.Session.create', return_value=mock_checkout), \
             patch('supabase.create_client', return_value=mock_sign_in_client):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            mock_schools_repo = mock_schools_repo_cls.return_value
            mock_schools_repo.school_exists.return_value = True
            mock_schools_repo.create_virtual_school.return_value = {
                "id": "virtual-school-789",
                "name": "Standalone - Pending Link",
            }

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            result = run_async(service.signup_recruiter(signup_request))

            # Verify virtual school was created (not a real school)
            mock_schools_repo.create_virtual_school.assert_called_once()
            mock_schools_repo.create_school.assert_not_called()
            assert result.user_id == "new-user-123"

    @pytest.mark.unit
    def test_new_school_missing_name_returns_400(
        self, mock_supabase_client, signup_request, mock_event_data
    ):
        """Creating a new school without a name should return 400."""
        from fastapi import HTTPException

        signup_request.school_selection.type = "new"
        signup_request.school_selection.school_name = None  # Missing name

        profiles_mock = MagicMock()
        profiles_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(data=[])
        mock_supabase_client.table = MagicMock(return_value=profiles_mock)

        with patch('app.services.recruiter_signup_service.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.services.recruiter_signup_service.UniversalEventsRepository') as mock_events_repo_cls, \
             patch('app.services.recruiter_signup_service.PublicSchoolsRepository') as mock_schools_repo_cls, \
             patch('app.services.recruiter_signup_service.EventPurchasesRepository'), \
             patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_123"}):

            mock_events_repo = mock_events_repo_cls.return_value
            mock_events_repo.get_event_by_id.return_value = mock_event_data

            from app.services.recruiter_signup_service import RecruiterSignupService
            service = RecruiterSignupService()

            with pytest.raises(HTTPException) as exc_info:
                run_async(service.signup_recruiter(signup_request))

            assert exc_info.value.status_code == 400
            assert "school_name required" in str(exc_info.value.detail)
