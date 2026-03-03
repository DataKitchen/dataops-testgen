from unittest.mock import MagicMock, patch

import pytest

from testgen.mcp.permissions import set_mcp_username


@pytest.fixture(autouse=True)
def mcp_user():
    """Set up an authenticated MCP user for all tool tests.

    Patches User.get to return a global admin by default (no filtering).
    The @mcp_permission decorator calls get_current_mcp_user() which uses
    User.get, then get_allowed_project_codes() which returns None for
    global admins — so the ContextVar is set to None (no project filtering).

    Individual tests can patch get_allowed_project_codes to simulate
    scoped access.
    """
    set_mcp_username("test_user")
    user = MagicMock()
    user.is_global_admin = True
    with patch("testgen.mcp.permissions.User") as mock_user_cls:
        mock_user_cls.get.return_value = user
        yield user
    set_mcp_username(None)
