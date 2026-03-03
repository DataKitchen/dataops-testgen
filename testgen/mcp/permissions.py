"""MCP permission enforcement — project-level and role-based access filtering."""

import contextvars
import functools
from collections.abc import Callable
from dataclasses import dataclass

from testgen.common.models.project_membership import ProjectMembership
from testgen.common.models.user import User
from testgen.utils.plugins import PluginHook

_NOT_SET = object()

_mcp_username: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_username", default=None)
_mcp_project_access: contextvars.ContextVar["ProjectAccess | object"] = contextvars.ContextVar(
    "mcp_project_access", default=_NOT_SET
)


class MCPPermissionDenied(Exception):
    """Raised by ProjectAccess when access is denied. Caught by the decorator."""


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    is_unrestricted: bool
    memberships: dict[str, str]
    permission: str
    allowed_codes: frozenset[str]

    def verify_access(self, project_code: str, not_found: str) -> None:
        """Raise MCPPermissionDenied if user can't access this project.

        - Admin: always passes (no-op).
        - Has access: passes.
        - Has membership but wrong role: raises with denial message.
        - No membership: raises with not_found (hides project existence).
        """
        if self.is_unrestricted or project_code in self.allowed_codes:
            return
        if project_code in self.memberships:
            raise MCPPermissionDenied(
                "Your role on this project does not include the necessary permission for this operation."
            )
        raise MCPPermissionDenied(not_found)

    def has_access(self, project_code: str) -> bool:
        """For filtering lists — no exception, just a bool."""
        return self.is_unrestricted or project_code in self.allowed_codes

    @property
    def query_codes(self) -> list[str] | None:
        """Project codes for SQL WHERE. None = no filter (admin)."""
        return None if self.is_unrestricted else list(self.allowed_codes)

    def query_codes_for(self, permission: str) -> list[str] | None:
        """Project codes for a different permission (e.g. 'view' inside a 'catalog' tool)."""
        if self.is_unrestricted:
            return None
        if permission == self.permission:
            return list(self.allowed_codes)
        allowed_roles = PluginHook.instance().rbac.get_roles_with_permission(permission)
        return [code for code, role in self.memberships.items() if role in allowed_roles]


def set_mcp_username(username: str | None) -> None:
    """Store the authenticated username (called by JWTTokenVerifier)."""
    _mcp_username.set(username)


def get_current_mcp_user() -> User:
    """Get the authenticated User for the current MCP request.

    Must be called within @with_database_session scope.
    """
    username = _mcp_username.get()
    if not username:
        raise RuntimeError("No authenticated user in MCP context")
    user = User.get(username)
    if user is None:
        raise ValueError(f"Authenticated user not found: {username}")
    return user


def _compute_project_access(user: User, permission: str) -> ProjectAccess:
    """Build a ProjectAccess for the given user and permission."""
    if user.is_global_admin:
        return ProjectAccess(
            is_unrestricted=True,
            memberships={},
            permission=permission,
            allowed_codes=frozenset(),
        )

    allowed_roles = PluginHook.instance().rbac.get_roles_with_permission(permission)
    memberships_list = ProjectMembership.get_memberships_for_user(user.id)
    memberships = {m.project_code: m.role for m in memberships_list}
    allowed_codes = frozenset(code for code, role in memberships.items() if role in allowed_roles)

    return ProjectAccess(
        is_unrestricted=False,
        memberships=memberships,
        permission=permission,
        allowed_codes=allowed_codes,
    )


def get_project_access() -> ProjectAccess:
    """Retrieve the ProjectAccess computed by @mcp_permission for the current request.

    Raises RuntimeError if called without @mcp_permission — prevents silent
    admin-level access when a developer forgets to add the decorator.
    """
    value = _mcp_project_access.get()
    if value is _NOT_SET:
        raise RuntimeError(
            "get_project_access() called without @mcp_permission — add the decorator to this tool"
        )
    return value  # type: ignore[return-value]


def resolve_project_access(permission: str) -> ProjectAccess:
    """Compute a ProjectAccess for a specific permission, using the current MCP user."""
    user = get_current_mcp_user()
    return _compute_project_access(user, permission)


def mcp_permission(permission: str) -> Callable:
    """Decorator that enforces role-based project filtering for MCP tools.

    Resolves the authenticated user, computes a ProjectAccess for the given
    permission, and stores it in a ContextVar. The tool retrieves the value
    via ``get_project_access()``.

    If the user has no projects with the required permission, returns an
    early denial message. Catches MCPPermissionDenied raised by tool code
    and returns str(e) as the tool response.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_mcp_user()
            access = _compute_project_access(user, permission)
            if not access.is_unrestricted and not access.allowed_codes:
                return "Your role does not include the necessary permission for this operation on any project."
            tok = _mcp_project_access.set(access)
            try:
                return fn(*args, **kwargs)
            except MCPPermissionDenied as e:
                return str(e)
            finally:
                _mcp_project_access.reset(tok)

        return wrapper

    return decorator
