"""MCP permission enforcement — project-level and role-based access filtering."""

import contextvars
import functools
from collections.abc import Callable
from dataclasses import dataclass

from testgen.common.models.project_membership import ProjectMembership
from testgen.common.models.user import User
from testgen.mcp.exceptions import MCPPermissionDenied
from testgen.utils.plugins import PluginHook

_NOT_SET = object()

_mcp_username: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_username", default=None)
_mcp_project_permissions: contextvars.ContextVar["ProjectPermissions | object"] = contextvars.ContextVar(
    "mcp_project_permissions", default=_NOT_SET
)


@dataclass(frozen=True, slots=True)
class ProjectPermissions:
    memberships: dict[str, str]  # {project_code: role}
    permission: str

    def codes_allowed_to(self, permission: str) -> list[str]:
        """Project codes where the user's role includes the given permission."""
        allowed_roles = PluginHook.instance().rbac.get_roles_with_permission(permission)
        return [code for code, role in self.memberships.items() if role in allowed_roles]

    @property
    def allowed_codes(self) -> list[str]:
        """Project codes for the decorator's permission."""
        return self.codes_allowed_to(self.permission)

    def has_access(self, project_code: str) -> bool:
        """For filtering lists — no exception, just a bool."""
        return project_code in self.allowed_codes

    def verify_access(self, project_code: str, not_found: str) -> None:
        """Raise MCPPermissionDenied if user can't access this project.

        - Has access: passes.
        - Has membership but wrong role: raises with denial message.
        - No membership: raises with not_found (hides project existence).
        """
        if project_code in self.allowed_codes:
            return
        if project_code in self.memberships:
            raise MCPPermissionDenied(
                "Your role on this project does not include the necessary permission for this operation."
            )
        raise MCPPermissionDenied(not_found)


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


def _compute_project_permissions(user: User, permission: str) -> ProjectPermissions:
    """Build a ProjectPermissions for the given user and permission."""
    memberships_list = ProjectMembership.get_memberships_for_user(user.id)
    return ProjectPermissions(
        memberships={m.project_code: m.role for m in memberships_list},
        permission=permission,
    )


def get_project_permissions() -> "ProjectPermissions":
    """Retrieve the ProjectPermissions computed by @mcp_permission for the current request.

    Raises RuntimeError if called without @mcp_permission — prevents silent
    unfiltered access when a developer forgets to add the decorator.
    """
    value = _mcp_project_permissions.get()
    if value is _NOT_SET:
        raise RuntimeError(
            "get_project_permissions() called without @mcp_permission — add the decorator to this tool"
        )
    return value  # type: ignore[return-value]


def mcp_permission(permission: str) -> Callable:
    """Decorator that enforces role-based project filtering for MCP tools.

    Resolves the authenticated user, computes a ProjectPermissions for the given
    permission, and stores it in a ContextVar. The tool retrieves the value
    via ``get_project_permissions()``.

    Raises ``MCPPermissionDenied`` if the user has no projects with the required
    permission. Other ``MCPPermissionDenied`` exceptions from tool code propagate
    through — the ``safe_tool`` error boundary handles conversion to text.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_mcp_user()
            perms = _compute_project_permissions(user, permission)
            if not perms.allowed_codes:
                raise MCPPermissionDenied(
                    "Your role does not include the necessary permission for this operation on any project."
                )
            tok = _mcp_project_permissions.set(perms)
            try:
                return fn(*args, **kwargs)
            finally:
                _mcp_project_permissions.reset(tok)

        return wrapper

    return decorator
