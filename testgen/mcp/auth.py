from testgen.common.auth import check_permission, create_jwt_token, decode_jwt_token, verify_password
from testgen.common.models.user import User

__all__ = ["authenticate_user", "check_permission", "validate_token"]


def authenticate_user(username: str, password: str) -> str:
    """Verify credentials and return a JWT token."""
    user = User.get(username)

    if user is None:
        raise ValueError("Invalid username or password")

    if not verify_password(password, user.password):
        raise ValueError("Invalid username or password")

    return create_jwt_token(user.username)


def validate_token(token: str) -> User:
    """Decode and validate a JWT token, returning the User."""
    payload = decode_jwt_token(token)

    username = payload.get("username")
    if not username:
        raise ValueError("Token missing username")

    user = User.get(username)
    if user is None:
        raise ValueError(f"User not found: {username}")

    return user
