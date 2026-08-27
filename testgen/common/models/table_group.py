from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, Column, Float, ForeignKey, String, asc, func, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.enums import MonitorType
from testgen.common.models import get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, YNString
from testgen.common.models.entity import Entity, EntityMinimal
from testgen.common.models.monitor import (
    build_series_sql,
    parse_freshness_message,
    parse_schema_event,
    parse_value_event,
)
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.utils import dict_from_kv, is_uuid4


@dataclass
class TableGroupMinimal(EntityMinimal):
    id: UUID
    project_code: str
    connection_id: int
    table_groups_name: str
    table_group_schema: str
    profiling_table_set: str
    profiling_include_mask: str
    profiling_exclude_mask: str
    profile_use_sampling: bool
    profiling_delay_days: str
    monitor_test_suite_id: UUID | None
    profile_flag_cdes: bool
    profile_flag_pii: bool
    profile_exclude_xde: bool
    last_complete_profile_run_id: UUID | None


@dataclass
class TableGroupStats(EntityMinimal):
    id: UUID
    table_groups_name: str
    table_group_schema: str
    table_ct: int
    column_ct: int
    approx_record_ct: int
    record_ct: int
    approx_data_point_ct: int
    data_point_ct: int


@dataclass
class TableGroupListItem(EntityMinimal):
    id: UUID
    table_groups_name: str
    table_group_schema: str
    project_code: str
    connection_name: str | None
    table_count: int
    column_count: int | None
    row_count: int | None
    last_profiled_date: datetime | None
    last_tested_date: datetime | None
    profiling_score: float | None
    testing_score: float | None
    quality_score: float | None


@dataclass
class TableGroupSummary(EntityMinimal):
    id: UUID
    table_groups_name: str
    connection_name: str | None
    table_ct: int
    column_ct: int
    approx_record_ct: int
    record_ct: int
    approx_data_point_ct: int
    data_point_ct: int
    dq_score_profiling: float
    dq_score_testing: float
    latest_profile_id: UUID | None
    latest_profile_job_execution_id: UUID | None
    latest_profile_start: datetime | None
    latest_hygiene_issues_ct: int
    latest_hygiene_issues_definite_ct: int
    latest_hygiene_issues_likely_ct: int
    latest_hygiene_issues_possible_ct: int
    latest_hygiene_issues_dismissed_ct: int
    monitor_test_suite_id: UUID | None
    monitor_lookback: int | None
    monitor_lookback_start: datetime | None
    monitor_lookback_end: datetime | None
    monitor_freshness_anomalies: int | None
    monitor_schema_anomalies: int | None
    monitor_volume_anomalies: int | None
    monitor_metric_anomalies: int | None
    monitor_freshness_has_errors: bool | None
    monitor_volume_has_errors: bool | None
    monitor_schema_has_errors: bool | None
    monitor_metric_has_errors: bool | None
    monitor_freshness_is_training: bool | None
    monitor_volume_is_training: bool | None
    monitor_metric_is_training: bool | None
    monitor_freshness_is_pending: bool | None
    monitor_volume_is_pending: bool | None
    monitor_schema_is_pending: bool | None
    monitor_metric_is_pending: bool | None
    total_count: int = 0


@dataclass
class MonitorTableSummary:
    """One row per monitored table in a table group's lookback window.

    Per-type ``*_anomalies`` count result_code = 0 results; ``*_is_training`` reflects the
    latest run's training-mode state (result_code = -1); ``*_is_pending`` is True when no
    result of that type exists in the window (monitor not yet configured / executed).
    Schema is special-cased: ``*_is_pending`` only when no events at all, and ``table_state``
    captures whether the table was added / dropped / column-modified in the window.

    Two prefixes re-scope the change measures from the whole window to a single run.
    ``latest_run_`` fields measure the most recent run alone: the ``latest_run_column_*``
    counts, ``latest_run_table_state``, and ``latest_run_schema_anomalies`` cover only that
    run's schema events, and ``latest_run_freshness_message`` carries its raw
    ``result_message`` for callers rendering the freshness verdict. ``previous_run_`` fields
    describe the run before it: ``previous_run_start`` is
    that run's start time, bounding the latest run's interval, and ``previous_run_row_count``
    is its row count — the baseline for a run-over-run delta, where ``previous_row_count`` is
    the baseline for a whole-window one. ``row_count`` is the latest run's count and serves as
    the current value for both deltas.
    """
    table_name: str
    lookback: int
    lookback_start: datetime | None
    lookback_end: datetime | None
    freshness_anomalies: int
    volume_anomalies: int
    schema_anomalies: int
    metric_anomalies: int
    freshness_is_training: bool | None
    volume_is_training: bool | None
    metric_is_training: bool | None
    freshness_is_pending: bool
    volume_is_pending: bool
    schema_is_pending: bool
    metric_is_pending: bool
    freshness_error_message: str | None
    volume_error_message: str | None
    schema_error_message: str | None
    metric_error_message: str | None
    latest_update: datetime | None
    row_count: int | None
    previous_row_count: int | None
    column_adds: int
    column_drops: int
    column_mods: int
    table_state: str | None
    freshness_monitor_id: UUID | None = None
    volume_monitor_id: UUID | None = None
    schema_monitor_id: UUID | None = None
    metric_monitors: list = field(default_factory=list)
    previous_run_start: datetime | None = None
    previous_run_row_count: int | None = None
    latest_run_schema_anomalies: int = 0
    latest_run_column_adds: int = 0
    latest_run_column_drops: int = 0
    latest_run_column_mods: int = 0
    latest_run_table_state: str | None = None
    latest_run_freshness_message: str | None = None


@dataclass
class MonitorGroupSummary:
    """Aggregated monitor health for a single table group across its lookback window.

    Booleans are group-wide: ``*_has_errors`` is True iff at least one monitored table errored;
    ``*_is_training`` is True iff every monitored table is in training (and at least one is);
    ``*_is_pending`` is True iff every monitored table is pending.
    """
    lookback: int
    lookback_start: datetime | None
    lookback_end: datetime | None
    total_monitored_tables: int
    freshness_anomalies: int
    volume_anomalies: int
    schema_anomalies: int
    metric_anomalies: int
    freshness_has_errors: bool
    volume_has_errors: bool
    schema_has_errors: bool
    metric_has_errors: bool
    freshness_is_training: bool
    volume_is_training: bool
    metric_is_training: bool
    freshness_is_pending: bool
    volume_is_pending: bool
    schema_is_pending: bool
    metric_is_pending: bool


