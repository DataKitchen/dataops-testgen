"""API v1 — monitor reads."""

from fastapi import APIRouter, Depends, Query

from testgen.api.deps import db_session, resolve_monitor, resolve_table_group
from testgen.api.enums import (
    MONITOR_TYPE_FROM_DB,
    MonitorSortField,
    SortOrder,
    TableState,
    monitor_sort_to_model,
    threshold_mode_from_db,
)
from testgen.api.schemas import (
    ErrorResponse,
    MetricMonitorSummary,
    MonitorSeriesResponse,
    MonitorSummaryListResponse,
    MonitorTableRow,
    MonitorTotals,
    MonitorTypeSummary,
    SchemaMonitorSummary,
)
from testgen.common.enums import MonitorType as DbMonitorType
from testgen.common.models.monitor import Monitor
from testgen.common.models.table_group import MonitorTableSummary, TableGroup

_ALL_MONITOR_TYPES = [m.value for m in DbMonitorType]

_error_responses = {404: {"model": ErrorResponse, "description": "Not found"}}

router = APIRouter(tags=["monitors"], dependencies=[Depends(db_session)], responses=_error_responses)


def _to_row(s: MonitorTableSummary) -> MonitorTableRow:
    return MonitorTableRow(
        table_name=s.table_name,
        row_count=s.row_count,
        previous_row_count=s.previous_row_count,
        latest_update=s.latest_update,
        table_state=TableState(s.table_state) if s.table_state else None,
        freshness=MonitorTypeSummary(
            monitor_id=s.freshness_monitor_id, anomalies=s.freshness_anomalies,
            is_training=s.freshness_is_training, is_pending=s.freshness_is_pending,
        ),
        volume=MonitorTypeSummary(
            monitor_id=s.volume_monitor_id, anomalies=s.volume_anomalies,
            is_training=s.volume_is_training, is_pending=s.volume_is_pending,
        ),
        schema_=SchemaMonitorSummary(
            monitor_id=s.schema_monitor_id, anomalies=s.schema_anomalies, is_pending=s.schema_is_pending,
            column_adds=s.column_adds, column_drops=s.column_drops, column_mods=s.column_mods,
        ),
        metrics=[
            MetricMonitorSummary(
                monitor_id=m["monitor_id"], metric_name=m["column_name"],
                anomalies=m["anomalies"], is_training=m["is_training"], is_pending=m["is_pending"],
            )
            for m in s.metric_monitors
        ],
    )


@router.get("/table-groups/{table_group_id}/monitors", response_model=MonitorSummaryListResponse)
def list_table_monitors(
    table_group: TableGroup = resolve_table_group("view"),  # noqa: B008
    table_name: str | None = Query(default=None),
    anomalies_only: bool = Query(default=False),
    sort: MonitorSortField = Query(default=MonitorSortField.table_name),  # noqa: B008
    order: SortOrder = Query(default=SortOrder.asc),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Per-table monitoring summary for a table group, with group totals.

    Each row nests per-type state: ``freshness`` / ``volume`` / ``schema`` (one monitor each)
    and ``metrics`` (one per metric). ``anomalies_only`` restricts to tables with at least one
    anomaly of any type. ``monitor_id`` on a per-type object addresses that monitor's series.
    """
    rows, total = TableGroup.list_monitor_table_summaries(
        table_group.id,
        anomaly_types=_ALL_MONITOR_TYPES if anomalies_only else None,
        sort_by=monitor_sort_to_model(sort, order),
        table_name_filter=table_name,
        page=page,
        limit=limit,
    )
    group = TableGroup.get_monitor_group_summary(table_group.id)
    return MonitorSummaryListResponse(
        items=[_to_row(r) for r in rows],
        page=page,
        limit=limit,
        total=total,
        totals=MonitorTotals(
            lookback=group.lookback,
            lookback_start=group.lookback_start,
            lookback_end=group.lookback_end,
            total_monitored_tables=group.total_monitored_tables,
            freshness_anomalies=group.freshness_anomalies,
            volume_anomalies=group.volume_anomalies,
            schema_anomalies=group.schema_anomalies,
            metric_anomalies=group.metric_anomalies,
        ),
    )


@router.get("/monitors/{monitor_id}/series", response_model=MonitorSeriesResponse)
def get_monitor_series(monitor: Monitor = resolve_monitor("view")):  # noqa: B008
    """A monitor's lookback time-series, type-discriminated, with a self-contained header.

    ``points`` shape depends on ``type``:
    - volume / metric: ``{time, value, lower_bound, upper_bound, threshold_value, is_anomaly, is_training, is_error, is_pending}``
    - freshness: ``{time, minutes_since_update, staleness_threshold, lower_bound, upper_bound, update_detected, is_anomaly, is_training, is_error, is_pending}``
    - schema: ``{time, table_change, additions, deletions, modifications, window_start, is_error}``

    ``current_bands`` carries the latest thresholds (null while training); its shape also
    depends on ``type``. The latest point is the monitor's current state.
    """
    series = monitor.series()
    return MonitorSeriesResponse(
        monitor_id=series.monitor_id,
        type=MONITOR_TYPE_FROM_DB[DbMonitorType(series.type)],
        threshold_mode=threshold_mode_from_db(series.threshold_mode),
        table_name=series.table_name,
        column_name=series.column_name,
        lookback=series.lookback,
        is_training=series.is_training,
        current_bands=series.bands,
        points=series.points,
    )
