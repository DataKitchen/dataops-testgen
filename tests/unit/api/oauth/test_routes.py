"""Tests for testgen.api.oauth.routes — OAuth endpoints and helpers."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from testgen.api.deps import db_session
from testgen.api.oauth.routes import (
    OAUTH_SESSION_COOKIE,
    _build_oauth2_request,
    _get_existing_user,
    _security_headers,
    router,
)


def _noop_db_session():
    yield None


def _make_client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[db_session] = _noop_db_session
    app.include_router(router)
    return TestClient(app)


# --- _build_oauth2_request ---


def test_build_oauth2_request_title_cases_headers():
    request = MagicMock()
    request.method = "POST"
    request.url = "http://localhost/oauth/token"
    request.headers = {"content-type": "application/json", "authorization": "Bearer abc"}

    result = _build_oauth2_request(request, {"grant_type": "client_credentials"})

    assert result.headers["Content-Type"] == "application/json"
    assert result.headers["Authorization"] == "Bearer abc"


def test_build_oauth2_request_sets_body_and_payload():
    request = MagicMock()
    request.method = "POST"
    request.url = "http://localhost/oauth/token"
    request.headers = {}
    body = {"grant_type": "authorization_code", "code": "abc"}

    result = _build_oauth2_request(request, body)

    assert result.form == body
    assert result.payload.data == body


def test_build_oauth2_request_defaults_to_empty_body():
    request = MagicMock()
    request.method = "GET"
    request.url = "http://localhost/oauth/authorize"
    request.headers = {}

    result = _build_oauth2_request(request)

    assert result.payload.data == {}


# --- _get_existing_user ---


@patch("testgen.api.oauth.routes.User")
@patch("testgen.api.oauth.routes.decode_jwt_token")
def test_get_existing_user_checks_oauth_cookie(mock_decode, mock_user_cls):
    mock_decode.return_value = {"username": "alice"}
    mock_user = MagicMock()
    mock_user_cls.get.return_value = mock_user

    request = MagicMock()
    request.cookies = {OAUTH_SESSION_COOKIE: "valid_token"}

    result = _get_existing_user(request)

    assert result is mock_user
    mock_decode.assert_called_once_with("valid_token")
    mock_user_cls.get.assert_called_once_with("alice")


@patch("testgen.api.oauth.routes.decode_jwt_token")
def test_get_existing_user_ignores_streamlit_cookie(mock_decode):
    """_get_existing_user should NOT check dk_cookie_name (Streamlit's cookie)."""
    request = MagicMock()
    request.cookies = {"dk_cookie_name": "streamlit_token"}

    result = _get_existing_user(request)

    assert result is None
    mock_decode.assert_not_called()


@patch("testgen.api.oauth.routes.decode_jwt_token")
def test_get_existing_user_returns_none_on_invalid_token(mock_decode):
    mock_decode.side_effect = Exception("invalid")

    request = MagicMock()
    request.cookies = {OAUTH_SESSION_COOKIE: "bad_token"}

    result = _get_existing_user(request)

    assert result is None


def test_get_existing_user_returns_none_when_no_cookies():
    request = MagicMock()
    request.cookies = {}

    result = _get_existing_user(request)

    assert result is None


# --- _get_client_name ---


@patch("testgen.api.oauth.routes.get_current_session")
def test_get_client_name_returns_name_from_metadata(mock_get_session):
    from testgen.api.oauth.routes import _get_client_name

    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_client = MagicMock()
    mock_client.client_metadata = {"client_name": "My App"}
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_client

    assert _get_client_name("client123") == "My App"


@patch("testgen.api.oauth.routes.get_current_session")
def test_get_client_name_returns_empty_when_not_found(mock_get_session):
    from testgen.api.oauth.routes import _get_client_name

    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    assert _get_client_name("nonexistent") == ""


# --- _security_headers ---


def test_security_headers_returns_expected_headers():
    headers = _security_headers()

    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in headers["Content-Security-Policy"]


# --- _issue_auth_code ---


@patch("testgen.api.oauth.routes._server")
@patch("testgen.api.oauth.routes.create_jwt_token")
def test_issue_auth_code_returns_redirect_with_cookie(mock_jwt, mock_server):
    from testgen.api.oauth.routes import _issue_auth_code

    mock_server.create_authorization_response.return_value = (
        302, "", [("Location", "http://localhost/callback?code=ABC")]
    )
    mock_jwt.return_value = "session_jwt"

    request = MagicMock()
    request.method = "GET"
    request.url = "http://localhost/oauth/authorize"
    request.headers = {}
    user = MagicMock()
    user.username = "alice"

    response = _issue_auth_code(request, user, {"client_id": "c1", "response_type": "code"})

    assert response.status_code == 302
    assert "callback?code=ABC" in response.headers["location"]
    cookie_header = response.headers.get("set-cookie", "")
    assert OAUTH_SESSION_COOKIE in cookie_header


@patch("testgen.api.oauth.routes._server")
def test_issue_auth_code_returns_json_on_non_302(mock_server):
    from testgen.api.oauth.routes import _issue_auth_code

    mock_server.create_authorization_response.return_value = (
        400, {"error": "invalid_request"}, [("X-Custom", "val")]
    )

    request = MagicMock()
    request.method = "GET"
    request.url = "http://localhost/oauth/authorize"
    request.headers = {}

    response = _issue_auth_code(request, MagicMock(), {"client_id": "c1"})

    assert response.status_code == 400
    assert response.body == b'{"error":"invalid_request"}'


# --- GET /oauth/logout ---


def test_logout_returns_302_redirect():
    client = _make_client()
    resp = client.get("/oauth/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_logout_clears_oauth_session_cookie():
    client = _make_client()
    resp = client.get("/oauth/logout", follow_redirects=False)
    set_cookie = resp.headers["set-cookie"]
    assert OAUTH_SESSION_COOKIE in set_cookie
    assert "Max-Age=0" in set_cookie


def test_logout_redirects_to_custom_uri():
    client = _make_client()
    resp = client.get("/oauth/logout?redirect_uri=/custom", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/custom"


def test_logout_rejects_external_redirect():
    client = _make_client()
    resp = client.get(
        "/oauth/logout?redirect_uri=https://evil.com/phish",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_logout_allows_relative_path():
    client = _make_client()
    resp = client.get("/oauth/logout?redirect_uri=/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


# --- cookie secure flag ---


@patch("testgen.api.oauth.routes._server")
@patch("testgen.api.oauth.routes.create_jwt_token")
@patch("testgen.api.oauth.routes.settings")
def test_issue_auth_code_sets_secure_cookie_when_https(mock_settings, mock_jwt, mock_server):
    from testgen.api.oauth.routes import _issue_auth_code

    mock_settings.BASE_URL = "https://testgen.example.com"
    mock_server.create_authorization_response.return_value = (
        302, "", [("Location", "http://localhost/callback?code=ABC")]
    )
    mock_jwt.return_value = "session_jwt"

    request = MagicMock()
    request.method = "GET"
    request.url = "https://testgen.example.com/oauth/authorize"
    request.headers = {}
    user = MagicMock()
    user.username = "alice"

    response = _issue_auth_code(request, user, {"client_id": "c1", "response_type": "code"})

    cookie_header = response.headers.get("set-cookie", "")
    assert "Secure" in cookie_header


@patch("testgen.api.oauth.routes._server")
@patch("testgen.api.oauth.routes.create_jwt_token")
@patch("testgen.api.oauth.routes.settings")
def test_issue_auth_code_no_secure_cookie_when_http(mock_settings, mock_jwt, mock_server):
    from testgen.api.oauth.routes import _issue_auth_code

    mock_settings.BASE_URL = "http://localhost:8530"
    mock_server.create_authorization_response.return_value = (
        302, "", [("Location", "http://localhost/callback?code=ABC")]
    )
    mock_jwt.return_value = "session_jwt"

    request = MagicMock()
    request.method = "GET"
    request.url = "http://localhost:8530/oauth/authorize"
    request.headers = {}
    user = MagicMock()
    user.username = "alice"

    response = _issue_auth_code(request, user, {"client_id": "c1", "response_type": "code"})

    cookie_header = response.headers.get("set-cookie", "")
    assert "Secure" not in cookie_header


# --- GET /oauth/authorize ---


@patch("testgen.api.oauth.routes._get_client_name", return_value="Test App")
@patch("testgen.api.oauth.routes._get_existing_user", return_value=None)
def test_authorize_get_shows_login_page(mock_existing, mock_client_name):
    client = _make_client()
    resp = client.get(
        "/oauth/authorize?response_type=code&client_id=abc123"
        "&redirect_uri=http://localhost/cb&code_challenge=xyz&code_challenge_method=S256",
    )

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "abc123" in resp.text
    assert "X-Frame-Options" in resp.headers


@patch("testgen.api.oauth.routes._issue_auth_code")
@patch("testgen.api.oauth.routes._get_existing_user")
def test_authorize_get_skips_login_for_existing_user(mock_existing, mock_issue):
    from fastapi.responses import RedirectResponse

    mock_user = MagicMock()
    mock_existing.return_value = mock_user
    mock_issue.return_value = RedirectResponse(url="http://localhost/cb?code=ABC", status_code=302)

    client = _make_client()
    resp = client.get(
        "/oauth/authorize?response_type=code&client_id=abc123",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    mock_issue.assert_called_once()
    assert mock_issue.call_args[0][1] is mock_user


# --- POST /oauth/authorize ---


@patch("testgen.api.oauth.routes._issue_auth_code")
@patch("testgen.api.oauth.routes.verify_password", return_value=True)
@patch("testgen.api.oauth.routes.User")
def test_authorize_post_valid_credentials_issues_code(mock_user_cls, mock_verify, mock_issue):
    from fastapi.responses import RedirectResponse

    mock_user = MagicMock()
    mock_user.password = "hashed"  # noqa: S105
    mock_user_cls.get.return_value = mock_user
    mock_issue.return_value = RedirectResponse(url="http://localhost/cb?code=ABC", status_code=302)

    client = _make_client()
    resp = client.post(
        "/oauth/authorize",
        data={
            "username": "alice",
            "password": "secret",
            "client_id": "abc123",
            "redirect_uri": "http://localhost/cb",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    mock_user_cls.get.assert_called_once_with("alice")
    mock_verify.assert_called_once_with("secret", "hashed")
    mock_issue.assert_called_once()


@patch("testgen.api.oauth.routes._get_client_name", return_value="")
@patch("testgen.api.oauth.routes.verify_password", return_value=False)
@patch("testgen.api.oauth.routes.User")
def test_authorize_post_invalid_password_returns_401(mock_user_cls, mock_verify, mock_client_name):
    mock_user = MagicMock()
    mock_user.password = "hashed"  # noqa: S105
    mock_user_cls.get.return_value = mock_user

    client = _make_client()
    resp = client.post(
        "/oauth/authorize",
        data={"username": "alice", "password": "wrong", "client_id": "abc123"},
    )

    assert resp.status_code == 401
    assert "Invalid username or password" in resp.text


@patch("testgen.api.oauth.routes._get_client_name", return_value="")
@patch("testgen.api.oauth.routes.User")
def test_authorize_post_unknown_user_returns_401(mock_user_cls, mock_client_name):
    mock_user_cls.get.return_value = None

    client = _make_client()
    resp = client.post(
        "/oauth/authorize",
        data={"username": "nobody", "password": "x", "client_id": "abc123"},
    )

    assert resp.status_code == 401
    assert "Invalid username or password" in resp.text


# --- POST /oauth/token ---


@patch("testgen.api.oauth.routes._server")
def test_token_endpoint_delegates_to_server(mock_server):
    mock_server.create_token_response.return_value = (
        200,
        {"access_token": "tok", "token_type": "Bearer"},
        [("Cache-Control", "no-store")],
    )

    client = _make_client()
    resp = client.post("/oauth/token", data={"grant_type": "client_credentials"})

    assert resp.status_code == 200
    assert resp.json()["access_token"] == "tok"  # noqa: S105
    mock_server.create_token_response.assert_called_once()


# --- POST /oauth/revoke ---


@patch("testgen.api.oauth.routes._server")
def test_revoke_endpoint_delegates_to_server(mock_server):
    mock_server.create_endpoint_response.return_value = (200, None, [])

    client = _make_client()
    resp = client.post("/oauth/revoke", data={"token": "some_token"})

    assert resp.status_code == 200
    mock_server.create_endpoint_response.assert_called_once()
    assert mock_server.create_endpoint_response.call_args[0][0] == "revocation"


# --- POST /oauth/register ---


@patch("testgen.api.oauth.routes.get_current_session")
def test_register_client_returns_201_with_credentials(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    client = _make_client()
    resp = client.post(
        "/oauth/register",
        json={"client_name": "My Tool", "redirect_uris": ["http://localhost/cb"]},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert "client_id" in data
    assert "client_secret" in data
    assert data["client_name"] == "My Tool"
    assert data["redirect_uris"] == ["http://localhost/cb"]
    assert data["client_secret_expires_at"] == 0
    mock_session.add.assert_called_once()


@patch("testgen.api.oauth.routes.get_current_session")
def test_register_client_uses_defaults_for_missing_fields(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    client = _make_client()
    resp = client.post("/oauth/register", json={})

    assert resp.status_code == 201
    data = resp.json()
    assert data["client_name"] == ""
    assert "authorization_code" in data["grant_types"]
    assert data["redirect_uris"] == []
