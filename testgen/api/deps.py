"""FastAPI dependencies for API endpoints."""

from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from testgen.common.auth import authorize_token, decode_jwt_token
from testgen.common.models import Session, _current_session_wrapper, get_current_session
from testgen.common.models.project_membership import ProjectMembership
from testgen.common.models.user import User
from testgen.utils.plugins import PluginHook


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


def api_error(status_code: int, code: str, detail: str) -> HTTPException:
    """Build an HTTPException with the standardized error response format."""
    return HTTPException(status_code=status_code, detail={"errors": [{"code": code, "detail": detail}]})


def has_project_permission(user: User, project_code: str, permission: str) -> bool:
    """Check if the user's role in the project includes the required permission."""
    role = ProjectMembership.get_user_role_in_project(user.id, project_code)
    if role is None:
        return False
    allowed_roles = PluginHook.instance().rbac.get_roles_with_permission(permission)
    return role in allowed_roles


# --- Resolver dependency factories ---
# Each factory takes a permission string and returns Depends(). The entity ID
# comes from a URL path parameter (FastAPI resolves it natively).
# Entity not found and insufficient permission both raise the same 404
# with a stable code/message — no variation that could leak the cause.

_require_user = Depends(get_authorized_user)
_not_found = api_error(404, "not_found", "Not found")


def resolve_table_group(permission: str):
    """Resolve a TableGroup by ``table_group_id`` path param and verify project permission."""
    from testgen.common.models.table_group import TableGroup

    def dependency(table_group_id: UUID, user: User = _require_user) -> TableGroup:
        if (table_group := TableGroup.get(table_group_id)) and has_project_permission(user, table_group.project_code, permission):
            return table_group
        raise _not_found
    return Depends(dependency)


def resolve_test_suite(permission: str):
    """Resolve a TestSuite by ``test_suite_id`` path param and verify project permission."""
    from testgen.common.models.test_suite import TestSuite

    def dependency(test_suite_id: UUID, user: User = _require_user) -> TestSuite:
        if (test_suite := TestSuite.get(test_suite_id)) and has_project_permission(user, test_suite.project_code, permission):
            return test_suite
        raise _not_found
    return Depends(dependency)


def resolve_job(permission: str):
    """Resolve a JobExecution by ``job_id`` path param and verify project permission."""
    from testgen.common.models.job_execution import JobExecution

    def dependency(job_id: UUID, user: User = _require_user) -> JobExecution:
        if (job := JobExecution.get(job_id)) and has_project_permission(user, job.project_code, permission):
            return job
        raise _not_found
    return Depends(dependency)
