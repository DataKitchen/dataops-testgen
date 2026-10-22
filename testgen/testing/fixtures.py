"""Reusable pytest fixtures for unit-testing TestGen.

Importable by the core test suite and any plugin test suite. To use, import the fixtures
you need into a ``conftest.py`` — pytest registers fixtures that are imported into a
conftest, preserving their ``autouse`` flag for that subtree::

    from testgen.testing.fixtures import db_session_mock, mcp_user  # noqa: F401
"""

import json
import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen import settings
from testgen.common.audit.sinks import AUDIT_LOG_FILE_NAME, get_sink
from testgen.mcp.permissions import set_mcp_username

# Fictional role matrix for tests. role_a has full access (but NOT view_pii — several
# tests rely on that to exercise the no-view_pii path), role_c is restricted, and
# role_d holds edit + view_pii so deny/allow pairs can be distinguished against a real
# ProjectPermissions without role_a accidentally granting view_pii.
TEST_PERM_MATRIX = {
    "view": ["role_a", "role_b"],
    "catalog": ["role_a", "role_b", "role_c"],
    "edit": ["role_a", "role_d"],
    "administer": ["role_a"],
    "view_pii": ["role_d"],
}


def _test_roles_with_permission(permission):
    return TEST_PERM_MATRIX.get(permission, [])


@pytest.fixture(autouse=True)
def patched_settings():
    with patch("testgen.settings.UI_BASE_URL", "http://tg-base-url"):
        yield


class AuditLog:
    """The audit records written during a test."""

    def __init__(self, folder: str) -> None:
        self.path = os.path.join(folder, AUDIT_LOG_FILE_NAME)

    def records(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path) as file:
            return [json.loads(line) for line in file]


@pytest.fixture(autouse=True)
def audit_log(tmp_path, monkeypatch):
    """Write audit records under ``tmp_path`` rather than the configured log folder."""
    folder = str(tmp_path / "log")
    monkeypatch.setattr(settings, "LOG_FILE_PATH", folder)
    monkeypatch.setattr(settings, "AUDIT_LOG_ENABLED", True)
    get_sink.cache_clear()
    yield AuditLog(folder)
    if get_sink.cache_info().currsize and (close := getattr(get_sink(), "close", None)):
        close()
    get_sink.cache_clear()


@pytest.fixture
def db_session_mock():
    with patch("testgen.common.models.Session") as factory_mock:
        yield factory_mock().__enter__()


@pytest.fixture(autouse=True)
def mcp_user():
    """Set up an authenticated MCP user for all tool tests.

    Default: user has 'role_a' on 'demo' project (full access).
    The @mcp_permission decorator passes for any permission.

    Tests needing scoped access patch _compute_project_permissions directly.
    """
    set_mcp_username("test_user")
    user = MagicMock()
    user.id = uuid4()
    user.name = None

    membership = MagicMock()
    membership.project_code = "demo"
    membership.role = "role_a"

    with (
        patch("testgen.common.auth.authorize_user", return_value=user),
        # Patch the session factory, not ``get_current_session``. ``database_session()``
        # calls ``get_current_session()`` to detect nesting, so a truthy return there makes
        # it reuse that value and never install a session in the thread-local — leaving
        # ``get_current_session()`` returning None everywhere except the one module the
        # patch was applied to. Patching the factory lets the real machinery install the
        # mock session, so every module resolves it no matter when it was imported.
        # A test wanting to assert against the session requests ``db_session_mock``, whose
        # patch is applied after this one and therefore wins.
        patch("testgen.common.models.Session"),
        patch("testgen.mcp.permissions.ProjectMembership") as mock_membership,
        patch("testgen.mcp.permissions.PluginHook") as mock_hook,
    ):
        mock_membership.get_memberships_for_user.return_value = [membership]
        mock_hook.instance.return_value.rbac.get_roles_with_permission.side_effect = (
            _test_roles_with_permission
        )
        yield user
    set_mcp_username(None)
