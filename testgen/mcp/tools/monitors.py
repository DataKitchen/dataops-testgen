from datetime import UTC

from testgen.common.enums import MonitorType
from testgen.common.models import with_database_session
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY
from testgen.common.models.table_group import MonitorTableSummary, TableGroup
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    MonitorTableSort,
    format_page_footer,
    format_page_info,
    next_scheduled_run,
    parse_monitor_table_sort,
    parse_monitor_type,
    resolve_monitored_table_group,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MONITORS

_NOT_MONITORED_OUTPUT = "This table group is not monitored."

_MONITOR_LABEL: dict[MonitorType, str] = {
    MonitorType.FRESHNESS: "Freshness",
    MonitorType.VOLUME: "Volume",
    MonitorType.SCHEMA: "Schema",
    MonitorType.METRIC: "Metric",
}

# Maps a ``MonitorTableSort`` value to the model-method ``sort_by`` argument. The
# anomaly-count sort uses the ``total_anomalies`` field — the model layer collapses
# it to the filtered type's column when exactly one ``anomaly_type`` is set.
_SORT_TO_MODEL_FIELD: dict[MonitorTableSort, str] = {
    MonitorTableSort.TABLE_NAME: "table_name",
    MonitorTableSort.ANOMALY_COUNT_DESC: "total_anomalies_desc",
    MonitorTableSort.LATEST_UPDATE_DESC: "latest_update_desc",
    MonitorTableSort.ROW_COUNT_CHANGE_DESC: "row_count_change_desc",
}


@with_database_session
@mcp_permission("view")
def get_monitor_summary(table_group_id: str, lookback: int | None = None) -> str:
    """Get monitor health for a table group: per-type anomaly counts, error / training / pending status, and the active lookback window.

    Args:
        table_group_id: UUID of the table group, e.g. from ``list_table_groups``.
        lookback: Number of monitor runs to summarize. Omit to use the lookback runs configured for the table group.
    """
    if lookback is not None and not 1 <= lookback <= 365:
        raise MCPUserError(f"Invalid lookback `{lookback}`: must be between 1 and 365.")

    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is None:
        return _NOT_MONITORED_OUTPUT

    summary = TableGroup.get_monitor_group_summary(tg.id, lookback_override=lookback)
    next_run = next_scheduled_run(
        RUN_MONITORS_JOB_KEY, {"test_suite_id": str(monitor_suite.id)}, tg.project_code
    )

    doc = MdDoc()
    doc.heading(1, f"Monitor summary for `{tg.table_groups_name}`")
    doc.field("Project", tg.project_code, code=True)
    doc.field("Monitored tables", summary.total_monitored_tables)
    lookback_label = f"{summary.lookback} runs"
    if lookback is not None:
        lookback_label += " (override)"
    doc.field("Lookback", lookback_label)
    if summary.lookback_start:
        doc.field("Window start", summary.lookback_start)
    if summary.lookback_end:
        doc.field("Window end", summary.lookback_end)
    if next_run:
        # Next-firing timestamps from JobSchedule are tz-aware in the schedule's
        # configured cron_tz. MdDoc renders any datetime with a blind "UTC" suffix,
        # so convert here to avoid claiming a local-tz timestamp is UTC.
        doc.field("Next scheduled run", next_run.astimezone(UTC))
    else:
        doc.field("Next scheduled run", "not scheduled")

    doc.heading(2, "Anomalies by type")
    doc.table(
        ["Monitor", "Anomalies", "Status"],
        [
            [
                _MONITOR_LABEL[MonitorType.FRESHNESS],
                summary.freshness_anomalies,
                _summary_status(
                    is_pending=summary.freshness_is_pending,
                    is_training=summary.freshness_is_training,
                    has_errors=summary.freshness_has_errors,
                ),
            ],
            [
                _MONITOR_LABEL[MonitorType.VOLUME],
                summary.volume_anomalies,
                _summary_status(
                    is_pending=summary.volume_is_pending,
                    is_training=summary.volume_is_training,
                    has_errors=summary.volume_has_errors,
                ),
            ],
            [
                _MONITOR_LABEL[MonitorType.SCHEMA],
                summary.schema_anomalies,
                _summary_status(
                    is_pending=summary.schema_is_pending,
                    is_training=False,
                    has_errors=summary.schema_has_errors,
                ),
            ],
            [
                _MONITOR_LABEL[MonitorType.METRIC],
                summary.metric_anomalies,
                _summary_status(
                    is_pending=summary.metric_is_pending,
                    is_training=summary.metric_is_training,
                    has_errors=summary.metric_has_errors,
                ),
            ],
        ],
    )

    return doc.render()


