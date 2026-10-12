"""Tests for testgen.api.deps — FastAPI authentication dependencies and db_session."""

import asyncio
import base64
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call, patch

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from pydantic import BaseModel

from testgen.api.deps import db_session, fields_to_change, get_authorized_user
from testgen.common.models import get_current_session

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


def _set_scalars_results(mock_session, *results):
    """Configure mock_session.scalars to return successive `.first()` values per call."""
    mock_session.scalars.side_effect = [
        MagicMock(first=MagicMock(return_value=r)) for r in results
    ]


@patch("testgen.common.auth.settings")
@patch("testgen.api.deps.get_current_session")
def test_get_authorized_user_returns_user_for_valid_token(mock_get_session, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_user = MagicMock()
    mock_user.username = "testuser"
    # authorize_token: 1st scalars() = User lookup, 2nd = OAuth2Token revocation lookup
    _set_scalars_results(mock_session, mock_user, None)

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
    # User lookup returns None — revocation lookup never reached
    _set_scalars_results(mock_session, None)

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

    # Token record exists and is revoked
    mock_token_record = MagicMock()
    mock_token_record.access_token_revoked_at = 1700000000
    _set_scalars_results(mock_session, mock_user, mock_token_record)

    token = _make_token("testuser")
    creds = _make_credentials(token)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_user(creds)
    assert exc_info.value.status_code == 401


# --- db_session ---


def _run_db_session(session, raise_inside: Exception | None = None):
    """Drive the dependency the way FastAPI does, returning the session it yielded."""

    async def drive():
        gen = db_session()
        yielded = await gen.__anext__()
        assert get_current_session() is yielded
        if raise_inside:
            await gen.athrow(raise_inside)
        else:
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
        return yielded

    with patch("testgen.api.deps.Session", return_value=session):
        return asyncio.run(drive())


def test_db_session_commits_and_closes_on_success():
    session = MagicMock()

    assert _run_db_session(session) is session

    assert session.method_calls == [call.commit(), call.close()]
    assert get_current_session() is None


def test_db_session_rolls_back_and_closes_on_exception():
    session = MagicMock()

    with pytest.raises(ValueError, match="boom"):
        _run_db_session(session, raise_inside=ValueError("boom"))

    assert session.method_calls == [call.rollback(), call.close()]


def test_every_request_sees_its_own_open_session_under_concurrency():
    """FastAPI runs sync dependencies and endpoints on worker threads other than the one that set the
    session up, so a session stored per thread reaches the wrong request, or none."""

    class FakeSession:
        def __init__(self):
            self.closed = False

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    def seen_by(name):
        def dependency():
            current = get_current_session()
            return None if current is None or current.closed else id(current)

        dependency.__name__ = name
        return dependency

    app = FastAPI()
    auth_dependency = seen_by("auth")

    @app.get("/{n}", dependencies=[Depends(db_session, scope="function")])
    def endpoint(n: int, from_dependency=Depends(auth_dependency)):  # noqa: B008
        time.sleep(0.002)
        current = get_current_session()
        return {"endpoint": None if current is None or current.closed else id(current), "dependency": from_dependency}

    async def burst():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await asyncio.gather(*(client.get(f"/{n}") for n in range(200)))

    with patch("testgen.api.deps.Session", FakeSession):
        responses = asyncio.run(burst())

    seen = [response.json() for response in responses]
    assert all(entry["endpoint"] is not None and entry["endpoint"] == entry["dependency"] for entry in seen)
    assert len({entry["endpoint"] for entry in seen}) == len(seen)


def test_every_router_commits_before_it_responds():
    from testgen import api
    from testgen.api.oauth import routes as oauth_routes

    routes = [
        route for route in (*api.router.routes, *oauth_routes.router.routes) if isinstance(route, APIRoute)
    ]
    declared = [
        dependency.scope
        for route in routes
        for dependency in route.dependencies
        if dependency.dependency is db_session
    ]
    assert len(declared) == len(routes)
    assert set(declared) == {"function"}


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


class _Patch(BaseModel):
    type: str = "email"
    name: str | None = None
    note: str | None = None


def test_fields_to_change_returns_what_the_body_sends():
    assert fields_to_change(_Patch.model_validate({"name": "Team"})) == {"name": "Team"}


@pytest.mark.parametrize(("body", "code"), [
    ({}, "no_fields"),
    ({"type": "email"}, "no_fields"),
    ({"name": None}, "null_field"),
])
def test_fields_to_change_refuses_an_empty_or_null_body(body, code):
    with pytest.raises(HTTPException) as excinfo:
        fields_to_change(_Patch.model_validate(body), ignore=("type",))

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["errors"][0]["code"] == code
