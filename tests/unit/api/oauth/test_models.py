"""Tests for testgen.api.oauth.models — OAuth2 ORM model business logic."""

import time

from testgen.api.oauth.models import OAuth2Token


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
    # Rotation is off: the access token is revoked on every refresh, but the
    # refresh token must stay live so clients can reuse it.
    token = _make_token(access_token_revoked_at=int(time.time()))
    assert token.is_refresh_token_active() is True


def test_is_refresh_token_active_returns_false_when_expired():
    token = _make_token(issued_at=int(time.time()) - (31 * 86400))
    assert token.is_refresh_token_active() is False
