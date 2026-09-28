"""
Tests for the team invite flow.

Invites no longer use Supabase's one-time invite email (email security scanners
consumed it before the user clicked). Instead the account is created up front
and our own /magic-link URL is emailed via Resend; the token is only consumed
when the user sets a password.
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.repositories import auth_repository
from app.services import auth_service

pytestmark = pytest.mark.unit

METADATA = {"first_name": "Avery", "school_id": "school-1", "role": ["recruiter"]}


def _client(create_user_error=None, profile_rows=None):
    client = MagicMock()
    if create_user_error:
        client.auth.admin.create_user.side_effect = Exception(create_user_error)
    else:
        client.auth.admin.create_user.return_value = SimpleNamespace(user=SimpleNamespace(id="new-user"))
    table = client.table.return_value
    table.select.return_value.ilike.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=profile_rows or []
    )
    table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"name": "McMurry University"}
    )
    return client


def _send_invite(client, sent=True):
    notifier = MagicMock()
    notifier.send_team_invite_email.return_value = sent
    with patch.object(auth_repository, "create_magic_link_db", return_value="tok123"), \
         patch.object(auth_repository, "get_frontend_url", return_value="https://cardcapture.io"), \
         patch("app.services.notification_service.NotificationService", return_value=notifier):
        result = auth_repository.send_magic_link_email_db(client, "hipps.avery@mcm.edu", "invite", METADATA)
    return result, notifier


def test_invite_sends_our_link_not_supabase_invite():
    client = _client()
    result, notifier = _send_invite(client)

    client.auth.admin.invite_user_by_email.assert_not_called()
    client.auth.admin.create_user.assert_called_once()
    assert "password" not in client.auth.admin.create_user.call_args[0][0]
    notifier.send_team_invite_email.assert_called_once_with(
        "hipps.avery@mcm.edu",
        "https://cardcapture.io/magic-link?token=tok123&type=invite",
        first_name="Avery",
        school_name="McMurry University",
    )
    assert result["success"] is True
    assert result["user_id"] == "new-user"


def test_reinvite_existing_user_uses_their_profile_id():
    client = _client("A user with this email address has already been registered", [{"id": "existing"}])
    result, notifier = _send_invite(client)

    assert result["user_id"] == "existing"
    notifier.send_team_invite_email.assert_called_once()


def test_invite_raises_when_email_fails():
    with pytest.raises(Exception, match="Failed to send invite email"):
        _send_invite(_client(), sent=False)


def test_accepting_invite_sets_password_on_existing_account():
    client = MagicMock()
    client.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": "existing"}])
    )
    client.auth.admin.get_user_by_id.return_value = SimpleNamespace(user=SimpleNamespace(id="existing"))
    magic_link = {"email": "hipps.avery@mcm.edu", "type": "invite", "metadata": METADATA}

    with patch.object(auth_service, "get_supabase_client", return_value=client), \
         patch.object(auth_service, "validate_magic_link_db", return_value=magic_link), \
         patch.object(auth_service, "consume_magic_link_db", return_value=True):
        result = asyncio.run(auth_service.create_user_service({"magic_link_token": "tok123", "password": "Pw!12345"}))

    client.auth.admin.update_user_by_id.assert_called_once_with(
        "existing", {"password": "Pw!12345", "email_confirm": True}
    )
    client.auth.admin.create_user.assert_not_called()
    assert result["user_id"] == "existing"
