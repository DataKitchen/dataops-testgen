from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from pydantic import Field
from sqlalchemy import select

from testgen.common.cron_service import describe_cron, get_cron_sample
from testgen.common.enums import MonitorCalculation, MonitorType
from testgen.common.history_calculation_service import (
    format_calculation_expression,
    parse_calculation_expression,
)
from testgen.common.holiday_service import (
    canonicalize_holiday_code,
    is_supported_holiday_code,
    list_market_holiday_codes,
)
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.data_structure_log import (
    SCHEMA_CHANGE_ADDED,
    SCHEMA_CHANGE_DROPPED,
    SCHEMA_CHANGE_MODIFIED,
    DataStructureLog,
)
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.monitor import parse_freshness_message
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import MonitorTableSummary, TableGroup
from testgen.common.models.test_definition import (
    MonitorForecastPoint,
    TestDefinition,
    TestDefinitionSummary,
    ThresholdMode,
    forecast_points_from_prediction,
)
from testgen.common.models.test_result import MonitorEvent, TestResult
from testgen.common.models.test_suite import PredictSensitivity, TestSuite
from testgen.common.monitor_forecast import (
    forecast_band_points,
    gated_forecast_prediction,
    next_update_window,
)
from testgen.common.monitor_service import disable_monitoring, enable_monitoring, update_monitoring
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    MonitorTableSort,
    format_page_footer,
    format_page_info,
    next_scheduled_run,
    parse_enum,
    parse_monitor_calculation,
    parse_monitor_table_sort,
    parse_monitor_type,
    parse_since_arg,
    parse_uuid,
    resolve_monitor,
    resolve_monitored_table_group,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MONITORS

_NOT_MONITORED_OUTPUT = "This table group is not monitored."

_FORECAST_PENDING_NOTE = (
    "_No forecast yet — monitors in Prediction Model mode produce a forecast once they "
    "have trained on enough history._"
)

# Used where a forecast can be absent for reasons other than training (e.g. the
# predicted next-update window has already passed, or no baseline is stored), so
# the message must not claim the model still needs to train.
_FORECAST_UNAVAILABLE_NOTE = "_No forecast available for this monitor right now._"

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
def get_monitor_summary(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    lookback: Annotated[
        int | None,
        Field(
            description="Number of monitor runs to summarize. Omit to use the lookback runs configured for the table "
            "group.",
        ),
    ] = None,
) -> str:
    """Get monitor health for a table group.
    Returns per-type anomaly counts, error / training / pending status, and the active
    lookback window.
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
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    anomaly_type: Annotated[
        str | None,
        Field(
            description="Filter to tables with at least one anomaly of this type. One of ``freshness`` / ``volume`` / "
            "``schema`` / ``metric``.",
        ),
    ] = None,
    sort_by: Annotated[
        str | None,
        Field(
            description="Sort order. One of ``table_name`` (default, case-insensitive ascending), "
            "``anomaly_count_desc`` (sorts by the filtered type when ``anomaly_type`` is set, total anomalies "
            "otherwise), ``latest_update_desc``, ``row_count_change_desc``.",
        ),
    ] = None,
    limit: Annotated[int, Field(description="Page size (default 20, max 100).")] = 20,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """List monitored tables in a table group with per-type anomaly counts.
    Each row also carries training / pending / error status, latest update timestamp,
    and row count change.
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
        return "Error"
    if is_pending:
        return "No results yet or not configured"
    if is_training:
        return "Training"
    return "Ok"


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
        return "Error"
    if count > 0:
        return str(count)
    if is_pending:
        return "Pending"
    if is_training:
        return "Training"
    return "0"


def _format_schema_cell(row: MonitorTableSummary) -> str:
    """Schema anomaly count, or pending / error status. Verbose detail is in the
    sibling ``Schema change`` column."""
    if row.schema_error_message is not None:
        return "Error"
    if row.schema_is_pending:
        return "Pending"
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

    ``+1,234`` / ``-1,234`` / ``0``. A missing pre-window count counts as zero, so a table
    first measured inside the window reports its full count as the change — matching how
    ``row_count_change`` orders it. ``None`` (em-dash) when the latest count is unknown,
    which makes the change unknown rather than zero. Sign reflects net change across the
    window, not run-to-run variance.
    """
    current = row.row_count
    if current is None:
        return None
    delta = current - (row.previous_row_count or 0)
    if delta == 0:
        return "0"
    return f"{delta:+,}"


# ---------------------------------------------------------------------------
# Lifecycle & settings tools
# ---------------------------------------------------------------------------

_LOOKBACK_RUNS_RANGE = (1, 200)
_MIN_TRAINING_LOOKBACK_RANGE = (20, 1000)


@with_database_session
@mcp_permission("edit")
def enable_monitors(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    cron_expression: Annotated[
        str,
        Field(
            description="Cron expression for the monitor schedule (required — monitors only run on a schedule), e.g. "
            "``0 6 * * *`` for 6 AM daily.",
        ),
    ],
    cron_tz: Annotated[str, Field(description="IANA timezone for the schedule. Defaults to ``UTC``.")] = "UTC",
) -> str:
    """Turn on monitoring for a table group.
    Creates its monitors and schedules them to run.

    Sets up the initial Volume and Schema monitors with default settings; adjust them afterward
    with ``update_monitor_settings``. Freshness monitors are added automatically once the table
    group has profiling data. Fails if monitoring is already on for the group.
    """
    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is not None:
        raise MCPUserError("Monitoring is already enabled for this table group.")
    _validate_cron_verbatim(cron_expression, cron_tz)

    _, count = enable_monitoring(tg, cron_expression, cron_tz)

    doc = MdDoc()
    doc.heading(1, f"Monitoring enabled for `{tg.table_groups_name}`")
    doc.field("Initial monitors created", count)
    doc.field("Cron expression", cron_expression, code=True)
    if (readable := describe_cron(cron_expression)) is not None:
        doc.field("Cron description", readable)
    doc.field("Timezone", cron_tz)
    return doc.render()


@with_database_session
@mcp_permission("view")
def get_monitor_settings(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
) -> str:
    """Get a table group's monitor configuration and schedule."""
    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is None:
        return _NOT_MONITORED_OUTPUT

    # A monitored table group always has a run-monitors schedule (enable_monitors creates it).
    schedule = cast(JobSchedule, JobSchedule.get_for_monitor_suite(monitor_suite.id))

    doc = MdDoc()
    doc.heading(1, f"Monitor settings for `{tg.table_groups_name}`")
    doc.field("Project", tg.project_code, code=True)
    _render_monitor_settings(doc, monitor_suite, schedule)
    return doc.render()