_ANOMALY_TYPE_TO_COLUMN: dict[str, str] = {
    MonitorType.FRESHNESS.value: "freshness_anomalies",
    MonitorType.VOLUME.value: "volume_anomalies",
    MonitorType.SCHEMA.value: "schema_anomalies",
    MonitorType.METRIC.value: "metric_anomalies",
}


def _row_count_change_expr(baseline_column: str, state_column: str) -> str:
    """SQL for a row-count delta that sorts unknown changes last.

    ``baseline_column`` is the ``baseline_tables`` count the delta measures from, and
    ``state_column`` the ``monitor_tables`` state describing the same window.
    """
    return (
        "(CASE WHEN monitor_tables.row_count IS NOT NULL THEN monitor_tables.row_count"
        f" WHEN monitor_tables.{state_column} = 'dropped' THEN 0 END"
        f" - CASE WHEN baseline_tables.{baseline_column} IS NOT NULL THEN baseline_tables.{baseline_column}"
        f" WHEN monitor_tables.{state_column} = 'added' THEN 0 END)"
    )


_MONITOR_SORT_COLUMN: dict[str, str] = {
    "table_name": "LOWER(monitor_tables.table_name)",
    "freshness_anomalies": "monitor_tables.freshness_anomalies",
    "volume_anomalies": "monitor_tables.volume_anomalies",
    "schema_anomalies": "monitor_tables.schema_anomalies",
    "metric_anomalies": "monitor_tables.metric_anomalies",
    "total_anomalies": (
        "monitor_tables.freshness_anomalies + monitor_tables.volume_anomalies"
        " + monitor_tables.schema_anomalies + monitor_tables.metric_anomalies"
    ),
    "latest_update": "monitor_tables.latest_update",
    "row_count": "monitor_tables.row_count",
    # A missing count is zero only where the table's state accounts for it: an added table
    # held no rows before it existed, a dropped one holds none now. Any other missing
    # endpoint leaves the expression NULL so the row sorts last as unknown, matching the
    # em-dash the cell renders rather than ranking it by a change nobody measured.
    "row_count_change": _row_count_change_expr("previous_row_count", "table_state"),
    "latest_run_row_count_change": _row_count_change_expr("previous_run_row_count", "latest_run_table_state"),
}


def _build_monitor_order_clause(sort_by: str | None, anomaly_type: str | None) -> str:
    """Build an ORDER BY clause for the monitor-changes-by-tables query.

    ``sort_by`` is a field name with optional ``_desc`` suffix. When ``sort_by`` is
    ``total_anomalies_desc`` and ``anomaly_type`` is set, the sort collapses to that
    type's column so callers see "most anomalies of the filtered type first." Falls
    back to ``LOWER(table_name) ASC`` for unknown / missing values.
    """
    descending = False
    field = sort_by
    if field and field.endswith("_desc"):
        descending = True
        field = field[: -len("_desc")]

    if field == "total_anomalies" and anomaly_type is not None:
        field = _ANOMALY_TYPE_TO_COLUMN[anomaly_type]

    column = _MONITOR_SORT_COLUMN.get(field or "table_name", _MONITOR_SORT_COLUMN["table_name"])
    direction = "DESC" if descending else "ASC"
    return f"ORDER BY {column} {direction} NULLS LAST"


