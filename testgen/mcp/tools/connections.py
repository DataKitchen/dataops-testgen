"""MCP tools for database connections — list, get, and test database connections.

The per-flavor connection shape (which auth modes exist and which ``connection_params`` keys
each needs) lives in ``testgen.common.database.connection_service`` and is exposed to the
model through the ``testgen://connection-parameters/{flavor}`` resource. Validation and
auth-path normalization are delegated to that same module so the rules stay in one place.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from testgen.common.database.connection_service import (
    apply_connection_defaults,
    normalize_auth_fields,
    test_connection_status,
)
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    SQL_FLAVOR_CODE_TO_LABEL,
    DocGroup,
    apply_connection_params,
    effective_mode,
    format_flavor_label,
    format_page_footer,
    format_page_info,
    parse_sql_flavor,
    raise_validation_error,
    render_connection_body,
    resolve_connection,
    validate_connection_fields,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MANAGE


@with_database_session
@mcp_permission("view")
def list_connections(
    project_code: Annotated[str, Field(description="The project code to list connections for.")],
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
    limit: Annotated[int, Field(description="Page size (default 20, max 100).")] = 20,
) -> str:
    """List database connections in a project.
    Each connection carries its database type and table-group counts.
    Use this before changing or referencing a connection to confirm its ID, name, and host.
    Credentials are never returned.
    """
    validate_page(page)
    validate_limit(limit, 100)

    perms = get_project_permissions()
    perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))

    rows, total = Connection.list_for_project(project_code, page=page, limit=limit)

    if not rows:
        if page > 1:
            return f"No connections on page {page} (total: {total})."
        return f"No connections found for project `{project_code}`."

    doc = MdDoc()
    doc.heading(1, f"Connections for `{project_code}`")
    doc.text(format_page_info(total, page, limit))
    table_rows: list[list[object]] = []
    for row in rows:
        table_rows.append(
            [
                row.connection_id,
                row.connection_name,
                format_flavor_label(row.sql_flavor_code),
                row.project_host,
                row.project_db,
                row.table_group_count,
            ]
        )
    doc.table(
        ["ID", "Name", "Type", "Host", "Database", "Table groups"],
        table_rows,
        code=[0, 3, 4],
    )
    if footer := format_page_footer(total, page, limit):
        doc.text(footer)
    return doc.render()


@with_database_session
@mcp_permission("view")
def get_connection(
    connection_id: Annotated[int, Field(description="Bigint connection ID returned by `list_connections`.")],
) -> str:
    """Get a connection's configuration.
    Includes database type, host, and authentication mode.
    Credentials (password, private key, service-account key) are never returned.
    Use this before editing a connection or creating a table group on it.
    """
    connection = resolve_connection(connection_id)
    doc = MdDoc()
    doc.heading(1, f"Connection `{connection.connection_name}`")
    render_connection_body(doc, connection)
    return doc.render()


@with_database_session
@mcp_permission("administer")
def test_connection(
    connection_id: Annotated[
        int | None,
        Field(description="Stored connection ID, e.g. from ``get_data_inventory``. Omit for inline tests."),
    ] = None,
    sql_flavor: Annotated[
        str | None,
        Field(
            description="SQL Database flavor. Required for inline tests; not accepted when ``connection_id`` is set.",
        ),
    ] = None,
    connection_params: Annotated[
        dict | None,
        Field(description="Connection field values. For a stored connection, omitted fields keep their stored value."),
    ] = None,
    connection_mode: Annotated[str | None, Field(description="Authentication mode for multi-mode flavors.")] = None,
) -> str:
    """Test connectivity against a stored or inline-supplied connection.

    Two call shapes: pass ``connection_id`` to test a stored connection
    (``connection_params`` / ``connection_mode`` override the stored values for
    the test only, nothing is saved); or pass ``sql_flavor`` plus
    ``connection_params`` (and ``connection_mode`` for multi-mode flavors) to
    test inline without persisting. See the
    ``testgen://connection-parameters/{flavor}`` resource for each flavor's
    ``connection_mode`` values and ``connection_params`` keys.
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
        mode = connection_mode if inline else effective_mode(connection, connection_mode)
        apply_connection_params(connection, connection.sql_flavor_code, mode, connection_params or {})

    normalize_auth_fields(connection)
    # No-op for stored connections; keeps the inline-test contract identical to create.
    apply_connection_defaults(connection)

    errors = validate_connection_fields(connection)
    if errors:
        raise_validation_error(errors, "Cannot test connection. Required fields missing or invalid.")

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
