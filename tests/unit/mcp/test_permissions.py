from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.permissions import (
    _NOT_SET,
    MCPPermissionDenied,
    ProjectAccess,
    _compute_project_access,
    _mcp_project_access,
    get_current_mcp_user,
    get_project_access,
    mcp_permission,
    resolve_project_access,
    set_mcp_username,
)


@pytest.fixture(autouse=True)
def _reset_contextvars():
    set_mcp_username(None)
    tok = _mcp_project_access.set(_NOT_SET)
    yield
    set_mcp_username(None)
    _mcp_project_access.reset(tok)


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


# --- _compute_project_access ---


def test_compute_project_access_global_admin():
    user = MagicMock()
    user.is_global_admin = True

    result = _compute_project_access(user, "view")

    assert result.is_unrestricted is True
    assert result.memberships == {}
    assert result.permission == "view"
    assert result.allowed_codes == frozenset()


@patch("testgen.mcp.permissions.ProjectMembership")
@patch("testgen.mcp.permissions.PluginHook")
def test_compute_project_access_os_default_all_roles_allowed(mock_hook, mock_membership):
    """OS default: get_roles_with_permission returns all roles — all memberships returned."""
    user = MagicMock()
    user.is_global_admin = False
    user.id = uuid4()

    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = [
        "admin", "data_quality", "analyst", "business", "catalog",
    ]

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "admin"
    m2 = MagicMock()
    m2.project_code = "proj_b"
    m2.role = "catalog"
    mock_membership.get_memberships_for_user.return_value = [m1, m2]

    result = _compute_project_access(user, "view")

    assert result.is_unrestricted is False
    assert result.memberships == {"proj_a": "admin", "proj_b": "catalog"}
    assert result.allowed_codes == frozenset(["proj_a", "proj_b"])


@patch("testgen.mcp.permissions.ProjectMembership")
@patch("testgen.mcp.permissions.PluginHook")
def test_compute_project_access_filters_by_role(mock_hook, mock_membership):
    """Enterprise: only memberships with allowed roles are returned."""
    user = MagicMock()
    user.is_global_admin = False
    user.id = uuid4()

    # "view" permission: admin, data_quality, analyst, business — NOT catalog
    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = [
        "admin", "data_quality", "analyst", "business",
    ]

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "admin"
    m2 = MagicMock()
    m2.project_code = "proj_b"
    m2.role = "catalog"
    mock_membership.get_memberships_for_user.return_value = [m1, m2]

    result = _compute_project_access(user, "view")

    assert result.allowed_codes == frozenset(["proj_a"])
    assert result.memberships == {"proj_a": "admin", "proj_b": "catalog"}


@patch("testgen.mcp.permissions.ProjectMembership")
@patch("testgen.mcp.permissions.PluginHook")
def test_compute_project_access_catalog_user_with_catalog_permission(mock_hook, mock_membership):
    """Catalog user calling catalog-permission tool gets their projects."""
    user = MagicMock()
    user.is_global_admin = False
    user.id = uuid4()

    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = [
        "admin", "data_quality", "analyst", "business", "catalog",
    ]

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "catalog"
    mock_membership.get_memberships_for_user.return_value = [m1]

    result = _compute_project_access(user, "catalog")

    assert result.allowed_codes == frozenset(["proj_a"])


@patch("testgen.mcp.permissions.ProjectMembership")
@patch("testgen.mcp.permissions.PluginHook")
def test_compute_project_access_catalog_user_with_view_permission_gets_empty(mock_hook, mock_membership):
    """Catalog user calling view-permission tool gets empty allowed set."""
    user = MagicMock()
    user.is_global_admin = False
    user.id = uuid4()

    # "view" excludes catalog role
    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = [
        "admin", "data_quality", "analyst", "business",
    ]

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "catalog"
    mock_membership.get_memberships_for_user.return_value = [m1]

    result = _compute_project_access(user, "view")

    assert result.allowed_codes == frozenset()


# --- ProjectAccess.verify_access ---


def test_verify_access_admin_always_passes():
    access = ProjectAccess(is_unrestricted=True, memberships={}, permission="view", allowed_codes=frozenset())
    access.verify_access("any_project", not_found="not found")


