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


def create_jwt_token(username: str, expiry_days: int = 30) -> str:
    """Create a signed JWT token with the standard TestGen payload schema."""
    payload = {
        "username": username,
        "exp_date": (datetime.now(UTC) + timedelta(days=expiry_days)).timestamp(),
    }
    return jwt.encode(payload, get_jwt_signing_key(), algorithm="HS256")


def decode_jwt_token(token_str: str) -> dict:
    """Decode and validate a JWT token. Returns the payload dict.

    Raises ValueError if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token_str, get_jwt_signing_key(), algorithms=["HS256"])
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}") from e

    if payload.get("exp_date", 0) <= datetime.now(UTC).timestamp():
        raise ValueError("Token has expired")

    return payload


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
