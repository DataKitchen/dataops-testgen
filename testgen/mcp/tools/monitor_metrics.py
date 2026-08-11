from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field
from sqlalchemy import exists, select

from testgen.common.custom_test_validation import validate_custom_query
from testgen.common.database.database_service import get_flavor_service
from testgen.common.enums import MonitorType
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_table import DataTable
from testgen.common.models.test_definition import TestDefinition
from testgen.common.pii_masking import get_pii_columns
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    raise_validation_error,
    render_diff_table,
    resolve_monitor,
    resolve_monitored_table_group,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MONITORS

_NOT_MONITORED_OUTPUT = "Monitoring is not enabled for this table group; run enable_monitors first."

_NON_METRIC_UPDATE_MSG = (
    "This tool only updates Metric monitors; the target is a Freshness/Volume/Schema monitor."
)
_NON_METRIC_DELETE_MSG = (
    "This tool only deletes Metric monitors; the target is a Freshness/Volume/Schema monitor. "
    "Use disable_monitors to remove monitoring entirely."
)

_DIFF_ORDER: tuple[str, ...] = ("column_name", "custom_query")
_DIFF_LABELS: dict[str, str] = {
    "column_name": "Metric name",
    "custom_query": "Metric expression",
}


@with_database_session
@mcp_permission("edit")
def create_metric_monitor(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
    metric_name: Annotated[str, Field(description="Display label for the monitor (e.g. ``Daily revenue``).")],
    metric_expression: Annotated[str, Field(description="SQL expression the monitor evaluates each run.")],
) -> str:
    """Create a new Metric monitor on a table. Always created in Predictive mode.

    Metric monitors evaluate a user-supplied SQL aggregate each run and track its
    drift from a learned baseline. Use ``validate_metric_expression`` first to
    confirm the SQL parses and returns rows.
    """
    clean_name = (metric_name or "").strip()
    clean_expr = (metric_expression or "").strip()
    errors: list[str] = []
    if not clean_name:
        errors.append("`metric_name` must not be empty.")
    if not clean_expr:
        errors.append("`metric_expression` must not be empty.")
    if errors:
        raise_validation_error(errors, "Cannot create Metric monitor. Invalid input.")

    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is None:
        raise MCPUserError(_NOT_MONITORED_OUTPUT)

    if not _table_in_catalog(tg.id, table_name):
        raise MCPUserError(
            f"Table `{table_name}` is not in the table group's catalog. "
            "Run profiling on the table group first."
        )

    monitor = TestDefinition(
        table_groups_id=tg.id,
        test_type=MonitorType.METRIC.value,
        test_suite_id=monitor_suite.id,
        schema_name=tg.table_group_schema,
        table_name=table_name,
        column_name=clean_name,
        custom_query=clean_expr,
        history_calculation="PREDICT",
        history_calculation_upper=None,
        history_lookback=None,
        test_active=True,
        lock_refresh=True,
        last_manual_update=datetime.now(UTC),
    )
    monitor.save()

    return _render_created(monitor, tg.table_groups_name)


@with_database_session
@mcp_permission("edit")
def update_metric_monitor(
    monitor_id: Annotated[str, Field(description="UUID of the monitor, e.g. from ``list_monitors``.")],
    metric_name: Annotated[
        str | None,
        Field(description="New display label for the monitor. Omit to leave unchanged."),
    ] = None,
    metric_expression: Annotated[
        str | None,
        Field(description="New SQL expression for the monitor. Omit to leave unchanged."),
    ] = None,
) -> str:
    """Update the name and / or expression of an existing Metric monitor.
    Partial update; at least one field must be supplied. Does not change threshold mode
    or bounds.
    """
    if metric_name is None and metric_expression is None:
        raise MCPUserError("At least one of `metric_name`, `metric_expression` must be supplied.")

    monitor = resolve_monitor(monitor_id)
    if monitor.test_type != MonitorType.METRIC.value:
        raise MCPUserError(_NON_METRIC_UPDATE_MSG)

    errors: list[str] = []
    clean_name = metric_name.strip() if metric_name is not None else None
    clean_expr = metric_expression.strip() if metric_expression is not None else None
    if metric_name is not None and not clean_name:
        errors.append("`metric_name` must not be empty.")
    if metric_expression is not None and not clean_expr:
        errors.append("`metric_expression` must not be empty.")
    if errors:
        raise_validation_error(errors, "Cannot update Metric monitor. Invalid input.")

    before = {attr: getattr(monitor, attr) for attr in _DIFF_ORDER}
    if clean_name is not None:
        monitor.column_name = clean_name
    if clean_expr is not None:
        monitor.custom_query = clean_expr
    monitor.lock_refresh = True
    monitor.last_manual_update = datetime.now(UTC)
    after = {attr: getattr(monitor, attr) for attr in _DIFF_ORDER}

    doc = MdDoc()
    doc.heading(1, "Metric Monitor updated")
    doc.field("Monitor ID", monitor.id, code=True)

    rendered = render_diff_table(doc, before, after, attrs=_DIFF_ORDER, labels=_DIFF_LABELS)
    if not rendered:
        doc.text("No fields changed — supplied values matched the current state.")
        return doc.render()

    monitor.save()
    return doc.render()