def test_verify_access_allowed_passes():
    access = ProjectAccess(
        is_unrestricted=False,
        memberships={"proj_a": "admin"},
        permission="view",
        allowed_codes=frozenset(["proj_a"]),
    )
    access.verify_access("proj_a", not_found="not found")


def test_verify_access_membership_but_wrong_role_raises():
    access = ProjectAccess(
        is_unrestricted=False,
        memberships={"proj_a": "admin", "proj_b": "catalog"},
        permission="view",
        allowed_codes=frozenset(["proj_a"]),
    )
    with pytest.raises(MCPPermissionDenied, match="necessary permission"):
        access.verify_access("proj_b", not_found="not found")


def test_verify_access_no_membership_raises_not_found():
    access = ProjectAccess(
        is_unrestricted=False,
        memberships={"proj_a": "admin"},
        permission="view",
        allowed_codes=frozenset(["proj_a"]),
    )
    with pytest.raises(MCPPermissionDenied, match="not found"):
        access.verify_access("secret", not_found="not found")


# --- ProjectAccess.has_access ---


def test_has_access_admin():
    access = ProjectAccess(is_unrestricted=True, memberships={}, permission="view", allowed_codes=frozenset())
    assert access.has_access("anything") is True


def test_has_access_allowed():
    access = ProjectAccess(
        is_unrestricted=False, memberships={"proj_a": "admin"}, permission="view", allowed_codes=frozenset(["proj_a"]),
    )
    assert access.has_access("proj_a") is True
    assert access.has_access("proj_b") is False


# --- ProjectAccess.query_codes ---


def test_query_codes_admin():
    access = ProjectAccess(is_unrestricted=True, memberships={}, permission="view", allowed_codes=frozenset())
    assert access.query_codes is None


def test_query_codes_scoped():
    access = ProjectAccess(
        is_unrestricted=False, memberships={"proj_a": "admin"}, permission="view", allowed_codes=frozenset(["proj_a"]),
    )
    assert access.query_codes == ["proj_a"]


# --- ProjectAccess.query_codes_for ---


@patch("testgen.mcp.permissions.PluginHook")
def test_query_codes_for_admin(mock_hook):
    access = ProjectAccess(is_unrestricted=True, memberships={}, permission="catalog", allowed_codes=frozenset())
    assert access.query_codes_for("view") is None


def test_query_codes_for_same_permission():
    access = ProjectAccess(
        is_unrestricted=False, memberships={"proj_a": "admin"}, permission="view", allowed_codes=frozenset(["proj_a"]),
    )
    assert access.query_codes_for("view") == ["proj_a"]


@patch("testgen.mcp.permissions.PluginHook")
def test_query_codes_for_different_permission(mock_hook):
    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = ["admin"]
    access = ProjectAccess(
        is_unrestricted=False,
        memberships={"proj_a": "admin", "proj_b": "catalog"},
        permission="catalog",
        allowed_codes=frozenset(["proj_a", "proj_b"]),
    )
    result = access.query_codes_for("view")
    assert result == ["proj_a"]


# --- get_project_access ---


def test_get_project_access_raises_without_decorator():
    with pytest.raises(RuntimeError, match="add the decorator"):
        get_project_access()


def test_get_project_access_returns_set_value():
    access = ProjectAccess(is_unrestricted=True, memberships={}, permission="view", allowed_codes=frozenset())
    token = _mcp_project_access.set(access)
    try:
        assert get_project_access() is access
    finally:
        _mcp_project_access.reset(token)


# --- resolve_project_access ---


@patch("testgen.mcp.permissions.User")
def test_resolve_project_access_global_admin(mock_user):
    user = MagicMock()
    user.is_global_admin = True
    mock_user.get.return_value = user
    set_mcp_username("admin")

    result = resolve_project_access("view")

    assert result.is_unrestricted is True


@patch("testgen.mcp.permissions.ProjectMembership")
@patch("testgen.mcp.permissions.PluginHook")
@patch("testgen.mcp.permissions.User")
def test_resolve_project_access_scoped_user(mock_user, mock_hook, mock_membership):
    user = MagicMock()
    user.is_global_admin = False
    user.id = uuid4()
    mock_user.get.return_value = user
    set_mcp_username("scoped")

    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = ["admin"]

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "admin"
    mock_membership.get_memberships_for_user.return_value = [m1]

    result = resolve_project_access("view")

    assert result.allowed_codes == frozenset(["proj_a"])


