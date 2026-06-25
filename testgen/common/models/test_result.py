import enum
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, desc, func, or_, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased
from sqlalchemy.sql.expression import case

from testgen.common.enums import MonitorType
from testgen.common.models import get_current_session
from testgen.common.models.entity import Entity
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_suite import TestSuite


class TestResultStatus(enum.Enum):
    Error = "Error"
    Log = "Log"
    Passed = "Passed"
    Warning = "Warning"
    Failed = "Failed"


class BucketInterval(enum.StrEnum):
    DAY = "day"
    WEEK = "week"


@dataclass
class ResultStatusCounts:
    """Counts of test results by outcome status, with dismissed/inactive separated."""

    passed: int = 0
    failed: int = 0
    warning: int = 0
    error: int = 0
    log: int = 0
    dismissed: int = 0


TestResultDiffType = tuple[TestResultStatus, TestResultStatus, list[UUID]]


@dataclass
class TestResultSearchRow:
    """Cross-run test result row for MCP ``search_test_results``."""

    test_definition_id: UUID
    test_run_id: UUID
    job_execution_id: UUID | None
    test_time: datetime
    test_suite_id: UUID
    test_suite_name: str
    test_type: str
    test_name_short: str | None
    table_name: str | None
    column_names: str | None
    status: TestResultStatus | None
    result_measure: str | None
    threshold_value: str | None
    result_message: str | None


@dataclass
class TestRunResultRow:
    """One individual result within a single test run for the API results endpoint."""

    test_definition_id: UUID
    test_type: str
    schema_name: str
    table_name: str | None
    column_names: str | None
    status: TestResultStatus | None
    result_measure: str | None
    threshold_value: str | None
    message: str | None
    test_time: datetime | None
    disposition: str | None


@dataclass
class TrendBucket:
    """One time-bucket of failure aggregates for ``get_failure_trend``."""

    bucket: date
    failed_ct: int
    warning_ct: int
    total_ct: int

    @property
    def failure_rate(self) -> float:
        return (self.failed_ct + self.warning_ct) / self.total_ct if self.total_ct else 0.0


@dataclass
class DiffRow:
    """One test definition's status across two runs for ``compare_test_runs``."""

    test_definition_id: UUID
    test_type: str
    test_name_short: str | None
    table_name: str | None
    column_names: str | None
    status_baseline: TestResultStatus | None
    status_target: TestResultStatus | None
    measure_baseline: str | None
    measure_target: str | None
    threshold_baseline: str | None
    threshold_target: str | None


@dataclass
class RunDiff:
    """Categorized diff between two test runs."""

    total_baseline: int
    total_target: int
    stable_passes: int = 0
    regressions: list[DiffRow] = field(default_factory=list)
    improvements: list[DiffRow] = field(default_factory=list)
    persistent_failures: list[DiffRow] = field(default_factory=list)
    new_tests: list[DiffRow] = field(default_factory=list)
    removed_tests: list[DiffRow] = field(default_factory=list)


@dataclass
class MonitorEvent:
    """One monitor result for a (table, monitor_type) pair within the lookback window.

    Type-specific fields are populated by ``test_type``:

    * ``Freshness_Trend``: ``signal`` carries minutes-since-last-update (string
      like ``"120"`` / ``"Unknown"``); ``message`` carries the human-readable
      detection text.
    * ``Volume_Trend``: ``signal`` carries the row count (string of integer);
      ``lower_bound`` / ``upper_bound`` carry the tolerance bounds the run was
      evaluated against (sourced from ``input_parameters`` at run time).
    * ``Schema_Drift``: ``schema_change_kind`` is the table-level code
      (``A`` / ``D`` / ``M``); ``column_adds`` / ``column_drops`` /
      ``column_mods`` carry per-event column-change counts.
    * ``Metric_Trend``: same as Volume_Trend plus ``metric_name`` (the
      user-defined name for the metric — the underlying SQL expression lives
      on ``MonitorConfig``, not on the event).

    Pending rows have no underlying ``test_results`` row — ``monitor_id``,
    ``test_time``, and result flags are ``None``; ``is_pending`` is True.
    Forecast points (future timestamps with predicted bounds) are NOT
    events and surface separately via ``TestDefinition.get_forecast_points``.
    """
    monitor_id: UUID | None
    test_type: str
    test_time: datetime | None
    is_anomaly: bool | None
    is_training: bool | None
    is_pending: bool
    is_error: bool
    message: str | None
    signal: str | None
    lower_bound: str | None = None
    upper_bound: str | None = None
    schema_change_kind: str | None = None
    column_adds: int | None = None
    column_drops: int | None = None
    column_mods: int | None = None
    metric_name: str | None = None


