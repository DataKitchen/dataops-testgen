"""Tests for testgen.api.deps — FastAPI authentication dependencies and db_session."""

import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest

from testgen.api.deps import db_session, get_authorized_user

JWT_KEY = base64.b64encode(b"test-secret-key-for-jwt-signing!").decode("ascii")


def _make_token(username="testuser", exp_seconds=86400 * 30):
    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = {
        "username": username,
        "exp": (datetime.now(UTC) + timedelta(seconds=exp_seconds)).timestamp(),
    }
    return jwt.encode(payload, key, algorithm="HS256")


def _make_credentials(token):
    creds = MagicMock()
    creds.credentials = token
    return creds


# --- get_authorized_user ---


@patch("testgen.common.auth.settings")
@patch("testgen.api.deps.get_current_session")
def test_get_authorized_user_returns_user_for_valid_token(mock_get_session, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_user = MagicMock()
    mock_user.username = "testuser"
    mock_session.query.return_value.filter.return_value.first.return_value = mock_user
    # No OAuth2Token record — not revoked
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    token = _make_token("testuser")
    result = get_authorized_user(_make_credentials(token))

    assert result is mock_user


@patch("testgen.common.auth.settings")
@patch("testgen.api.deps.get_current_session")
def test_get_authorized_user_raises_401_for_expired_token(mock_get_session, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY

    token = _make_token("testuser", exp_seconds=-3600)
    creds = _make_credentials(token)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_user(creds)
    assert exc_info.value.status_code == 401


@patch("testgen.common.auth.settings")
def test_get_authorized_user_raises_401_for_invalid_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    creds = _make_credentials("not.a.valid.token")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_user(creds)
    assert exc_info.value.status_code == 401


@patch("testgen.common.auth.settings")
@patch("testgen.api.deps.get_current_session")
def test_get_authorized_user_raises_401_when_user_not_found(mock_get_session, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_session.query.return_value.filter.return_value.first.return_value = None

    token = _make_token("nonexistent_user")
    creds = _make_credentials(token)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_user(creds)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired token"


@patch("testgen.common.auth.settings")
@patch("testgen.api.deps.get_current_session")
def test_get_authorized_user_rejects_revoked_token(mock_get_session, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_user = MagicMock()
    mock_user.username = "testuser"
    mock_session.query.return_value.filter.return_value.first.return_value = mock_user

    # Token record exists and is revoked
    mock_token_record = MagicMock()
    mock_token_record.access_token_revoked_at = 1700000000
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_token_record

    token = _make_token("testuser")
    creds = _make_credentials(token)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_user(creds)
    assert exc_info.value.status_code == 401


# --- db_session ---


@patch("testgen.api.deps._current_session_wrapper")
@patch("testgen.api.deps.Session")
def test_db_session_commits_on_success(mock_session_cls, mock_wrapper):
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    gen = db_session()
    session = next(gen)

    assert session is mock_session
    mock_wrapper.__setattr__("value", mock_session)

    # Exhaust the generator (simulates successful request completion)
    with pytest.raises(StopIteration):
        next(gen)

    mock_session.commit.assert_called_once()


@patch("testgen.api.deps._current_session_wrapper")
@patch("testgen.api.deps.Session")
def test_db_session_rolls_back_on_exception(mock_session_cls, mock_wrapper):
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    gen = db_session()
    next(gen)

    # Simulate an exception thrown into the generator
    with pytest.raises(ValueError):
        gen.throw(ValueError("boom"))

    mock_session.rollback.assert_called_once()
    mock_session.commit.assert_not_called()


# --- has_project_permission ---

DEPS_MODULE = "testgen.api.deps"


@patch(f"{DEPS_MODULE}.PluginHook")
@patch(f"{DEPS_MODULE}.ProjectMembership")
def test_has_permission_returns_true_when_role_has_permission(mock_pm, mock_hook):
    from testgen.api.deps import has_project_permission

    user = MagicMock()
    mock_pm.get_user_role_in_project.return_value = "data_quality"
    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = ["admin", "data_quality"]

    assert has_project_permission(user, "project_a", "edit") is True
    mock_pm.get_user_role_in_project.assert_called_once_with(user.id, "project_a")


@patch(f"{DEPS_MODULE}.PluginHook")
@patch(f"{DEPS_MODULE}.ProjectMembership")
def test_has_permission_returns_false_when_role_lacks_permission(mock_pm, mock_hook):
    from testgen.api.deps import has_project_permission

    user = MagicMock()
    mock_pm.get_user_role_in_project.return_value = "business"
    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = ["admin", "data_quality"]

    assert has_project_permission(user, "project_a", "edit") is False


@patch(f"{DEPS_MODULE}.ProjectMembership")
def test_has_permission_returns_false_when_no_membership(mock_pm):
    from testgen.api.deps import has_project_permission

    user = MagicMock()
    mock_pm.get_user_role_in_project.return_value = None

    assert has_project_permission(user, "project_a", "edit") is False


@patch(f"{DEPS_MODULE}.ProjectMembership")
def test_has_permission_checks_membership_even_for_global_admin(mock_pm):
    from testgen.api.deps import has_project_permission

    # is_global_admin only grants access to the admin area, not project-level RBAC bypass
    user = MagicMock()
    user.is_global_admin = True
    mock_pm.get_user_role_in_project.return_value = None

    assert has_project_permission(user, "project_a", "edit") is False