@with_database_session
@mcp_permission("edit")
def update_monitor_settings(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    sensitivity: Annotated[
        str | None,
        Field(
            description="How readily monitors flag a deviation. ``high`` flags smaller deviations (more alerts), "
            "``low`` only large ones (fewer alerts), ``medium`` is balanced.",
        ),
    ] = None,
    lookback_runs: Annotated[
        int | None,
        Field(
            description="Monitor runs aggregated for dashboard summaries. Display only — does not affect detection "
            "(1-200).",
        ),
    ] = None,
    min_training_lookback: Annotated[
        int | None,
        Field(description="Minimum monitor runs required to train the prediction model (20-1000)."),
    ] = None,
    exclude_weekends: Annotated[
        bool | None,
        Field(description="Whether to exclude weekends from the model's training data."),
    ] = None,
    holiday_codes: Annotated[
        list[str] | None,
        Field(
            description="Holiday calendars to exclude from the model's training data — ISO 3166-1 alpha-2 country "
            "codes (e.g. ``US``, ``GB``) or financial-market MICs (e.g. ``XNYS``, ``XECB``). Pass an empty list to clear.",
        ),
    ] = None,
    regenerate_freshness: Annotated[
        bool | None,
        Field(
            description="Whether to automatically reconfigure Freshness monitors with new fingerprints after each "
            "profiling run.",
        ),
    ] = None,
    cron_expression: Annotated[
        str | None,
        Field(description="New cron expression for the schedule, e.g. ``0 6 * * *``."),
    ] = None,
    cron_tz: Annotated[
        str | None,
        Field(description="New IANA timezone for the schedule, e.g. ``America/New_York``."),
    ] = None,
    active: Annotated[bool | None, Field(description="``True`` to resume the schedule, ``False`` to pause it.")] = None,
) -> str:
    """Update a table group's monitor configuration and/or schedule.
    Partial — omitted fields are left unchanged.
    """
    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is None:
        return _NOT_MONITORED_OUTPUT

    if all(
        value is None
        for value in (
            sensitivity,
            lookback_runs,
            min_training_lookback,
            exclude_weekends,
            holiday_codes,
            regenerate_freshness,
            cron_expression,
            cron_tz,
            active,
        )
    ):
        raise MCPUserError("No fields supplied to update.")

    # A monitored table group always has a run-monitors schedule (enable_monitors creates it).
    schedule = cast(JobSchedule, JobSchedule.get_for_monitor_suite(monitor_suite.id))

    suite_attrs: dict[str, Any] = {}
    if sensitivity is not None:
        suite_attrs["predict_sensitivity"] = _parse_sensitivity(sensitivity)
    if lookback_runs is not None:
        _validate_range(lookback_runs, "lookback_runs", *_LOOKBACK_RUNS_RANGE)
        suite_attrs["monitor_lookback"] = lookback_runs
    if min_training_lookback is not None:
        _validate_range(min_training_lookback, "min_training_lookback", *_MIN_TRAINING_LOOKBACK_RANGE)
        suite_attrs["predict_min_lookback"] = min_training_lookback
    if exclude_weekends is not None:
        suite_attrs["predict_exclude_weekends"] = exclude_weekends
    if holiday_codes is not None:
        cleaned = [code.strip() for code in holiday_codes if code.strip()]
        invalid = [code for code in cleaned if not is_supported_holiday_code(code)]
        if invalid:
            raise MCPUserError(
                f"Unknown holiday codes: {', '.join(invalid)}. Countries use ISO 3166-1 alpha-2 codes "
                f"(e.g. `US`, `GB`); financial markets use one of: {', '.join(list_market_holiday_codes())}."
            )
        canonical = list(dict.fromkeys(canonicalize_holiday_code(code) for code in cleaned))
        suite_attrs["predict_holiday_codes"] = canonical or None
    if regenerate_freshness is not None:
        suite_attrs["monitor_regenerate_freshness"] = regenerate_freshness

    if cron_expression is not None or cron_tz is not None:
        effective_expr = cron_expression if cron_expression is not None else schedule.cron_expr
        effective_tz = cron_tz if cron_tz is not None else schedule.cron_tz
        _validate_cron_verbatim(effective_expr, effective_tz)

    update_monitoring(
        monitor_suite,
        schedule,
        suite_attrs=suite_attrs,
        cron_expr=cron_expression,
        cron_tz=cron_tz,
        active=active,
    )

    doc = MdDoc()
    doc.heading(1, f"Monitor settings updated for `{tg.table_groups_name}`")
    _render_monitor_settings(doc, monitor_suite, schedule)
    return doc.render()


