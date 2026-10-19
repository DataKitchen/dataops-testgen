import asyncio
import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt

from testgen.common.auth import AuthError
from testgen.mcp.server import JWTTokenVerifier

JWT_KEY = base64.b64encode(b"test-secret-key-for-jwt-signing!").decode("ascii")


def _make_token(username="testuser", exp_seconds=86400 * 30):
    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = {
        "username": username,
        "exp": (datetime.now(UTC) + timedelta(seconds=exp_seconds)).timestamp(),
    }
    return jwt.encode(payload, key, algorithm="HS256")


@patch("testgen.mcp.server._authorize_token")
@patch("testgen.common.auth.settings")
def test_token_verifier_returns_access_token_for_valid_jwt(mock_settings, mock_authorize):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    verifier = JWTTokenVerifier()
    token = _make_token()

    result = asyncio.run(verifier.verify_token(token))

    assert result is not None
    assert result.client_id == "testuser"
    assert result.token == token
    mock_authorize.assert_called_once_with(token, "testuser")


@patch("testgen.mcp.server._authorize_token", side_effect=AuthError("Token has been revoked"))
@patch("testgen.common.auth.settings")
def test_token_verifier_returns_none_for_revoked_token(mock_settings, _mock_authorize, caplog):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    verifier = JWTTokenVerifier()

    result = asyncio.run(verifier.verify_token(_make_token()))

    assert result is None
    assert "MCP token rejected for testuser: Token has been revoked" in caplog.text


@patch("testgen.mcp.server._authorize_token")
@patch("testgen.common.auth.settings")
def test_token_verifier_returns_none_for_expired_jwt(mock_settings, mock_authorize):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    verifier = JWTTokenVerifier()

    result = asyncio.run(verifier.verify_token(_make_token(exp_seconds=-3600)))

    assert result is None
    mock_authorize.assert_not_called()


@patch("testgen.common.auth.settings")
def test_token_verifier_returns_none_for_invalid_jwt(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    verifier = JWTTokenVerifier()

    result = asyncio.run(verifier.verify_token("garbage"))

    assert result is None
