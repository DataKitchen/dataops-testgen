"""Tests for testgen.api.oauth.server — authorization server and grant types."""

import base64
import hashlib
import itertools
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from authlib.oauth2.rfc6749.errors import InvalidRequestError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testgen import settings
from testgen.api.deps import db_session
from testgen.api.oauth import routes
from testgen.api.oauth.server import (
    AuthorizationCodeGrant,
    RefreshTokenGrant,
    S256CodeChallenge,
    TestGenAuthorizationServer,
    TestGenRevocationEndpoint,
    _generate_bearer_token,
    create_authorization_server,
)
from testgen.common.models.oauth import OAuth2AuthorizationCode, OAuth2Client, OAuth2ClientAuthMethod, OAuth2Token

# --- AuthorizationCodeGrant ---


@patch("testgen.api.oauth.server.get_current_session")
def test_auth_code_save_authorization_code(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    grant = AuthorizationCodeGrant.__new__(AuthorizationCodeGrant)

    request = MagicMock()
    request.client.client_id = "client_abc"
    request.redirect_uri = "http://localhost/callback"
    request.scope = "read"
    request.user.id = uuid4()
    request.data = {"code_challenge": "abc123", "code_challenge_method": "S256"}

    grant.save_authorization_code("CODE123", request)

    mock_session.add.assert_called_once()
    saved = mock_session.add.call_args[0][0]
    assert saved.code == "CODE123"
    assert saved.client_id == "client_abc"


@patch("testgen.api.oauth.server.get_current_session")
def test_auth_code_query_returns_valid_code(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_code = MagicMock()
    mock_code.is_expired.return_value = False
    mock_session.scalars.return_value.first.return_value = mock_code

    grant = AuthorizationCodeGrant.__new__(AuthorizationCodeGrant)
    client = MagicMock()
    client.client_id = "client_abc"

    result = grant.query_authorization_code("CODE123", client)
    assert result is mock_code


@patch("testgen.api.oauth.server.get_current_session")
def test_auth_code_query_returns_none_for_expired(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_code = MagicMock()
    mock_code.is_expired.return_value = True
    mock_session.scalars.return_value.first.return_value = mock_code

    grant = AuthorizationCodeGrant.__new__(AuthorizationCodeGrant)
    client = MagicMock()
    client.client_id = "client_abc"

    result = grant.query_authorization_code("CODE123", client)
    assert result is None


@patch("testgen.api.oauth.server.get_current_session")
def test_auth_code_delete(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    grant = AuthorizationCodeGrant.__new__(AuthorizationCodeGrant)
    auth_code = MagicMock()

    grant.delete_authorization_code(auth_code)

    mock_session.delete.assert_called_once_with(auth_code)


@patch("testgen.api.oauth.server.get_current_session")
def test_auth_code_authenticate_user(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_user = MagicMock()
    mock_session.scalars.return_value.first.return_value = mock_user

    grant = AuthorizationCodeGrant.__new__(AuthorizationCodeGrant)
    auth_code = MagicMock()
    auth_code.user_id = uuid4()

    result = grant.authenticate_user(auth_code)

    assert result is mock_user
    mock_session.scalars.assert_called_once()


# --- RefreshTokenGrant ---


@patch("testgen.api.oauth.server.get_current_session")
def test_refresh_token_authenticate_valid_token(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_token = MagicMock()
    mock_token.is_refresh_token_active.return_value = True
    mock_session.scalars.return_value.first.return_value = mock_token

    grant = RefreshTokenGrant.__new__(RefreshTokenGrant)

    result = grant.authenticate_refresh_token("refresh_abc")

    assert result is mock_token


@patch("testgen.api.oauth.server.get_current_session")
def test_refresh_token_authenticate_returns_none_for_revoked(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_token = MagicMock()
    mock_token.is_refresh_token_active.return_value = False
    mock_session.scalars.return_value.first.return_value = mock_token

    grant = RefreshTokenGrant.__new__(RefreshTokenGrant)

    result = grant.authenticate_refresh_token("revoked_token")

    assert result is None


@patch("testgen.api.oauth.server.get_current_session")
def test_refresh_token_authenticate_returns_none_when_not_found(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_session.scalars.return_value.first.return_value = None

    grant = RefreshTokenGrant.__new__(RefreshTokenGrant)

    result = grant.authenticate_refresh_token("nonexistent")

    assert result is None


def test_revoke_old_credential_revokes_access_but_keeps_refresh_live():
    grant = RefreshTokenGrant.__new__(RefreshTokenGrant)
    grant.request = MagicMock()
    grant.request.client.token_endpoint_auth_method = OAuth2ClientAuthMethod.CLIENT_SECRET_BASIC
    credential = MagicMock()
    credential.refresh_token_revoked_at = 0

    before = int(time.time())
    grant.revoke_old_credential(credential)
    after = int(time.time())

    assert before <= credential.access_token_revoked_at <= after
    assert credential.refresh_token_revoked_at == 0


def test_revoke_old_credential_revokes_refresh_for_public_client():
    grant = RefreshTokenGrant.__new__(RefreshTokenGrant)
    grant.request = MagicMock()
    grant.request.client.token_endpoint_auth_method = OAuth2ClientAuthMethod.NONE
    credential = MagicMock()
    credential.refresh_token_revoked_at = 0

    before = int(time.time())
    grant.revoke_old_credential(credential)
    after = int(time.time())

    assert before <= credential.access_token_revoked_at <= after
    assert before <= credential.refresh_token_revoked_at <= after


@patch("testgen.api.oauth.server.get_current_session")
def test_refresh_token_authenticate_user(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_user = MagicMock()
    mock_session.scalars.return_value.first.return_value = mock_user

    grant = RefreshTokenGrant.__new__(RefreshTokenGrant)
    credential = MagicMock()
    credential.user_id = uuid4()

    result = grant.authenticate_user(credential)

    assert result is mock_user


# --- TestGenAuthorizationServer ---


@patch("testgen.api.oauth.server.get_current_session")
def test_server_query_client_returns_client(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_client = MagicMock()
    mock_session.scalars.return_value.first.return_value = mock_client

    server = TestGenAuthorizationServer()
    result = server.query_client("test_client_id")

    assert result is mock_client


@patch("testgen.api.oauth.server.get_current_session")
def test_server_query_client_returns_none_when_not_found(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_session.scalars.return_value.first.return_value = None

    server = TestGenAuthorizationServer()
    result = server.query_client("nonexistent")

    assert result is None


@patch("testgen.api.oauth.server.get_current_session")
def test_server_save_token_persists_with_user_id(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    server = TestGenAuthorizationServer()
    user_id = uuid4()
    request = MagicMock()
    request.user.id = user_id
    request.client.client_id = "client_abc"

    token_data = {
        "access_token": "access_xyz",
        "refresh_token": "refresh_xyz",
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    server.save_token(token_data, request)

    mock_session.add.assert_called_once()
    saved = mock_session.add.call_args[0][0]
    assert saved.client_id == "client_abc"
    assert saved.user_id == user_id


@patch("testgen.api.oauth.server.get_current_session")
def test_server_save_token_handles_no_user(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    server = TestGenAuthorizationServer()
    request = MagicMock()
    request.user = None
    request.client.client_id = "client_abc"

    token_data = {"access_token": "access_xyz", "token_type": "Bearer", "expires_in": 3600}

    server.save_token(token_data, request)

    saved = mock_session.add.call_args[0][0]
    assert saved.user_id is None


def test_server_handle_response_passes_through():
    server = TestGenAuthorizationServer()
    status, payload, headers = server.handle_response(200, {"key": "val"}, {"X-Custom": "1"})

    assert status == 200
    assert payload == {"key": "val"}
    assert headers == {"X-Custom": "1"}


def test_server_send_signal_is_noop():
    server = TestGenAuthorizationServer()
    server.send_signal("test_signal", "arg1", key="val")


# --- _generate_bearer_token ---


@patch("testgen.api.oauth.server.create_jwt_token", return_value="jwt_access_token")
def test_generate_bearer_token_with_user(mock_jwt):
    user = MagicMock()
    user.username = "alice"
    client = MagicMock()
    client.client_id = "client_abc"

    token = _generate_bearer_token("authorization_code", client, user=user, scope="read")

    assert token["token_type"] == "Bearer"  # noqa: S105
    assert token["access_token"] == "jwt_access_token"  # noqa: S105
    assert token["expires_in"] == settings.ACCESS_TOKEN_EXPIRES_IN
    assert "refresh_token" in token
    assert token["scope"] == "read"
    mock_jwt.assert_called_once_with("alice", expiry_seconds=settings.ACCESS_TOKEN_EXPIRES_IN)


def test_generate_bearer_token_raises_when_no_user():
    client = MagicMock()
    client.client_id = "client_abc"

    with pytest.raises(RuntimeError, match="Token generation requires a user"):
        _generate_bearer_token("client_credentials", client)


@patch("testgen.api.oauth.server.create_jwt_token", return_value="jwt")
def test_generate_bearer_token_no_refresh_token(mock_jwt):
    user = MagicMock()
    user.username = "alice"
    client = MagicMock()
    client.client_id = "c"

    token = _generate_bearer_token("authorization_code", client, user=user, include_refresh_token=False)

    assert "refresh_token" not in token


@patch("testgen.api.oauth.server.create_jwt_token", return_value="jwt")
def test_generate_bearer_token_custom_expiry(mock_jwt):
    user = MagicMock()
    user.username = "alice"
    client = MagicMock()
    client.client_id = "c"

    token = _generate_bearer_token("authorization_code", client, user=user, expires_in=7200)

    assert token["expires_in"] == 7200


@patch("testgen.api.oauth.server.create_jwt_token", return_value="jwt")
def test_generate_bearer_token_no_scope_omits_field(mock_jwt):
    user = MagicMock()
    user.username = "alice"
    client = MagicMock()
    client.client_id = "c"

    token = _generate_bearer_token("authorization_code", client, user=user)

    assert "scope" not in token


# --- RevocationEndpoint ---


@patch("testgen.api.oauth.server.get_current_session")
def test_revocation_query_token_by_access_token(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_token = MagicMock()
    mock_session.scalars.return_value.first.return_value = mock_token

    ep = TestGenRevocationEndpoint.__new__(TestGenRevocationEndpoint)
    result = ep.query_token("tok_abc", "access_token")

    assert result is mock_token
    mock_session.scalars.assert_called_once()


@patch("testgen.api.oauth.server.get_current_session")
def test_revocation_query_token_by_refresh_token(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_token = MagicMock()
    mock_session.scalars.return_value.first.return_value = mock_token

    ep = TestGenRevocationEndpoint.__new__(TestGenRevocationEndpoint)
    result = ep.query_token("ref_abc", "refresh_token")

    assert result is mock_token
    mock_session.scalars.assert_called_once()


def test_revocation_revoke_token_sets_timestamps():
    token = MagicMock()
    request = MagicMock()
    request.form = {}

    ep = TestGenRevocationEndpoint.__new__(TestGenRevocationEndpoint)
    before = int(time.time())
    ep.revoke_token(token, request)
    after = int(time.time())

    assert before <= token.access_token_revoked_at <= after
    assert before <= token.refresh_token_revoked_at <= after


def test_revocation_access_only_hint():
    token = MagicMock()
    token.refresh_token_revoked_at = None
    request = MagicMock()
    request.form = {"token_type_hint": "access_token"}

    ep = TestGenRevocationEndpoint.__new__(TestGenRevocationEndpoint)
    ep.revoke_token(token, request)

    assert token.access_token_revoked_at is not None
    # refresh_token_revoked_at should NOT have been set
    assert token.refresh_token_revoked_at is None


# --- create_authorization_server ---


def test_create_authorization_server_returns_configured_server():
    server = create_authorization_server()

    assert isinstance(server, TestGenAuthorizationServer)
    token_grant_classes = [entry[0] for entry in server._token_grants]
    assert RefreshTokenGrant in token_grant_classes
    assert AuthorizationCodeGrant in token_grant_classes

    assert "revocation" in server._endpoints


# --- Token and revocation flows through the real authorization server ---

REDIRECT_URI = "http://localhost/cb"
CODE_VERIFIER = "v" * 64
SECRET = "the-real-secret"  # noqa: S105


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _basic(client_id: str, secret: str) -> dict[str, str]:
    return {"Authorization": f"Basic {base64.b64encode(f'{client_id}:{secret}'.encode()).decode()}"}


@dataclass
class _Store:
    clients: dict[str, OAuth2Client] = field(default_factory=dict)
    codes: dict[str, OAuth2AuthorizationCode] = field(default_factory=dict)
    tokens: list[OAuth2Token] = field(default_factory=list)

    def add_client(self, client_id: str, auth_method: str) -> OAuth2Client:
        client = OAuth2Client(
            client_id=client_id,
            client_secret=None if auth_method == "none" else SECRET,
            client_id_issued_at=int(time.time()),
        )
        client.set_client_metadata({
            "grant_types": ["authorization_code", "refresh_token"],
            "redirect_uris": [REDIRECT_URI],
            "response_types": ["code"],
            "scope": "",
            "token_endpoint_auth_method": auth_method,
        })
        self.clients[client_id] = client
        return client

    def add_code(self, client_id: str) -> str:
        code = uuid4().hex
        self.codes[code] = OAuth2AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=REDIRECT_URI,
            scope="",
            auth_time=int(time.time()),
            code_challenge=_s256(CODE_VERIFIER),
            code_challenge_method="S256",
        )
        return code

    def save(self, item: OAuth2Token) -> None:
        item.issued_at = item.issued_at or int(time.time())
        self.tokens.append(item)

    def by_refresh(self, refresh_token: str) -> OAuth2Token | None:
        return next((t for t in self.tokens if t.refresh_token == refresh_token), None)


@pytest.fixture
def store() -> Iterator[_Store]:
    data = _Store()
    user = MagicMock()
    user.id = uuid4()
    user.username = "alice"
    session = MagicMock()
    session.add.side_effect = data.save
    counter = itertools.count()

    def query_code(_grant, code, client):
        item = data.codes.get(code)
        return item if item and item.client_id == client.client_id else None

    def query_refresh(_grant, refresh_token):
        item = data.by_refresh(refresh_token)
        return item if item and item.is_refresh_token_active() else None

    def query_token(_endpoint, token_string, _hint):
        return next(
            (t for t in data.tokens if token_string in (t.access_token, t.refresh_token)),
            None,
        )

    with (
        patch("testgen.api.oauth.server.get_current_session", return_value=session),
        patch("testgen.api.oauth.server.create_jwt_token", side_effect=lambda *_a, **_k: f"jwt-{next(counter)}"),
        patch.object(TestGenAuthorizationServer, "query_client", lambda _s, cid: data.clients.get(cid)),
        patch.object(AuthorizationCodeGrant, "query_authorization_code", query_code),
        patch.object(AuthorizationCodeGrant, "delete_authorization_code", lambda _g, c: data.codes.pop(c.code)),
        patch.object(AuthorizationCodeGrant, "authenticate_user", lambda _g, _c: user),
        patch.object(RefreshTokenGrant, "authenticate_refresh_token", query_refresh),
        patch.object(RefreshTokenGrant, "authenticate_user", lambda _g, _c: user),
        patch.object(TestGenRevocationEndpoint, "query_token", query_token),
        patch.object(routes, "_server", create_authorization_server()),
    ):
        yield data


@pytest.fixture
def http() -> TestClient:
    def _noop_db_session():
        yield None

    app = FastAPI()
    app.dependency_overrides[db_session] = _noop_db_session
    app.include_router(routes.router)
    return TestClient(app)


def _code_form(client_id: str | None, code: str, **extra: str) -> dict[str, str]:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": CODE_VERIFIER,
        **extra,
    }
    if client_id:
        form["client_id"] = client_id
    return form


def test_public_client_exchanges_code_without_secret(store, http):
    store.add_client("pub", "none")

    resp = http.post("/oauth/token", data=_code_form("pub", store.add_code("pub")))

    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert resp.json()["refresh_token"]


def test_public_client_without_code_verifier_is_rejected(store, http):
    store.add_client("pub", "none")
    form = _code_form("pub", store.add_code("pub"))
    del form["code_verifier"]

    resp = http.post("/oauth/token", data=form)

    assert resp.status_code == 400
    assert not store.tokens


def test_public_client_refresh_rotates_and_revokes_old_refresh_token(store, http):
    store.add_client("pub", "none")
    first = http.post("/oauth/token", data=_code_form("pub", store.add_code("pub"))).json()

    resp = http.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": "pub"},
    )

    assert resp.status_code == 200
    second = resp.json()
    assert second["refresh_token"]
    assert second["refresh_token"] != first["refresh_token"]
    old = store.by_refresh(first["refresh_token"])
    assert old.refresh_token_revoked_at
    assert old.access_token_revoked_at

    reuse = http.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": "pub"},
    )
    assert reuse.status_code == 400
    assert reuse.json()["error"] == "invalid_grant"

    again = http.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": second["refresh_token"], "client_id": "pub"},
    )
    assert again.status_code == 200


def test_public_client_refresh_chain_expires_with_its_first_token(store, http):
    store.add_client("pub", "none")
    first = http.post("/oauth/token", data=_code_form("pub", store.add_code("pub"))).json()
    first_row = store.by_refresh(first["refresh_token"])
    first_row.issued_at -= settings.REFRESH_TOKEN_EXPIRES_IN - 30

    second = http.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": "pub"},
    ).json()
    assert store.by_refresh(second["refresh_token"]).refresh_token_chain_issued_at == first_row.issued_at

    with patch("testgen.common.models.oauth.time.time", return_value=time.time() + 60):
        resp = http.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": second["refresh_token"], "client_id": "pub"},
        )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


def test_confidential_client_refresh_keeps_refresh_token(store, http):
    store.add_client("conf", "client_secret_basic")
    first = http.post(
        "/oauth/token", data=_code_form(None, store.add_code("conf")), headers=_basic("conf", SECRET)
    ).json()

    resp = http.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]},
        headers=_basic("conf", SECRET),
    )

    assert resp.status_code == 200
    assert "refresh_token" not in resp.json()
    old = store.by_refresh(first["refresh_token"])
    assert old.access_token_revoked_at
    assert not old.refresh_token_revoked_at


def test_public_client_with_wrong_basic_secret_is_rejected(store, http):
    store.add_client("pub", "none")

    resp = http.post(
        "/oauth/token", data=_code_form("pub", store.add_code("pub")), headers=_basic("pub", "guess")
    )

    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_client"
    assert not store.tokens


def test_public_client_with_wrong_post_secret_is_rejected(store, http):
    store.add_client("pub", "none")

    resp = http.post("/oauth/token", data=_code_form("pub", store.add_code("pub"), client_secret="guess"))  # noqa: S106

    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_client"
    assert not store.tokens


def test_public_client_refresh_with_secret_is_rejected(store, http):
    store.add_client("pub", "none")
    first = http.post("/oauth/token", data=_code_form("pub", store.add_code("pub"))).json()

    resp = http.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": "pub",
            "client_secret": "guess",
        },
    )

    assert resp.status_code == 401
    assert not store.by_refresh(first["refresh_token"]).refresh_token_revoked_at


@pytest.mark.parametrize(
    ("auth_method", "use_basic", "expected_status"),
    [
        ("client_secret_basic", True, 200),
        ("client_secret_basic", False, 401),
        ("client_secret_post", False, 200),
        ("client_secret_post", True, 401),
    ],
)
def test_confidential_client_authenticates_only_with_registered_method(
    store, http, auth_method, use_basic, expected_status
):
    store.add_client("conf", auth_method)
    code = store.add_code("conf")
    if use_basic:
        resp = http.post("/oauth/token", data=_code_form(None, code), headers=_basic("conf", SECRET))
    else:
        resp = http.post("/oauth/token", data=_code_form("conf", code, client_secret=SECRET))

    assert resp.status_code == expected_status


def test_confidential_client_cannot_authenticate_without_secret(store, http):
    store.add_client("conf", "client_secret_basic")

    resp = http.post("/oauth/token", data=_code_form("conf", store.add_code("conf")))

    assert resp.status_code == 401
    assert not store.tokens


def test_public_client_revokes_its_token_without_secret(store, http):
    store.add_client("pub", "none")
    issued = http.post("/oauth/token", data=_code_form("pub", store.add_code("pub"))).json()

    resp = http.post("/oauth/revoke", data={"token": issued["refresh_token"], "client_id": "pub"})

    assert resp.status_code == 200
    assert store.by_refresh(issued["refresh_token"]).refresh_token_revoked_at


def test_public_client_revokes_with_a_bearer_header(store, http):
    store.add_client("pub", "none")
    issued = http.post("/oauth/token", data=_code_form("pub", store.add_code("pub"))).json()

    resp = http.post(
        "/oauth/revoke",
        data={"token": issued["refresh_token"], "client_id": "pub"},
        headers={"Authorization": f"Bearer {issued['access_token']}"},
    )

    assert resp.status_code == 200


@pytest.mark.parametrize("auth_method", ["client_secret_basic", "client_secret_post"])
def test_confidential_client_revokes_with_its_method(store, http, auth_method):
    store.add_client("conf", auth_method)
    if auth_method == "client_secret_basic":
        credentials, headers = {}, _basic("conf", SECRET)
    else:
        credentials, headers = {"client_id": "conf", "client_secret": SECRET}, {}
    issued = http.post(
        "/oauth/token", data={**_code_form(None, store.add_code("conf")), **credentials}, headers=headers
    ).json()

    resp = http.post("/oauth/revoke", data={"token": issued["refresh_token"], **credentials}, headers=headers)

    assert resp.status_code == 200
    assert store.by_refresh(issued["refresh_token"]).refresh_token_revoked_at


def test_confidential_client_cannot_revoke_by_client_id_alone(store, http):
    store.add_client("conf", "client_secret_basic")
    issued = http.post(
        "/oauth/token", data=_code_form(None, store.add_code("conf")), headers=_basic("conf", SECRET)
    ).json()

    resp = http.post("/oauth/revoke", data={"token": issued["refresh_token"], "client_id": "conf"})

    assert resp.status_code == 401
    assert not store.by_refresh(issued["refresh_token"]).refresh_token_revoked_at


# --- S256CodeChallenge ---


def _challenge_grant(data: dict[str, str]) -> MagicMock:
    grant = MagicMock()
    grant.request.payload.data = data
    grant.request.payload.datalist = {key: [value] for key, value in data.items()}
    return grant


@pytest.mark.parametrize("method", ["plain", ""])
def test_code_challenge_rejects_methods_other_than_s256(method):
    grant = _challenge_grant({"code_challenge": _s256(CODE_VERIFIER), "code_challenge_method": method})

    with pytest.raises(InvalidRequestError, match="Unsupported 'code_challenge_method'"):
        S256CodeChallenge(required=True).validate_code_challenge(grant, REDIRECT_URI)


@pytest.mark.parametrize("data", [
    {"code_challenge": _s256(CODE_VERIFIER), "code_challenge_method": "S256"},
    {"code_challenge": _s256(CODE_VERIFIER)},
])
def test_code_challenge_accepts_s256_or_omitted_method(data):
    S256CodeChallenge(required=True).validate_code_challenge(_challenge_grant(data), REDIRECT_URI)


@pytest.mark.parametrize("data", [{}, {"code_challenge_method": "S256"}, {"code_challenge": ""}])
def test_code_challenge_is_required_for_every_client(data):
    with pytest.raises(InvalidRequestError, match="Missing 'code_challenge'"):
        S256CodeChallenge(required=True).validate_code_challenge(_challenge_grant(data), REDIRECT_URI)
