import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, MagicMock, patch

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


def test_check_permission_allowed_with_plugin():
    mock_rbac = MagicMock()
    mock_rbac.check_permission.return_value = True
    mock_hook = MagicMock()
    mock_hook.rbac = mock_rbac
    with patch("testgen.utils.plugins.PluginHook.instance", return_value=mock_hook):
        assert check_permission(MagicMock(role="admin"), "edit") is True
        mock_rbac.check_permission.assert_called_once_with(ANY, "edit")


def test_check_permission_denied_with_plugin():
    mock_rbac = MagicMock()
    mock_rbac.check_permission.return_value = False
    mock_hook = MagicMock()
    mock_hook.rbac = mock_rbac
    with patch("testgen.utils.plugins.PluginHook.instance", return_value=mock_hook):
        assert check_permission(MagicMock(role="business"), "administer") is False


def test_check_permission_defaults_without_plugin():
    from testgen.utils.plugins import PluginHook

    with patch("testgen.utils.plugins.PluginHook.instance") as mock_instance:
        hook = PluginHook()
        mock_instance.return_value = hook
        assert check_permission(MagicMock(role="business"), "administer") is True
