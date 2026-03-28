from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.exceptions import MCPPermissionDenied
from testgen.mcp.permissions import (
    _NOT_SET,
    ProjectPermissions,
    _compute_project_permissions,
    _mcp_project_permissions,
    get_current_mcp_user,
    get_project_permissions,
    mcp_permission,
    set_mcp_username,
)


@pytest.fixture(autouse=True)
def _reset_contextvars():
    set_mcp_username(None)
    tok = _mcp_project_permissions.set(_NOT_SET)
    yield
    set_mcp_username(None)
    _mcp_project_permissions.reset(tok)


# --- get_current_mcp_user ---


def test_get_current_mcp_user_raises_when_no_username():
    with pytest.raises(RuntimeError, match="No authenticated user"):
        get_current_mcp_user()


@patch("testgen.mcp.permissions.User")
def test_get_current_mcp_user_raises_when_user_not_found(mock_user):
    mock_user.get.return_value = None
    set_mcp_username("ghost")

    with pytest.raises(ValueError, match="Authenticated user not found: ghost"):
        get_current_mcp_user()


@patch("testgen.mcp.permissions.User")
def test_get_current_mcp_user_returns_user(mock_user):
    user = MagicMock()
    mock_user.get.return_value = user
    set_mcp_username("admin")

    result = get_current_mcp_user()

    assert result is user
    mock_user.get.assert_called_once_with("admin")


# --- _compute_project_permissions ---


@patch("testgen.mcp.permissions.ProjectMembership")
def test_compute_project_permissions_returns_memberships(mock_membership):
    user = MagicMock()
    user.id = uuid4()

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "role_a"
    m2 = MagicMock()
    m2.project_code = "proj_b"
    m2.role = "role_c"
    mock_membership.get_memberships_for_user.return_value = [m1, m2]

    result = _compute_project_permissions(user, "view")

    assert result.memberships == {"proj_a": "role_a", "proj_b": "role_c"}
    assert result.permission == "view"
    mock_membership.get_memberships_for_user.assert_called_once_with(user.id)


@patch("testgen.mcp.permissions.ProjectMembership")
def test_compute_project_permissions_no_memberships(mock_membership):
    user = MagicMock()
    user.id = uuid4()
    mock_membership.get_memberships_for_user.return_value = []

    result = _compute_project_permissions(user, "view")

    assert result.memberships == {}
    assert result.permission == "view"


# --- ProjectPermissions.codes_allowed_to ---
# These rely on the conftest's PluginHook mock (TEST_PERM_MATRIX).


def test_codes_allowed_to_filters_by_role():
    perms = ProjectPermissions(
        memberships={"proj_a": "role_a", "proj_b": "role_c"},
        permission="catalog",
    )
    # "view" includes role_a but not role_c
    result = perms.codes_allowed_to("view")
    assert result == ["proj_a"]


def test_codes_allowed_to_all_matching():
    perms = ProjectPermissions(
        memberships={"proj_a": "role_a", "proj_b": "role_b"},
        permission="catalog",
    )
    # "catalog" includes all roles
    result = perms.codes_allowed_to("catalog")
    assert sorted(result) == ["proj_a", "proj_b"]


def test_codes_allowed_to_none_matching():
    perms = ProjectPermissions(
        memberships={"proj_a": "role_c"},
        permission="catalog",
    )
    # "view" excludes role_c
    result = perms.codes_allowed_to("view")
    assert result == []


# --- ProjectPermissions.allowed_codes ---


def test_allowed_codes_uses_decorator_permission():
    perms = ProjectPermissions(
        memberships={"proj_a": "role_a", "proj_b": "role_c"},
        permission="view",
    )
    # "view" includes role_a but not role_c
    assert perms.allowed_codes == ["proj_a"]


# --- ProjectPermissions.verify_access ---


def test_verify_access_allowed_passes():
    perms = ProjectPermissions(memberships={"proj_a": "role_a"}, permission="view")
    perms.verify_access("proj_a", not_found="not found")


def test_verify_access_membership_but_wrong_role_raises():
    perms = ProjectPermissions(
        memberships={"proj_a": "role_a", "proj_b": "role_c"},
        permission="view",
    )
    with pytest.raises(MCPPermissionDenied, match="necessary permission"):
        perms.verify_access("proj_b", not_found="not found")


def test_verify_access_no_membership_raises_not_found():
    perms = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    with pytest.raises(MCPPermissionDenied, match="not found"):
        perms.verify_access("secret", not_found="not found")


# --- ProjectPermissions.has_access ---


def test_has_access():
    perms = ProjectPermissions(memberships={"proj_a": "role_a"}, permission="view")
    assert perms.has_access("proj_a") is True
    assert perms.has_access("proj_b") is False


# --- get_project_permissions ---


def test_get_project_permissions_raises_without_decorator():
    with pytest.raises(RuntimeError, match="add the decorator"):
        get_project_permissions()


def test_get_project_permissions_returns_set_value():
    perms = ProjectPermissions(memberships={}, permission="view")
    token = _mcp_project_permissions.set(perms)
    try:
        assert get_project_permissions() is perms
    finally:
        _mcp_project_permissions.reset(token)


# --- mcp_permission decorator ---
# These rely on conftest's mocks (User, ProjectMembership, PluginHook).


def test_mcp_permission_sets_contextvar():
    set_mcp_username("test")

    captured = {}

    @mcp_permission("view")
    def tool_fn():
        perms = get_project_permissions()
        captured["perms"] = perms
        return "ok"

    result = tool_fn()

    assert result == "ok"
    assert "demo" in captured["perms"].allowed_codes
    assert captured["perms"].memberships == {"demo": "role_a"}


@patch("testgen.mcp.permissions.ProjectMembership")
def test_mcp_permission_raises_when_no_allowed_codes(mock_membership):
    """Decorator raises MCPPermissionDenied if user has no projects with the required permission."""
    set_mcp_username("test")

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "role_c"
    mock_membership.get_memberships_for_user.return_value = [m1]

    @mcp_permission("view")
    def tool_fn():
        raise AssertionError("Should not be called")

    with pytest.raises(MCPPermissionDenied, match="permission"):
        tool_fn()


def test_mcp_permission_propagates_mcp_permission_denied():
    """Decorator lets MCPPermissionDenied propagate — safe_tool handles conversion."""
    set_mcp_username("test")

    @mcp_permission("view")
    def tool_fn():
        raise MCPPermissionDenied("Access denied for testing")

    with pytest.raises(MCPPermissionDenied, match="Access denied for testing"):
        tool_fn()


def test_mcp_permission_resets_contextvar_after_call():
    set_mcp_username("test")

    @mcp_permission("view")
    def tool_fn():
        return "ok"

    tool_fn()

    assert _mcp_project_permissions.get() is _NOT_SET


def test_mcp_permission_preserves_function_metadata():
    @mcp_permission("view")
    def my_tool(x: int, y: str = "default") -> str:
        """Tool docstring."""
        return f"{x}-{y}"

    assert my_tool.__name__ == "my_tool"
    assert my_tool.__doc__ == "Tool docstring."
