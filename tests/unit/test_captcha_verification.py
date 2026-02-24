"""
Unit tests for CAPTCHA verification on public endpoints.

Tests that recruiter signup and event submission endpoints
properly call captcha_service.verify and handle failures.
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

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
from fastapi import HTTPException


def run_async(coro):
    """Helper to run async functions synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# Recruiter Signup CAPTCHA Tests
# =============================================================================

class TestRecruiterSignupCaptcha:
    """Tests for CAPTCHA verification on the recruiter signup endpoint."""

    def _make_signup_request(self, captcha_token=None):
        from app.models.recruiter_signup import RecruiterSignupRequest
        return RecruiterSignupRequest(
            email="test@example.com",
            password="securepassword123",
            first_name="Test",
            last_name="User",
            school_selection={
                "type": "new",
                "school_name": "Test School",
            },
            universal_event_ids=["event-1"],
            captcha_token=captcha_token,
        )

    def _make_mock_request(self):
        mock_req = MagicMock()
        mock_req.client.host = "127.0.0.1"
        return mock_req

    @patch("app.api.routes.public.captcha_service")
    @patch("app.api.routes.public.RecruiterSignupService")
    def test_rejects_failed_captcha_verification(self, mock_service_cls, mock_captcha):
        """Recruiter signup rejects request when captcha verification fails."""
        from app.api.routes.public import recruiter_signup

        mock_captcha.verify = AsyncMock(
            side_effect=HTTPException(status_code=400, detail="CAPTCHA verification failed")
        )

        request_body = self._make_signup_request(captcha_token="bad-token")
        mock_request = self._make_mock_request()

        with pytest.raises(HTTPException) as exc_info:
            run_async(recruiter_signup(request_body, mock_request))

        assert exc_info.value.status_code == 400
        assert "CAPTCHA" in exc_info.value.detail

    @patch("app.api.routes.public.captcha_service")
    @patch("app.api.routes.public.RecruiterSignupService")
    def test_succeeds_with_valid_captcha_token(self, mock_service_cls, mock_captcha):
        """Recruiter signup succeeds when valid captcha_token is provided."""
        from app.api.routes.public import recruiter_signup

        mock_captcha.verify = AsyncMock(return_value=True)

        mock_service = MagicMock()
        mock_service.signup_recruiter = AsyncMock(return_value=MagicMock(
            user_id="user-1",
            checkout_session_id="cs_test",
            checkout_url="https://checkout.stripe.com/test",
            access_token="token",
            refresh_token="refresh",
        ))
        mock_service_cls.return_value = mock_service

        request_body = self._make_signup_request(captcha_token="valid-token")
        mock_request = self._make_mock_request()

        result = run_async(recruiter_signup(request_body, mock_request))
        assert result.user_id == "user-1"
        mock_captcha.verify.assert_awaited_once_with("valid-token", "127.0.0.1", required=False)

    @patch("app.api.routes.public.captcha_service")
    @patch("app.api.routes.public.RecruiterSignupService")
    def test_passes_none_token_in_dev_mode(self, mock_service_cls, mock_captcha):
        """Recruiter signup passes None token to captcha_service (noop allows it)."""
        from app.api.routes.public import recruiter_signup

        mock_captcha.verify = AsyncMock(return_value=True)

        mock_service = MagicMock()
        mock_service.signup_recruiter = AsyncMock(return_value=MagicMock(
            user_id="user-1",
            checkout_session_id="cs_test",
            checkout_url="https://checkout.stripe.com/test",
            access_token="token",
            refresh_token="refresh",
        ))
        mock_service_cls.return_value = mock_service

        request_body = self._make_signup_request(captcha_token=None)
        mock_request = self._make_mock_request()

        result = run_async(recruiter_signup(request_body, mock_request))
        assert result.user_id == "user-1"
        mock_captcha.verify.assert_awaited_once_with(None, "127.0.0.1", required=False)


# =============================================================================
# Event Submission CAPTCHA Tests
# =============================================================================

class TestEventSubmissionCaptcha:
    """Tests for CAPTCHA verification on the event submission endpoint."""

    def _make_event_request(self, captcha_token=None):
        from app.models.universal_event_submission import UniversalEventSubmissionRequest
        return UniversalEventSubmissionRequest(
            name="Test College Fair",
            event_date="2026-06-15",
            contact_name="Jane Doe",
            contact_email="jane@example.com",
            contact_phone="5551234567",
            captcha_token=captcha_token,
        )

    def _make_mock_request(self):
        mock_req = MagicMock()
        mock_req.client.host = "127.0.0.1"
        return mock_req

    @patch("app.api.routes.public.captcha_service")
    def test_rejects_failed_captcha_verification(self, mock_captcha):
        """Event submission rejects request when captcha verification fails."""
        from app.api.routes.public import submit_universal_event

        mock_captcha.verify = AsyncMock(
            side_effect=HTTPException(status_code=400, detail="CAPTCHA verification failed")
        )

        request_body = self._make_event_request(captcha_token="bad-token")
        mock_request = self._make_mock_request()

        with pytest.raises(HTTPException) as exc_info:
            run_async(submit_universal_event(request_body, mock_request))

        assert exc_info.value.status_code == 400
        assert "CAPTCHA" in exc_info.value.detail

    @patch("app.api.routes.public.captcha_service")
    def test_succeeds_with_valid_captcha_token(self, mock_captcha):
        """Event submission succeeds when valid captcha_token is provided."""
        from app.api.routes.public import submit_universal_event

        mock_captcha.verify = AsyncMock(return_value=True)

        mock_repo = MagicMock()
        mock_repo.create_event.return_value = {"id": "event-123"}

        mock_notif = MagicMock()

        request_body = self._make_event_request(captcha_token="valid-token")
        mock_request = self._make_mock_request()

        with patch("app.repositories.universal_events_repository.UniversalEventsRepository", return_value=mock_repo), \
             patch("app.services.notification_service.NotificationService", return_value=mock_notif):
            result = run_async(submit_universal_event(request_body, mock_request))

        assert result["success"] is True
        assert result["event_id"] == "event-123"
        mock_captcha.verify.assert_awaited_once_with("valid-token", "127.0.0.1", required=False)


# =============================================================================
# Noop Provider Tests
# =============================================================================

class TestNoopCaptchaProvider:
    """Tests that endpoints work with noop provider (dev mode)."""

    def test_noop_provider_auto_approves(self):
        """CaptchaService with noop provider accepts any token (including None)."""
        from app.core.captcha import CaptchaService

        with patch.dict(os.environ, {"CAPTCHA_PROVIDER": "noop"}):
            CaptchaService._instance = None
            CaptchaService._provider = None
            service = CaptchaService()

            # None token with required=False passes through
            result = run_async(service.verify(None, "127.0.0.1", required=False))
            assert result is True

            # Any token with noop provider passes
            result = run_async(service.verify("any-token", "127.0.0.1", required=False))
            assert result is True

        CaptchaService._instance = None
        CaptchaService._provider = None

    def test_noop_provider_rejects_missing_token_when_required(self):
        """With required=True, missing token raises 400 even with noop provider."""
        from app.core.captcha import CaptchaService

        with patch.dict(os.environ, {"CAPTCHA_PROVIDER": "noop"}):
            CaptchaService._instance = None
            CaptchaService._provider = None
            service = CaptchaService()

            with pytest.raises(HTTPException) as exc_info:
                run_async(service.verify(None, "127.0.0.1", required=True))
            assert exc_info.value.status_code == 400

        CaptchaService._instance = None
        CaptchaService._provider = None
