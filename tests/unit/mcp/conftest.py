from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.permissions import set_mcp_token, set_mcp_username

# Fictional role matrix for tests. role_a has full access, role_c is restricted.
TEST_PERM_MATRIX = {
    "view": ["role_a", "role_b"],
    "catalog": ["role_a", "role_b", "role_c"],
}


def _test_roles_with_permission(permission):
    return TEST_PERM_MATRIX.get(permission, [])


@pytest.fixture(autouse=True)
def mcp_user():
    """Set up an authenticated MCP user for all tool tests.

    Default: user has 'role_a' on 'demo' project (full access).
    The @mcp_permission decorator passes for any permission.

    Tests needing scoped access patch _compute_project_permissions directly.
    """
    set_mcp_username("test_user")
    set_mcp_token("test_bearer_token")
    user = MagicMock()
    user.id = uuid4()

    membership = MagicMock()
    membership.project_code = "demo"
    membership.role = "role_a"

    with (
        patch("testgen.common.auth.authorize_token", return_value=user),
        patch("testgen.common.models.get_current_session", return_value=MagicMock()),
        patch("testgen.mcp.permissions.ProjectMembership") as mock_membership,
        patch("testgen.mcp.permissions.PluginHook") as mock_hook,
    ):
        mock_membership.get_memberships_for_user.return_value = [membership]
        mock_hook.instance.return_value.rbac.get_roles_with_permission.side_effect = (
            _test_roles_with_permission
        )
        yield user
    set_mcp_username(None)
    set_mcp_token(None)
