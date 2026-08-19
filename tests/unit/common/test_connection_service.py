"""Tests for the connection_service common-layer module.

Domain only: ``ConnectionStatus`` (with its load-bearing random field), the
``test_connection_status`` runner, and auth-path normalization. The label-bearing
connection-parameter schema / validation lives in ``mcp/tools/common.py`` and is
tested in ``tests/unit/mcp/test_connection_schema.py``.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import DatabaseError, DBAPIError

from testgen.common.database.connection_service import (
    ConnectionStatus,
    apply_connection_defaults,
    normalize_auth_fields,
)

# Aliased on import so pytest doesn't try to collect the ``test_*`` function as a test.
from testgen.common.database.connection_service import test_connection_status as run_connection_test
from testgen.common.models.connection import Connection

pytestmark = pytest.mark.unit

MODULE = "testgen.common.database.connection_service"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conn(**overrides) -> Connection:
    """Build a Connection without touching the DB. Defaults to a complete PG config."""
    defaults = {
        "sql_flavor": "postgresql",
        "sql_flavor_code": "postgresql",
        "connection_name": "My DB",
        "project_host": "localhost",
        "project_port": "5432",
        "project_db": "testgen_local",
        "project_user": "testgen",
        "project_pw_encrypted": "pw",
        "connect_by_url": False,
        "connect_by_key": False,
        "connect_with_identity": False,
        "connect_with_service_principal": False,
        "max_threads": 4,
        "max_query_chars": 20000,
    }
    defaults.update(overrides)
    return Connection(**defaults)


# ---------------------------------------------------------------------------
# ConnectionStatus dataclass
# ---------------------------------------------------------------------------


def test_connection_status_random_field_breaks_equality():
    """Two instances with identical (message, successful, details) MUST compare unequal.

    The random ``_`` field is required so Streamlit's reactive system re-renders
    on repeated failed-test clicks producing the same error. Removing the field
    would silently swallow the second click.
    """
    a = ConnectionStatus(message="Error attempting the connection.", successful=False, details="boom")
    b = ConnectionStatus(message="Error attempting the connection.", successful=False, details="boom")
    assert a != b


# ---------------------------------------------------------------------------
# test_connection_status — happy path and exception branches
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.fetch_from_target_db", return_value=[{"col": 1}])
@patch(f"{MODULE}.get_flavor_service")
def test_connection_status_success(mock_flavor, mock_fetch, mock_empty_cache):
    mock_flavor.return_value.test_query = "SELECT 1"

    status = run_connection_test(_conn())

    assert status.successful is True
    assert status.message == "The connection was successful."
    assert status.details is None
    mock_empty_cache.assert_called_once()  # service owns the cache reset


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.fetch_from_target_db", return_value=[{"col": 0}])
@patch(f"{MODULE}.get_flavor_service")
def test_connection_status_query_returns_wrong_result(mock_flavor, mock_fetch, mock_empty_cache):
    """``SELECT 1`` returns something other than 1 → 'Error completing a query'."""
    mock_flavor.return_value.test_query = "SELECT 1"

    status = run_connection_test(_conn())

    assert status.successful is False
    assert status.message == "Error completing a query to the database server."


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.fetch_from_target_db", side_effect=KeyError("host"))
@patch(f"{MODULE}.get_flavor_service")
def test_connection_status_key_error(mock_flavor, mock_fetch, mock_empty_cache):
    """Missing required field → 'Complete all the required fields.'"""
    mock_flavor.return_value.test_query = "SELECT 1"

    status = run_connection_test(_conn())

    assert status.successful is False
    assert status.message == "Error attempting the connection. "
    assert status.details == "Complete all the required fields."


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}.fetch_from_target_db")
def test_connection_status_database_error(mock_fetch, mock_flavor, mock_empty_cache):
    mock_flavor.return_value.test_query = "SELECT 1"
    orig = Exception("FATAL: password authentication failed")
    mock_fetch.side_effect = DatabaseError("stmt", {}, orig)

    status = run_connection_test(_conn())

    assert status.successful is False
    assert status.message == "Error attempting the connection."
    assert "password authentication failed" in str(status.details)


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}.fetch_from_target_db")
def test_connection_status_dbapi_error(mock_fetch, mock_flavor, mock_empty_cache):
    mock_flavor.return_value.test_query = "SELECT 1"
    orig = Exception("driver-level failure")
    mock_fetch.side_effect = DBAPIError("stmt", {}, orig)

    status = run_connection_test(_conn())

    assert status.successful is False
    assert status.message == "Error attempting the connection."
    assert "driver-level failure" in str(status.details)


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}.fetch_from_target_db")
def test_connection_status_open_ssl_error(mock_fetch, mock_flavor, mock_empty_cache):
    """A TypeError whose args[1][0] is an OpenSSLError uses args[0] as details."""
    mock_flavor.return_value.test_query = "SELECT 1"

    class OpenSSLError:  # name matches what is_open_ssl_error sniffs for
        pass

    err = TypeError("bad key", [OpenSSLError()])
    mock_fetch.side_effect = err

    status = run_connection_test(_conn())

    assert status.successful is False
    assert status.message == "Error attempting the connection."
    assert status.details == "bad key"


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}.fetch_from_target_db")
def test_connection_status_missing_private_key(mock_fetch, mock_flavor, mock_empty_cache):
    """connect_by_key=True with no private_key → 'The private key is missing.'"""
    mock_flavor.return_value.test_query = "SELECT 1"
    mock_fetch.side_effect = RuntimeError("something")

    conn = _conn(sql_flavor="snowflake", sql_flavor_code="snowflake", connect_by_key=True, private_key=None)
    status = run_connection_test(conn)

    assert status.successful is False
    assert status.message == "Error attempting the connection."
    assert status.details == "The private key is missing."


@patch(f"{MODULE}.empty_cache")
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}.fetch_from_target_db")
def test_connection_status_generic_exception(mock_fetch, mock_flavor, mock_empty_cache):
    mock_flavor.return_value.test_query = "SELECT 1"
    mock_fetch.side_effect = RuntimeError("unexpected")

    status = run_connection_test(_conn())

    assert status.successful is False
    assert status.message == "Error attempting the connection."
    assert status.details == "Something went wrong while testing the connection."


# ---------------------------------------------------------------------------
# normalize_auth_fields
# ---------------------------------------------------------------------------


def test_normalize_clears_password_when_connect_by_key_non_databricks():
    """Snowflake connect_by_key=True → project_pw_encrypted cleared."""
    conn = _conn(
        sql_flavor_code="snowflake",
        sql_flavor="snowflake",
        connect_by_key=True,
        project_pw_encrypted="old_pw",
        private_key="key",
    )
    normalize_auth_fields(conn)
    assert conn.project_pw_encrypted in (None, "")
    assert conn.private_key == "key"  # untouched


def test_normalize_keeps_password_for_databricks_connect_by_key():
    """Databricks OAuth uses connect_by_key but stores the secret in project_pw_encrypted."""
    conn = _conn(
        sql_flavor_code="databricks",
        sql_flavor="databricks",
        connect_by_key=True,
        project_pw_encrypted="client_secret_xyz",
    )
    normalize_auth_fields(conn)
    assert conn.project_pw_encrypted == "client_secret_xyz"
    assert not conn.private_key
    assert not conn.private_key_passphrase


def test_normalize_clears_private_key_fields_when_password_auth():
    """connect_by_key=False → private_key + passphrase cleared."""
    conn = _conn(
        sql_flavor_code="snowflake",
        sql_flavor="snowflake",
        connect_by_key=False,
        private_key="old_key",
        private_key_passphrase="old_phrase",  # noqa: S106
    )
    normalize_auth_fields(conn)
    assert not conn.private_key
    assert not conn.private_key_passphrase


def test_normalize_clears_user_password_when_identity():
    """connect_with_identity=True → project_user + project_pw_encrypted cleared."""
    conn = _conn(
        sql_flavor_code="azure_mssql",
        sql_flavor="mssql",
        connect_with_identity=True,
        project_user="leftover_user",
        project_pw_encrypted="leftover_pw",
    )
    normalize_auth_fields(conn)
    assert not conn.project_user
    assert not conn.project_pw_encrypted


def test_normalize_rejects_both_identity_and_service_principal():
    """Hard fail: the two Entra ID auth flags are mutually exclusive."""
    conn = _conn(
        sql_flavor_code="azure_mssql",
        sql_flavor="mssql",
        connect_with_identity=True,
        connect_with_service_principal=True,
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        normalize_auth_fields(conn)


def test_normalize_preserves_user_password_when_service_principal():
    """SPN mode reuses project_user (client_id@tenant_id) and project_pw_encrypted (client secret)."""
    conn = _conn(
        sql_flavor_code="azure_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
        project_user="cid@tid",
        project_pw_encrypted="csec",
    )
    normalize_auth_fields(conn)
    assert conn.project_user == "cid@tid"
    assert conn.project_pw_encrypted == "csec"


@pytest.mark.parametrize("code", ["mssql", "postgresql", "snowflake"])
def test_normalize_rejects_service_principal_on_unsupported_flavor(code):
    """SPN is only supported on azure_mssql, synapse_mssql, and onelake_mssql. Guard against stale flag elsewhere."""
    conn = _conn(
        sql_flavor_code=code,
        sql_flavor="mssql" if code == "mssql" else code,
        connect_with_service_principal=True,
    )
    with pytest.raises(ValueError, match="azure_mssql"):
        normalize_auth_fields(conn)


def test_normalize_accepts_service_principal_on_synapse_mssql():
    """Synapse's SQL endpoint is Entra-aware and honors the same ODBC ``ActiveDirectoryServicePrincipal`` keyword as Azure SQL DB."""
    conn = _conn(
        sql_flavor_code="synapse_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
        project_user="cid@tid",
        project_pw_encrypted="csec",
    )
    normalize_auth_fields(conn)
    assert conn.project_user == "cid@tid"
    assert conn.project_pw_encrypted == "csec"