# --- mcp_permission decorator ---


@patch("testgen.mcp.permissions.User")
def test_mcp_permission_sets_contextvar_for_global_admin(mock_user):
    user = MagicMock()
    user.is_global_admin = True
    mock_user.get.return_value = user
    set_mcp_username("admin")

    captured = {}

    @mcp_permission("view")
    def tool_fn():
        access = get_project_access()
        captured["access"] = access
        return "ok"

    result = tool_fn()

    assert result == "ok"
    assert captured["access"].is_unrestricted is True
    assert captured["access"].query_codes is None


@patch("testgen.mcp.permissions.ProjectMembership")
@patch("testgen.mcp.permissions.PluginHook")
@patch("testgen.mcp.permissions.User")
def test_mcp_permission_sets_contextvar_for_scoped_user(mock_user, mock_hook, mock_membership):
    user = MagicMock()
    user.is_global_admin = False
    user.id = uuid4()
    mock_user.get.return_value = user
    set_mcp_username("scoped")

    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = [
        "admin", "data_quality", "analyst", "business", "catalog",
    ]

    m1 = MagicMock()
    m1.project_code = "proj_x"
    m1.role = "admin"
    mock_membership.get_memberships_for_user.return_value = [m1]

    captured = {}

    @mcp_permission("view")
    def tool_fn():
        access = get_project_access()
        captured["access"] = access
        return "ok"

    result = tool_fn()

    assert result == "ok"
    assert captured["access"].allowed_codes == frozenset(["proj_x"])
    assert captured["access"].memberships == {"proj_x": "admin"}


@patch("testgen.mcp.permissions.ProjectMembership")
@patch("testgen.mcp.permissions.PluginHook")
@patch("testgen.mcp.permissions.User")
def test_mcp_permission_early_return_when_no_allowed_codes(mock_user, mock_hook, mock_membership):
    """Decorator returns early if user has no projects with the required permission."""
    user = MagicMock()
    user.is_global_admin = False
    user.id = uuid4()
    mock_user.get.return_value = user
    set_mcp_username("scoped")

    # "view" excludes catalog role
    mock_hook.instance.return_value.rbac.get_roles_with_permission.return_value = ["admin"]

    m1 = MagicMock()
    m1.project_code = "proj_a"
    m1.role = "catalog"
    mock_membership.get_memberships_for_user.return_value = [m1]

    @mcp_permission("view")
    def tool_fn():
        raise AssertionError("Should not be called")

    result = tool_fn()

    assert "permission" in result
    assert "role" in result.lower()


@patch("testgen.mcp.permissions.User")
def test_mcp_permission_catches_mcp_permission_denied(mock_user):
    """Decorator catches MCPPermissionDenied and returns str(e)."""
    user = MagicMock()
    user.is_global_admin = True
    mock_user.get.return_value = user
    set_mcp_username("admin")

    @mcp_permission("view")
    def tool_fn():
        raise MCPPermissionDenied("Access denied for testing")

    result = tool_fn()

    assert result == "Access denied for testing"


@patch("testgen.mcp.permissions.User")
def test_mcp_permission_resets_contextvar_after_call(mock_user):
    user = MagicMock()
    user.is_global_admin = True
    mock_user.get.return_value = user
    set_mcp_username("admin")

    @mcp_permission("view")
    def tool_fn():
        return "ok"

    tool_fn()

    assert _mcp_project_access.get() is _NOT_SET


@patch("testgen.mcp.permissions.User")
def test_mcp_permission_preserves_function_metadata(mock_user):
    user = MagicMock()
    user.is_global_admin = True
    mock_user.get.return_value = user

    @mcp_permission("view")
    def my_tool(x: int, y: str = "default") -> str:
        """Tool docstring."""
        return f"{x}-{y}"

    assert my_tool.__name__ == "my_tool"
    assert my_tool.__doc__ == "Tool docstring."
