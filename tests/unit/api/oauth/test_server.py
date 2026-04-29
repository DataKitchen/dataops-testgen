"""Tests for testgen.api.oauth.server — authorization server and grant types."""

import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from authlib.oauth2.rfc6749 import grants

from testgen import settings
from testgen.api.oauth.server import (
    AuthorizationCodeGrant,
    ClientCredentialsGrant,
    RefreshTokenGrant,
    TestGenAuthorizationServer,
    TestGenRevocationEndpoint,
    _generate_bearer_token,
    create_authorization_server,
)

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
    credential = MagicMock()
    credential.refresh_token_revoked_at = 0

    before = int(time.time())
    grant.revoke_old_credential(credential)
    after = int(time.time())

    assert before <= credential.access_token_revoked_at <= after
    assert credential.refresh_token_revoked_at == 0


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


# --- ClientCredentialsGrant ---


@patch("testgen.api.oauth.server.get_current_session")
def test_client_credentials_resolves_owner(mock_get_session):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    mock_owner = MagicMock()
    mock_owner.username = "owner_user"
    mock_session.scalars.return_value.first.return_value = mock_owner

    grant = ClientCredentialsGrant.__new__(ClientCredentialsGrant)
    grant.request = MagicMock()
    grant.request.client.user_id = uuid4()
    grant.request.client.check_grant_type.return_value = True

    with patch.object(grants.ClientCredentialsGrant, "validate_token_request"):
        grant.validate_token_request()

    assert grant.request.user is mock_owner


@patch("testgen.api.oauth.server.get_current_session")
def test_client_credentials_rejects_client_without_owner(mock_get_session):
    from authlib.oauth2.rfc6749.errors import InvalidGrantError

    grant = ClientCredentialsGrant.__new__(ClientCredentialsGrant)
    grant.request = MagicMock()
    grant.request.client.user_id = None

    with (
        patch.object(grants.ClientCredentialsGrant, "validate_token_request"),
        pytest.raises(InvalidGrantError),
    ):
        grant.validate_token_request()


@patch("testgen.api.oauth.server.get_current_session")
def test_client_credentials_rejects_deleted_owner(mock_get_session):
    from authlib.oauth2.rfc6749.errors import InvalidGrantError

    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_session.scalars.return_value.first.return_value = None

    grant = ClientCredentialsGrant.__new__(ClientCredentialsGrant)
    grant.request = MagicMock()
    grant.request.client.user_id = uuid4()

    with (
        patch.object(grants.ClientCredentialsGrant, "validate_token_request"),
        pytest.raises(InvalidGrantError),
    ):
        grant.validate_token_request()


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
    assert ClientCredentialsGrant in token_grant_classes

    assert "revocation" in server._endpoints
