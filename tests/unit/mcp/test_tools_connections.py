"""Tests for the core MCP connection tools — list / get / test.

The tools take a flavor-shaped ``connection_params`` dict (keyed by UI label)
plus an explicit ``connection_mode``; mapping + validation are delegated to
``connection_service``.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.database.connection_service import ConnectionStatus
from testgen.common.models.connection import Connection
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
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
    conn.connect_with_service_principal = overrides.get("connect_with_service_principal", False)
    conn.http_path = overrides.get("http_path", None)
    conn.warehouse = overrides.get("warehouse", None)
    conn.service_account_key = overrides.get("service_account_key", None)
    conn.max_threads = overrides.get("max_threads", 4)
    conn.max_query_chars = overrides.get("max_query_chars", None)
    return conn


def _stored_connection(**overrides) -> Connection:
    """Build a real, unsaved Connection standing in for one loaded from the database."""
    columns = {
        "connection_id": 7,
        "project_code": "demo",
        "connection_name": "Local PG",
        "sql_flavor": "postgresql",
        "sql_flavor_code": "postgresql",
        "project_host": "localhost",
        "project_port": "5432",
        "project_db": "testgen_local",
        "project_user": "testgen",
        "project_pw_encrypted": "stored_pw",
        "connect_by_url": False,
        "connect_by_key": False,
        "connect_with_identity": False,
        "connect_with_service_principal": False,
        "max_threads": 4,
        **overrides,
    }
    return Connection(**columns)


def _s3_access_keys_connection() -> Connection:
    return _stored_connection(
        connection_name="Claims bucket",
        sql_flavor="duckdb",
        sql_flavor_code="s3",
        project_host=None,
        project_port=None,
        project_db=None,
        project_user=None,
        project_pw_encrypted=None,
        max_threads=1,
        parameters={
            "base_uri": "s3://claims/landing",
            "region": "us-east-1",
            "strategy": "access_keys",
            "access_key_id": "AKIAEXAMPLE",
        },
        secrets={"secret_access_key": "stored-secret"},
    )


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


def test_test_connection_neither_id_nor_connection_type(db_session_mock):
    from testgen.mcp.tools.connections import test_connection

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        test_connection()
    msg = str(exc.value)
    assert "`connection_id`" in msg
    assert "`connection_type`" in msg


@patch(f"{MODULE}.resolve_connection")
def test_test_connection_rejects_connection_type_with_id(mock_resolve, db_session_mock):
    """sql_flavor override is meaningless on a stored connection — must reject loud."""
    mock_resolve.return_value = _mock_connection()

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        test_connection(connection_id=7, connection_type="Snowflake")
    assert "connection_type" in str(exc.value)


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="The connection was successful.", successful=True))
@patch(f"{MODULE}.resolve_connection")
def test_test_connection_with_id_only(mock_resolve, mock_runner, db_session_mock):
    mock_resolve.return_value = _stored_connection()

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
    """Overrides reach the test, and the stored connection keeps its values."""
    stored = _stored_connection(project_host="old.host")
    mock_resolve.return_value = stored

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        test_connection(connection_id=7, connection_params={"Host": "new.host", "Password": "tried"})

    tested = mock_runner.call_args.args[0]
    assert tested is not stored
    assert tested.project_host == "new.host"
    assert tested.project_pw_encrypted == "tried"
    assert stored.project_host == "old.host"
    assert stored.project_pw_encrypted == "stored_pw"


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="Access denied.", successful=False))
@patch(f"{MODULE}.resolve_connection")
def test_test_connection_mode_override_keeps_stored_secrets(mock_resolve, mock_runner, db_session_mock):
    """Switching the mode for a test drops the key pair from the tested copy only."""
    stored = _s3_access_keys_connection()
    mock_resolve.return_value = stored

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        test_connection(connection_id=7, connection_mode="IAM Role")

    tested = mock_runner.call_args.args[0]
    assert tested.parameters["strategy"] == "iam_role"
    assert "access_key_id" not in tested.parameters
    assert not tested.secrets
    assert stored.parameters == {
        "base_uri": "s3://claims/landing",
        "region": "us-east-1",
        "strategy": "access_keys",
        "access_key_id": "AKIAEXAMPLE",
    }
    assert stored.secrets == {"secret_access_key": "stored-secret"}


@patch(f"{MODULE}.test_connection_status")
@patch(f"{MODULE}.resolve_connection")
def test_test_connection_rejected_override_keeps_stored_values(mock_resolve, mock_runner, db_session_mock):
    """An override that fails validation leaves the stored connection as it was."""
    stored = _s3_access_keys_connection()
    mock_resolve.return_value = stored

    from testgen.mcp.tools.connections import test_connection

    with _patch_perms(), pytest.raises(MCPUserError):
        test_connection(connection_id=7, connection_params={"Base URI": "not-a-bucket"})

    mock_runner.assert_not_called()
    assert stored.parameters["base_uri"] == "s3://claims/landing"
    assert stored.secrets == {"secret_access_key": "stored-secret"}


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="The connection was successful.", successful=True))
def test_test_connection_inline_only(mock_runner, db_session_mock):
    """Inline settings build an unnamed Connection, which passes validation and reaches the test."""
    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        out = test_connection(
            connection_type="PostgreSQL",
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
    tested = mock_runner.call_args.args[0]
    assert isinstance(tested, Connection)
    assert tested.connection_name is None
    assert tested.project_host == "localhost"


@patch(f"{MODULE}.test_connection_status", return_value=ConnectionStatus(message="OK", successful=True))
def test_test_connection_inline_applies_defaults(mock_runner, db_session_mock):
    """Inline tests get the same flavor defaults as create."""
    from testgen.mcp.tools.connections import test_connection

    with _patch_perms():
        test_connection(
            connection_type="PostgreSQL",
            connection_params={"Host": "h", "Port": 5432, "Database": "d", "Username": "u", "Password": "p"},
        )

    assert mock_runner.call_args.args[0].max_query_chars == 20000


@patch(f"{MODULE}.test_connection_status")
@patch(f"{MODULE}.resolve_connection")
def test_test_connection_failure_renders_details(mock_resolve, mock_runner, db_session_mock):
    """Failure with detail string renders the detail verbatim in a code block."""
    mock_resolve.return_value = _stored_connection()
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
        test_connection(connection_type="PostgreSQL", connection_params={})
    msg = str(exc.value)
    assert "Cannot test connection" in msg
    assert "`Host` is required for PostgreSQL." in msg


def test_test_connection_inline_multi_mode_requires_mode(db_session_mock):
    """Inline test of a multi-mode flavor without connection_mode is rejected (not defaulted)."""
    from testgen.mcp.tools.connections import test_connection

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        test_connection(
            connection_type="Salesforce Data 360",
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
            connection_type="PostgreSQL",
            connection_params={"Host": "h", "Port": 5432, "Database": "d", "Username": "u", "Password": "p"},
        )

    inline.save.assert_not_called()


# ---------------------------------------------------------------------------
# list_connections
# ---------------------------------------------------------------------------


def _list_item(**overrides):
    from testgen.common.models.connection import ConnectionListItem

    return ConnectionListItem(
        connection_id=overrides.get("connection_id", 1),
        connection_name=overrides.get("connection_name", "warehouse_prod"),
        project_code=overrides.get("project_code", "demo"),
        sql_flavor_code=overrides.get("sql_flavor_code", "snowflake"),
        project_host=overrides.get("project_host", "abc.snowflakecomputing.com"),
        project_db=overrides.get("project_db", "ANALYTICS"),
        connect_by_url=overrides.get("connect_by_url", False),
        url=overrides.get("url"),
        parameters=overrides.get("parameters"),
        table_group_count=overrides.get("table_group_count", 4),
    )


@patch(f"{MODULE}.Connection.list_for_project")
def test_list_connections_returns_rows_with_display_label(mock_list, db_session_mock):
    mock_list.return_value = (
        [_list_item(project_host="warehouse-host.example.com")],
        1,
    )

    from testgen.mcp.tools.connections import list_connections

    with _patch_perms(permission="view"):
        out = list_connections("demo")

    assert "Connections for `demo`" in out
    assert "warehouse_prod" in out
    # Display label is rendered, NOT the raw sql_flavor_code:
    assert "Snowflake" in out
    assert "snowflake" not in out
    assert "`warehouse-host.example.com / ANALYTICS`" in out
    assert "4" in out  # table_group_count


@patch(f"{MODULE}.Connection.list_for_project")
def test_list_connections_locates_a_file_connection_by_its_storage_settings(mock_list, db_session_mock):
    blob = _list_item(
        sql_flavor_code="azure_blob",
        project_host=None,
        project_db=None,
        parameters={"storage_account": "claimsacct", "container": "claims", "strategy": "account_key"},
    )
    mock_list.return_value = ([blob], 1)

    from testgen.mcp.tools.connections import list_connections

    with _patch_perms(permission="view"):
        out = list_connections("demo")

    assert "`claimsacct / claims`" in out
    assert "account_key" not in out


@patch(f"{MODULE}.Connection.list_for_project")
def test_list_connections_pagination_footer(mock_list, db_session_mock):
    rows = [_list_item(connection_id=i, connection_name=f"c{i}") for i in range(1, 3)]
    mock_list.return_value = (rows, 25)

    from testgen.mcp.tools.connections import list_connections

    with _patch_perms(permission="view"):
        out = list_connections("demo", page=1, limit=2)

    assert "Showing 1\u20132 of 25" in out
    assert "Use `page=2`" in out


@patch(f"{MODULE}.Connection.list_for_project")
def test_list_connections_empty(mock_list, db_session_mock):
    mock_list.return_value = ([], 0)

    from testgen.mcp.tools.connections import list_connections

    with _patch_perms(permission="view"):
        out = list_connections("demo")

    assert "No connections" in out


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_connections_rejects_inaccessible_project(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"other": "role_a"}, permission="view", username="test_user",
    )

    from testgen.mcp.tools.connections import list_connections

    with pytest.raises(MCPResourceNotAccessible, match="Project `secret` not found or not accessible"):
        list_connections("secret")


def test_list_connections_invalid_limit_raises(db_session_mock):
    from testgen.mcp.tools.connections import list_connections

    with _patch_perms(permission="view"), pytest.raises(MCPUserError, match="Invalid limit"):
        list_connections("demo", limit=500)


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.resolve_connection")
def test_get_connection_returns_config_with_display_label(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_connection(
        sql_flavor_code="snowflake",
        connection_name="warehouse_prod",
        connection_id=12,
    )

    from testgen.mcp.tools.connections import get_connection

    with _patch_perms(permission="view"):
        out = get_connection(12)

    assert "Connection `warehouse_prod`" in out
    assert "**ID:** `12`" in out
    assert "**Type:** Snowflake" in out
    # The raw flavor code MUST NOT appear in the output
    assert "snowflake" not in out


@patch(f"{MODULE}.resolve_connection")
def test_get_connection_never_returns_secrets(mock_resolve, db_session_mock):
    """Password, private key, passphrase, service-account key must not leak.

    Uses a real ``Connection`` ORM instance so the test would fail if the rendering
    started reading the encrypted attributes (a MagicMock would silently return
    a ``MagicMock`` for any attribute, masking the regression).
    """
    from testgen.common.models.connection import Connection

    conn = Connection(
        id=uuid4(),
        connection_id=42,
        project_code="demo",
        connection_name="warehouse_prod",
        sql_flavor="postgresql",
        sql_flavor_code="postgresql",
        project_host="localhost",
        project_port="5432",
        project_db="testgen",
        project_user="dq_user",
        project_pw_encrypted="sentinel-password-hunter2",
        private_key="-----BEGIN PRIVATE KEY-----\nsentinel-private-key-body\n-----END PRIVATE KEY-----",
        private_key_passphrase="sentinel-passphrase",  # noqa: S106
        service_account_key={"client_email": "sentinel-account@example.com", "private_key": "sentinel-sak-key"},
    )
    mock_resolve.return_value = conn

    from testgen.mcp.tools.connections import get_connection

    with _patch_perms(permission="view"):
        out = get_connection(42)

    # Every populated secret value must NOT appear in output.
    for needle in (
        "sentinel-password-hunter2",
        "sentinel-private-key-body",
        "BEGIN PRIVATE KEY",
        "sentinel-passphrase",
        "sentinel-account@example.com",
        "sentinel-sak-key",
    ):
        assert needle not in out, f"secret material `{needle}` leaked into get_connection output"

    # The non-secret content we DO render should be present — sanity check that the
    # test is exercising the real rendering path (not silently bypassing it).
    assert "warehouse_prod" in out
    assert "localhost" in out


@patch(f"{MODULE}.resolve_connection")
def test_get_connection_authentication_password(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_connection(
        connect_by_key=False, connect_by_url=False, connect_with_identity=False,
    )

    from testgen.mcp.tools.connections import get_connection

    with _patch_perms(permission="view"):
        out = get_connection(42)

    assert "**Authentication:** Password" in out


@patch("testgen.mcp.tools.common.Connection")
def test_get_connection_raises_not_found_for_inaccessible(mock_conn_cls, db_session_mock):
    mock_conn_cls.get.return_value = None

    from testgen.mcp.tools.connections import get_connection

    with pytest.raises(MCPResourceNotAccessible, match="Connection .* not found or not accessible"):
        get_connection(999)
