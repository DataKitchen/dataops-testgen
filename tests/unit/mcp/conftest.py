# Importing the fixture registers the autouse authenticated-MCP-user setup for these tests.
from unittest.mock import patch

import pytest

from testgen.testing.fixtures import mcp_user  # noqa: F401


@pytest.fixture(autouse=True)
def source_data_protection_off():
    """Read the protection setting as unset unless a test says otherwise.

    ``db_session_mock`` patches the session factory, so an unstubbed
    ``PersistedSetting.get`` returns a ``MagicMock``. That is not a protection
    level, and the accessor resolves an unreadable value to the most restrictive
    level — which would silently turn the mode on for every tool test. Tests that
    want the mode patch ``mcp_source_data_protected`` at the tool module, or
    ``PersistedSetting.get`` inside the test body, either of which wins over this.
    """
    with patch(
        "testgen.mcp.services.source_data_protection.PersistedSetting.get",
        return_value=None,
    ):
        yield
