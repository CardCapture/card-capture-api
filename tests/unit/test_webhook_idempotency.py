"""
Unit tests for webhook handler idempotency.

Tests that the Stripe webhook handler:
1. Processes first webhook normally
2. Skips duplicate purchases that are already completed (idempotent)
3. Handles missing metadata gracefully
4. Handles expired checkout sessions

All external services (Supabase, Stripe) are mocked.
"""

import pytest
import sys
import os
import json
import asyncio
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

    def mock_table(name):
        table = MagicMock()
        table.select.return_value = table
        table.insert.return_value = table
        table.update.return_value = table
        table.upsert.return_value = table
        table.delete.return_value = table
        table.eq.return_value = table
        table.in_.return_value = table
        table.limit.return_value = table
        table.single.return_value = table
        table.maybe_single.return_value = table

        result = Mock()
        result.data = []
        result.error = None
        table.execute.return_value = result
        return table

    client.table = mock_table
    return client


@pytest.fixture
def checkout_session():
    """Create a sample completed checkout session dict."""
    return {
        "id": "cs_test_session_123",
        "payment_intent": "pi_test_intent_456",
        "metadata": {
            "user_id": "user-123",
            "school_id": "school-123",
            "universal_event_ids": json.dumps(["ue-event-1"]),
            "signup_type": "recruiter_self_service",
            "event_count": "1",
        },
    }


@pytest.fixture
def pending_purchase():
    """A purchase record in pending state."""
    return {
        "id": "purchase-001",
        "user_id": "user-123",
        "universal_event_id": "ue-event-1",
        "stripe_checkout_session_id": "cs_test_session_123",
        "status": "pending",
        "amount": 1700,
    }


@pytest.fixture
def completed_purchase():
    """A purchase record that has already been completed."""
    return {
        "id": "purchase-001",
        "user_id": "user-123",
        "universal_event_id": "ue-event-1",
        "stripe_checkout_session_id": "cs_test_session_123",
        "status": "completed",
        "amount": 1700,
        "completed_at": "2025-10-15T12:00:00+00:00",
        "event_id": "created-event-001",
    }


@pytest.fixture
def universal_event():
    """Sample universal event data."""
    return {
        "id": "ue-event-1",
        "name": "Fall College Fair 2025",
        "event_date": "2025-10-15",
    }


# =============================================================================
# First Webhook (Normal Processing) Tests
# =============================================================================