def _parse_kv_pairs(raw: str | None) -> dict[str, str]:
    """Parse an ``input_parameters`` blob (``key=value; key=value; ...``) into a dict.

    ``input_parameters`` is built with ``"; ".join(...)`` in ``execute_tests_query``
    and read by the dashboard via ``dict_from_kv`` (default separator ``;``).
    Tolerant of missing values, trailing/leading whitespace, empty strings.
    Returns ``{}`` on empty input.
    """
    if not raw:
        return {}
    pairs: dict[str, str] = {}
    for entry in raw.split(";"):
        if "=" not in entry:
            continue
        key, _, value = entry.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def _build_monitor_event(row) -> MonitorEvent:
    """Translate one CTE row into a ``MonitorEvent``, populating type-specific extras."""
    is_pending = row["result_id"] is None
    result_code = row["result_code"]
    is_anomaly = (result_code == 0) if result_code is not None else None
    is_training = (result_code == -1) if result_code is not None else None
    is_error = (row["result_status"] == "Error")

    event = MonitorEvent(
        monitor_id=row["test_definition_id"],
        test_type=row["test_type"],
        test_time=row["test_time"] if not is_pending else None,
        is_anomaly=is_anomaly,
        is_training=is_training,
        is_pending=is_pending,
        is_error=is_error,
        message=row["result_message"],
        signal=row["result_signal"],
    )

    params = _parse_kv_pairs(row["input_parameters"])
    if event.test_type in (MonitorType.VOLUME.value, MonitorType.METRIC.value):
        event.lower_bound = params.get("lower_tolerance") or None
        event.upper_bound = params.get("upper_tolerance") or None
        if event.test_type == MonitorType.METRIC.value:
            event.metric_name = row["column_names"] or None
    elif event.test_type == MonitorType.SCHEMA.value:
        signal = row["result_signal"]
        if signal:
            parts = signal.split("|")
            event.schema_change_kind = parts[0] or None
            event.column_adds = _int_or_none(parts, 1)
            event.column_drops = _int_or_none(parts, 2)
            event.column_mods = _int_or_none(parts, 3)

    return event


def _int_or_none(parts: list[str], index: int) -> int | None:
    try:
        value = parts[index]
    except IndexError:
        return None
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