@with_database_session
@mcp_permission("view")
def list_monitored_tables(
    table_group_id: str,
    anomaly_type: str | None = None,
    sort_by: str | None = None,
    limit: int = 20,
    page: int = 1,
) -> str:
    """List monitored tables in a table group with per-type anomaly counts, training / pending / error status, latest update timestamp, and row count change.

    Args:
        table_group_id: UUID of the table group, e.g. from ``list_table_groups``.
        anomaly_type: Filter to tables with at least one anomaly of this type. One of ``freshness`` / ``volume`` / ``schema`` / ``metric``.
        sort_by: Sort order. One of ``table_name`` (default, case-insensitive ascending), ``anomaly_count_desc`` (sorts by the filtered type when ``anomaly_type`` is set, total anomalies otherwise), ``latest_update_desc``, ``row_count_change_desc``.
        limit: Page size (default 20, max 100).
        page: Page number starting at 1 (default 1).
    """
    validate_page(page)
    validate_limit(limit, 100)

    monitor_type = parse_monitor_type(anomaly_type, "anomaly_type") if anomaly_type is not None else None
    sort = parse_monitor_table_sort(sort_by) if sort_by is not None else None

    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is None:
        return _NOT_MONITORED_OUTPUT

    rows, total = TableGroup.list_monitor_table_summaries(
        tg.id,
        anomaly_types=[monitor_type.value] if monitor_type is not None else None,
        sort_by=_SORT_TO_MODEL_FIELD[sort] if sort is not None else None,
        page=page,
        limit=limit,
    )

    doc = MdDoc()
    scope = f" — anomaly type `{anomaly_type}`" if anomaly_type else ""
    doc.heading(1, f"Monitored tables in `{tg.table_groups_name}`{scope}")
    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    if not rows:
        if page > 1:
            doc.text(f"No tables on page {page} (total: {total}).")
        else:
            doc.text("_No monitored tables match this filter._")
        return doc.render()

    doc.table(
        [
            "Table",
            "Freshness",
            "Volume",
            "Schema",
            "Schema change",
            "Metric",
            "Latest update",
            "Row count change",
        ],
        [
            [
                row.table_name,
                _format_monitor_cell(
                    count=row.freshness_anomalies,
                    is_pending=row.freshness_is_pending,
                    is_training=row.freshness_is_training,
                    has_error=row.freshness_error_message is not None,
                ),
                _format_monitor_cell(
                    count=row.volume_anomalies,
                    is_pending=row.volume_is_pending,
                    is_training=row.volume_is_training,
                    has_error=row.volume_error_message is not None,
                ),
                _format_schema_cell(row),
                _format_schema_change(row),
                _format_monitor_cell(
                    count=row.metric_anomalies,
                    is_pending=row.metric_is_pending,
                    is_training=row.metric_is_training,
                    has_error=row.metric_error_message is not None,
                ),
                row.latest_update,
                _format_row_count_change(row),
            ]
            for row in rows
        ],
        code=[0],
    )

    if footer := format_page_footer(total, page, limit):
        doc.text(footer)

    return doc.render()


def _summary_status(*, is_pending: bool, is_training: bool, has_errors: bool) -> str:
    """Single status word for the group-level summary cell."""
    if has_errors:
        return "error"
    if is_pending:
        return "no results yet or not configured"
    if is_training:
        return "training"
    return "ok"


def _format_monitor_cell(
    *,
    count: int,
    is_pending: bool,
    is_training: bool | None,
    has_error: bool,
) -> str:
    """Render a per-table, per-monitor cell (non-schema).

    Precedence: error > positive count > pending > training > zero. A positive
    count wins over training/pending so anomalies stay visible when a monitor is
    still learning, and so a row that surfaces via ``anomaly_type=X`` actually
    shows the X count in its column.
    """
    if has_error:
        return "error"
    if count > 0:
        return str(count)
    if is_pending:
        return "pending"
    if is_training:
        return "training"
    return "0"


def _format_schema_cell(row: MonitorTableSummary) -> str:
    """Schema anomaly count, or pending / error status. Verbose detail is in the
    sibling ``Schema change`` column."""
    if row.schema_error_message is not None:
        return "error"
    if row.schema_is_pending:
        return "pending"
    return str(row.schema_anomalies)


def _format_schema_change(row: MonitorTableSummary) -> str | None:
    """Verbose description of schema events in the lookback window.

    Mirrors the dashboard tooltip wording: "Table added with N columns.",
    "Table dropped with N columns.", or a per-kind breakdown when the table was
    modified ("1 column added. 2 columns dropped."). Empty when there are no
    schema events or the monitor is in an unfinished state.
    """
    if row.schema_is_pending or row.schema_error_message is not None:
        return None
    state = row.table_state
    if state == "added":
        return f"Table added with {row.column_adds} columns."
    if state == "dropped":
        return f"Table dropped with {row.column_drops} columns."
    if state == "modified":
        parts: list[str] = []
        if row.column_adds:
            parts.append(f"{row.column_adds} column{'' if row.column_adds == 1 else 's'} added")
        if row.column_drops:
            parts.append(f"{row.column_drops} column{'' if row.column_drops == 1 else 's'} dropped")
        if row.column_mods:
            parts.append(f"{row.column_mods} column{'' if row.column_mods == 1 else 's'} modified")
        return ". ".join(parts) + "." if parts else None
    return None


def _format_row_count_change(row: MonitorTableSummary) -> str | None:
    """Signed delta between the latest and pre-window row count.

    ``+1,234`` / ``-1,234`` / ``0`` when both endpoints are known; ``None`` (em-dash)
    when either is missing (e.g. first run with no baseline). Sign reflects net
    change across the window, not run-to-run variance.
    """
    current = row.row_count
    previous = row.previous_row_count
    if current is None or previous is None:
        return None
    delta = current - previous
    if delta == 0:
        return "0"
    return f"{delta:+,}"