class TableGroup(Entity):
    __tablename__ = "table_groups"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String, ForeignKey("projects.project_code"))
    connection_id: int = Column(BigInteger, ForeignKey("connections.connection_id"))
    default_test_suite_id: UUID | None = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("test_suites.id"),
        default=None,
    )
    monitor_test_suite_id: UUID | None = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("test_suites.id"),
        default=None,
    )
    table_groups_name: str = Column(String)
    table_group_schema: str = Column(String)
    profiling_table_set: str = Column(NullIfEmptyString)
    profiling_include_mask: str = Column(NullIfEmptyString)
    profiling_exclude_mask: str = Column(NullIfEmptyString)
    profile_id_column_mask: str = Column(String, default="%id")
    profile_sk_column_mask: str = Column(String, default="%_sk")
    profile_use_sampling: bool = Column(YNString, default="N")
    profile_sample_percent: str = Column(String, default="30")
    profile_sample_min_count: int = Column(BigInteger, default=100000)
    profiling_delay_days: str = Column(String, default="0")
    profile_flag_cdes: bool = Column(Boolean, default=True)
    profile_flag_pii: bool = Column(Boolean, default=True)
    profile_exclude_xde: bool = Column(Boolean, default=True)
    include_in_dashboard: bool = Column(Boolean, default=True)
    description: str = Column(NullIfEmptyString)
    data_source: str = Column(NullIfEmptyString)
    source_system: str = Column(NullIfEmptyString)
    source_process: str = Column(NullIfEmptyString)
    data_location: str = Column(NullIfEmptyString)
    business_domain: str = Column(NullIfEmptyString)
    stakeholder_group: str = Column(NullIfEmptyString)
    transform_level: str = Column(NullIfEmptyString)
    data_product: str = Column(NullIfEmptyString)
    data_classification: str = Column(NullIfEmptyString)
    last_complete_profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True))
    dq_score_profiling: float = Column(Float)
    dq_score_testing: float = Column(Float)

    _default_order_by = (asc(func.lower(table_groups_name)),)
    _minimal_columns = TableGroupMinimal.__annotations__.keys()
    _update_exclude_columns = (
        id,
        project_code,
        connection_id,
        last_complete_profile_run_id,
        dq_score_profiling,
        dq_score_testing,
    )

    @property
    def quality_score(self) -> float:
        """Overall quality score per ``utils.score``: profiling * testing when both
        exist; the non-null one when only one ran; ``0.0`` when neither has run.

        Mirrors what Project Dashboard, data_catalog, and inventory_service display.
        Render through ``utils.friendly_score`` to get the user-facing percentage form
        (``"95.0"`` rather than ``"0.95"``). The list-side equivalent is computed in
        SQL inside ``_list_with_activity`` — keep both in sync if the formula changes.
        """
        from testgen.utils import score

        return score(self.dq_score_profiling, self.dq_score_testing)

    @classmethod
    def get_minimal(cls, id_: str | UUID) -> TableGroupMinimal | None:
        result = cls._get_columns(id_, cls._minimal_columns)
        return TableGroupMinimal(**result) if result else None

    @classmethod
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TableGroupMinimal]:
        results = cls._select_columns_where(cls._minimal_columns, *clauses, order_by=order_by)
        return [TableGroupMinimal(**row) for row in results]

    @classmethod
    def select_stats(cls, project_code: str, table_group_id: str | UUID | None = None) -> Iterable[TableGroupStats]:
        query = f"""
        WITH stats AS (
            SELECT table_groups_id,
                COUNT(*) AS table_ct,
                SUM(column_ct) AS column_ct,
                SUM(approx_record_ct) AS approx_record_ct,
                SUM(record_ct) AS record_ct,
                SUM(column_ct * approx_record_ct) AS approx_data_point_ct,
                SUM(column_ct * record_ct) AS data_point_ct
            FROM data_table_chars
            GROUP BY table_groups_id
        )
        SELECT groups.id,
            groups.table_groups_name,
            groups.table_group_schema,
            stats.table_ct,
            stats.column_ct,
            stats.approx_record_ct,
            stats.record_ct,
            stats.approx_data_point_ct,
            stats.data_point_ct
        FROM table_groups AS groups
            LEFT JOIN stats ON (groups.id = stats.table_groups_id)
        WHERE groups.project_code = :project_code
            {"AND groups.id = :table_group_id" if table_group_id else ""}
        ORDER BY LOWER(groups.table_groups_name);
        """
        params = {"project_code": project_code, "table_group_id": table_group_id}
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        return [TableGroupStats(**row) for row in results]

    @classmethod
    def select_summary(
        cls,
        project_code: str,
        table_group_id: str | UUID | None = None,
        for_dashboard: bool = False,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[TableGroupSummary], int]:
        if table_group_id is not None and not is_uuid4(table_group_id):
            return [], 0

        paginate = page is not None and page_size is not None

        query = f"""
        WITH stats AS (
            SELECT table_groups_id,
                COUNT(*) AS table_ct,
                SUM(column_ct) AS column_ct,
                SUM(approx_record_ct) AS approx_record_ct,
                SUM(record_ct) AS record_ct,
                SUM(column_ct * approx_record_ct) AS approx_data_point_ct,
                SUM(column_ct * record_ct) AS data_point_ct
            FROM data_table_chars
            GROUP BY table_groups_id
        ),
        latest_profile AS (
            SELECT latest_run.table_groups_id,
                latest_run.id,
                MAX(latest_je.started_at) AS started_at,
                latest_run.anomaly_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                        AND anomaly_types.issue_likelihood = 'Definite' THEN 1
                        ELSE 0
                    END
                ) AS definite_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                        AND anomaly_types.issue_likelihood = 'Likely' THEN 1
                        ELSE 0
                    END
                ) AS likely_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                        AND anomaly_types.issue_likelihood IN ('Possible', 'Potential PII') THEN 1
                        ELSE 0
                    END
                ) AS possible_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                        ELSE 0
                    END
                ) AS dismissed_ct
            FROM table_groups groups
                LEFT JOIN profiling_runs latest_run ON (
                    groups.last_complete_profile_run_id = latest_run.id
                )
                LEFT JOIN job_executions latest_je ON (
                    latest_run.id = latest_je.id
                )
                LEFT JOIN profile_anomaly_results latest_anomalies ON (
                    latest_run.id = latest_anomalies.profile_run_id
                )
                LEFT JOIN profile_anomaly_types anomaly_types ON (
                    anomaly_types.id = latest_anomalies.anomaly_id
                )
            GROUP BY latest_run.id
        ),
        ranked_test_runs AS (
            SELECT
                table_groups.id AS table_group_id,
                test_runs.id,
                test_runs.test_starttime,
                COALESCE(test_suites.monitor_lookback, 1) AS lookback,
                ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
            FROM table_groups
            INNER JOIN test_runs
                ON (test_runs.test_suite_id = table_groups.monitor_test_suite_id)
            INNER JOIN test_suites
                ON (table_groups.monitor_test_suite_id = test_suites.id)
            WHERE table_groups.project_code = :project_code
        ),
        monitor_tables AS (
            SELECT
                ranked_test_runs.table_group_id,
                SUM(CASE WHEN results.test_type = 'Freshness_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END) AS freshness_anomalies,
                SUM(CASE WHEN results.test_type = 'Schema_Drift' AND results.result_code = 0 THEN 1 ELSE 0 END) AS schema_anomalies,
                SUM(CASE WHEN results.test_type = 'Volume_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END) AS volume_anomalies,
                SUM(CASE WHEN results.test_type = 'Metric_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END) AS metric_anomalies,
                BOOL_OR(results.result_status = 'Error') FILTER (WHERE results.test_type = 'Freshness_Trend' AND ranked_test_runs.position = 1) AS freshness_has_errors,
                BOOL_OR(results.result_status = 'Error') FILTER (WHERE results.test_type = 'Volume_Trend' AND ranked_test_runs.position = 1) AS volume_has_errors,
                BOOL_OR(results.result_status = 'Error') FILTER (WHERE results.test_type = 'Schema_Drift' AND ranked_test_runs.position = 1) AS schema_has_errors,
                BOOL_OR(results.result_status = 'Error') FILTER (WHERE results.test_type = 'Metric_Trend' AND ranked_test_runs.position = 1) AS metric_has_errors,
                BOOL_AND(results.result_code = -1) FILTER (WHERE results.test_type = 'Freshness_Trend' AND ranked_test_runs.position = 1) AS freshness_is_training,
                BOOL_AND(results.result_code = -1) FILTER (WHERE results.test_type = 'Volume_Trend' AND ranked_test_runs.position = 1) AS volume_is_training,
                BOOL_AND(results.result_code = -1) FILTER (WHERE results.test_type = 'Metric_Trend' AND ranked_test_runs.position = 1) AS metric_is_training,
                BOOL_OR(results.test_type = 'Freshness_Trend') IS NOT TRUE AS freshness_is_pending,
                BOOL_OR(results.test_type = 'Volume_Trend') IS NOT TRUE AS volume_is_pending,
                -- Schema monitor only creates results on schema changes (Failed)
                -- Mark it as pending only if there are no results of any test type
                BOOL_OR(results.test_time IS NOT NULL) IS NOT TRUE AS schema_is_pending,
                BOOL_OR(results.test_type = 'Metric_Trend') IS NOT TRUE AS metric_is_pending
            FROM ranked_test_runs
            INNER JOIN test_results AS results
                ON (results.test_run_id = ranked_test_runs.id)
            WHERE ranked_test_runs.position <= ranked_test_runs.lookback
                AND results.table_name IS NOT NULL
            GROUP BY ranked_test_runs.table_group_id
        ),
        lookback_windows AS (
            SELECT
                table_group_id,
                lookback,
                MIN(test_starttime) FILTER (WHERE position = LEAST(lookback + 1, max_position)) AS lookback_start,
                MAX(test_starttime) FILTER (WHERE position = 1) AS lookback_end
            FROM (
                SELECT *, MAX(position) OVER (PARTITION BY table_group_id) as max_position
                FROM ranked_test_runs
            ) pos
            GROUP BY table_group_id, lookback
        )
        SELECT groups.id,
            groups.table_groups_name,
            connections.connection_name,
            stats.table_ct,
            stats.column_ct,
            stats.approx_record_ct,
            stats.record_ct,
            stats.approx_data_point_ct,
            stats.data_point_ct,
            groups.dq_score_profiling,
            groups.dq_score_testing,
            latest_profile.id AS latest_profile_id,
            latest_profile.id AS latest_profile_job_execution_id,
            latest_profile.started_at AS latest_profile_start,
            latest_profile.anomaly_ct AS latest_hygiene_issues_ct,
            latest_profile.definite_ct AS latest_hygiene_issues_definite_ct,
            latest_profile.likely_ct AS latest_hygiene_issues_likely_ct,
            latest_profile.possible_ct AS latest_hygiene_issues_possible_ct,
            latest_profile.dismissed_ct AS latest_hygiene_issues_dismissed_ct,
            groups.monitor_test_suite_id AS monitor_test_suite_id,
            lookback_windows.lookback AS monitor_lookback,
            lookback_windows.lookback_start AS monitor_lookback_start,
            lookback_windows.lookback_end AS monitor_lookback_end,
            monitor_tables.freshness_anomalies AS monitor_freshness_anomalies,
            monitor_tables.schema_anomalies AS monitor_schema_anomalies,
            monitor_tables.volume_anomalies AS monitor_volume_anomalies,
            monitor_tables.metric_anomalies AS monitor_metric_anomalies,
            monitor_tables.freshness_has_errors AS monitor_freshness_has_errors,
            monitor_tables.volume_has_errors AS monitor_volume_has_errors,
            monitor_tables.schema_has_errors AS monitor_schema_has_errors,
            monitor_tables.metric_has_errors AS monitor_metric_has_errors,
            monitor_tables.freshness_is_training AS monitor_freshness_is_training,
            monitor_tables.volume_is_training AS monitor_volume_is_training,
            monitor_tables.metric_is_training AS monitor_metric_is_training,
            monitor_tables.freshness_is_pending AS monitor_freshness_is_pending,
            monitor_tables.volume_is_pending AS monitor_volume_is_pending,
            monitor_tables.schema_is_pending AS monitor_schema_is_pending,
            monitor_tables.metric_is_pending AS monitor_metric_is_pending,
            COUNT(*) OVER() AS total_count
        FROM table_groups AS groups
            LEFT JOIN connections ON (groups.connection_id = connections.connection_id)
            LEFT JOIN stats ON (groups.id = stats.table_groups_id)
            LEFT JOIN latest_profile ON (groups.id = latest_profile.table_groups_id)
            LEFT JOIN monitor_tables ON (groups.id = monitor_tables.table_group_id)
            LEFT JOIN lookback_windows ON (groups.id = lookback_windows.table_group_id)
        WHERE groups.project_code = :project_code
            {"AND groups.id = :table_group_id" if table_group_id else ""}
            {"AND groups.include_in_dashboard IS TRUE" if for_dashboard else ""}
        ORDER BY LOWER(groups.table_groups_name)
        {"LIMIT :limit OFFSET :offset" if paginate else ""};
        """
        params: dict = {"project_code": project_code}
        if table_group_id:
            params["table_group_id"] = str(table_group_id)
        if paginate:
            params["limit"] = page_size
            params["offset"] = (page - 1) * page_size

        results = get_current_session().execute(text(query), params).mappings().all()
        items = [TableGroupSummary(**row) for row in results]
        total = items[0].total_count if items else 0
        return items, total

    @classmethod
    def list_for_project(
        cls, project_code: str, *, page: int = 1, limit: int = 20
    ) -> tuple[list[TableGroupListItem], int]:
        """Config-focused paginated listing for a project, with table count and activity timestamps."""
        return cls._list_with_activity(
            scope_sql="groups.project_code = :project_code",
            scope_params={"project_code": project_code},
            page=page,
            limit=limit,
        )

    @classmethod
    def list_for_connection(
        cls, connection_id: int, *, page: int = 1, limit: int = 20
    ) -> tuple[list[TableGroupListItem], int]:
        """Config-focused paginated listing for a connection, with table count and activity timestamps."""
        return cls._list_with_activity(
            scope_sql="groups.connection_id = :connection_id",
            scope_params={"connection_id": connection_id},
            page=page,
            limit=limit,
        )

    @classmethod
    def _list_with_activity(
        cls,
        *,
        scope_sql: str,
        scope_params: dict,
        page: int,
        limit: int,
    ) -> tuple[list[TableGroupListItem], int]:
        session = get_current_session()

        # Separate COUNT(*) query — keeps `total` correct on out-of-range pages where
        # the page rows are empty (a window function over zero rows would return 0).
        total_query = f"SELECT COUNT(*) FROM table_groups AS groups WHERE {scope_sql};"
        total = session.execute(text(total_query), scope_params).scalar() or 0
        if total == 0:
            return [], 0

        params: dict = {**scope_params, "limit": limit, "offset": (page - 1) * limit}
        rows_query = f"""
        WITH stats AS (
            SELECT table_groups_id,
                COUNT(*) AS table_count,
                SUM(column_ct) AS column_count,
                SUM(COALESCE(record_ct, approx_record_ct)) AS row_count
            FROM data_table_chars
            GROUP BY table_groups_id
        ),
        latest_profile AS (
            SELECT pr.table_groups_id, MAX(je.started_at) AS started_at
            FROM profiling_runs pr
                LEFT JOIN job_executions je ON je.id = pr.id
            GROUP BY pr.table_groups_id
        ),
        latest_test AS (
            SELECT ts.table_groups_id, MAX(tr.test_starttime) AS test_starttime
            FROM test_runs tr
                JOIN test_suites ts ON ts.id = tr.test_suite_id
            WHERE ts.is_monitor IS NOT TRUE
            GROUP BY ts.table_groups_id
        )
        SELECT
            groups.id,
            groups.table_groups_name,
            groups.table_group_schema,
            groups.project_code,
            connections.connection_name,
            COALESCE(stats.table_count, 0) AS table_count,
            stats.column_count,
            stats.row_count,
            latest_profile.started_at AS last_profiled_date,
            latest_test.test_starttime AS last_tested_date,
            groups.dq_score_profiling AS profiling_score,
            groups.dq_score_testing AS testing_score,
            -- Mirrors utils.score: product when both exist, else the non-null one, else NULL.
            CASE
                WHEN groups.dq_score_profiling IS NOT NULL AND groups.dq_score_testing IS NOT NULL
                    THEN groups.dq_score_profiling * groups.dq_score_testing
                ELSE COALESCE(groups.dq_score_profiling, groups.dq_score_testing)
            END AS quality_score
        FROM table_groups AS groups
            LEFT JOIN connections ON connections.connection_id = groups.connection_id
            LEFT JOIN stats ON stats.table_groups_id = groups.id
            LEFT JOIN latest_profile ON latest_profile.table_groups_id = groups.id
            LEFT JOIN latest_test ON latest_test.table_groups_id = groups.id
        WHERE {scope_sql}
        ORDER BY LOWER(groups.table_groups_name)
        LIMIT :limit OFFSET :offset;
        """
        rows = session.execute(text(rows_query), params).mappings().all()
        items = [TableGroupListItem(**row) for row in rows]
        return items, total

    @classmethod
    def list_monitor_table_summaries(
        cls,
        table_group_id: str | UUID,
        *,
        anomaly_types: list[str] | None = None,
        sort_by: str | None = None,
        lookback_override: int | None = None,
        table_name_filter: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[MonitorTableSummary], int]:
        """Per-monitored-table summary, paginated within the group's lookback window.

        ``anomaly_types`` are internal ``test_type`` values (``Freshness_Trend`` /
        ``Volume_Trend`` / ``Schema_Drift`` / ``Metric_Trend``) — filters to tables with
        at least one anomaly of any listed type in the window. ``lookback_override``
        replaces the suite-configured lookback for ad-hoc views. ``sort_by`` accepts
        the dataclass field names (e.g. ``freshness_anomalies``, ``latest_update``,
        ``row_count``, ``total_anomalies``) suffixed with ``_desc`` for descending
        order; ``table_name`` is the default and sorts case-insensitively.
        """
        # Run the CTE twice (rows + COUNT) so the total reflects every matching table,
        # not just rows on the requested page — a window function would short-cut to 0
        # on out-of-range pages.
        query, params = cls._monitor_changes_by_tables_query(
            table_group_id,
            anomaly_types=anomaly_types,
            sort_by=sort_by,
            lookback_override=lookback_override,
            table_name_filter=table_name_filter,
            limit=limit,
            offset=(page - 1) * limit,
        )
        count_query, count_params = cls._monitor_changes_by_tables_query(
            table_group_id,
            anomaly_types=anomaly_types,
            lookback_override=lookback_override,
            table_name_filter=table_name_filter,
        )
        session = get_current_session()
        rows = session.execute(text(query), params).mappings().all()
        total = session.scalar(
            text(f"SELECT COUNT(*) FROM ({count_query}) AS subquery"), count_params
        ) or 0
        return [MonitorTableSummary(**row) for row in rows], int(total)

    @classmethod
    def get_monitor_group_summary(
        cls,
        table_group_id: str | UUID,
        *,
        lookback_override: int | None = None,
    ) -> MonitorGroupSummary:
        """Group-level monitor health across the lookback window.

        Aggregates per-table results from ``list_monitor_table_summaries`` into a single
        row. Returns zeroed counts and all-pending booleans when no tables are
        monitored — callers detect "not monitored" upstream via the linked suite.
        """
        inner_query, params = cls._monitor_changes_by_tables_query(
            table_group_id, lookback_override=lookback_override,
        )
        query = f"""
        SELECT
            COALESCE(MAX(lookback), 0)::INTEGER AS lookback,
            MIN(lookback_start) AS lookback_start,
            MAX(lookback_end) AS lookback_end,
            COUNT(*)::INTEGER AS total_monitored_tables,
            COALESCE(SUM(freshness_anomalies), 0)::INTEGER AS freshness_anomalies,
            COALESCE(SUM(volume_anomalies), 0)::INTEGER AS volume_anomalies,
            COALESCE(SUM(schema_anomalies), 0)::INTEGER AS schema_anomalies,
            COALESCE(SUM(metric_anomalies), 0)::INTEGER AS metric_anomalies,
            COALESCE(BOOL_OR(freshness_error_message IS NOT NULL), FALSE) AS freshness_has_errors,
            COALESCE(BOOL_OR(volume_error_message IS NOT NULL), FALSE) AS volume_has_errors,
            COALESCE(BOOL_OR(schema_error_message IS NOT NULL), FALSE) AS schema_has_errors,
            COALESCE(BOOL_OR(metric_error_message IS NOT NULL), FALSE) AS metric_has_errors,
            COALESCE(
                BOOL_OR(freshness_is_training) AND BOOL_AND(freshness_is_training OR freshness_is_pending),
                FALSE
            ) AS freshness_is_training,
            COALESCE(
                BOOL_OR(volume_is_training) AND BOOL_AND(volume_is_training OR volume_is_pending),
                FALSE
            ) AS volume_is_training,
            COALESCE(
                BOOL_OR(metric_is_training) AND BOOL_AND(metric_is_training OR metric_is_pending),
                FALSE
            ) AS metric_is_training,
            COALESCE(BOOL_AND(freshness_is_pending), TRUE) AS freshness_is_pending,
            COALESCE(BOOL_AND(volume_is_pending), TRUE) AS volume_is_pending,
            COALESCE(BOOL_AND(schema_is_pending), TRUE) AS schema_is_pending,
            COALESCE(BOOL_AND(metric_is_pending), TRUE) AS metric_is_pending
        FROM ({inner_query}) AS subquery
        """
        # Outer query has no GROUP BY — aggregates over zero rows still yield one
        # COALESCE'd row, so .first() never returns None here. ``lookback`` is 0
        # when the per-table CTE has no rows OR no runs against the monitor suite,
        # so the dashboard / MCP can render the "no monitor runs yet" state.
        row = get_current_session().execute(text(query), params).mappings().first()
        return MonitorGroupSummary(**row)

    @classmethod
    def get_table_monitor_series(
        cls,
        test_suite_id: str | UUID,
        table_name: str,
        lookback_multiplier: int = 1,
    ) -> dict:
        """Per-table monitor series for all four monitor types.

        Returns a dict with keys ``freshness_events``, ``volume_events``,
        ``schema_events``, and ``metric_events`` shaped identically to the monitors
        dashboard's ``get_monitor_events_for_table``. A single batched query covers all
        four types; no N-query regression.
        """
        query, params = build_series_sql(
            test_suite_id=test_suite_id,
            table_name=table_name,
            lookback_multiplier=lookback_multiplier,
        )
        rows = [dict(row) for row in get_current_session().execute(text(query), params).mappings().all()]

        metric_events: dict[str, dict] = {}
        for event in rows:
            if event["test_type"] == "Metric_Trend" and event["result_status"] != "Error" and (definition_id := event["test_definition_id"]):
                if definition_id not in metric_events:
                    metric_events[definition_id] = {
                        "test_definition_id": definition_id,
                        "column_name": event["column_names"],
                        "events": [],
                    }
                point = parse_value_event(event)
                metric_events[definition_id]["events"].append({
                    "value": point["value"],
                    "time": point["time"],
                    "is_anomaly": point["is_anomaly"],
                    "is_training": point["is_training"],
                    "is_pending": point["is_pending"],
                    # Frontend chart (table_monitoring_trends.js) reads lower_tolerance/upper_tolerance.
                    "lower_tolerance": point["lower_bound"],
                    "upper_tolerance": point["upper_bound"],
                    "threshold_value": point["threshold_value"],
                })

        freshness_events = []
        for event in rows:
            if event["test_type"] != "Freshness_Trend" or event["result_status"] == "Error":
                continue
            changed, detail = parse_freshness_message(event["result_message"])
            freshness_events.append({
                "changed": bool(changed),
                "message": detail,
                "status": event["result_status"],
                "is_training": event["result_code"] == -1,
                "is_pending": not bool(event["result_id"]),
                "time": event["test_time"],
            })

        return {
            "freshness_events": freshness_events,
            "volume_events": [
                {
                    "record_count": int(event["result_signal"] or 0),
                    "time": event["test_time"],
                    "is_anomaly": int(event["result_code"]) == 0 if event["result_code"] is not None else None,
                    "is_training": int(event["result_code"]) == -1 if event["result_code"] is not None else None,
                    "is_pending": not bool(event["result_id"]),
                    **params_kv,
                }
                for event in rows if event["test_type"] == "Volume_Trend" and event["result_status"] != "Error" and (
                    params_kv := dict_from_kv(event.get("input_parameters"))
                        or {"lower_tolerance": None, "upper_tolerance": None}
                )
            ],
            "schema_events": [
                parse_schema_event(event)
                for event in rows if event["test_type"] == "Schema_Drift" and event["result_status"] != "Error"
            ],
            "metric_events": list(metric_events.values()),
        }

    @classmethod
    def _monitor_changes_by_tables_query(
        cls,
        table_group_id: str | UUID,
        *,
        anomaly_types: list[str] | None = None,
        sort_by: str | None = None,
        lookback_override: int | None = None,
        table_name_filter: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[str, dict]:
        """Build the CTE that produces one ``MonitorTableSummary``-shaped row per table.

        Shared by ``list_monitor_table_summaries`` and ``get_monitor_group_summary``
        and by the monitors dashboard. ``anomaly_types`` filters the outer SELECT (so
        the group summary can omit it and get all tables). ``sort_by`` is the
        dataclass field name with optional ``_desc`` suffix — the caller (MCP /
        dashboard) is responsible for validating it against a known set.
        """
        lookback_expr = (
            ":lookback_override" if lookback_override is not None
            else "COALESCE(test_suites.monitor_lookback, 1)"
        )

        anomaly_filter_clause = ""
        if anomaly_types:
            columns = [_ANOMALY_TYPE_TO_COLUMN[t] for t in anomaly_types]
            anomaly_filter_clause = (
                "WHERE ("
                + " OR ".join(f"monitor_tables.{col} > 0" for col in columns)
                + ")"
            )

        sort_anomaly_type = anomaly_types[0] if anomaly_types and len(anomaly_types) == 1 else None
        order_clause = _build_monitor_order_clause(sort_by, sort_anomaly_type)

        query = f"""
        WITH ranked_test_runs AS (
            SELECT
                test_runs.id,
                test_runs.test_starttime,
                {lookback_expr} AS lookback,
                ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
            FROM table_groups
            INNER JOIN test_runs
                ON (test_runs.test_suite_id = table_groups.monitor_test_suite_id)
            INNER JOIN test_suites
                ON (table_groups.monitor_test_suite_id = test_suites.id)
            WHERE table_groups.id = :table_group_id
        ),
        lookback_window AS (
            SELECT MIN(test_starttime) AS lookback_start
            FROM ranked_test_runs
            WHERE position <= lookback
        ),
        latest_tables AS (
            SELECT DISTINCT
                table_chars.schema_name,
                table_chars.table_name
            FROM data_table_chars table_chars
            CROSS JOIN lookback_window
            WHERE table_chars.table_groups_id = :table_group_id
                -- Include current tables and tables dropped within lookback window
                AND (table_chars.drop_date IS NULL OR table_chars.drop_date >= lookback_window.lookback_start)
                {"AND table_chars.table_name ILIKE :table_name_filter" if table_name_filter else ''}
        ),
        monitor_defs AS (
            SELECT td.id AS monitor_id, td.table_name, td.test_type, td.column_name
            FROM test_definitions td
            INNER JOIN table_groups tg ON tg.monitor_test_suite_id = td.test_suite_id
            WHERE tg.id = :table_group_id
        ),
        metric_defs AS (
            SELECT
                monitor_defs.table_name,
                JSON_AGG(JSON_BUILD_OBJECT(
                    'monitor_id', monitor_defs.monitor_id,
                    'column_name', monitor_defs.column_name,
                    'anomalies', COALESCE(metric_counts.anomalies, 0),
                    'is_training', COALESCE(metric_counts.is_training, FALSE),
                    'is_pending', metric_counts.result_ct IS NULL OR metric_counts.result_ct = 0
                ) ORDER BY monitor_defs.column_name) AS metric_monitors
            FROM monitor_defs
            LEFT JOIN (
                SELECT results.test_definition_id,
                       SUM(CASE WHEN results.result_code = 0 THEN 1 ELSE 0 END)::INT AS anomalies,
                       BOOL_OR(results.result_code = -1) FILTER (WHERE ranked_test_runs.position = 1) AS is_training,
                       COUNT(results.id) AS result_ct
                FROM test_results results
                INNER JOIN ranked_test_runs ON ranked_test_runs.id = results.test_run_id
                WHERE ranked_test_runs.position <= ranked_test_runs.lookback
                  AND results.test_type = 'Metric_Trend'
                GROUP BY results.test_definition_id
            ) AS metric_counts ON metric_counts.test_definition_id = monitor_defs.monitor_id
            WHERE monitor_defs.test_type = 'Metric_Trend'
            GROUP BY monitor_defs.table_name
        ),
        monitor_results AS (
            SELECT
                latest_tables.table_name,
                results.test_time,
                results.test_type,
                results.result_code,
                ranked_test_runs.lookback,
                ranked_test_runs.position,
                ranked_test_runs.test_starttime,
                -- result_code = -1 indicates training mode
                CASE WHEN results.result_code = -1 THEN 1 ELSE 0 END AS is_training,
                CASE WHEN results.test_type = 'Freshness_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END AS freshness_anomaly,
                CASE WHEN results.test_type = 'Volume_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END AS volume_anomaly,
                CASE WHEN results.test_type = 'Schema_Drift' AND results.result_code = 0 THEN 1 ELSE 0 END AS schema_anomaly,
                CASE WHEN results.test_type = 'Metric_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END AS metric_anomaly,
                CASE WHEN results.test_type = 'Freshness_Trend' THEN results.result_signal ELSE NULL END AS freshness_interval,
                CASE WHEN results.test_type = 'Volume_Trend' THEN results.result_signal::BIGINT ELSE NULL END AS row_count,
                CASE WHEN results.test_type = 'Schema_Drift' THEN SPLIT_PART(results.result_signal, '|', 1) ELSE NULL END AS table_change,
                CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 2), '')::INT ELSE 0 END AS col_adds,
                CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 3), '')::INT ELSE 0 END AS col_drops,
                CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 4), '')::INT ELSE 0 END AS col_mods,
                CASE WHEN results.result_status = 'Error' THEN results.result_message ELSE NULL END AS error_message,
                CASE WHEN results.test_type = 'Freshness_Trend' THEN results.result_message ELSE NULL END AS freshness_message
            FROM latest_tables
            LEFT JOIN ranked_test_runs ON TRUE
            LEFT JOIN test_results AS results
                ON results.test_run_id = ranked_test_runs.id
                AND results.table_name = latest_tables.table_name
            WHERE ranked_test_runs.position IS NULL
                -- Also capture 1 run before the lookback to get baseline results
                OR ranked_test_runs.position <= ranked_test_runs.lookback + 1
        ),
        monitor_tables AS (
            SELECT
                table_name,
                MAX(lookback)::INTEGER AS lookback,
                COALESCE(SUM(freshness_anomaly), 0)::INTEGER AS freshness_anomalies,
                COALESCE(SUM(volume_anomaly), 0)::INTEGER AS volume_anomalies,
                COALESCE(SUM(schema_anomaly), 0)::INTEGER AS schema_anomalies,
                COALESCE(SUM(metric_anomaly), 0)::INTEGER AS metric_anomalies,
                MAX(test_time - (COALESCE(NULLIF(freshness_interval, 'Unknown')::INTEGER, 0) * INTERVAL '1 minute'))
                    FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS latest_update,
                MAX(row_count) FILTER (WHERE position = 1) AS row_count,
                COALESCE(SUM(col_adds), 0)::INTEGER AS column_adds,
                COALESCE(SUM(col_drops), 0)::INTEGER AS column_drops,
                COALESCE(SUM(col_mods), 0)::INTEGER AS column_mods,
                COALESCE(SUM(schema_anomaly) FILTER (WHERE position = 1), 0)::INTEGER AS latest_run_schema_anomalies,
                COALESCE(SUM(col_adds) FILTER (WHERE position = 1), 0)::INTEGER AS latest_run_column_adds,
                COALESCE(SUM(col_drops) FILTER (WHERE position = 1), 0)::INTEGER AS latest_run_column_drops,
                COALESCE(SUM(col_mods) FILTER (WHERE position = 1), 0)::INTEGER AS latest_run_column_mods,
                MAX(freshness_message) FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS latest_run_freshness_message,
                MAX(error_message) FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS freshness_error_message,
                MAX(error_message) FILTER (WHERE test_type = 'Volume_Trend' AND position = 1) AS volume_error_message,
                MAX(error_message) FILTER (WHERE test_type = 'Schema_Drift' AND position = 1) AS schema_error_message,
                MAX(error_message) FILTER (WHERE test_type = 'Metric_Trend' AND position = 1) AS metric_error_message,
                BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS freshness_is_training,
                BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Volume_Trend' AND position = 1) AS volume_is_training,
                BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Metric_Trend' AND position = 1) AS metric_is_training,
                BOOL_OR(test_type = 'Freshness_Trend') IS NOT TRUE AS freshness_is_pending,
                BOOL_OR(test_type = 'Volume_Trend') IS NOT TRUE AS volume_is_pending,
                -- Schema monitor only creates results on schema changes (Failed)
                -- Mark it as pending only if there are no results of any test type
                BOOL_OR(test_time IS NOT NULL) IS NOT TRUE AS schema_is_pending,
                BOOL_OR(test_type = 'Metric_Trend') IS NOT TRUE AS metric_is_pending,
                CASE
                    -- Mark as Dropped if latest Schema Drift result for the table indicates it was dropped
                    WHEN (ARRAY_AGG(table_change ORDER BY test_time DESC) FILTER (WHERE table_change IS NOT NULL))[1] = 'D'
                        THEN 'dropped'
                    -- Only mark as Added if latest change does not indicate a drop
                    WHEN MAX(CASE WHEN table_change = 'A' THEN 1 ELSE 0 END) = 1
                        THEN 'added'
                    WHEN SUM(schema_anomaly) > 0
                        THEN 'modified'
                    ELSE NULL
                END AS table_state,
                CASE
                    WHEN MAX(CASE WHEN table_change = 'D' AND position = 1 THEN 1 ELSE 0 END) = 1
                        THEN 'dropped'
                    WHEN MAX(CASE WHEN table_change = 'A' AND position = 1 THEN 1 ELSE 0 END) = 1
                        THEN 'added'
                    WHEN SUM(CASE WHEN position = 1 THEN schema_anomaly ELSE 0 END) > 0
                        THEN 'modified'
                    ELSE NULL
                END AS latest_run_table_state
            FROM monitor_results
            -- Only aggregate within lookback runs
            WHERE position IS NULL OR position <= COALESCE(lookback, 1)
            GROUP BY table_name
        ),
        table_bounds AS (
            SELECT
                table_name,
                MIN(position) AS min_position,
                MAX(position) AS max_position
            FROM monitor_results
            WHERE position IS NOT NULL
            GROUP BY table_name
        ),
        baseline_tables AS (
            SELECT
                monitor_results.table_name,
                MIN(monitor_results.test_starttime) FILTER (
                    WHERE monitor_results.position = LEAST(monitor_results.lookback + 1, table_bounds.max_position)
                ) AS lookback_start,
                MAX(monitor_results.test_starttime) FILTER (
                    WHERE monitor_results.position = GREATEST(1, table_bounds.min_position)
                ) AS lookback_end,
                MAX(monitor_results.row_count) FILTER (
                    WHERE monitor_results.test_type = 'Volume_Trend'
                    AND monitor_results.position = LEAST(monitor_results.lookback + 1, table_bounds.max_position)
                ) AS previous_row_count,
                MAX(monitor_results.test_starttime) FILTER (
                    WHERE monitor_results.position = 2
                ) AS previous_run_start,
                MAX(monitor_results.row_count) FILTER (
                    WHERE monitor_results.test_type = 'Volume_Trend'
                    AND monitor_results.position = 2
                ) AS previous_run_row_count
            FROM monitor_results
            JOIN table_bounds ON monitor_results.table_name = table_bounds.table_name
            GROUP BY monitor_results.table_name
        )
        SELECT
            monitor_tables.table_name,
            monitor_tables.lookback,
            baseline_tables.lookback_start,
            baseline_tables.lookback_end,
            monitor_tables.freshness_anomalies,
            monitor_tables.volume_anomalies,
            monitor_tables.schema_anomalies,
            monitor_tables.metric_anomalies,
            monitor_tables.freshness_is_training,
            monitor_tables.volume_is_training,
            monitor_tables.metric_is_training,
            monitor_tables.freshness_is_pending,
            monitor_tables.volume_is_pending,
            monitor_tables.schema_is_pending,
            monitor_tables.metric_is_pending,
            monitor_tables.freshness_error_message,
            monitor_tables.volume_error_message,
            monitor_tables.schema_error_message,
            monitor_tables.metric_error_message,
            monitor_tables.latest_update,
            monitor_tables.row_count,
            baseline_tables.previous_row_count,
            monitor_tables.column_adds,
            monitor_tables.column_drops,
            monitor_tables.column_mods,
            monitor_tables.table_state,
            baseline_tables.previous_run_start,
            baseline_tables.previous_run_row_count,
            monitor_tables.latest_run_schema_anomalies,
            monitor_tables.latest_run_column_adds,
            monitor_tables.latest_run_column_drops,
            monitor_tables.latest_run_column_mods,
            monitor_tables.latest_run_table_state,
            monitor_tables.latest_run_freshness_message,
            (SELECT monitor_id FROM monitor_defs md
             WHERE md.table_name = monitor_tables.table_name AND md.test_type = 'Freshness_Trend' LIMIT 1) AS freshness_monitor_id,
            (SELECT monitor_id FROM monitor_defs md
             WHERE md.table_name = monitor_tables.table_name AND md.test_type = 'Volume_Trend' LIMIT 1) AS volume_monitor_id,
            (SELECT monitor_id FROM monitor_defs md
             WHERE md.table_name = monitor_tables.table_name AND md.test_type = 'Schema_Drift' LIMIT 1) AS schema_monitor_id,
            COALESCE(metric_defs.metric_monitors, '[]'::json) AS metric_monitors
        FROM monitor_tables
        LEFT JOIN baseline_tables ON monitor_tables.table_name = baseline_tables.table_name
        LEFT JOIN metric_defs ON metric_defs.table_name = monitor_tables.table_name
        {anomaly_filter_clause}
        {order_clause}
        {"LIMIT :limit" if limit is not None else ""}
        {"OFFSET :offset" if offset is not None else ""}
        """

        escaped_name_filter = (
            table_name_filter.replace("_", "\\_") if table_name_filter else None
        )
        params: dict = {"table_group_id": str(table_group_id)}
        if escaped_name_filter is not None:
            params["table_name_filter"] = f"%{escaped_name_filter}%"
        if lookback_override is not None:
            params["lookback_override"] = lookback_override
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return query, params

    @classmethod
    def is_in_use(cls, ids: list[str]) -> bool:
        test_suites = TestSuite.select_minimal_where(TestSuite.table_groups_id.in_(ids))
        if test_suites:
            return True

        query = "SELECT id FROM profiling_runs WHERE table_groups_id IN :table_group_ids;"
        params = {"table_group_ids": tuple(ids)}
        dependency_count = get_current_session().execute(text(query), params).rowcount
        return dependency_count > 0

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        test_suites = TestSuite.select_minimal_where(TestSuite.table_groups_id.in_(ids))
        if test_suites:
            TestSuite.cascade_delete([item.id for item in test_suites])

        query = """
        DELETE FROM profile_anomaly_results par
        USING table_groups tg
        WHERE tg.id = par.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM profile_results pr
        USING table_groups tg
        WHERE tg.id = pr.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM job_executions
        WHERE id IN (
            SELECT pr.id FROM profiling_runs pr
            WHERE pr.table_groups_id IN :table_group_ids
        );

        DELETE FROM profiling_runs pr
        USING table_groups tg
        WHERE tg.id = pr.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM data_table_chars dtc
        USING table_groups tg
        WHERE tg.id = dtc.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM data_column_chars dcs
        USING table_groups tg
        WHERE tg.id = dcs.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM job_schedules
        WHERE (kwargs->>'table_group_id')::UUID IN :table_group_ids;
        """
        params = {"table_group_ids": tuple(ids)}
        db_session = get_current_session()
        db_session.execute(text(query), params)
        cls.delete_where(cls.id.in_(ids))

    def save(self, add_scorecard_definition: bool = False) -> None:
        if self.id:
            values = {
                column.key: getattr(self, column.key, None)
                for column in self.__table__.columns
                if column not in self._update_exclude_columns
            }
            query = update(TableGroup).where(TableGroup.id == self.id).values(**values)
            db_session = get_current_session()
            db_session.execute(query)
        else:
            super().save()
            if add_scorecard_definition:
                ScoreDefinition.from_table_group(self).save()
