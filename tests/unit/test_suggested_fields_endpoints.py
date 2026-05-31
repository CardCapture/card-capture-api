"""
Tests for the suggested-card-fields accept/dismiss endpoints.

Covers the happy path (accept promotes a suggestion into card_fields and drops
it from suggestions; dismiss just drops it) plus the tenant-isolation and
validation guards.
"""
import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

pytestmark = pytest.mark.unit

SCHOOL_ID = "school-1"
SUGGESTION = {"key": "cell_phone", "label": "Phone Number", "field_type": "phone", "sample_value": "830-470-0865"}
CARD_FIELDS = [{"key": "first_name", "label": "First Name", "enabled": True, "required": True, "field_type": "text"}]


def _mock_sb(card_fields, suggestions):
    sb = MagicMock()
    tbl = sb.table.return_value
    sel = tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
    sel.data = {"card_fields": list(card_fields), "suggested_card_fields": list(suggestions)}
    upd = tbl.update.return_value.eq.return_value.execute.return_value
    upd.data = [{"id": SCHOOL_ID}]
    return sb


@pytest.fixture
def auth_app(app):
    from app.core.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"school_id": SCHOOL_ID, "id": "u1"}
    yield app
    app.dependency_overrides.clear()


def test_accept_promotes_field_and_removes_suggestion(client, auth_app, monkeypatch):
    from app.api.routes import schools_routes
    monkeypatch.setattr(schools_routes, "get_supabase_client", lambda: _mock_sb(CARD_FIELDS, [SUGGESTION]))

    resp = client.post(f"/schools/{SCHOOL_ID}/suggested-fields/accept", json={"key": "cell_phone"})
    assert resp.status_code == 200
    body = resp.json()
    promoted = [f for f in body["card_fields"] if f["key"] == "cell_phone"]
    assert promoted and promoted[0]["enabled"] is True and promoted[0]["field_type"] == "phone"
    assert all(s["key"] != "cell_phone" for s in body["suggested_card_fields"])


def test_accept_is_idempotent_when_already_in_card_fields(client, auth_app, monkeypatch):
    from app.api.routes import schools_routes
    already = CARD_FIELDS + [{"key": "cell_phone", "label": "Phone Number", "enabled": True, "required": False, "field_type": "phone"}]
    monkeypatch.setattr(schools_routes, "get_supabase_client", lambda: _mock_sb(already, [SUGGESTION]))

    resp = client.post(f"/schools/{SCHOOL_ID}/suggested-fields/accept", json={"key": "cell_phone"})
    assert resp.status_code == 200
    body = resp.json()
    # not duplicated, and removed from suggestions
    assert sum(1 for f in body["card_fields"] if f["key"] == "cell_phone") == 1
    assert all(s["key"] != "cell_phone" for s in body["suggested_card_fields"])


def test_dismiss_removes_suggestion_without_promoting(client, auth_app, monkeypatch):
    from app.api.routes import schools_routes
    monkeypatch.setattr(schools_routes, "get_supabase_client", lambda: _mock_sb(CARD_FIELDS, [SUGGESTION]))

    resp = client.post(f"/schools/{SCHOOL_ID}/suggested-fields/dismiss", json={"key": "cell_phone"})
    assert resp.status_code == 200
    assert all(s["key"] != "cell_phone" for s in resp.json()["suggested_card_fields"])


def test_accept_requires_key(client, auth_app, monkeypatch):
    from app.api.routes import schools_routes
    monkeypatch.setattr(schools_routes, "get_supabase_client", lambda: _mock_sb(CARD_FIELDS, [SUGGESTION]))
    resp = client.post(f"/schools/{SCHOOL_ID}/suggested-fields/accept", json={})
    assert resp.status_code == 400


def test_accept_denies_other_school(client, app, monkeypatch):
    from app.core.auth import get_current_user
    from app.api.routes import schools_routes
    app.dependency_overrides[get_current_user] = lambda: {"school_id": "other-school", "id": "u1"}
    monkeypatch.setattr(schools_routes, "get_supabase_client", lambda: _mock_sb(CARD_FIELDS, [SUGGESTION]))
    try:
        resp = client.post(f"/schools/{SCHOOL_ID}/suggested-fields/accept", json={"key": "cell_phone"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
