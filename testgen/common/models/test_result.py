import enum
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, desc, func, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased
from sqlalchemy.sql.expression import case

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
    """One test definition's status across two runs for ``get_test_run_diff``."""

    test_definition_id: UUID
    test_type: str
    test_name_short: str | None
    table_name: str | None
    column_names: str | None
    status_a: TestResultStatus | None
    status_b: TestResultStatus | None
    measure_a: str | None
    measure_b: str | None
    threshold_a: str | None
    threshold_b: str | None


@dataclass
class RunDiff:
    """Categorized diff between two test runs."""

    total_a: int
    total_b: int
    regressions: list[DiffRow] = field(default_factory=list)
    improvements: list[DiffRow] = field(default_factory=list)
    persistent_failures: list[DiffRow] = field(default_factory=list)
    new_tests: list[DiffRow] = field(default_factory=list)
    removed_tests: list[DiffRow] = field(default_factory=list)


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
                TestRun.job_execution_id.label("job_execution_id"),
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
    def diff_with_details(cls, test_run_id_a: UUID, test_run_id_b: UUID) -> RunDiff:
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

        def _row(tid: UUID, info_a: dict | None, info_b: dict | None) -> DiffRow:
            base = info_b or info_a  # prefer B for display fields (test_type, table, column names)
            return DiffRow(
                test_definition_id=tid,
                test_type=base["test_type"],
                test_name_short=base["test_name_short"],
                table_name=base["table_name"],
                column_names=base["column_names"],
                status_a=info_a["status"] if info_a else None,
                status_b=info_b["status"] if info_b else None,
                measure_a=info_a["measure"] if info_a else None,
                measure_b=info_b["measure"] if info_b else None,
                threshold_a=info_a["threshold"] if info_a else None,
                threshold_b=info_b["threshold"] if info_b else None,
            )

        results_a = _fetch(test_run_id_a)
        results_b = _fetch(test_run_id_b)
        failing = {TestResultStatus.Failed, TestResultStatus.Warning}
        diff = RunDiff(total_a=len(results_a), total_b=len(results_b))

        for tid in results_a.keys() & results_b.keys():
            info_a, info_b = results_a[tid], results_b[tid]
            row = _row(tid, info_a, info_b)
            if info_a["status"] == TestResultStatus.Passed and info_b["status"] in failing:
                diff.regressions.append(row)
            elif info_a["status"] in failing and info_b["status"] == TestResultStatus.Passed:
                diff.improvements.append(row)
            elif info_a["status"] in failing and info_b["status"] in failing:
                diff.persistent_failures.append(row)

        for tid in results_b.keys() - results_a.keys():
            diff.new_tests.append(_row(tid, None, results_b[tid]))

        for tid in results_a.keys() - results_b.keys():
            diff.removed_tests.append(_row(tid, results_a[tid], None))

        return diff