@with_database_session
@mcp_permission("edit")
def disable_monitors(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
) -> str:
    """Turn off monitoring for a table group.
    Removes all its monitors, the schedule, and monitor history. This is irreversible —
    the monitors and their accumulated history are deleted.
    """
    tg, monitor_suite = resolve_monitored_table_group(table_group_id)
    if monitor_suite is None:
        raise MCPUserError("Monitoring is not enabled for this table group.")

    counts = disable_monitoring(monitor_suite)

    doc = MdDoc()
    doc.heading(1, f"Monitoring disabled for `{tg.table_groups_name}`")
    doc.text("Removed all monitors, the schedule, and monitor history.")
    doc.field("Monitors removed", counts["monitors"])
    doc.field("Events removed", counts["events"])
    doc.field("Runs removed", counts["runs"])
    return doc.render()


def _parse_sensitivity(value: str) -> PredictSensitivity:
    return parse_enum(value, PredictSensitivity, "sensitivity")


def _validate_range(value: int, label: str, low: int, high: int) -> None:
    if not low <= value <= high:
        raise MCPUserError(f"Invalid {label} `{value}`: must be between {low} and {high}.")


def _validate_cron_verbatim(cron_expr: str, cron_tz: str) -> None:
    """Validate a cron expression + timezone, surfacing the parser's message verbatim."""
    sample = get_cron_sample(cron_expr, cron_tz, sample_count=1)
    if "error" in sample:
        raise MCPUserError(sample["error"])


def _last_monitor_run(schedule_id: UUID) -> datetime | None:
    je = (
        get_current_session()
        .scalars(
            select(JobExecution)
            .where(JobExecution.job_schedule_id == schedule_id)
            .order_by(JobExecution.created_at.desc())
            .limit(1)
        )
        .first()
    )
    if je is None:
        return None
    return je.completed_at or je.started_at


def _render_monitor_settings(doc: MdDoc, monitor_suite: TestSuite, schedule: JobSchedule) -> None:
    doc.field("Lookback runs", monitor_suite.monitor_lookback)
    doc.field("Regenerate freshness", monitor_suite.monitor_regenerate_freshness)

    doc.heading(2, "Prediction Model")
    sensitivity = monitor_suite.predict_sensitivity.value if monitor_suite.predict_sensitivity else None
    doc.field("Sensitivity", sensitivity)
    doc.field("Min training lookback", monitor_suite.predict_min_lookback)
    doc.field("Exclude weekends", monitor_suite.predict_exclude_weekends)
    holidays = monitor_suite.holiday_codes_list
    doc.field("Holiday codes", ", ".join(holidays) if holidays else None)

    doc.heading(2, "Schedule")
    doc.field("Cron expression", schedule.cron_expr, code=True)
    if (readable := describe_cron(schedule.cron_expr)) is not None:
        doc.field("Cron description", readable)
    doc.field("Timezone", schedule.cron_tz)
    doc.field("Status", "Active" if schedule.active else "Paused")
    if schedule.active:
        try:
            next_runs = schedule.get_sample_triggering_timestamps(1)
        except Exception:
            next_runs = []
        if next_runs:
            # Cron samples are tz-aware in the schedule's timezone; convert to UTC so the
            # rendered " UTC" suffix is accurate.
            doc.field("Next run", next_runs[0].astimezone(UTC))
    if (last_run := _last_monitor_run(schedule.id)) is not None:
        # job_executions timestamps are tz-aware UTC; convert so the rendered " UTC" suffix is accurate.
        doc.field("Last run", last_run.astimezone(UTC))
# list_monitor_events
# ---------------------------------------------------------------------------


