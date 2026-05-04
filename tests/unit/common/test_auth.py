import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, MagicMock, patch

import bcrypt
import jwt
import pytest

from testgen.common.auth import (
    authorize_token,
    check_permission,
    create_jwt_token,
    decode_jwt_token,
    verify_password,
)

JWT_KEY = base64.b64encode(b"test-secret-key-for-jwt-signing!").decode("ascii")
TEST_PASSWORD = "testpass"  # noqa: S105


def _make_token(username="testuser", exp_seconds=86400 * 30):
    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = {
        "username": username,
        "exp": (datetime.now(UTC) + timedelta(seconds=exp_seconds)).timestamp(),
    }
    return jwt.encode(payload, key, algorithm="HS256")


@patch("testgen.common.auth.settings")
def test_create_jwt_token_creates_valid_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    token = create_jwt_token("testuser", expiry_seconds=604800)

    key = base64.b64decode(JWT_KEY.encode("ascii"))
    payload = jwt.decode(token, key, algorithms=["HS256"])
    assert payload["username"] == "testuser"
    assert payload["exp"] > datetime.now(UTC).timestamp()


@patch("testgen.common.auth.settings")
def test_decode_jwt_token_decodes_valid_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    token = _make_token()
    payload = decode_jwt_token(token)
    assert payload["username"] == "testuser"


@patch("testgen.common.auth.settings")
def test_decode_jwt_token_raises_for_expired_token(mock_settings):
    mock_settings.JWT_HASHING_KEY_B64 = JWT_KEY
    token = _make_token(exp_seconds=-3600)
    with pytest.raises(ValueError, match="Invalid token"):
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


# --- authorize_token ---


def _set_scalars_results(mock_session, *results):
    """Configure mock_session.scalars to return successive `.first()` values per call."""
    mock_session.scalars.side_effect = [
        MagicMock(first=MagicMock(return_value=r)) for r in results
    ]


def test_authorize_token_returns_user():
    mock_session = MagicMock()
    mock_user = MagicMock()
    mock_user.username = "testuser"
    # 1st scalars() = User lookup, 2nd = OAuth2Token revocation lookup
    _set_scalars_results(mock_session, mock_user, None)

    result = authorize_token("some_token", "testuser", mock_session)
    assert result is mock_user


def test_authorize_token_rejects_revoked():
    mock_session = MagicMock()
    mock_user = MagicMock()
    mock_token_record = MagicMock()
    mock_token_record.access_token_revoked_at = 1700000000
    _set_scalars_results(mock_session, mock_user, mock_token_record)

    with pytest.raises(ValueError, match="Token has been revoked"):
        authorize_token("revoked_token", "testuser", mock_session)


def test_authorize_token_allows_unknown_token():
    """When no OAuth2Token record exists (e.g. session cookie), authorization passes."""
    mock_session = MagicMock()
    mock_user = MagicMock()
    _set_scalars_results(mock_session, mock_user, None)

    result = authorize_token("session_cookie_jwt", "testuser", mock_session)
    assert result is mock_user


def test_authorize_token_raises_when_user_not_found():
    mock_session = MagicMock()
    # User lookup returns None — token check is never reached
    _set_scalars_results(mock_session, None)

    with pytest.raises(ValueError, match="User not found"):
        authorize_token("some_token", "ghost", mock_session)


# --- check_permission ---


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
