"""Shared validation for custom-test SQL queries.

Wraps user-supplied SQL in a parent ``SELECT COUNT(*) FROM (<sql>) ERR_TABLE`` form
matching the test execution runtime, then runs it against the target database. Optional
preview returns the first N rows for inspection. Metric queries, which return a single value
rather than error rows, run through the metric test's own execution template.

Wrapping serves two purposes:
- Validation parity with runtime — a bare query that runs may still fail when wrapped.
- DDL/DML rejection — non-SELECT statements fail to parse as a subquery.
"""

from dataclasses import dataclass, field

from sqlalchemy.engine import RowMapping

from testgen.common.clean_sql import strip_trailing_semicolons
from testgen.common.database.database_service import fetch_dict_from_db, get_flavor_service, replace_params
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.ui.services.database_service import fetch_from_target_db


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
    table_group: TableGroup | None = None,
) -> CustomQueryResult:
    """Wrap and execute a custom-test SQL query against the target DB.

    Args:
        connection: Target ``Connection`` to run the query on.
        schema: Schema name for ``{DATA_SCHEMA}`` substitution in the user's SQL.
        custom_sql: User-supplied query. Should return rows matching the test failure criteria.
        preview_limit: When > 0, also fetch up to N rows for preview (only when row_count > 0).
        table_group: Table group whose tables the query reads, when the flavor needs it to open
            the connection.

    Returns the failure-criteria row count and (optionally) the preview rows. DB errors
    propagate as-is — the caller decides how to surface them.
    """
    sql_with_schema = strip_trailing_semicolons(replace_params(custom_sql, {"DATA_SCHEMA": schema}))
    flavor_service = get_flavor_service(connection.sql_flavor)

    count_sql = f"SELECT COUNT(*) AS row_count FROM ({sql_with_schema}) ERR_TABLE"
    count_rows = fetch_from_target_db(connection, count_sql, table_group=table_group)
    row_count = int(count_rows[0]["row_count"]) if count_rows else 0

    preview_rows: list[RowMapping] = []
    if preview_limit > 0 and row_count > 0:
        prefix, suffix = flavor_service.row_limit_clauses(preview_limit)
        preview_sql = f"SELECT {prefix} * FROM ({sql_with_schema}) ERR_TABLE {suffix}".strip()
        preview_rows = fetch_from_target_db(connection, preview_sql, table_group=table_group)

    return CustomQueryResult(row_count=row_count, preview_rows=preview_rows)


class InvalidMetricQuery(ValueError):
    """A metric query ran but did not return a numeric value."""


def render_metric_validation_query(template: str, schema: str, metric_sql: str) -> str:
    """Render the metric test's execution template for a dry run of ``metric_sql``.

    Both bounds render as ``NULL``, so the query passes or errors on its result alone. The
    bookkeeping columns get placeholder values; the result columns are computed as in a test run.
    """
    params = {
        "TEST_TYPE": "SQL_Metric",
        "TEST_DEFINITION_ID": "",
        "TEST_SUITE_ID": "",
        "TEST_RUN_ID": "",
        "RUN_DATE": "",
        "SCHEMA_NAME": schema,
        "TABLE_NAME": "",
        "COLUMN_NAME_NO_QUOTES": "",
        "SKIP_ERRORS": 0,
        "INPUT_PARAMETERS": "",
        "LOWER_TOLERANCE": "NULL",
        "UPPER_TOLERANCE": "NULL",
        "CUSTOM_QUERY": strip_trailing_semicolons(metric_sql),
        # After CUSTOM_QUERY, which may contain it
        "DATA_SCHEMA": schema,
    }
    return replace_params(template, params)


def validate_metric_query(
    connection: Connection,
    schema: str,
    metric_sql: str,
    table_group: TableGroup | None = None,
) -> object:
    """Run a metric query through the metric test's execution template against the target DB.

    Args:
        connection: Target ``Connection`` to run the query on.
        schema: Schema name for ``{DATA_SCHEMA}`` substitution in the user's SQL.
        metric_sql: User-supplied query expected to return one row with one numeric column.
        table_group: Table group whose tables the query reads, when the flavor needs it to open
            the connection.

    Returns the value the query produced. Raises :class:`InvalidMetricQuery` when the query
    returns no numeric value. DB errors propagate as-is — the template makes the engine raise on
    more than one row or column and on a value that cannot be cast to a number.
    """
    templates = fetch_dict_from_db(
        "SELECT template FROM test_templates WHERE test_type = :test_type AND sql_flavor = :sql_flavor",
        {"test_type": "SQL_Metric", "sql_flavor": connection.sql_flavor},
    )
    if not templates:
        raise InvalidMetricQuery("The metric test is not available for this connection.")

    query = render_metric_validation_query(templates[0]["template"], schema, metric_sql)
    rows = fetch_from_target_db(connection, query, table_group=table_group)
    result = rows[0]
    if result["result_code"] is None:
        raise InvalidMetricQuery(result["result_message"])
    return result["result_measure"]