@with_database_session
@mcp_permission("view")
def list_monitor_events(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
    monitor_type: Annotated[str, Field(description="One of ``freshness`` / ``volume`` / ``schema`` / ``metric``.")],
    monitor_id: Annotated[
        str | None,
        Field(
            description='Required for ``monitor_type="metric"``, rejected for other types. Get it from '
            "``list_monitors``.",
        ),
    ] = None,
    include_predictions: Annotated[
        bool,
        Field(description="When True, append the monitor's forecast, if available (shown on the first page only)."),
    ] = False,
    limit: Annotated[int, Field(description="Page size (default 20, max 100).")] = 20,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """List per-table monitor events for one monitor type.
    Covers the lookback window, newest first.
    """
    validate_page(page)
    validate_limit(limit, 100)
    parsed_type = parse_monitor_type(monitor_type)

    if parsed_type == MonitorType.METRIC and monitor_id is None:
        raise MCPUserError(
            '`monitor_id` is required for `monitor_type="metric"`. '
            "Metric monitors are user-defined and many can apply to one table — "
            "use `list_monitors(table_group_id, table_name)` to find the metric's "
            "`monitor_id` first, then call this tool with it."
        )
    if monitor_id is not None and parsed_type != MonitorType.METRIC:
        raise MCPUserError(
            '`monitor_id` only applies when `monitor_type="metric"`. '
            "For singleton monitor types (`freshness`, `volume`, `schema`), "
            "the monitor is uniquely identified by table + type."
        )

    tg, suite = resolve_monitored_table_group(table_group_id)
    if suite is None:
        return _NOT_MONITORED_OUTPUT

    monitor_def: TestDefinition | TestDefinitionSummary | None
    if parsed_type == MonitorType.METRIC:
        monitor_uuid = parse_uuid(monitor_id, "monitor_id")
        # Scope the lookup to this suite + table + Metric_Trend so a monitor_id
        # for a metric on another table (or another suite) can't be rendered
        # under this table's heading.
        monitor_def = next(
            iter(
                TestDefinition.select_where(
                    TestDefinition.id == monitor_uuid,
                    TestDefinition.test_suite_id == suite.id,
                    TestDefinition.table_name == table_name,
                    TestDefinition.test_type == MonitorType.METRIC.value,
                )
            ),
            None,
        )
        if monitor_def is None:
            raise MCPUserError(
                f"No metric monitor `{monitor_id}` found on table `{table_name}`. "
                "Use `list_monitors(table_group_id, table_name)` to find a metric's `monitor_id`."
            )
        events, total = TestResult.list_metric_monitor_events(
            suite.id,
            monitor_uuid,
            page=page,
            limit=limit,
        )
        metric_name = monitor_def.column_name or None
    else:
        events, total = TestResult.list_monitor_events_for_table(
            suite.id,
            table_name,
            monitor_type=parsed_type.value,
            page=page,
            limit=limit,
        )
        # Singleton lookup only needed when we will render a forecast — Schema
        # short-circuits to "not applicable" without touching the definition.
        monitor_def = (
            TestDefinition.get_singleton_monitor(suite.id, table_name, parsed_type.value)
            if include_predictions and parsed_type != MonitorType.SCHEMA
            else None
        )
        metric_name = None

    doc = MdDoc()
    if parsed_type == MonitorType.METRIC and metric_name:
        doc.heading(
            1,
            f"Monitor events: Metric `{metric_name}` on `{table_name}` in `{tg.table_groups_name}`",
        )
    else:
        doc.heading(
            1,
            f"Monitor events: `{table_name}` — `{monitor_type}` in `{tg.table_groups_name}`",
        )

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    if not events:
        if page > 1:
            doc.text(f"No events on page {page} (total: {total}).")
        else:
            doc.text("_No monitor events in the active lookback window._")
        if include_predictions and page == 1:
            _render_forecast_section(doc, _compute_forecast(suite, table_name, parsed_type, monitor_def, events))
        return doc.render()

    if parsed_type == MonitorType.SCHEMA:
        doc.table(
            ["Time", "Status", "Table change", "Columns added", "Columns dropped", "Columns modified"],
            [
                [
                    event.test_time,
                    _event_status(event),
                    _format_schema_change_kind(event.schema_change_kind),
                    event.column_adds,
                    event.column_drops,
                    event.column_mods,
                ]
                for event in events
            ],
        )
    elif parsed_type == MonitorType.FRESHNESS:
        doc.table(
            ["Time", "Status", "Update detected", "Detail"],
            [
                [event.test_time, _event_status(event), *_format_freshness_message(event.message)]
                for event in events
            ],
        )
    elif parsed_type == MonitorType.METRIC:
        doc.table(
            ["Time", "Status", "Value", "Lower bound", "Upper bound"],
            [
                [
                    event.test_time,
                    _event_status(event),
                    event.signal,
                    event.lower_bound,
                    event.upper_bound,
                ]
                for event in events
            ],
        )
    else:  # VOLUME
        doc.table(
            ["Time", "Status", "Row count", "Lower bound", "Upper bound"],
            [
                [
                    event.test_time,
                    _event_status(event),
                    event.signal,
                    event.lower_bound,
                    event.upper_bound,
                ]
                for event in events
            ],
        )

    if footer := format_page_footer(total, page, limit):
        doc.text(footer)

    if include_predictions:
        _render_forecast_section(doc, _compute_forecast(suite, table_name, parsed_type, monitor_def, events))

    return doc.render()


@dataclass
class _Forecast:
    """The forecast to render under a monitor's events. Exactly one of
    ``window`` / ``points`` / ``note`` is meaningful — see ``_compute_forecast``."""
    note: str | None = None
    sensitivity: str | None = None
    points: list[MonitorForecastPoint] = field(default_factory=list)
    window: dict | None = None  # {"start": epoch_ms | None, "end": epoch_ms}


def _compute_forecast(
    suite: TestSuite,
    table_name: str,
    parsed_type: MonitorType,
    monitor_def: TestDefinition | TestDefinitionSummary | None,
    events: list[MonitorEvent],
) -> _Forecast:
    """Compute the same forecast the monitors dashboard plots for this monitor.

    Volume / Metric in Prediction Model mode get a forward value band — the
    coupled baseline-then-refresh band when the monitor is tied to a Freshness
    monitor, otherwise the per-step prediction band. Freshness gets its predicted
    next-update window. Everything else gets an explanatory note."""
    if parsed_type == MonitorType.SCHEMA:
        return _Forecast(
            note="_Predictions not applicable to Schema monitors._"
        )
    if monitor_def is None:
        return _Forecast(note="_No monitor configured for this table._")
    if monitor_def.history_calculation != MonitorCalculation.PREDICT:
        return _Forecast(
            note="_Predictions not available — this monitor's threshold mode is "
            "Static or Historical Calculation, not Prediction Model._"
        )

    if parsed_type == MonitorType.FRESHNESS:
        window = _next_update_window_for_table(suite, monitor_def, events)
        if window is None:
            return _Forecast(note=_FORECAST_PENDING_NOTE)
        return _Forecast(window=window)

    last_run_time = max((e.test_time for e in events if e.test_time is not None), default=None)

    # A monitor coupled to a Freshness monitor holds at its baseline until the
    # next expected refresh, so its band is the coupled baseline-then-refresh
    # shape keyed off the freshness next-update window — not the raw per-step
    # prediction series. The tolerance precondition mirrors the dashboard: a
    # coupled monitor with no configured tolerance has no band on either surface.
    if monitor_def.prediction and monitor_def.prediction.get("freshness_gated"):
        if monitor_def.lower_tolerance is None and monitor_def.upper_tolerance is None:
            return _Forecast(note=_FORECAST_UNAVAILABLE_NOTE)
        freshness_def = TestDefinition.get_singleton_monitor(
            suite.id, table_name, MonitorType.FRESHNESS.value
        )
        freshness_events, _ = TestResult.list_monitor_events_for_table(
            suite.id, table_name, monitor_type=MonitorType.FRESHNESS.value, limit=None
        )
        window = _next_update_window_for_table(suite, freshness_def, freshness_events)
        points = forecast_band_points(gated_forecast_prediction(monitor_def, window, last_run_time))
        if not points:
            return _Forecast(note=_FORECAST_UNAVAILABLE_NOTE)
        return _Forecast(points=points)

    sensitivity = (
        suite.predict_sensitivity.value if suite.predict_sensitivity is not None else PredictSensitivity.medium.value
    )
    points = forecast_points_from_prediction(monitor_def.prediction, sensitivity)
    if not points:
        return _Forecast(note=_FORECAST_PENDING_NOTE)
    return _Forecast(sensitivity=sensitivity, points=points)


def _next_update_window_for_table(
    suite: TestSuite,
    freshness_def: TestDefinition | TestDefinitionSummary | None,
    freshness_events: list[MonitorEvent],
) -> dict | None:
    """Predicted next-update window from the table's Freshness monitor, computed
    the same way the dashboard does (last detected update + business-time tolerance)."""
    last_detection = max(
        (
            e.test_time for e in freshness_events
            if e.test_time is not None and not e.is_training and not e.is_pending and not e.is_error
            and parse_freshness_message(e.message)[0]
        ),
        default=None,
    )
    schedule = JobSchedule.get_for_monitor_suite(suite.id)
    return next_update_window(
        freshness_def,
        last_detection,
        test_suite=suite,
        cron_tz=schedule.cron_tz if schedule else None,
    )


def _render_forecast_section(doc: MdDoc, forecast: _Forecast) -> None:
    """Append the forecast under its own `## Forecast` heading. Predictions are
    NEVER mixed into the events table so the consumer can tell observed-past from
    predicted-future at a glance."""
    doc.heading(2, "Forecast")

    if forecast.window is not None:
        end = datetime.fromtimestamp(forecast.window["end"] / 1000.0, UTC)
        start_ms = forecast.window.get("start")
        if start_ms is not None:
            start = datetime.fromtimestamp(start_ms / 1000.0, UTC)
            doc.field("Next update expected", f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC")
        else:
            doc.field("Next update expected by", f"{end:%Y-%m-%d %H:%M} UTC")
        return

    if forecast.points:
        if forecast.sensitivity:
            doc.field("Sensitivity", forecast.sensitivity)
        doc.table(
            ["Time", "Predicted lower", "Predicted upper"],
            [[p.test_time, p.lower_bound, p.upper_bound] for p in forecast.points],
        )
        return

    doc.text(forecast.note or "_No forecast available._")


def _event_status(event: MonitorEvent) -> str:
    """Single status word for a monitor-event row."""
    if event.is_error:
        return "Error"
    if event.is_pending:
        return "Pending"
    if event.is_training:
        return "Training"
    if event.is_anomaly:
        return "Anomaly"
    return "Ok"


def _format_freshness_message(message: str | None) -> tuple[str, str]:
    """Render a freshness ``result_message`` as ``(update_detected, detail)`` table cells:
    ``"Yes"``/``"No"``/``"—"`` and the descriptive tail (``"On time"`` /
    ``"Earlier than expected"`` / ``"Later than expected"`` / ``"Late"`` / ``"—"``)."""
    detected, detail = parse_freshness_message(message)
    if detected is None:
        return "—", detail or "—"
    return ("Yes" if detected else "No"), detail or "—"


# ---------------------------------------------------------------------------
# list_monitors
# ---------------------------------------------------------------------------


_SCHEMA_CHANGE_LABEL: dict[str, str] = {
    SCHEMA_CHANGE_ADDED: "added",
    SCHEMA_CHANGE_DROPPED: "dropped",
    SCHEMA_CHANGE_MODIFIED: "modified",
}


def _format_schema_change_kind(code: str | None) -> str | None:
    """Map an audit-log change code (``A`` / ``D`` / ``M``) to its user-facing word."""
    if code is None:
        return None
    return _SCHEMA_CHANGE_LABEL.get(code, code)


@with_database_session
@mcp_permission("view")
def list_monitors(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
) -> str:
    """List configured monitors for a table.
    Returns monitor IDs, types, threshold modes, and bounds.
    """
    tg, suite = resolve_monitored_table_group(table_group_id)
    if suite is None:
        return _NOT_MONITORED_OUTPUT

    configs = TestDefinition.list_monitor_configs_for_table(suite.id, table_name)

    doc = MdDoc()
    doc.heading(1, f"Monitors on `{table_name}` in `{tg.table_groups_name}`")
    sensitivity = (
        suite.predict_sensitivity.value
        if suite.predict_sensitivity is not None
        else PredictSensitivity.medium.value
    )
    doc.field("Prediction model sensitivity", sensitivity)

    if not configs:
        doc.text("_No monitors configured for this table._")
        return doc.render()

    doc.table(
        ["Monitor ID", "Type", "Metric name", "Threshold mode", "Lower", "Upper", "Metric expression"],
        [
            [
                str(c.monitor_id),
                _MONITOR_LABEL[MonitorType(c.test_type)],
                c.metric_name,
                c.threshold_mode,
                c.threshold_lower,
                c.threshold_upper,
                c.custom_query,
            ]
            for c in configs
        ],
        code=[0, 6],
    )

    return doc.render()


# ---------------------------------------------------------------------------
# list_monitor_schema_changes
# ---------------------------------------------------------------------------


@with_database_session
@mcp_permission("view")
def list_monitor_schema_changes(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from ``list_table_groups``.")],
    table_name: Annotated[
        str | None,
        Field(
            description="Filter to one table (exact, case-sensitive). Omit to list changes across every table in the "
            "group.",
        ),
    ] = None,
    since: Annotated[
        str | None,
        Field(
            description="Lower-bound date (e.g. ``'7 days'``, ``'2 weeks'``, ``'2026-04-01'``). Omit to include the "
            "entire stored history.",
        ),
    ] = None,
    limit: Annotated[int, Field(description="Page size (default 20, max 100).")] = 20,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """List schema changes detected for a table group, newest first."""
    validate_page(page)
    validate_limit(limit, 100)
    since_date = parse_since_arg(since) if since is not None else None

    tg, suite = resolve_monitored_table_group(table_group_id)
    if suite is None:
        return _NOT_MONITORED_OUTPUT

    clauses = []
    if table_name is not None:
        clauses.append(DataStructureLog.table_name == table_name)
    if since_date is not None:
        clauses.append(DataStructureLog.change_date >= since_date)

    entries, total = DataStructureLog.list_for_table_group(
        tg.id,
        *clauses,
        page=page,
        limit=limit,
    )

    doc = MdDoc()
    scope_parts: list[str] = []
    if table_name:
        scope_parts.append(f"table `{table_name}`")
    if since:
        scope_parts.append(f"since `{since}`")
    scope = f" — {' — '.join(scope_parts)}" if scope_parts else ""
    doc.heading(1, f"Schema changes in `{tg.table_groups_name}`{scope}")

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    if not entries:
        if page > 1:
            doc.text(f"No schema changes on page {page} (total: {total}).")
        else:
            doc.text("_No schema changes recorded for this scope._")
        return doc.render()

    doc.table(
        ["Time", "Change", "Table", "Column", "Old type", "New type"],
        [
            [
                entry.change_date,
                _format_schema_change_kind(entry.change),
                entry.table_name,
                entry.column_name,
                entry.old_data_type,
                entry.new_data_type,
            ]
            for entry in entries
        ],
        code=[2, 3],
    )

    if footer := format_page_footer(total, page, limit):
        doc.text(footer)

    return doc.render()


# ---------------------------------------------------------------------------
# set_monitor_predictive / set_monitor_static / set_monitor_historical
# ---------------------------------------------------------------------------

_SCHEMA_REJECT_MSG = "Schema monitors have no configurable threshold mode."
_FRESHNESS_STATIC_LOWER_REJECT_MSG = "Freshness monitors have no lower bound — pass upper_bound only."
_FRESHNESS_HISTORICAL_REJECT_MSG = (
    "Freshness monitors cannot use Historical Calculation mode; use Prediction Model or Static Thresholds."
)

_HISTORY_LOOKBACK_RANGE: tuple[int, int] = (1, 1000)

def _reject_schema_monitor(monitor: TestDefinition) -> None:
    if monitor.test_type == MonitorType.SCHEMA.value:
        raise MCPUserError(_SCHEMA_REJECT_MSG)


def _monitor_display_name(monitor: TestDefinition) -> str:
    """Confirmation-line label: type name for auto types (``Volume``), backticked
    metric name for Metric monitors (``\\`Daily revenue\\```)."""
    if monitor.test_type == MonitorType.METRIC.value:
        name = monitor.column_name or "unnamed metric"
        return f"`{name}`"
    return _MONITOR_LABEL[MonitorType(monitor.test_type)]


@with_database_session
@mcp_permission("edit")
def set_monitor_predictive(
    monitor_id: Annotated[str, Field(description="UUID of a monitor, e.g. from ``list_monitors``.")],
) -> str:
    """Switch a monitor to Prediction Model mode.
    Bounds are computed automatically from historical runs; no manual thresholds.

    Applies to Freshness, Volume, and Metric monitors. Schema monitors have no threshold mode and are rejected.
    """
    monitor = resolve_monitor(monitor_id)
    _reject_schema_monitor(monitor)

    current_mode, _, _ = TestDefinition._derive_threshold_mode(monitor)
    if current_mode == ThresholdMode.PREDICTION:
        raise MCPUserError("Monitor is already in Prediction Model mode.")

    # Bounds preserved — matches UI (test_definition_form.js:302-303) where prior override
    # values roll over to Predictive as a sensitivity-override pinch. ``prediction`` is
    # also preserved for parity with the UI save handler, which does not clear it on
    # mode switches; the next scheduled run refits from the training window.
    monitor.history_calculation = MonitorCalculation.PREDICT
    monitor.history_calculation_upper = None
    monitor.history_lookback = 0
    monitor.lock_refresh = True
    monitor.last_manual_update = datetime.now(UTC)
    monitor.save()

    display_name = _monitor_display_name(monitor)
    doc = MdDoc()
    doc.heading(1, f"Switched {display_name} monitor on `{monitor.table_name}` to {ThresholdMode.PREDICTION}.")
    doc.field("Mode", ThresholdMode.PREDICTION)

    # Mode-switch resets training. N starts at 0 because any prior training progress
    # belongs to the outgoing prediction and does not apply to this fresh window.
    suite = TestSuite.get(monitor.test_suite_id)
    if suite and suite.predict_min_lookback:
        m = suite.predict_min_lookback
        doc.text(
            f"Monitor is in training mode (0 of {m} runs complete); predictions activate after run {m}."
        )

    return doc.render()


@with_database_session
@mcp_permission("edit")
def set_monitor_static(
    monitor_id: Annotated[str, Field(description="UUID of a monitor, e.g. from ``list_monitors``.")],
    lower_bound: Annotated[float | None, Field(description="Numeric lower bound (Volume / Metric only).")] = None,
    upper_bound: Annotated[
        float | None,
        Field(description="Numeric upper bound. For Freshness, in minutes since last update."),
    ] = None,
) -> str:
    """Switch a monitor to Static Thresholds mode with fixed manual bounds.

    Volume and Metric monitors accept both bounds; Freshness monitors only accept
    ``upper_bound`` (the maximum interval since last update, in minutes). Passing
    ``lower_bound`` on a Freshness monitor is rejected.

    On a monitor already in Static mode, this is a partial update — only supplied fields
    change. On a mode switch, all required fields for the new mode must be supplied.
    Schema monitors have no threshold mode and are rejected.
    """
    monitor = resolve_monitor(monitor_id)
    _reject_schema_monitor(monitor)

    is_freshness = monitor.test_type == MonitorType.FRESHNESS.value
    if is_freshness and lower_bound is not None:
        raise MCPUserError(_FRESHNESS_STATIC_LOWER_REJECT_MSG)

    current_mode, _, _ = TestDefinition._derive_threshold_mode(monitor)
    is_partial_update = current_mode == ThresholdMode.STATIC

    if is_partial_update:
        if lower_bound is None and upper_bound is None:
            raise MCPUserError(
                "No fields supplied to update. Pass lower_bound or upper_bound."
            )
    elif is_freshness:
        if upper_bound is None:
            raise MCPUserError("Static mode requires upper_bound for Freshness monitors.")
    elif lower_bound is None or upper_bound is None:
        raise MCPUserError("Static mode requires lower_bound and upper_bound.")

    # Clear the fields that only Historical uses so a stale value never leaks into the
    # Static-mode SQL evaluation. ``prediction`` is preserved because it is ignored
    # outside Predictive mode — matches UI monitors_dashboard.py, which only clears it
    # inside the Freshness branch below.
    monitor.history_calculation = None
    monitor.history_calculation_upper = None
    monitor.history_lookback = 0

    if is_freshness:
        # UI hard-codes lower_tolerance=0, mirrors upper_tolerance to threshold_value,
        # and clears prediction. See monitors_dashboard.py:871-874.
        monitor.lower_tolerance = "0"
        if upper_bound is not None:
            monitor.upper_tolerance = str(upper_bound)
            monitor.threshold_value = str(upper_bound)
        monitor.prediction = None
    else:
        if lower_bound is not None:
            monitor.lower_tolerance = str(lower_bound)
        if upper_bound is not None:
            monitor.upper_tolerance = str(upper_bound)

    monitor.lock_refresh = True
    monitor.last_manual_update = datetime.now(UTC)
    monitor.save()

    display_name = _monitor_display_name(monitor)
    doc = MdDoc()
    if is_partial_update:
        supplied = [
            name for name, value in (("lower_bound", lower_bound), ("upper_bound", upper_bound))
            if value is not None
        ]
        doc.heading(1, f"Monitor already in {ThresholdMode.STATIC}; updated {', '.join(supplied)}.")
    else:
        doc.heading(1, f"Switched {display_name} monitor on `{monitor.table_name}` to {ThresholdMode.STATIC}.")

    doc.field("Mode", ThresholdMode.STATIC)
    if is_freshness:
        doc.field(
            "Maximum interval since last update",
            f"{monitor.upper_tolerance} minutes since last update",
        )
    else:
        doc.field("Lower Bound", monitor.lower_tolerance)
        doc.field("Upper Bound", monitor.upper_tolerance)

    return doc.render()


def _validate_expression_pair(
    calc: MonitorCalculation | None,
    expression: str | None,
    calc_field: str,
    expression_field: str,
) -> None:
    """Enforce the ``EXPRESSION`` calculation ↔ expression-body coupling on supplied args.

    An expression body is meaningful only when its calculation is ``Expression``; supplying
    one without the other is a shape error, not a silent default.
    """
    if expression is not None and calc != MonitorCalculation.EXPRESSION:
        raise MCPUserError(
            f"{expression_field} accepted only when {calc_field} is 'Expression'."
        )
    if calc == MonitorCalculation.EXPRESSION and expression is None:
        raise MCPUserError(
            f"{calc_field} is 'Expression' but no {expression_field} supplied."
        )


def _calculation_column_value(
    calc: MonitorCalculation, expression: str | None,
) -> str:
    """Encode a resolved calculation as the string that goes into ``history_calculation``
    / ``.history_calculation_upper`` — the raw label for standard calculations, the
    ``EXPR:[...]`` wrapper for expressions."""
    if calc == MonitorCalculation.EXPRESSION:
        return format_calculation_expression(expression or "")
    return calc.value


def _render_calculation_summary(doc: MdDoc, label: str, stored: str | None) -> None:
    """Render a `<label> Calculation` field, plus a `<label> Expression` field on the
    line below when the stored value is an ``EXPR:[...]`` wrapper."""
    if stored is None:
        return
    is_expression, payload = parse_calculation_expression(stored)
    if is_expression:
        doc.field(f"{label} Calculation", MonitorCalculation.EXPRESSION.value)
        doc.field(f"{label} Expression", payload)
    else:
        doc.field(f"{label} Calculation", stored)


@with_database_session
@mcp_permission("edit")
def set_monitor_historical(
    monitor_id: Annotated[str, Field(description="UUID of a monitor, e.g. from ``list_monitors``.")],
    lower_bound_calculation: Annotated[
        str | None,
        Field(
            description="How the lower bound is computed. One of ``Value``, ``Minimum``, ``Maximum``, ``Sum``, "
            "``Average``, ``Expression`` (case-insensitive).",
        ),
    ] = None,
    upper_bound_calculation: Annotated[
        str | None,
        Field(description="How the upper bound is computed. Same allowed values as ``lower_bound_calculation``."),
    ] = None,
    history_lookback: Annotated[
        int | None,
        Field(description="Number of past runs to aggregate over (1-1000)."),
    ] = None,
    lower_bound_expression: Annotated[
        str | None,
        Field(
            description="SQL expression for the lower bound, referencing ``{VALUE}`` / ``{MINIMUM}`` / ``{MAXIMUM}`` / "
            "``{SUM}`` / ``{AVERAGE}`` / ``{STANDARD_DEVIATION}`` placeholders (e.g. ``0.5 * {AVERAGE}``). Required "
            "when ``lower_bound_calculation`` is ``Expression``; rejected otherwise.",
        ),
    ] = None,
    upper_bound_expression: Annotated[
        str | None,
        Field(
            description="SQL expression for the upper bound, same placeholders as ``lower_bound_expression``. Required "
            "when ``upper_bound_calculation`` is ``Expression``; rejected otherwise.",
        ),
    ] = None,
) -> str:
    """Switch a monitor to Historical Calculation mode.
    Bounds are derived from a rolling window of past runs.

    Applies to Volume and Metric monitors. Freshness monitors are rejected.

    On a monitor already in Historical mode, this is a partial update — only supplied
    fields change. On a mode switch, ``lower_bound_calculation``, ``upper_bound_calculation``,
    and ``history_lookback`` are all required.
    """
    monitor = resolve_monitor(monitor_id)
    _reject_schema_monitor(monitor)

    if monitor.test_type == MonitorType.FRESHNESS.value:
        raise MCPUserError(_FRESHNESS_HISTORICAL_REJECT_MSG)

    lower_calc = (
        parse_monitor_calculation(lower_bound_calculation, "lower_bound_calculation")
        if lower_bound_calculation is not None else None
    )
    upper_calc = (
        parse_monitor_calculation(upper_bound_calculation, "upper_bound_calculation")
        if upper_bound_calculation is not None else None
    )

    _validate_expression_pair(
        lower_calc, lower_bound_expression, "lower_bound_calculation", "lower_bound_expression",
    )
    _validate_expression_pair(
        upper_calc, upper_bound_expression, "upper_bound_calculation", "upper_bound_expression",
    )

    if history_lookback is not None:
        low, high = _HISTORY_LOOKBACK_RANGE
        if not low <= history_lookback <= high:
            raise MCPUserError(f"history_lookback must be between {low} and {high}.")

    current_mode, _, _ = TestDefinition._derive_threshold_mode(monitor)
    is_partial_update = current_mode == ThresholdMode.HISTORICAL

    if is_partial_update:
        if lower_calc is None and upper_calc is None and history_lookback is None:
            raise MCPUserError(
                "No fields supplied to update. Pass lower_bound_calculation, "
                "upper_bound_calculation, or history_lookback."
            )
    elif lower_calc is None or upper_calc is None or history_lookback is None:
        raise MCPUserError(
            "Historical mode requires lower_bound_calculation, upper_bound_calculation, and history_lookback."
        )

    if lower_calc is not None:
        monitor.history_calculation = _calculation_column_value(lower_calc, lower_bound_expression)
    if upper_calc is not None:
        monitor.history_calculation_upper = _calculation_column_value(upper_calc, upper_bound_expression)
    if history_lookback is not None:
        monitor.history_lookback = history_lookback

    # Clear Static-mode bound fields so the Historical-mode SQL never reads a stale
    # bound. The execution template writes fresh lower_tolerance / upper_tolerance on
    # each run from history_calculation / history_calculation_upper. ``prediction`` is
    # preserved — it is ignored outside Predictive mode, matching UI behaviour.
    monitor.lower_tolerance = None
    monitor.upper_tolerance = None
    monitor.lock_refresh = True
    monitor.last_manual_update = datetime.now(UTC)
    monitor.save()

    display_name = _monitor_display_name(monitor)
    doc = MdDoc()
    if is_partial_update:
        supplied = [
            name for name, value in (
                ("lower_bound_calculation", lower_bound_calculation),
                ("upper_bound_calculation", upper_bound_calculation),
                ("history_lookback", history_lookback),
                ("lower_bound_expression", lower_bound_expression),
                ("upper_bound_expression", upper_bound_expression),
            )
            if value is not None
        ]
        doc.heading(1, f"Monitor already in {ThresholdMode.HISTORICAL}; updated {', '.join(supplied)}.")
    else:
        doc.heading(1, f"Switched {display_name} monitor on `{monitor.table_name}` to {ThresholdMode.HISTORICAL}.")

    doc.field("Mode", ThresholdMode.HISTORICAL)
    _render_calculation_summary(doc, "Lower Bound", monitor.history_calculation)
    _render_calculation_summary(doc, "Upper Bound", monitor.history_calculation_upper)
    doc.field("History Lookback", f"{monitor.history_lookback} runs")

    return doc.render()
