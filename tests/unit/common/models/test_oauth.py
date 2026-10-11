"""Tests for testgen.common.models.oauth — OAuth2 ORM model business logic."""

import time

import pytest

from testgen.common.models.oauth import OAuth2Client, OAuth2Token, PersonalAccessTokenStatus


def _make_token(**overrides):
    """Create an OAuth2Token instance with sensible defaults."""
    token = OAuth2Token()
    token.issued_at = int(time.time())
    token.expires_in = 3600
    token.access_token_revoked_at = 0
    token.refresh_token_revoked_at = 0
    for k, v in overrides.items():
        setattr(token, k, v)
    return token


def test_is_refresh_token_active_returns_true_when_valid():
    token = _make_token()
    assert token.is_refresh_token_active() is True


def test_is_refresh_token_active_returns_false_when_refresh_revoked():
    token = _make_token(refresh_token_revoked_at=int(time.time()))
    assert token.is_refresh_token_active() is False


def test_is_refresh_token_active_ignores_access_revocation():
    # A confidential client's refresh revokes only the access token; its refresh token
    # stays live so the client can reuse it.
    token = _make_token(access_token_revoked_at=int(time.time()))
    assert token.is_refresh_token_active() is True


def test_is_refresh_token_active_returns_false_when_expired():
    token = _make_token(issued_at=int(time.time()) - (31 * 86400))
    assert token.is_refresh_token_active() is False


def test_is_refresh_token_active_measures_from_the_start_of_its_chain():
    token = _make_token(refresh_token_chain_issued_at=int(time.time()) - (31 * 86400))
    assert token.is_refresh_token_active() is False


# --- status (hybrid_property) ---


def test_status_active_when_unrevoked_and_unexpired():
    token = _make_token(issued_at=int(time.time()) - 10, expires_in=3600)
    assert token.status == PersonalAccessTokenStatus.ACTIVE


def test_status_expired_when_past_expiry():
    token = _make_token(issued_at=int(time.time()) - 3600, expires_in=60)
    assert token.status == PersonalAccessTokenStatus.EXPIRED


def test_status_revoked_when_access_revoked():
    token = _make_token(access_token_revoked_at=int(time.time()))
    assert token.status == PersonalAccessTokenStatus.REVOKED


def test_status_revoked_takes_precedence_over_expired():
    # Past expiry AND revoked: revoked wins.
    token = _make_token(
        issued_at=int(time.time()) - 3600,
        expires_in=60,
        access_token_revoked_at=int(time.time()),
    )
    assert token.status == PersonalAccessTokenStatus.REVOKED


def _make_client(client_secret: str | None, auth_method: str) -> OAuth2Client:
    client = OAuth2Client(client_id="c", client_secret=client_secret)
    client.set_client_metadata({"token_endpoint_auth_method": auth_method})
    return client


@pytest.mark.parametrize("secret", ["anything", ""])
def test_check_client_secret_false_when_no_secret_stored(secret):
    assert _make_client(None, "none").check_client_secret(secret) is False


def test_check_client_secret_matches_stored_secret():
    client = _make_client("s3cret", "client_secret_basic")

    assert client.check_client_secret("s3cret") is True
    assert client.check_client_secret("wrong") is False


@pytest.mark.parametrize("endpoint", ["token", "revocation"])
def test_check_endpoint_auth_method_requires_registered_method(endpoint):
    client = _make_client("s3cret", "client_secret_basic")

    assert client.check_endpoint_auth_method("client_secret_basic", endpoint) is True
    assert client.check_endpoint_auth_method("client_secret_post", endpoint) is False
    assert client.check_endpoint_auth_method("none", endpoint) is False
