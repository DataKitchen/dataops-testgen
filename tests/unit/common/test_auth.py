import base64
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import bcrypt
import jwt
import pytest

from testgen.common.auth import (
    check_permission,
    create_jwt_token,
    decode_jwt_token,
    verify_password,
)

JWT_KEY = base64.b64encode(b"test-secret-key-for-jwt-signing!").decode("ascii")
TEST_PASSWORD = "testpass"  # noqa: S105


def _make_token(username="testuser", exp_days=30):
    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = {
        "username": username,
        "exp_date": (datetime.now(UTC) + timedelta(days=exp_days)).timestamp(),
    }
    return jwt.encode(payload, key, algorithm="HS256")


@patch("testgen.common.auth.settings")
def test_create_jwt_token_creates_valid_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    token = create_jwt_token("testuser", expiry_days=7)

    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = jwt.decode(token, key, algorithms=["HS256"])
    assert payload["username"] == "testuser"
    assert payload["exp_date"] > datetime.now(UTC).timestamp()


@patch("testgen.common.auth.settings")
def test_decode_jwt_token_decodes_valid_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    token = _make_token()
    payload = decode_jwt_token(token)
    assert payload["username"] == "testuser"


@patch("testgen.common.auth.settings")
def test_decode_jwt_token_raises_for_expired_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    token = _make_token(exp_days=-1)
    with pytest.raises(ValueError, match="Token has expired"):
        decode_jwt_token(token)


@patch("testgen.common.auth.settings")
def test_decode_jwt_token_raises_for_invalid_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    with pytest.raises(ValueError, match="Invalid token"):
        decode_jwt_token("not-a-valid-token")


def test_verify_password_correct():
    hashed = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()
    assert verify_password(TEST_PASSWORD, hashed) is True


def test_verify_password_wrong():
    hashed = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()
    assert verify_password("wrongpass", hashed) is False


def test_check_permission_allowed_with_enterprise_plugin():
    mock_matrix = {
        "admin": ["administer", "edit", "disposition", "view", "catalog"],
        "business": ["view", "catalog"],
    }
    mock_auth = MagicMock()
    mock_auth.ROLE_PERMISSION_MATRIX = mock_matrix
    with patch.dict(sys.modules, {"testgen_enterprise_auth": MagicMock(), "testgen_enterprise_auth.auth": mock_auth}):
        user = MagicMock(role="admin")
        assert check_permission(user, "edit") is True


def test_check_permission_denied_with_enterprise_plugin():
    mock_matrix = {
        "admin": ["administer", "edit", "disposition", "view", "catalog"],
        "business": ["view", "catalog"],
    }
    mock_auth = MagicMock()
    mock_auth.ROLE_PERMISSION_MATRIX = mock_matrix
    with patch.dict(sys.modules, {"testgen_enterprise_auth": MagicMock(), "testgen_enterprise_auth.auth": mock_auth}):
        user = MagicMock(role="business")
        assert check_permission(user, "administer") is False


def test_check_permission_falls_back_when_no_plugin():
    with patch.dict(sys.modules, {"testgen_enterprise_auth": None, "testgen_enterprise_auth.auth": None}):
        user = MagicMock(role="business")
        assert check_permission(user, "administer") is True
