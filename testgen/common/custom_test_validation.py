"""Shared validation for custom-test SQL queries.

Wraps user-supplied SQL in a parent ``SELECT COUNT(*) FROM (<sql>) ERR_TABLE`` form
matching the test execution runtime, then runs it against the target database. Optional
preview returns the first N rows for inspection.

Wrapping serves two purposes:
- Validation parity with runtime — a bare query that runs may still fail when wrapped.
- DDL/DML rejection — non-SELECT statements fail to parse as a subquery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.engine import RowMapping

from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.ui.services.database_service import fetch_from_target_db

if TYPE_CHECKING:
    from testgen.common.database.flavor.flavor_service import FlavorService
    from testgen.common.models.connection import Connection


@dataclass
class CustomQueryResult:
    """Outcome of running a wrapped custom-test SQL query."""

    row_count: int
    preview_rows: list[RowMapping] = field(default_factory=list)


def validate_custom_query(
    connection: Connection,
    schema: str,
    custom_sql: str,
    preview_limit: int = 0,
) -> CustomQueryResult:
    """Wrap and execute a custom-test SQL query against the target DB.

    Args:
        connection: Target ``Connection`` to run the query on.
        schema: Schema name for ``{DATA_SCHEMA}`` substitution in the user's SQL.
        custom_sql: User-supplied query. Should return rows matching the test failure criteria.
        preview_limit: When > 0, also fetch up to N rows for preview (only when row_count > 0).

    Returns the failure-criteria row count and (optionally) the preview rows. DB errors
    propagate as-is — the caller decides how to surface them.
    """
    sql_with_schema = replace_params(custom_sql, {"DATA_SCHEMA": schema}).rstrip().rstrip(";")
    flavor_service = get_flavor_service(connection.sql_flavor)

    count_sql = f"SELECT COUNT(*) FROM ({sql_with_schema}) ERR_TABLE"
    count_rows = fetch_from_target_db(connection, count_sql)
    row_count = int(count_rows[0][0]) if count_rows else 0

    preview_rows: list[RowMapping] = []
    if preview_limit > 0 and row_count > 0:
        prefix, suffix = _row_limit_clauses(flavor_service, preview_limit)
        preview_sql = f"SELECT {prefix} * FROM ({sql_with_schema}) ERR_TABLE {suffix}".strip()
        preview_rows = fetch_from_target_db(connection, preview_sql)

    return CustomQueryResult(row_count=row_count, preview_rows=preview_rows)


def _row_limit_clauses(flavor_service: FlavorService, n: int) -> tuple[str, str]:
    """Return (prefix, suffix) for limiting a SELECT to N rows on the given flavor."""
    clause = flavor_service.row_limiting_clause
    if clause == "top":
        return f"TOP {n}", ""
    if clause == "fetch":
        return "", f"FETCH FIRST {n} ROWS ONLY"
    return "", f"LIMIT {n}"