@with_database_session
@mcp_permission("edit")
def delete_metric_monitor(
    monitor_id: Annotated[str, Field(description="UUID of the monitor, e.g. from ``list_monitors``.")],
) -> str:
    """Remove a Metric monitor. Auto-managed types (Freshness, Volume, Schema) are
    rejected — use ``disable_monitors`` to remove monitoring entirely.

    Test results recorded against the deleted monitor are not deleted; they remain
    in the run history but no longer link to a live monitor definition.
    """
    monitor = resolve_monitor(monitor_id)
    if monitor.test_type != MonitorType.METRIC.value:
        raise MCPUserError(_NON_METRIC_DELETE_MSG)

    doc = MdDoc()
    doc.heading(1, "Metric Monitor deleted")
    doc.field("Monitor ID", monitor.id, code=True)
    doc.field("Table", monitor.table_name)
    doc.field("Metric name", monitor.column_name)

    monitor.delete()

    return doc.render()


@with_database_session
@mcp_permission("edit")
def validate_metric_expression(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    table_name: Annotated[
        str,
        Field(description="Table the expression evaluates against, exactly as stored in TestGen (case-sensitive)."),
    ],
    metric_expression: Annotated[
        str,
        Field(
            description="SQL expression (typically an aggregate) that produces the monitored value — e.g. "
            "``SUM(amount)`` or ``COUNT(DISTINCT customer_id)``.",
        ),
    ],
) -> str:
    """Dry-run a metric expression against the table group's connection without saving.

    Wraps the expression the same way monitor evaluation does — ``SELECT ({expr}) AS
    metric_value FROM {schema.table}`` — so parse-and-run parity with runtime is
    automatic. Use this to iterate on SQL before calling ``create_metric_monitor``
    or ``update_metric_monitor``. On success, surfaces the column names and the
    first returned row. On failure, surfaces the driver's error message verbatim so
    the expression can be corrected. Individual columns marked as PII in the
    catalog are redacted for callers lacking ``view_pii``.
    """
    clean_expr = (metric_expression or "").strip()
    if not clean_expr:
        raise MCPUserError("`metric_expression` must not be empty.")

    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is None:
        raise MCPUserError(_NOT_MONITORED_OUTPUT)

    if not _table_in_catalog(tg.id, table_name):
        raise MCPUserError(
            f"Table `{table_name}` is not in the table group's catalog. "
            "Run profiling on the table group first."
        )

    connection = Connection.get(tg.connection_id)
    if connection is None:
        raise MCPUserError("The table group's connection is no longer configured.")

    flavor_service = get_flavor_service(connection.sql_flavor)
    table_ref = flavor_service.get_table_ref(tg.table_group_schema, table_name)
    wrapped_sql = f"SELECT ({clean_expr}) AS metric_value FROM {table_ref}"

    can_view_pii = get_project_permissions().has_permission("view_pii", tg.project_code)
    pii_columns: set[str] = (
        set()
        if can_view_pii
        else get_pii_columns(str(tg.id), tg.table_group_schema, table_name)
    )

    doc = MdDoc()
    doc.heading(1, "Metric expression dry-run")

    try:
        result = validate_custom_query(
            connection=connection,
            schema=tg.table_group_schema,
            custom_sql=wrapped_sql,
            preview_limit=1,
        )
    except Exception as err:
        doc.text(f"**SQL did not execute** against `{connection.connection_name}`.")
        message = str(err.args[0]) if err.args else str(err)
        doc.text("**Error:**")
        doc.code_block(message)
        return doc.render()

    doc.text(f"**SQL ran successfully** against `{connection.connection_name}`.")

    if not result.preview_rows:
        doc.text("The expression parsed and ran, but returned no rows.")
        return doc.render()

    first = result.preview_rows[0]
    columns = list(first.keys())
    values = [
        "[PII redacted]" if col in pii_columns else first[col]
        for col in columns
    ]
    doc.heading(2, "Sample row")
    doc.table(columns, [values])
    if pii_columns & set(columns):
        doc.text(
            "_PII columns redacted: caller does not have `view_pii` permission on this project._"
        )
    return doc.render()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_in_catalog(table_group_id, table_name: str) -> bool:
    """True when the table group's catalog has a row for ``table_name`` (not dropped)."""
    session = get_current_session()
    query = select(
        exists().where(
            DataTable.table_groups_id == table_group_id,
            DataTable.table_name == table_name,
            DataTable.drop_date.is_(None),
        )
    )
    return bool(session.scalar(query))


def _render_created(monitor: TestDefinition, table_group_name: str) -> str:
    doc = MdDoc()
    doc.heading(1, "Metric Monitor created")
    doc.field("Monitor ID", monitor.id, code=True)
    doc.field("Table Group", table_group_name)
    doc.field("Table", monitor.table_name)
    doc.field("Metric name", monitor.column_name)
    doc.field("Threshold mode", "Predictive")
    doc.heading(2, "Metric expression")
    doc.code_block(monitor.custom_query, language="sql")
    return doc.render()