def test_normalize_accepts_service_principal_on_onelake_mssql():
    """SPN is a first-class auth mode on OneLake — Fabric SQL rejects SQL logins."""
    conn = _conn(
        sql_flavor_code="onelake_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
        project_user="cid@tid",
        project_pw_encrypted="csec",
    )
    normalize_auth_fields(conn)
    assert conn.project_user == "cid@tid"
    assert conn.project_pw_encrypted == "csec"


def test_normalize_rejects_service_principal_with_connect_by_url():
    """SPN + URL is unsupported — the flavor URL header drops the Authentication keyword."""
    conn = _conn(
        sql_flavor_code="azure_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
        connect_by_url=True,
        url="host.example:1433/db",
    )
    with pytest.raises(ValueError, match="connect_by_url"):
        normalize_auth_fields(conn)


# ---------------------------------------------------------------------------
# apply_connection_defaults
# ---------------------------------------------------------------------------


def test_defaults_fill_max_query_chars():
    conn = _conn(max_query_chars=None)
    apply_connection_defaults(conn)
    assert conn.max_query_chars == 20000


def test_defaults_salesforce_lower_max_query_chars():
    """Salesforce Data 360's Hyper engine gets the lower 15000 default."""
    conn = _conn(sql_flavor="salesforce_data360", sql_flavor_code="salesforce_data360", max_query_chars=None)
    apply_connection_defaults(conn)
    assert conn.max_query_chars == 15000


def test_defaults_keep_explicit_max_query_chars():
    conn = _conn(max_query_chars=30000)
    apply_connection_defaults(conn)
    assert conn.max_query_chars == 30000
