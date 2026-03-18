"""FastAPI dependencies for API endpoints."""

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from testgen.common.auth import authorize_token, decode_jwt_token
from testgen.common.models import Session, _current_session_wrapper, get_current_session
from testgen.common.models.user import User


def db_session():
    """One DB session per request. Commits on success, rolls back on exception."""
    with Session() as session:
        _current_session_wrapper.value = session
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            _current_session_wrapper.value = None


_bearer_scheme = HTTPBearer()
_bearer_security = Security(_bearer_scheme)


def get_authorized_user(credentials: HTTPAuthorizationCredentials = _bearer_security) -> User:
    """Validate a Bearer token and return the authenticated User.

    Checks JWT validity, user existence, and token revocation status.
    """
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_jwt_token(credentials.credentials)
    except ValueError:
        raise _invalid from None

    username = payload.get("username")
    if not username:
        raise _invalid

    session = get_current_session()
    try:
        return authorize_token(credentials.credentials, username, session)
    except ValueError:
        raise _invalid from None
