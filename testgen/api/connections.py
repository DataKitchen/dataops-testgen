"""API v1 — connection reads."""

from fastapi import APIRouter, Depends, Query

from testgen.api.deps import db_session, resolve_connection, resolve_project_code
from testgen.api.enums import AUTHENTICATION_FROM_MODE
from testgen.api.schemas import (
    ConnectionItem,
    ConnectionListResponse,
    ConnectionResponse,
    ErrorResponse,
)
from testgen.common.connection_schema import (
    authentication_method,
    connection_display_values,
    settings_key,
)
from testgen.common.flavors import FLAVOR_CODE_TO_LABEL
from testgen.common.models.connection import Connection

_error_responses = {404: {"model": ErrorResponse, "description": "Not found"}}

router = APIRouter(tags=["Connections"], dependencies=[Depends(db_session, scope="function")], responses=_error_responses)


@router.get(
    "/projects/{project_code}/connections",
    response_model=ConnectionListResponse,
    summary="List connections",
)
def list_connections(
    project_code: str = resolve_project_code("view"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Connections in a project, each with the number of table groups defined on it.

    Connection parameters are not included — read a single connection for those.
    """
    rows, total = Connection.list_for_project(project_code, page=page, limit=limit)
    return ConnectionListResponse(
        items=[
            ConnectionItem(
                connection_id=row.connection_id,
                connection_name=row.connection_name,
                project_code=row.project_code,
                connection_type=FLAVOR_CODE_TO_LABEL[row.sql_flavor_code],
                table_group_count=row.table_group_count,
            )
            for row in rows
        ],
        page=page,
        limit=limit,
        total=total,
    )


@router.get(
    "/connections/{connection_id}",
    response_model=ConnectionResponse,
    summary="Read a connection",
)
def get_connection(connection: Connection = resolve_connection("view")):  # noqa: B008
    """A connection's configuration, including the parameters used to reach its data source.

    The keys under ``settings`` depend on the connection type and authentication method —
    a Databricks connection carries ``catalog`` and ``http_path`` where a PostgreSQL one
    carries ``database``. Credentials are never returned.
    """
    return ConnectionResponse(
        connection_id=connection.connection_id,
        connection_name=connection.connection_name,
        project_code=connection.project_code,
        connection_type=FLAVOR_CODE_TO_LABEL[connection.sql_flavor_code],
        authentication=(
            AUTHENTICATION_FROM_MODE[mode] if (mode := authentication_method(connection)) is not None else None
        ),
        max_threads=connection.max_threads,
        max_expression_length=connection.max_query_chars,
        settings={
            settings_key(field.label): str(value)
            for field, value in connection_display_values(connection)
        },
    )
