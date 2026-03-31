import base64
import logging
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from testgen import settings

LOG = logging.getLogger("testgen")


def get_jwt_signing_key() -> bytes:
    """Decode the base64-encoded JWT signing key from settings."""
    return base64.b64decode(settings.JWT_HASHING_KEY_B64.encode("ascii"))


def create_jwt_token(username: str, expiry_seconds: int = 86400) -> str:
    """Create a signed JWT token with the standard TestGen payload schema."""
    payload = {
        "username": username,
        "exp": (datetime.now(UTC) + timedelta(seconds=expiry_seconds)).timestamp(),
    }
    return jwt.encode(payload, get_jwt_signing_key(), algorithm="HS256")


def decode_jwt_token(token_str: str) -> dict:
    """Decode and validate a JWT token. Returns the payload dict.

    Raises ValueError if the token is invalid or expired.
    PyJWT auto-validates the standard ``exp`` claim during decode.
    """
    try:
        return jwt.decode(token_str, get_jwt_signing_key(), algorithms=["HS256"])
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}") from e


def authorize_token(token_str: str, username: str, session):
    """Verify the user exists and the token isn't revoked.

    Shared implementation for API and MCP authorization.
    """
    from sqlalchemy import func

    from testgen.api.oauth.models import OAuth2Token
    from testgen.common.models.user import User

    user = session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
    if user is None:
        raise ValueError("User not found")

    token_record = session.query(OAuth2Token).filter_by(access_token=token_str).first()
    if token_record and token_record.access_token_revoked_at:
        raise ValueError("Token has been revoked")

    return user


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Same algorithm as streamlit_authenticator.
    """
    return bcrypt.checkpw(password.encode(), hashed_password.encode())


def check_permission(user: object, permission: str) -> bool:
    """Check if a user has the given permission.

    Uses the RBAC provider registered by installed plugins.
    Returns True (all allowed) if no plugin overrides the default.
    """
    from testgen.utils.plugins import PluginHook

    return PluginHook.instance().rbac.check_permission(user, permission)