class TestResult(Entity):
    __tablename__ = "test_results"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4)

    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id"), nullable=False)
    test_run_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=False)

    test_definition_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_definitions.id"), nullable=False)
    test_type: str = Column(String, ForeignKey("test_types.test_type"), nullable=False)
    auto_gen: bool = Column(Boolean)

    schema_name: str = Column(String, nullable=False)
    table_name: str = Column(String)
    column_names: str = Column(String)

    status: TestResultStatus = Column("result_status", Enum(TestResultStatus))
    message: str = Column("result_message", String)

    test_time: datetime = Column(postgresql.TIMESTAMP)
    result_code: int = Column(Integer)
    disposition: str = Column(String)
    result_measure: str = Column(String)
    threshold_value: str = Column(String)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))

    # Unmapped columns: result_id, skip_errors, input_parameters, severity,
    # result_signal, test_description, dq_prevalence,
    # dq_record_ct, observability_status

    @classmethod
    def select_results(
        cls,
        test_run_id: UUID,
        status: TestResultStatus | None = None,
        table_name: str | None = None,
        test_type: str | None = None,
        project_codes: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Self]:
        """Paginated results for a single run, with optional status/table/type filters.

        Monitor suites and dismissed/inactive results are always filtered out.
        Project-level access is enforced when ``project_codes`` is set.
        """
        clauses = [
            cls.test_run_id == test_run_id,
            func.coalesce(cls.disposition, "Confirmed") == "Confirmed",
        ]
        if status:
            clauses.append(cls.status == status)
        if table_name:
            clauses.append(cls.table_name == table_name)
        if test_type:
            clauses.append(cls.test_type == test_type)
        query = (
            select(cls)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(*clauses, TestSuite.is_monitor.isnot(True))
        )
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        query = query.order_by(cls.status, cls.table_name, cls.column_names).offset(offset).limit(limit)
        return get_current_session().scalars(query).all()

    @classmethod
    def list_for_run(
        cls,
        test_run_id: UUID,
        *clauses,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[TestRunResultRow], int]:
        """Paginated individual results for a single run, scoped by caller-supplied WHERE clauses.

        Monitor suites are always filtered out.
        """
        query = (
            select(
                cls.test_definition_id.label("test_definition_id"),
                cls.test_type.label("test_type"),
                cls.schema_name.label("schema_name"),
                cls.table_name.label("table_name"),
                cls.column_names.label("column_names"),
                cls.status.label("status"),
                cls.result_measure.label("result_measure"),
                cls.threshold_value.label("threshold_value"),
                cls.message.label("message"),
                cls.test_time.label("test_time"),
                cls.disposition.label("disposition"),
            )
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(cls.test_run_id == test_run_id, TestSuite.is_monitor.isnot(True), *clauses)
            .order_by(cls.status, cls.table_name, cls.column_names, cls.id)
        )
        return cls._paginate(query, page=page, limit=limit, data_class=TestRunResultRow)

    @classmethod
    def select_failures(
        cls,
        *,
        project_codes: list[str] | None = None,
        test_suite_id: UUID | None = None,
        test_run_id: UUID | None = None,
        since: date | None = None,
        group_by: str = "test_type",
    ) -> list[tuple]:
        """Failed/Warning counts scoped by run, suite, or date, grouped by test_type, table, or column.

        Monitor suites and dismissed/inactive results are always filtered out.
        Project-level access is enforced when ``project_codes`` is set.
        """
        allowed = {"test_type", "table_name", "column_names"}
        if group_by not in allowed:
            raise ValueError(f"group_by must be one of {allowed}")
        if test_run_id is None and test_suite_id is None and since is None:
            raise ValueError("Provide test_run_id, test_suite_id, or since to scope the query.")

        where = [
            cls.status.in_([TestResultStatus.Failed, TestResultStatus.Warning]),
            func.coalesce(cls.disposition, "Confirmed") == "Confirmed",
        ]
        if test_run_id is not None:
            where.append(cls.test_run_id == test_run_id)
        if test_suite_id is not None:
            where.append(cls.test_suite_id == test_suite_id)
        if since is not None:
            where.append(cls.test_time >= since)

        # Column grouping includes table_name for context → (table, column, count)
        if group_by == "column_names":
            group_cols = (cls.table_name, cls.column_names)
        elif group_by == "test_type":
            group_cols = (cls.test_type, cls.status)
        else:
            group_cols = (getattr(cls, group_by),)

        query = (
            select(*group_cols, func.count().label("failure_count"))
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(*where, TestSuite.is_monitor.isnot(True))
        )
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        query = query.group_by(*group_cols).order_by(func.count().desc())
        return get_current_session().execute(query).all()

    @classmethod
    def count_by_status(cls, test_run_id: UUID) -> ResultStatusCounts:
        """Count test results by outcome status for a single run."""
        dismissed = func.coalesce(cls.disposition, "Confirmed").in_(("Dismissed", "Inactive"))

        def _count_active(status: TestResultStatus):
            return func.sum(case((~dismissed & (cls.status == status), 1), else_=0))

        query = select(
            _count_active(TestResultStatus.Passed).label("passed"),
            _count_active(TestResultStatus.Failed).label("failed"),
            _count_active(TestResultStatus.Warning).label("warning"),
            _count_active(TestResultStatus.Error).label("error"),
            _count_active(TestResultStatus.Log).label("log"),
            func.sum(case((dismissed, 1), else_=0)).label("dismissed"),
        ).where(cls.test_run_id == test_run_id)

        row = get_current_session().execute(query).first()
        return ResultStatusCounts(**{k: v for k, v in row._mapping.items() if v is not None})

    @classmethod
    def select_history(
        cls,
        test_definition_id: UUID,
        project_codes: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Self]:
        """Historical results for a test definition, newest first.

        Monitor suites are always filtered out.
        Project-level access is enforced when ``project_codes`` is set.
        """
        query = (
            select(cls)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(cls.test_definition_id == test_definition_id, TestSuite.is_monitor.isnot(True))
        )
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        query = query.order_by(desc(cls.test_time)).offset(offset).limit(limit)
        return get_current_session().scalars(query).all()

    @classmethod
    def diff(cls, test_run_id_a: UUID, test_run_id_b: UUID) -> list[TestResultDiffType]:
        alias_a = aliased(cls)
        alias_b = aliased(cls)
        query = select(
            alias_a.status, alias_b.status, alias_b.test_definition_id,
        ).join(
            alias_b,
            alias_a.test_definition_id == alias_b.test_definition_id,
            full=True,
        ).where(
            or_(alias_a.test_run_id == test_run_id_a, alias_a.test_run_id.is_(None)),
            or_(alias_b.test_run_id == test_run_id_b, alias_b.test_run_id.is_(None)),
            alias_a.status != alias_b.status,
        )

        diff = defaultdict(list)
        for run_a_status, run_b_status, result_id in get_current_session().execute(query):
            diff[(run_a_status, run_b_status)].append(result_id)

        return [(*statuses, id_list) for statuses, id_list in diff.items()]

    @classmethod
    def search_results(
        cls,
        *clauses,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[TestResultSearchRow], int]:
        """Paginated cross-run search over test results, scoped by caller-supplied WHERE clauses.

        Monitor suites and dismissed/inactive results are always filtered out. All other
        scoping is up to the caller.
        """
        # TestRun has its own top-level import of TestResult, so we import it here to avoid the cycle.
        from testgen.common.models.test_run import TestRun

        query = (
            select(
                cls.test_definition_id.label("test_definition_id"),
                cls.test_run_id.label("test_run_id"),
                TestRun.id.label("job_execution_id"),
                cls.test_time.label("test_time"),
                TestSuite.id.label("test_suite_id"),
                TestSuite.test_suite.label("test_suite_name"),
                cls.test_type.label("test_type"),
                TestType.test_name_short.label("test_name_short"),
                cls.table_name.label("table_name"),
                cls.column_names.label("column_names"),
                cls.status.label("status"),
                cls.result_measure.label("result_measure"),
                cls.threshold_value.label("threshold_value"),
                cls.message.label("result_message"),
            )
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .join(TestRun, cls.test_run_id == TestRun.id)
            .outerjoin(TestType, cls.test_type == TestType.test_type)
            .where(
                TestSuite.is_monitor.isnot(True),
                func.coalesce(cls.disposition, "Confirmed") == "Confirmed",
                *clauses,
            )
        )
        query = query.order_by(desc(cls.test_time), cls.table_name, cls.column_names)
        return cls._paginate(query, page=page, limit=limit, data_class=TestResultSearchRow)

    @classmethod
    def failure_trend(
        cls,
        *clauses,
        start_date: date,
        end_date: date,
        bucket: BucketInterval = BucketInterval.DAY,
    ) -> list[TrendBucket]:
        """Time-series of test result counts per bucket, scoped by caller-supplied WHERE clauses.

        Analyzes test results in the inclusive window ``[start_date, end_date]``.

        Daily buckets are calendar-aligned (``date_trunc('day', ...)``).

        Weekly buckets are rolling 7-day windows ending on ``end_date`` inclusive, earlier
        buckets step back in 7-day increments. The oldest bucket is dropped if it would be
        incomplete — i.e. its 7-day window is not fully inside ``start_date``.

        Monitor suites and dismissed/inactive results are always filtered out.
        """
        # Naive midnight — matches the naive TIMESTAMP column so Postgres compares in the session's TZ
        # without any implicit UTC-based conversion.
        upper_bound = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

        # Always query at daily granularity; aggregate in Python.
        day_expr = func.date_trunc("day", cls.test_time).label("day")
        query = (
            select(
                day_expr,
                cls.status.label("status"),
                func.count().label("n"),
            )
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(
                TestSuite.is_monitor.isnot(True),
                cls.test_time >= start_date,
                cls.test_time < upper_bound,
                func.coalesce(cls.disposition, "Confirmed") == "Confirmed",
                *clauses,
            )
            .group_by(day_expr, cls.status)
            .order_by(day_expr)
        )

        # Normalize the SQL-returned timestamp (date_trunc returns a timestamp in Postgres) to a date.
        daily: dict[date, dict[str, int]] = {}
        for row in get_current_session().execute(query):
            day_date = row.day.date() if isinstance(row.day, datetime) else row.day
            slot = daily.setdefault(day_date, {"failed": 0, "warning": 0, "total": 0})
            slot["total"] += row.n
            if row.status == TestResultStatus.Failed:
                slot["failed"] += row.n
            elif row.status == TestResultStatus.Warning:
                slot["warning"] += row.n

        if bucket == BucketInterval.DAY:
            buckets = daily
        else:
            buckets = {}
            for day_date, counts in daily.items():
                days_ago = (end_date - day_date).days
                weeks_ago = days_ago // 7
                bucket_end = end_date - timedelta(days=weeks_ago * 7)
                bucket_start = bucket_end - timedelta(days=6)
                if bucket_start < start_date:
                    continue  # drop incomplete oldest bucket
                slot = buckets.setdefault(bucket_start, {"failed": 0, "warning": 0, "total": 0})
                for k, v in counts.items():
                    slot[k] += v

        return [
            TrendBucket(
                bucket=bucket_date,
                failed_ct=counts["failed"],
                warning_ct=counts["warning"],
                total_ct=counts["total"],
            )
            for bucket_date, counts in sorted(buckets.items())
        ]

    @classmethod
    def diff_with_details(cls, baseline_run_id: UUID, target_run_id: UUID) -> RunDiff:
        """Compare two runs by ``test_definition_id`` and return categorized diff rows."""

        def _fetch(run_id: UUID) -> dict[UUID, dict]:
            query = (
                select(
                    cls.test_definition_id.label("test_definition_id"),
                    cls.test_type.label("test_type"),
                    TestType.test_name_short.label("test_name_short"),
                    cls.table_name.label("table_name"),
                    cls.column_names.label("column_names"),
                    cls.status.label("status"),
                    cls.result_measure.label("result_measure"),
                    cls.threshold_value.label("threshold_value"),
                )
                .outerjoin(TestType, cls.test_type == TestType.test_type)
                .where(
                    cls.test_run_id == run_id,
                    func.coalesce(cls.disposition, "Confirmed") == "Confirmed",
                )
            )
            return {
                row.test_definition_id: {
                    "test_type": row.test_type,
                    "test_name_short": row.test_name_short,
                    "table_name": row.table_name,
                    "column_names": row.column_names,
                    "status": row.status,
                    "measure": row.result_measure,
                    "threshold": row.threshold_value,
                }
                for row in get_current_session().execute(query)
            }

        def _row(tid: UUID, baseline_info: dict | None, target_info: dict | None) -> DiffRow:
            base = target_info or baseline_info  # prefer target for display fields (test_type, table, column names)
            return DiffRow(
                test_definition_id=tid,
                test_type=base["test_type"],
                test_name_short=base["test_name_short"],
                table_name=base["table_name"],
                column_names=base["column_names"],
                status_baseline=baseline_info["status"] if baseline_info else None,
                status_target=target_info["status"] if target_info else None,
                measure_baseline=baseline_info["measure"] if baseline_info else None,
                measure_target=target_info["measure"] if target_info else None,
                threshold_baseline=baseline_info["threshold"] if baseline_info else None,
                threshold_target=target_info["threshold"] if target_info else None,
            )

        baseline_results = _fetch(baseline_run_id)
        target_results = _fetch(target_run_id)
        failing = {TestResultStatus.Failed, TestResultStatus.Warning}
        diff = RunDiff(total_baseline=len(baseline_results), total_target=len(target_results))

        for tid in baseline_results.keys() & target_results.keys():
            baseline_info, target_info = baseline_results[tid], target_results[tid]
            baseline_status, target_status = baseline_info["status"], target_info["status"]
            if baseline_status == TestResultStatus.Passed and target_status == TestResultStatus.Passed:
                diff.stable_passes += 1
                continue
            row = _row(tid, baseline_info, target_info)
            if baseline_status == TestResultStatus.Passed and target_status in failing:
                diff.regressions.append(row)
            elif baseline_status in failing and target_status == TestResultStatus.Passed:
                diff.improvements.append(row)
            elif baseline_status in failing and target_status in failing:
                diff.persistent_failures.append(row)

        for tid in target_results.keys() - baseline_results.keys():
            diff.new_tests.append(_row(tid, None, target_results[tid]))

        for tid in baseline_results.keys() - target_results.keys():
            diff.removed_tests.append(_row(tid, baseline_results[tid], None))

        return diff

    @classmethod
    def list_monitor_events_for_table(
        cls,
        test_suite_id: str | UUID,
        table_name: str,
        *,
        monitor_type: str | None = None,
        lookback_multiplier: int = 1,
        page: int = 1,
        limit: int | None = None,
    ) -> tuple[list[MonitorEvent], int]:
        """Per-table monitor events within the suite's lookback window, newest first.

        ``monitor_type`` is the internal ``test_type`` value; when ``None`` events
        for all four monitor types are returned (used by the dashboard, which
        groups by type on the JS side). ``lookback_multiplier`` extends the
        active window for the "show more history" toggle. ``limit=None``
        skips pagination entirely (the caller wants every event in the window).

        Forecast points for Prediction-Model monitors are NOT included here —
        events are only past, observed runs. Read forecasts separately via
        ``TestDefinition.get_forecast_points(sensitivity)``.
        """
        monitor_codes = (
            [monitor_type] if monitor_type is not None
            else [m.value for m in MonitorType]
        )
        type_filter_sql = "AND results.test_type = :monitor_type" if monitor_type else ""

        query = f"""
        WITH ranked_test_runs AS (
            SELECT
                test_runs.id,
                test_runs.test_starttime,
                COALESCE(test_suites.monitor_lookback, 1) * :lookback_multiplier AS lookback,
                ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
            FROM test_suites
            INNER JOIN test_runs ON (test_suites.id = test_runs.test_suite_id)
            WHERE test_suites.id = :test_suite_id
        ),
        active_runs AS (
            SELECT id, test_starttime FROM ranked_test_runs WHERE position <= lookback
        ),
        target_types AS (
            SELECT UNNEST(CAST(:monitor_codes AS TEXT[])) AS test_type
        )
        SELECT
            COALESCE(results.test_time, active_runs.test_starttime) AS test_time,
            tt.test_type,
            results.id AS result_id,
            results.test_definition_id,
            results.result_code,
            COALESCE(results.result_status, 'Log') AS result_status,
            results.result_signal,
            results.result_message,
            COALESCE(results.input_parameters, '') AS input_parameters,
            results.column_names
        FROM active_runs
        CROSS JOIN target_types tt
        LEFT JOIN test_results AS results
            ON results.test_run_id = active_runs.id
            AND results.test_type = tt.test_type
            AND results.table_name = :table_name
            {type_filter_sql}
        ORDER BY test_time DESC, tt.test_type, results.id NULLS LAST, active_runs.id
        """

        params: dict = {
            "test_suite_id": str(test_suite_id),
            "table_name": table_name,
            "lookback_multiplier": lookback_multiplier,
            "monitor_codes": monitor_codes,
        }
        if monitor_type is not None:
            params["monitor_type"] = monitor_type

        session = get_current_session()
        rows = session.execute(text(query), params).mappings().all()
        events = [_build_monitor_event(row) for row in rows]

        # Paginate in Python — the CTE is bounded by lookback x |monitor_types|
        # (typically <= ~120 rows for a single table). Revisit if either grows.
        total = len(events)
        if limit is not None:
            start = (page - 1) * limit
            events = events[start:start + limit]
        return events, total

    @classmethod
    def list_metric_monitor_events(
        cls,
        test_suite_id: str | UUID,
        test_definition_id: str | UUID,
        *,
        lookback_multiplier: int = 1,
        page: int = 1,
        limit: int | None = None,
    ) -> tuple[list[MonitorEvent], int]:
        """Per-metric event history within the suite's lookback window, newest
        first. Scoped to one ``test_definition_id`` since Metric_Trend is the
        only multi-instance monitor type — table + type alone would interleave
        events across every metric on the table.

        Distinct from ``list_monitor_events_for_table`` in two ways: (1) no
        cross join with target_types — only one monitor type to query; (2) no
        synthesized pending rows — a pending result for a specific
        ``test_definition_id`` can't be distinguished from "no run yet"
        without a results row to anchor on, so the model returns only rows
        that actually ran. ``limit=None`` skips pagination.
        """
        query = """
        WITH suite_window AS (
            SELECT COALESCE(monitor_lookback, 1) * :lookback_multiplier AS lookback
            FROM test_suites
            WHERE id = :test_suite_id
        )
        SELECT
            results.test_time,
            results.test_type,
            results.id AS result_id,
            results.test_definition_id,
            results.result_code,
            COALESCE(results.result_status, 'Log') AS result_status,
            results.result_signal,
            results.result_message,
            COALESCE(results.input_parameters, '') AS input_parameters,
            results.column_names
        FROM test_results AS results
        WHERE results.test_suite_id = :test_suite_id
          AND results.test_definition_id = :test_definition_id
        ORDER BY results.test_time DESC, results.id
        LIMIT (SELECT lookback FROM suite_window)
        """

        params: dict = {
            "test_suite_id": str(test_suite_id),
            "test_definition_id": str(test_definition_id),
            "lookback_multiplier": lookback_multiplier,
        }

        session = get_current_session()
        rows = session.execute(text(query), params).mappings().all()
        events = [_build_monitor_event(row) for row in rows]

        total = len(events)
        if limit is not None:
            start = (page - 1) * limit
            events = events[start:start + limit]
        return events, total