class TestWebhookFirstProcessing:
    """Test that the first webhook processes purchases normally."""

    @pytest.mark.unit
    def test_first_webhook_creates_event_and_completes_purchase(
        self, mock_supabase_client, checkout_session, pending_purchase, universal_event
    ):
        """First webhook should create event, mark purchase completed."""
        # Mock events table insert
        events_table = MagicMock()
        events_table.insert.return_value = events_table
        events_table.execute.return_value = Mock(
            data=[{"id": "created-event-001", "name": "Fall College Fair 2025", "school_id": "school-123"}]
        )

        # Mock event_purchases table update
        purchases_table = MagicMock()
        purchases_table.update.return_value = purchases_table
        purchases_table.eq.return_value = purchases_table
        purchases_table.execute.return_value = Mock(data=[{"id": "purchase-001", "status": "completed"}])

        # Mock profiles table (for account linking + emails)
        profiles_table = MagicMock()
        profiles_table.select.return_value = profiles_table
        profiles_table.eq.return_value = profiles_table
        profiles_table.single.return_value = profiles_table
        profiles_table.execute.return_value = Mock(data={
            "id": "user-123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "parent_school_id": None,
            "account_status": "linked",
            "school_id": "school-123",
        })

        def table_router(name):
            if name == "events":
                return events_table
            if name == "event_purchases":
                return purchases_table
            if name == "profiles":
                return profiles_table
            # Default for other tables (schools, admin_invites, etc.)
            default = MagicMock()
            default.select.return_value = default
            default.eq.return_value = default
            default.single.return_value = default
            default.limit.return_value = default
            default.execute.return_value = Mock(data=None)
            return default

        mock_supabase_client.table = MagicMock(side_effect=table_router)

        with patch('app.api.routes.webhooks.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls, \
             patch('app.api.routes.webhooks.UniversalEventsRepository') as mock_events_cls, \
             patch('app.api.routes.webhooks.NotificationService') as mock_notif_cls, \
             patch('app.api.routes.webhooks.notification_service', MagicMock()):

            mock_purchases = mock_purchases_cls.return_value
            mock_purchases.get_purchases_by_session_id.return_value = [pending_purchase]

            mock_events = mock_events_cls.return_value
            mock_events.get_event_by_id.return_value = universal_event

            from app.api.routes.webhooks import handle_checkout_completed
            run_async(handle_checkout_completed(checkout_session))

            # Verify event was inserted
            events_table.insert.assert_called_once()
            insert_data = events_table.insert.call_args[0][0]
            assert insert_data["name"] == "Fall College Fair 2025"
            assert insert_data["school_id"] == "school-123"
            assert insert_data["universal_event_id"] == "ue-event-1"

            # Verify purchase was updated to completed
            purchases_table.update.assert_called_once()
            update_data = purchases_table.update.call_args[0][0]
            assert update_data["status"] == "completed"
            assert "completed_at" in update_data
            assert update_data["stripe_payment_intent_id"] == "pi_test_intent_456"


# =============================================================================
# Duplicate Webhook (Idempotency) Tests
# =============================================================================

class TestWebhookIdempotency:
    """Test that duplicate webhooks with the same session_id are handled idempotently."""

    @pytest.mark.unit
    def test_duplicate_webhook_skips_already_completed_purchase(
        self, mock_supabase_client, checkout_session, completed_purchase, universal_event
    ):
        """When a purchase is already completed, it should be skipped (not duplicated)."""
        # Events table should NOT be called for insert since purchase is already done
        events_table = MagicMock()

        # Profiles table for email/linking
        profiles_table = MagicMock()
        profiles_table.select.return_value = profiles_table
        profiles_table.eq.return_value = profiles_table
        profiles_table.single.return_value = profiles_table
        profiles_table.execute.return_value = Mock(data={
            "id": "user-123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "parent_school_id": None,
            "account_status": "linked",
            "school_id": "school-123",
        })

        def table_router(name):
            if name == "events":
                return events_table
            if name == "profiles":
                return profiles_table
            default = MagicMock()
            default.select.return_value = default
            default.eq.return_value = default
            default.single.return_value = default
            default.limit.return_value = default
            default.execute.return_value = Mock(data=None)
            return default

        mock_supabase_client.table = MagicMock(side_effect=table_router)

        with patch('app.api.routes.webhooks.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls, \
             patch('app.api.routes.webhooks.UniversalEventsRepository') as mock_events_cls, \
             patch('app.api.routes.webhooks.NotificationService') as mock_notif_cls, \
             patch('app.api.routes.webhooks.notification_service', MagicMock()):

            mock_purchases = mock_purchases_cls.return_value
            mock_purchases.get_purchases_by_session_id.return_value = [completed_purchase]

            mock_events = mock_events_cls.return_value
            mock_events.get_event_by_id.return_value = universal_event

            from app.api.routes.webhooks import handle_checkout_completed
            run_async(handle_checkout_completed(checkout_session))

            # The events table should NOT have had an insert call
            # because the purchase was already completed
            events_table.insert.assert_not_called()

    @pytest.mark.unit
    def test_no_purchases_found_returns_silently(
        self, mock_supabase_client, checkout_session
    ):
        """If no purchases found for session, handler should return without error."""
        with patch('app.api.routes.webhooks.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls, \
             patch('app.api.routes.webhooks.UniversalEventsRepository'), \
             patch('app.api.routes.webhooks.notification_service', MagicMock()):

            mock_purchases = mock_purchases_cls.return_value
            mock_purchases.get_purchases_by_session_id.return_value = []

            from app.api.routes.webhooks import handle_checkout_completed
            # Should complete without raising
            run_async(handle_checkout_completed(checkout_session))


# =============================================================================
# Missing/Invalid Metadata Tests
# =============================================================================

class TestWebhookMissingMetadata:
    """Test handling of webhooks with missing or invalid metadata."""

    @pytest.mark.unit
    def test_missing_user_id_returns_silently(self, mock_supabase_client):
        """Checkout session with no user_id in metadata should return without processing."""
        session = {
            "id": "cs_test_no_user",
            "payment_intent": "pi_test",
            "metadata": {
                "school_id": "school-123",
                "universal_event_ids": json.dumps(["ue-1"]),
            },
        }

        with patch('app.api.routes.webhooks.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls, \
             patch('app.api.routes.webhooks.notification_service', MagicMock()):

            mock_purchases = mock_purchases_cls.return_value

            from app.api.routes.webhooks import handle_checkout_completed
            run_async(handle_checkout_completed(session))

            # Should not attempt to fetch purchases
            mock_purchases.get_purchases_by_session_id.assert_not_called()

    @pytest.mark.unit
    def test_missing_event_ids_returns_silently(self, mock_supabase_client):
        """Checkout session with no event IDs should return without processing."""
        session = {
            "id": "cs_test_no_events",
            "payment_intent": "pi_test",
            "metadata": {
                "user_id": "user-123",
                "school_id": "school-123",
                # No universal_event_ids or universal_event_id
            },
        }

        with patch('app.api.routes.webhooks.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls, \
             patch('app.api.routes.webhooks.notification_service', MagicMock()):

            mock_purchases = mock_purchases_cls.return_value

            from app.api.routes.webhooks import handle_checkout_completed
            run_async(handle_checkout_completed(session))

            mock_purchases.get_purchases_by_session_id.assert_not_called()

    @pytest.mark.unit
    def test_backward_compat_single_event_id(
        self, mock_supabase_client, pending_purchase, universal_event
    ):
        """Checkout session with old single universal_event_id format should still work."""
        session = {
            "id": "cs_test_old_format",
            "payment_intent": "pi_test",
            "metadata": {
                "user_id": "user-123",
                "school_id": "school-123",
                "universal_event_id": "ue-event-1",  # Old format: single ID
                "signup_type": "recruiter_self_service",
            },
        }

        events_table = MagicMock()
        events_table.insert.return_value = events_table
        events_table.execute.return_value = Mock(
            data=[{"id": "created-event-001", "name": "Fall College Fair 2025"}]
        )

        purchases_table = MagicMock()
        purchases_table.update.return_value = purchases_table
        purchases_table.eq.return_value = purchases_table
        purchases_table.execute.return_value = Mock(data=[{"id": "purchase-001"}])

        profiles_table = MagicMock()
        profiles_table.select.return_value = profiles_table
        profiles_table.eq.return_value = profiles_table
        profiles_table.single.return_value = profiles_table
        profiles_table.execute.return_value = Mock(data={
            "id": "user-123", "email": "test@example.com",
            "first_name": "Test", "last_name": "User",
            "parent_school_id": None, "account_status": "linked",
            "school_id": "school-123",
        })

        def table_router(name):
            if name == "events":
                return events_table
            if name == "event_purchases":
                return purchases_table
            if name == "profiles":
                return profiles_table
            default = MagicMock()
            default.select.return_value = default
            default.eq.return_value = default
            default.single.return_value = default
            default.limit.return_value = default
            default.execute.return_value = Mock(data=None)
            return default

        mock_supabase_client.table = MagicMock(side_effect=table_router)

        with patch('app.api.routes.webhooks.get_supabase_client', return_value=mock_supabase_client), \
             patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls, \
             patch('app.api.routes.webhooks.UniversalEventsRepository') as mock_events_cls, \
             patch('app.api.routes.webhooks.NotificationService') as mock_notif_cls, \
             patch('app.api.routes.webhooks.notification_service', MagicMock()):

            mock_purchases = mock_purchases_cls.return_value
            mock_purchases.get_purchases_by_session_id.return_value = [pending_purchase]

            mock_events = mock_events_cls.return_value
            mock_events.get_event_by_id.return_value = universal_event

            from app.api.routes.webhooks import handle_checkout_completed
            run_async(handle_checkout_completed(session))

            # Should still process successfully
            events_table.insert.assert_called_once()


# =============================================================================
# Checkout Expired Tests
# =============================================================================

class TestCheckoutExpired:
    """Test handling of expired/cancelled checkout sessions."""

    @pytest.mark.unit
    def test_expired_checkout_marks_pending_purchases_as_failed(self):
        """Expired checkout should mark all pending purchases as failed."""
        session = {"id": "cs_test_expired_123"}

        with patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls:
            mock_purchases = mock_purchases_cls.return_value
            mock_purchases.get_purchases_by_session_id.return_value = [
                {"id": "purchase-001", "status": "pending"},
                {"id": "purchase-002", "status": "pending"},
            ]

            from app.api.routes.webhooks import handle_checkout_expired
            run_async(handle_checkout_expired(session))

            assert mock_purchases.fail_purchase.call_count == 2
            mock_purchases.fail_purchase.assert_any_call("purchase-001")
            mock_purchases.fail_purchase.assert_any_call("purchase-002")

    @pytest.mark.unit
    def test_expired_checkout_skips_already_completed_purchases(self):
        """Expired checkout should not touch already-completed purchases."""
        session = {"id": "cs_test_expired_mixed"}

        with patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls:
            mock_purchases = mock_purchases_cls.return_value
            mock_purchases.get_purchases_by_session_id.return_value = [
                {"id": "purchase-001", "status": "completed"},  # Already done
                {"id": "purchase-002", "status": "pending"},    # Should be failed
            ]

            from app.api.routes.webhooks import handle_checkout_expired
            run_async(handle_checkout_expired(session))

            # Only the pending purchase should be failed
            mock_purchases.fail_purchase.assert_called_once_with("purchase-002")

    @pytest.mark.unit
    def test_expired_checkout_no_purchases(self):
        """Expired checkout with no purchases should complete without error."""
        session = {"id": "cs_test_expired_empty"}

        with patch('app.api.routes.webhooks.EventPurchasesRepository') as mock_purchases_cls:
            mock_purchases = mock_purchases_cls.return_value
            mock_purchases.get_purchases_by_session_id.return_value = []

            from app.api.routes.webhooks import handle_checkout_expired
            run_async(handle_checkout_expired(session))

            mock_purchases.fail_purchase.assert_not_called()
