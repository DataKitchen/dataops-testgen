"""Tests for the MCP connection CRUD tools — create / update / test.

The tools take a flavor-shaped ``connection_params`` dict (keyed by UI label)
plus an explicit ``connection_mode``; mapping + validation are delegated to
``connection_service``.
"""

from unittest.mock import MagicMock, patch

import pytest

from testgen.common.database.connection_service import ConnectionStatus
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.connections"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _patch_perms(allowed=("demo",), memberships=None, permission="administer"):
    """Inject a ProjectPermissions for the given access set."""
    memberships = memberships or dict.fromkeys(allowed, "role_a")
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships=memberships, permission=permission, username="test_user",
        ),
    )


def _mock_connection(**overrides) -> MagicMock:
    """Build a MagicMock matching the Connection model surface used by the tools."""
    conn = MagicMock()
    conn.connection_id = overrides.get("connection_id", 42)
    conn.project_code = overrides.get("project_code", "demo")
    conn.connection_name = overrides.get("connection_name", "Local PG")
    conn.sql_flavor = overrides.get("sql_flavor", "postgresql")
    conn.sql_flavor_code = overrides.get("sql_flavor_code", "postgresql")
    conn.project_host = overrides.get("project_host", "localhost")
    conn.project_port = overrides.get("project_port", "5432")
    conn.project_db = overrides.get("project_db", "testgen_local")
    conn.project_user = overrides.get("project_user", "testgen")
    conn.project_pw_encrypted = overrides.get("project_pw_encrypted", "stored_pw")
    conn.connect_by_url = overrides.get("connect_by_url", False)
    conn.url = overrides.get("url", None)
    conn.connect_by_key = overrides.get("connect_by_key", False)
    conn.private_key = overrides.get("private_key", None)
    conn.private_key_passphrase = overrides.get("private_key_passphrase", None)
    conn.connect_with_identity = overrides.get("connect_with_identity", False)
    conn.http_path = overrides.get("http_path", None)
    conn.warehouse = overrides.get("warehouse", None)
    conn.service_account_key = overrides.get("service_account_key", None)
    conn.max_threads = overrides.get("max_threads", 4)
    conn.max_query_chars = overrides.get("max_query_chars", None)
    return conn


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


def test_test_connection_neither_id_nor_flavor(db_session_mock):
    from testgen.mcp.tools.connections import test_connection

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        test_connection()
    msg = str(exc.value)
    assert "`connection_id`" in msg
    assert "`sql_flavor`" in msg


@patch(f"{MODULE}.resolve_connection")
def test_test_connection_rejects_sql_flavor_with_id(mock_resolve, db_session_mock):
    """sql_flavor override is meaningless on a stored connection — must reject loud."""
    mock_resolve.return_value = _mock_connection()

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        test_connection(connection_id=7, sql_flavor="Snowflake")
    assert "sql_flavor" in str(exc.value)


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="The connection was successful.", successful=True))
@patch(f"{MODULE}.resolve_connection")
def test_test_connection_with_id_only(mock_resolve, mock_runner, db_session_mock):
    conn = _mock_connection(connection_id=7, connection_name="Local PG", project_host="localhost")
    mock_resolve.return_value = conn

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        out = test_connection(connection_id=7)

    assert "Connection test succeeded" in out
    assert "**ID:** `7`" in out
    assert "**Name:** `Local PG`" in out
    assert "**Type:** PostgreSQL" in out
    mock_runner.assert_called_once()


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="The connection was successful.", successful=True))
@patch(f"{MODULE}.resolve_connection")
def test_test_connection_with_id_and_overrides(mock_resolve, mock_runner, db_session_mock):
    """Overrides win: assigned to the loaded connection before status runs."""
    conn = _mock_connection(connection_id=7, project_host="old.host")
    mock_resolve.return_value = conn

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        test_connection(connection_id=7, connection_params={"Host": "new.host"})

    assert conn.project_host == "new.host"


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="The connection was successful.", successful=True))
@patch(f"{MODULE}.Connection")
def test_test_connection_inline_only(mock_conn_cls, mock_runner, db_session_mock):
    """No connection_id supplied → builds an inline Connection from args."""
    inline_conn = _mock_connection()
    mock_conn_cls.return_value = inline_conn

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        out = test_connection(
            sql_flavor="PostgreSQL",
            connection_params={
                "Host": "localhost",
                "Port": 5432,
                "Database": "d",
                "Username": "u",
                "Password": "p",
            },
        )

    assert "Connection test succeeded" in out
    # No ID/Name lines on inline tests (no entity).
    assert "**ID:**" not in out
    assert "**Name:**" not in out
    mock_runner.assert_called_once()


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="OK", successful=True))
@patch(f"{MODULE}.Connection")
def test_test_connection_inline_applies_defaults(mock_conn_cls, mock_runner, db_session_mock):
    """Inline tests get the same flavor defaults as create."""
    inline = _mock_connection(max_query_chars=None)
    mock_conn_cls.return_value = inline

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        test_connection(
            sql_flavor="PostgreSQL",
            connection_params={"Host": "h", "Port": 5432, "Database": "d", "Username": "u", "Password": "p"},
        )

    assert inline.max_query_chars == 20000


@patch(f"{MODULE}.test_connection_status")
@patch(f"{MODULE}.resolve_connection")
def test_test_connection_failure_renders_details(mock_resolve, mock_runner, db_session_mock):
    """Failure with detail string renders the detail verbatim in a code block."""
    mock_resolve.return_value = _mock_connection()
    driver_text = "FATAL: password authentication failed for user 'dq'"
    mock_runner.return_value = ConnectionStatus(
        message="Error attempting the connection.",
        successful=False,
        details=driver_text,
    )

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        out = test_connection(connection_id=7)

    assert "Connection test failed" in out
    assert driver_text in out  # verbatim, no scrubbing


def test_test_connection_inline_validation_failure(db_session_mock):
    """Inline test with missing required field rejects before opening any DB connection."""
    from testgen.mcp.tools.connections import test_connection

    # PostgreSQL inline with no params -> uses a real Connection (no patch) with empty fields.
    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        test_connection(sql_flavor="PostgreSQL", connection_params={})
    msg = str(exc.value)
    assert "Cannot test connection" in msg
    assert "`Host` is required for PostgreSQL." in msg


def test_test_connection_inline_multi_mode_requires_mode(db_session_mock):
    """Inline test of a multi-mode flavor without connection_mode is rejected (not defaulted)."""
    from testgen.mcp.tools.connections import test_connection

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        test_connection(
            sql_flavor="Salesforce Data 360",
            connection_params={"Login URL": "https://my.salesforce.com", "Consumer Key": "ck"},
        )
    msg = str(exc.value)
    assert "requires a connection_mode" in msg
    assert "JWT Bearer Flow" in msg and "Client Credentials Flow" in msg


@patch(f"{MODULE}.test_connection_status")
@patch(f"{MODULE}.Connection")
def test_test_connection_inline_does_not_save(mock_conn_cls, mock_runner, db_session_mock):
    """Inline test never persists — the constructed connection is not saved."""
    inline = _mock_connection()
    mock_conn_cls.return_value = inline
    mock_runner.return_value = ConnectionStatus(message="OK", successful=True)

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        test_connection(
            sql_flavor="PostgreSQL",
            connection_params={"Host": "h", "Port": 5432, "Database": "d", "Username": "u", "Password": "p"},
        )

    inline.save.assert_not_called()
