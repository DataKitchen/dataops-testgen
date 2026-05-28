"""MCP tools for database connection — create, update, and test database connections.

Each tool gates on the ``administer`` permission. The per-flavor connection shape
(which auth modes exist and which ``connection_params`` keys each needs) lives in
``testgen.common.database.connection_service`` and is exposed to the model through
the ``testgen://connection-parameters/{flavor}`` resource. Validation and
auth-path normalization are delegated to that same module so the rules stay in
one place.
"""

from __future__ import annotations

from typing import Any

from testgen.common.database.connection_service import (
    apply_connection_defaults,
    normalize_auth_fields,
    test_connection_status,
)
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    SQL_FLAVOR_CODE_TO_LABEL,
    apply_connection_params,
    connection_display_fields,
    connection_field_labels,
    infer_mode,
    parse_sql_flavor,
    resolve_connection,
    validate_connection_fields,
)
from testgen.mcp.tools.markdown import MdDoc


@with_database_session
@mcp_permission("administer")
def test_connection(
    connection_id: int | None = None,
    sql_flavor: str | None = None,
    connection_params: dict | None = None,
    connection_mode: str | None = None,
) -> str:
    """Test connectivity against a stored or inline-supplied connection.

    Two call shapes: pass ``connection_id`` to test a stored connection
    (``connection_params`` / ``connection_mode`` override the stored values for
    the test only, nothing is saved); or pass ``sql_flavor`` plus
    ``connection_params`` (and ``connection_mode`` for multi-mode flavors) to
    test inline without persisting. See the
    ``testgen://connection-parameters/{flavor}`` resource for each flavor's
    ``connection_mode`` values and ``connection_params`` keys.

    Args:
        connection_id: Stored connection ID, e.g. from ``get_data_inventory``.
            Omit for inline tests.
        sql_flavor: SQL Database flavor. Required for inline tests; not accepted
            when ``connection_id`` is set.
        connection_params: Connection field values. For a stored connection,
            omitted fields keep their stored value.
        connection_mode: Authentication mode for multi-mode flavors.
    """
    if connection_id is None and sql_flavor is None:
        raise MCPUserError(
            "Provide `connection_id` to test an existing connection, "
            "or `sql_flavor` plus `connection_params` to test inline."
        )

    connection: Connection | None = None
    if connection_id is not None:
        if sql_flavor is not None:
            raise MCPUserError(
                "`sql_flavor` cannot be overridden when `connection_id` is set "
                "— database type is immutable on an existing connection."
            )
        connection = resolve_connection(connection_id)

    inline = connection is None
    if connection is None:
        _, code, family = parse_sql_flavor(sql_flavor)  # type: ignore[arg-type]
        connection = Connection(sql_flavor=family, sql_flavor_code=code)

    if connection_params is not None or connection_mode is not None:
        mode = connection_mode if inline else _effective_mode(connection, connection_mode)
        apply_connection_params(connection, connection.sql_flavor_code, mode, connection_params or {})

    normalize_auth_fields(connection)
    # No-op for stored connections; keeps the inline-test contract identical to create.
    apply_connection_defaults(connection)

    errors = validate_connection_fields(connection)
    if errors:
        _raise_validation_error(errors, "Cannot test connection. Required fields missing or invalid.")

    status = test_connection_status(connection)

    doc = MdDoc()
    heading = "Connection test succeeded" if status.successful else "Connection test failed"
    doc.heading(1, heading)

    if connection_id is not None:
        doc.field("ID", connection.connection_id, code=True)
        if connection.connection_name:
            doc.field("Name", connection.connection_name, code=True)
    label = SQL_FLAVOR_CODE_TO_LABEL.get(connection.sql_flavor_code)
    doc.field("Type", label.value if label else connection.sql_flavor_code)
    if connection.project_host:
        doc.field("Host", connection.project_host, code=True)

    doc.text(status.message)
    if status.details:
        doc.code_block(status.details)
    return doc.render()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _effective_mode(connection: Connection, connection_mode: str | None) -> str | None:
    """Mode label to apply: the explicit override, else the connection's current mode."""
    if connection_mode is not None:
        return connection_mode
    inferred = infer_mode(connection)
    return str(inferred) if inferred is not None else None


def _raise_validation_error(errors: list[str], header: str) -> None:
    bullets = "\n".join(f"- {err}" for err in errors)
    raise MCPUserError(f"{header}\n\n{bullets}")


def _render_created_connection(connection: Connection) -> str:
    doc = MdDoc()
    doc.heading(1, f"Connection `{connection.connection_name}` created")
    doc.field("ID", connection.connection_id, code=True)
    doc.field("Project", connection.project_code, code=True)
    label = SQL_FLAVOR_CODE_TO_LABEL.get(connection.sql_flavor_code)
    doc.field("Type", label.value if label else connection.sql_flavor_code)

    # Render each populated, non-secret field under its flavor-specific label
    # (e.g. "Catalog" for Databricks, "Login URL" for Salesforce).
    for fld in connection_display_fields(connection):
        if fld.secret:
            continue
        value = getattr(connection, fld.column, None)
        if value in (None, ""):
            continue
        doc.field(fld.label, value, code=fld.column != "project_port")

    doc.field("Authentication", _authentication_label(connection))
    if connection.max_threads is not None:
        doc.field("Max Threads", connection.max_threads)
    if connection.max_query_chars is not None:
        doc.field("Max Expression Length", connection.max_query_chars)

    return doc.render()


def _authentication_label(connection: Connection) -> str:
    """The connection's auth method: the active connection mode for multi-mode
    flavors, else the implicit method (service account key, else password).
    """
    mode = infer_mode(connection)
    if mode is not None:
        return str(mode)
    if connection.service_account_key:
        return "Service Account Key"
    return "Password"


def _snapshot(connection: Connection) -> dict[str, Any]:
    return {attr: getattr(connection, attr, None) for attr in _DIFF_ATTRS}


def _render_field_value(attr: str, value: Any) -> str | None:
    if attr == "sql_flavor_code" and value is not None:
        return SQL_FLAVOR_CODE_TO_LABEL.get(value, value).value
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None or value == "":
        return None
    return str(value)


_DIFF_ATTRS: tuple[str, ...] = (
    "connection_name",
    "sql_flavor_code",
    "project_host",
    "project_port",
    "project_db",
    "project_user",
    "project_pw_encrypted",
    "url",
    "connect_by_url",
    "connect_by_key",
    "private_key",
    "private_key_passphrase",
    "connect_with_identity",
    "warehouse",
    "http_path",
    "service_account_key",
    "max_threads",
    "max_query_chars",
)

_DIFF_LABELS: dict[str, str] = {
    "connection_name": "Name",
    "sql_flavor_code": "Type",
    "project_host": "Host",
    "project_port": "Port",
    "project_db": "Database",
    "project_user": "Username",
    "project_pw_encrypted": "Password",
    "url": "URL",
    "connect_by_url": "Connect by URL",
    "connect_by_key": "Connect by Key-Pair",
    "private_key": "Private Key",
    "private_key_passphrase": "Private Key Passphrase",
    "connect_with_identity": "Connect with Managed Identity",
    "warehouse": "Warehouse",
    "http_path": "HTTP Path",
    "service_account_key": "Service Account Key",
    "max_threads": "Max Threads",
    "max_query_chars": "Max Expression Length",
}

_ATTR_IS_SECRET: dict[str, bool] = {
    "project_pw_encrypted": True,
    "private_key": True,
    "private_key_passphrase": True,
    "service_account_key": True,
}
