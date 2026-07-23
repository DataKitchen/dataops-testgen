"""FastAPI dependencies for API endpoints."""

from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from testgen.common.auth import AuthError, authorize_token, decode_jwt_token
from testgen.common.enums import PublicJobKey
from testgen.common.models import Session, _current_session_wrapper, get_current_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.monitor import Monitor
from testgen.common.models.project_membership import ProjectMembership
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
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
    except AuthError:
        raise _invalid from None

    username = payload.get("username")
    if not username:
        raise _invalid

    session = get_current_session()
    try:
        return authorize_token(credentials.credentials, username, session)
    except AuthError:
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
# comes from a URL path parameter (FastAPI resolves it natively, including
# UUID validation that yields a 422 for malformed inputs).

_require_user = Depends(get_authorized_user)
_not_found = api_error(404, "not_found", "Not found")


def _check_access(entity, user: User, permission: str):
    """Return ``entity`` if the user has ``permission`` on its project, else raise 404.

    Entity-not-found and insufficient-permission both surface as the same 404
    with a stable code/message — no variation that could leak the cause to an
    unauthorized caller.
    """
    if entity and has_project_permission(user, entity.project_code, permission):
        return entity
    raise _not_found


def resolve_project_code(permission: str):
    """Verify the user has ``permission`` on the project identified by ``project_code`` path param."""
    def dependency(project_code: str, user: User = _require_user) -> str:
        if has_project_permission(user, project_code, permission):
            return project_code
        raise _not_found
    return Depends(dependency)


def resolve_table_group(permission: str):
    """Resolve a TableGroup by ``table_group_id`` path param and verify project permission."""
    def dependency(table_group_id: UUID, user: User = _require_user) -> TableGroup:
        return _check_access(TableGroup.get(table_group_id), user, permission)
    return Depends(dependency)


def resolve_test_suite(permission: str):
    """Resolve a non-monitor TestSuite by ``test_suite_id`` path param and verify project permission."""
    def dependency(test_suite_id: UUID, user: User = _require_user) -> TestSuite:
        return _check_access(TestSuite.get_regular(test_suite_id), user, permission)
    return Depends(dependency)


def resolve_job(permission: str, *extra_filters):
    """Resolve a JobExecution by ``job_id`` path param and verify project permission.

    Only externally-triggerable jobs (``PublicJobKey``) are exposed via the API.
    Internal kinds (score rollups, recalculations, monitor runs) are filtered out
    by construction. Extra ORM clauses are appended to the WHERE clause to further
    restrict by job_key when a caller wants a single kind.
    """
    def dependency(job_id: UUID, user: User = _require_user) -> JobExecution:
        query = select(JobExecution).where(
            JobExecution.id == job_id,
            JobExecution.job_key.in_(list(PublicJobKey)),
            *extra_filters,
        )
        return _check_access(get_current_session().scalars(query).first(), user, permission)
    return Depends(dependency)


def resolve_monitor(permission: str):
    """Resolve a Monitor by ``monitor_id`` path param and verify project permission.

    ``Monitor.get`` returns None for unknown ids and for definitions that are not monitors,
    so non-monitor resources are indistinguishable from missing ones (uniform 404).
    """
    def dependency(monitor_id: UUID, user: User = _require_user) -> Monitor:
        return _check_access(Monitor.get(monitor_id), user, permission)
    return Depends(dependency)
