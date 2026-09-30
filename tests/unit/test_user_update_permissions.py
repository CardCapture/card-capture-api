"""
Tests for who may update a user's profile and roles (PUT /users/{user_id}).

- SuperAdmins can update anyone
- School admins can update users in their own school, including roles
- Other users can edit their own name but not their roles
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.api.routes import users_routes
from app.models.user import UserUpdateRequest

pytestmark = pytest.mark.unit

ADMIN = {"id": "admin-1", "role": ["admin"], "school_id": "school-a"}
RECRUITER = {"id": "rec-1", "role": ["recruiter"], "school_id": "school-a"}
SUPERADMIN = {"id": "super-1", "role": ["admin"], "school_id": None}


def _call(caller, target_id, target_profile, role):
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        SimpleNamespace(data=target_profile)
    )
    update = UserUpdateRequest(first_name="Pat", last_name="Lee", role=role)
    controller = AsyncMock(return_value={"ok": True})
    with patch.object(users_routes, "get_supabase_client", return_value=client), \
         patch.object(users_routes, "update_user_controller", controller):
        result = asyncio.run(users_routes.update_user(target_id, update, user=caller))
    return result, controller


def test_admin_can_change_roles_for_teammate():
    result, controller = _call(ADMIN, "rec-1", {"school_id": "school-a", "role": ["recruiter"]}, ["recruiter", "reviewer"])
    controller.assert_awaited_once()
    assert result == {"ok": True}


def test_admin_cannot_update_user_in_another_school():
    with pytest.raises(HTTPException) as exc:
        _call(ADMIN, "other-1", {"school_id": "school-b", "role": ["recruiter"]}, ["admin"])
    assert exc.value.status_code == 403


def test_user_can_edit_own_name_without_changing_roles():
    _, controller = _call(RECRUITER, "rec-1", {"school_id": "school-a", "role": ["recruiter"]}, ["recruiter"])
    controller.assert_awaited_once()


def test_user_cannot_change_own_roles():
    with pytest.raises(HTTPException) as exc:
        _call(RECRUITER, "rec-1", {"school_id": "school-a", "role": ["recruiter"]}, ["recruiter", "admin"])
    assert exc.value.status_code == 403


def test_non_admin_cannot_update_teammate():
    with pytest.raises(HTTPException) as exc:
        _call(RECRUITER, "rec-2", {"school_id": "school-a", "role": ["reviewer"]}, ["reviewer"])
    assert exc.value.status_code == 403


def test_superadmin_can_update_anyone():
    _, controller = _call(SUPERADMIN, "other-1", None, ["admin"])
    controller.assert_awaited_once()
