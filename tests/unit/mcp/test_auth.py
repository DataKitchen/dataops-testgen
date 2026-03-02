import asyncio
import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import bcrypt
import jwt
import pytest

from testgen.mcp.auth import authenticate_user, validate_token
from testgen.mcp.server import JWTTokenVerifier

JWT_KEY = base64.b64encode(b"test-secret-key-for-jwt-signing!").decode("ascii")
TEST_PASSWORD = "testpass"  # noqa: S105


def _make_user(username="testuser", role="admin"):
    hashed = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()
    user = MagicMock()
    user.username = username
    user.password = hashed
    user.role = role
    return user


def _make_token(username="testuser", exp_days=30):
    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = {
        "username": username,
        "exp_date": (datetime.now(UTC) + timedelta(days=exp_days)).timestamp(),
    }
    return jwt.encode(payload, key, algorithm="HS256")


@patch("testgen.common.auth.settings")
@patch("testgen.mcp.auth.User")
def test_authenticate_user_returns_jwt(mock_user_cls, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_user_cls.get.return_value = _make_user()

    token = authenticate_user("testuser", TEST_PASSWORD)

    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = jwt.decode(token, key, algorithms=["HS256"])
    assert payload["username"] == "testuser"
    assert payload["exp_date"] > datetime.now(UTC).timestamp()


@patch("testgen.common.auth.settings")
@patch("testgen.mcp.auth.User")
def test_authenticate_user_raises_for_wrong_password(mock_user_cls, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_user_cls.get.return_value = _make_user()

    with pytest.raises(ValueError, match="Invalid username or password"):
        authenticate_user("testuser", "wrongpass")


@patch("testgen.common.auth.settings")
@patch("testgen.mcp.auth.User")
def test_authenticate_user_raises_for_unknown_user(mock_user_cls, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_user_cls.get.return_value = None

    with pytest.raises(ValueError, match="Invalid username or password"):
        authenticate_user("nobody", TEST_PASSWORD)


@patch("testgen.common.auth.settings")
@patch("testgen.mcp.auth.User")
def test_validate_token_returns_user(mock_user_cls, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    expected_user = _make_user()
    mock_user_cls.get.return_value = expected_user

    user = validate_token(_make_token())

    assert user is expected_user
    mock_user_cls.get.assert_called_once_with("testuser")


@patch("testgen.common.auth.settings")
def test_validate_token_raises_for_expired_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY

    with pytest.raises(ValueError, match="Token has expired"):
        validate_token(_make_token(exp_days=-1))


@patch("testgen.common.auth.settings")
def test_validate_token_raises_for_invalid_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY

    with pytest.raises(ValueError, match="Invalid token"):
        validate_token("not-a-valid-token")


@patch("testgen.common.auth.settings")
@patch("testgen.mcp.auth.User")
def test_validate_token_raises_for_missing_user(mock_user_cls, mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    mock_user_cls.get.return_value = None

    with pytest.raises(ValueError, match="User not found"):
        validate_token(_make_token())


@patch("testgen.common.auth.settings")
def test_token_verifier_returns_access_token_for_valid_jwt(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    verifier = JWTTokenVerifier()
    token = _make_token()

    result = asyncio.run(verifier.verify_token(token))

    assert result is not None
    assert result.client_id == "testuser"
    assert result.token == token


@patch("testgen.common.auth.settings")
def test_token_verifier_returns_none_for_expired_jwt(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    verifier = JWTTokenVerifier()

    result = asyncio.run(verifier.verify_token(_make_token(exp_days=-1)))

    assert result is None


@patch("testgen.common.auth.settings")
def test_token_verifier_returns_none_for_invalid_jwt(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    verifier = JWTTokenVerifier()

    result = asyncio.run(verifier.verify_token("garbage"))

    assert result is None
