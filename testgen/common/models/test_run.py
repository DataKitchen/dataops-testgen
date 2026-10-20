from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Literal, NamedTuple, Self, TypedDict
from uuid import UUID

from sqlalchemy import BigInteger, Column, Float, ForeignKey, Integer, delete, desc, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import foreign, relationship
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import case

from testgen.common.enums import JOB_STATUS_LABEL, JobStatus, SuiteType
from testgen.common.models import database_session, get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.entity import Entity, EntityMinimal
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.project import Project
from testgen.common.models.suite_version import SuiteVersion, VersionState, format_version, version_state
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_result import TestResult, TestResultStatus
from testgen.common.models.test_suite import TestSuite
from testgen.utils import is_uuid4

ProgressKey = Literal["data_chars", "validation", "QUERY", "CAT", "METADATA"]
ProgressStatus = Literal["Pending", "Running", "Completed", "Warning"]

class ProgressStep(TypedDict):
    key: ProgressKey
    status: ProgressStatus
    label: str
    detail: str
    error: str


@dataclass
class TestRunMinimal(EntityMinimal):
    id: UUID
    project_code: str
    table_groups_id: UUID
    test_suite_id: UUID
    test_suite: str
    test_starttime: datetime
    dq_score_test_run: float
    is_latest_run: bool
    match_schema_override: str | None
    external_url: str | None
    caller_metadata: dict | None


@dataclass(frozen=True)
class RunVersion:
    """The contract version a run checked, with its state at read time."""

    number: int
    frozen_at: datetime | None
    active_number: int | None
    test_starttime: datetime | None
    in_force_at_start: int | None = None
    status: JobStatus | None = None

    @property
    def state(self) -> VersionState:
        return version_state(self.frozen_at, self.number == self.active_number)

    @property
    def checked_version_in_force(self) -> bool:
        """Whether the run's version was the highest frozen when the run started."""
        return not self.is_preview and self.number == self.in_force_at_start

    @property
    def counts_as_status(self) -> bool:
        """Whether the run completed a verification of the agreement in force when it started."""
        return self.status == JobStatus.COMPLETED and self.checked_version_in_force

    @property
    def is_preview(self) -> bool:
        """Whether the run checked the version before it was frozen."""
        if self.frozen_at is None:
            return True
        if self.test_starttime is None:
            return False
        return self.test_starttime.replace(tzinfo=UTC) < self.frozen_at


@dataclass
class TestRunSummary(EntityMinimal):
    job_execution_id: UUID
    test_run_id: UUID | None
    job_schedule_id: UUID | None
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    active_seconds: float | None
    error_message: str | None
    progress: list[ProgressStep]
    table_groups_name: str | None
    test_suite: str | None
    project_code: str
    project_name: str
    test_ct: int | None
    passed_ct: int | None
    warning_ct: int | None
    failed_ct: int | None
    error_ct: int | None
    log_ct: int | None
    dismissed_ct: int | None
    dq_score_testing: float | None
    total_count: int
    version_number: int | None = None
    version_frozen_at: datetime | None = None
    active_version_number: int | None = None
    test_starttime: datetime | None = None
    version_in_force_at_start: int | None = None
    version_discarded: bool = False

    STATUS_LABEL: ClassVar[dict[str, str]] = JOB_STATUS_LABEL

    @property
    def run_version(self) -> RunVersion | None:
        """The contract version the run checked; ``None`` for a suite that keeps no versions or a discarded draft."""
        if self.version_number is None:
            return None
        return RunVersion(
            self.version_number,
            self.version_frozen_at,
            self.active_version_number,
            self.test_starttime,
            self.version_in_force_at_start,
            self.status,
        )

    @property
    def version_label(self) -> str | None:
        """The run's version as every surface names it, e.g. ``v3 active``, or None for an unversioned run."""
        if self.version_discarded:
            return "discarded draft"
        if (run_version := self.run_version) is None:
            return None
        return format_version(run_version.number, run_version.state)

    @property
    def is_preview(self) -> bool:
        """Whether the run checked a version before it was frozen, including a draft since discarded."""
        if self.version_discarded:
            return True
        return self.run_version is not None and self.run_version.is_preview

    @property
    def status_label(self) -> str:
        return self.STATUS_LABEL.get(self.status, self.status)


def run_verdict(run: TestRunSummary) -> TestResultStatus:
    """A run's outcome by its worst confirmed result: Failed, else Error, else Warning, else Passed."""
    if run.failed_ct:
        return TestResultStatus.Failed
    if run.error_ct:
        return TestResultStatus.Error
    if run.warning_ct:
        return TestResultStatus.Warning
    return TestResultStatus.Passed


@dataclass
class TestRunMonitorSummary(EntityMinimal):
    test_run_id: UUID
    table_group_id: UUID
    test_endtime: datetime
    table_groups_name: str
    project_name: str
    freshness_anomalies: int
    schema_anomalies: int
    volume_anomalies: int
    table_name: str | None = None


class LatestTestRun(NamedTuple):
    id: str
    run_time: datetime


class TestRun(Entity):
    __tablename__ = "test_runs"

    id: UUID = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("job_executions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id"), nullable=False)
    test_starttime: datetime = Column(postgresql.TIMESTAMP)
    progress: list[ProgressStep] = Column(postgresql.JSONB, default=[])
    test_ct: int = Column(Integer)
    passed_ct: int = Column(Integer)
    failed_ct: int = Column(Integer)
    warning_ct: int = Column(Integer)
    error_ct: int = Column(Integer)
    log_ct: int = Column(Integer)
    table_ct: int = Column(Integer)
    column_ct: int = Column(Integer)
    dq_affected_data_points: int = Column(BigInteger)
    dq_total_data_points: int = Column(BigInteger)
    dq_score_test_run: float = Column(Float)
    version_id: UUID = Column(postgresql.UUID(as_uuid=True))

    job_execution = relationship(
        JobExecution,
        primaryjoin=foreign(id) == JobExecution.id,
        uselist=False,
        viewonly=True,
    )

    _default_order_by = (desc(test_starttime),)
    _minimal_columns = (
        id,
        TestSuite.project_code,
        TestSuite.table_groups_id,
        TestSuite.id.label("test_suite_id"),
        TestSuite.test_suite,
        test_starttime,
        dq_score_test_run,
        case(
            (id == TestSuite.last_complete_test_run_id, True),
            else_=False,
        ).label("is_latest_run"),
        # Only set when the run pointed its referential tests at another schema.
        JobExecution.kwargs["match_schema_name"].astext.label("match_schema_override"),
        JobExecution.external_url,
        JobExecution.caller_metadata,
    )

    @classmethod
    def get_minimal(cls, run_id: str | UUID) -> TestRunMinimal | None:
        if not is_uuid4(run_id):
            return None

        query = (
            select(*cls._minimal_columns)
            .join(TestSuite)
            .join(JobExecution, cls.id == JobExecution.id)
            .where(cls.id == run_id)
        )
        result = get_current_session().execute(query).mappings().first()
        return TestRunMinimal(**result) if result else None

    @classmethod
    def latest_verification(cls, version: SuiteVersion, *clauses) -> "TestRun | None":
        """The latest run of a frozen version that started after it was frozen, narrowed by ``clauses``, if any."""
        if version.frozen_at is None:
            return None
        return get_current_session().scalars(
            select(cls)
            .join(JobExecution, cls.id == JobExecution.id)
            .where(
                cls.test_suite_id == version.test_suite_id,
                cls.version_id == version.id,
                cls.test_starttime >= version.frozen_at,
                *clauses,
            )
            .order_by(desc(cls.test_starttime))
            .limit(1)
        ).first()

    @classmethod
    def get_latest_run(cls, project_code: str) -> LatestTestRun | None:
        query = (
            select(TestRun.id, JobExecution.started_at.label("run_time"))
            .join(JobExecution, TestRun.id == JobExecution.id)
            .join(TestSuite)
            .where(TestSuite.project_code == project_code, JobExecution.status == JobStatus.COMPLETED)
            .order_by(desc(JobExecution.started_at))
            .limit(1)
        )
        result = get_current_session().execute(query).mappings().first()
        if result:
            return LatestTestRun(str(result["id"]), result["run_time"])
        return None

    def get_previous(self, *clauses) -> Self | None:
        """The suite's most recent completed run before this one, narrowed by ``clauses``."""
        query = (
            select(TestRun)
            .join(JobExecution, TestRun.id == JobExecution.id)
            .where(
                TestRun.test_suite_id == self.test_suite_id,
                JobExecution.status == JobStatus.COMPLETED,
                TestRun.test_starttime < self.test_starttime,
                *clauses,
            )
            .order_by(desc(TestRun.test_starttime))
            .limit(1)
        )
        return get_current_session().scalar(query)

    @property
    def ct_by_status(self):
        return {
            TestResultStatus.Error: self.error_ct,
            TestResultStatus.Failed: self.failed_ct,
            TestResultStatus.Warning: self.warning_ct,
            TestResultStatus.Log: self.log_ct,
            TestResultStatus.Passed: self.passed_ct,
        }

    @classmethod
    def select_summary(
        cls,
        project_code: str | None = None,
        table_group_id: str | None = None,
        test_suite_id: str | None = None,
        test_run_ids: list[str | UUID] | None = None,
        job_execution_id: str | UUID | None = None,
        schedule_id: str | None = None,
        statuses: list[JobStatus] | None = None,
        page: int = 1,
        page_size: int = 20,
        *,
        suite_types: Sequence[SuiteType] = (SuiteType.REGULAR,),
        version_id: UUID | str | None = None,
    ) -> tuple[list[TestRunSummary], int]:
        if (
            (table_group_id and not is_uuid4(table_group_id))
            or (test_suite_id and not is_uuid4(test_suite_id))
            or (test_run_ids and not all(is_uuid4(run_id) for run_id in test_run_ids))
            or (job_execution_id and not is_uuid4(job_execution_id))
            or (schedule_id and not is_uuid4(schedule_id))
        ):
            return [], 0

        # A test run shares its job's id. Postgres does not reliably push the outer filters into the grouped CTE.
        results_filter = ""
        if test_run_ids:
            results_filter = "WHERE test_run_id IN :test_run_ids"
        elif job_execution_id:
            results_filter = "WHERE test_run_id = :job_execution_id"

        # Pending JEs (no tr row) surface in project-scope queries — the LEFT JOIN to
        # test_suites yields a NULL ts row that the ``ts.id IS NULL`` clause lets through —
        # but not in suite/TG-scoped queries, since the WHERE filter requires ts to match.
        query = f"""
        WITH run_results AS (
            SELECT test_run_id,
                SUM(CASE WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Passed' THEN 1 ELSE 0 END) AS passed_ct,
                SUM(CASE WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Warning' THEN 1 ELSE 0 END) AS warning_ct,
                SUM(CASE WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Failed' THEN 1 ELSE 0 END) AS failed_ct,
                SUM(CASE WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Error' THEN 1 ELSE 0 END) AS error_ct,
                SUM(CASE WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Log' THEN 1 ELSE 0 END) AS log_ct,
                SUM(CASE WHEN COALESCE(disposition, 'Confirmed') IN ('Dismissed', 'Inactive')
                    THEN 1 ELSE 0 END) AS dismissed_ct
            FROM test_results
            {results_filter}
            GROUP BY test_run_id
        )
        SELECT
            je.id AS job_execution_id,
            tr.id AS test_run_id,
            je.job_schedule_id,
            je.status,
            je.created_at,
            je.started_at,
            je.completed_at,
            je.active_seconds,
            je.error_message,
            COALESCE(tr.progress, '[]'::jsonb) AS progress,
            tg.table_groups_name,
            ts.test_suite,
            je.project_code,
            p.project_name,
            tr.test_ct,
            rr.passed_ct,
            rr.warning_ct,
            rr.failed_ct,
            rr.error_ct,
            rr.log_ct,
            rr.dismissed_ct,
            tr.dq_score_test_run AS dq_score_testing,
            COUNT(*) OVER() AS total_count,
            sv.version AS version_number,
            sv.frozen_at AS version_frozen_at,
            (SELECT MAX(av.version) FROM suite_versions av
                WHERE av.test_suite_id = ts.id AND av.frozen_at IS NOT NULL) AS active_version_number,
            tr.test_starttime,
            -- test_starttime is stored as UTC without a zone.
            (SELECT MAX(fv.version) FROM suite_versions fv
                WHERE fv.test_suite_id = ts.id
                    AND fv.frozen_at <= tr.test_starttime AT TIME ZONE 'UTC') AS version_in_force_at_start,
            (tr.version_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM suite_versions dv WHERE dv.id = tr.version_id)) AS version_discarded
        FROM job_executions je
            LEFT JOIN test_runs tr ON tr.id = je.id
            LEFT JOIN suite_versions sv ON sv.id = tr.version_id AND sv.test_suite_id IS NOT NULL
            LEFT JOIN test_suites ts ON ts.id = tr.test_suite_id
            LEFT JOIN table_groups tg ON tg.id = ts.table_groups_id
            LEFT JOIN projects p ON p.project_code = je.project_code
            LEFT JOIN run_results rr ON rr.test_run_id = tr.id
        WHERE je.job_key = 'run-tests'
            AND (ts.suite_type IN :suite_types OR ts.id IS NULL)
            {" AND je.project_code = :project_code" if project_code else ""}
            {" AND ts.table_groups_id = :table_group_id" if table_group_id else ""}
            {" AND ts.id = :test_suite_id" if test_suite_id else ""}
            {" AND tr.id IN :test_run_ids" if test_run_ids else ""}
            {" AND tr.version_id = :version_id" if version_id else ""}
            {" AND je.id = :job_execution_id" if job_execution_id else ""}
            {" AND je.job_schedule_id = :schedule_id" if schedule_id else ""}
            {" AND je.status IN :statuses" if statuses else ""}
        ORDER BY je.created_at DESC
        LIMIT :limit OFFSET :offset;
        """
        params = {
            "project_code": project_code,
            "suite_types": tuple(t.value for t in suite_types),
            "table_group_id": table_group_id,
            "test_suite_id": test_suite_id,
            "test_run_ids": tuple(test_run_ids or []),
            "version_id": str(version_id) if version_id else None,
            "job_execution_id": str(job_execution_id) if job_execution_id else None,
            "schedule_id": schedule_id,
            "statuses": tuple(statuses) if statuses else (),
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        items = [TestRunSummary(**row) for row in results]
        total = items[0].total_count if items else 0
        return items, total

    def get_monitoring_summary(self, table_name: str | None = None) -> TestRunMonitorSummary:
        freshness_anomalies = func.sum(case(
            ((TestResult.test_type == "Table_Freshness") & (TestResult.result_code == 0), 1),
            else_=0,
        ))
        schema_anomalies = func.sum(case(
            ((TestResult.test_type == "Schema_Drift") & (TestResult.result_code == 0), 1),
            else_=0,
        ))
        volume_anomalies = func.sum(case(
            ((TestResult.test_type == "Volume_Trend") & (TestResult.result_code == 0), 1),
            else_=0,
        ))
        projection = [
            TestRun.id.label("test_run_id"),
            JobExecution.completed_at.label("test_endtime"),
            TableGroup.id.label("table_group_id"),
            TableGroup.table_groups_name,
            Project.project_name,
            freshness_anomalies.label("freshness_anomalies"),
            schema_anomalies.label("schema_anomalies"),
            volume_anomalies.label("volume_anomalies"),
        ]
        group_by = [
            TestRun.id,
            JobExecution.completed_at,
            TableGroup.id,
            TableGroup.table_groups_name,
            Project.project_name,
        ]
        if table_name:
            projection.append(TestResult.table_name)
            group_by.append(TestResult.table_name)

        query = (
            select(*projection)
            .join(TableGroup, TableGroup.monitor_test_suite_id == TestRun.test_suite_id)
            .join(Project, Project.project_code == TableGroup.project_code)
            .join(TestResult, TestResult.test_run_id == TestRun.id)
            .join(JobExecution, JobExecution.id == TestRun.id)
            .where(
                TestRun.id == self.id,
                (TestResult.table_name == table_name) if table_name else True,
            )
            .group_by(*group_by)
        )

        return TestRunMonitorSummary(**get_current_session().execute(query).mappings().first())

    @classmethod
    def has_active_job_for(cls, entity_cls: type[Entity], *entity_ids: str | int | UUID) -> bool:
        """Check whether any active test run job exists for the given entity or entities."""
        query = (
            select(func.count(cls.id))
            .join(JobExecution, cls.id == JobExecution.id)
            .where(JobExecution.status.in_(JobStatus.active()))
        )
        if entity_cls is cls:
            query = query.where(cls.id.in_(entity_ids))
        elif entity_cls is TestSuite:
            query = query.where(cls.test_suite_id.in_(entity_ids))
        elif entity_cls is TableGroup:
            query = query.join(TestSuite, cls.test_suite_id == TestSuite.id).where(TestSuite.table_groups_id.in_(entity_ids))
        elif entity_cls is Connection:
            query = query.join(TestSuite, cls.test_suite_id == TestSuite.id).where(TestSuite.connection_id.in_(entity_ids))
        elif entity_cls is Project:
            query = query.join(TestSuite, cls.test_suite_id == TestSuite.id).where(TestSuite.project_code.in_(entity_ids))
        else:
            raise ValueError(f"Unsupported entity: {entity_cls.__name__}")
        return get_current_session().execute(query).scalar() > 0

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        """Delete runs and their results by removing the parent job executions.

        The run id is the job execution id, and the foreign-key chain
        (test_results -> test_runs -> job_executions) cascades on delete.
        """
        get_current_session().execute(delete(JobExecution).where(JobExecution.id.in_(ids)))

    @classmethod
    def find_latest_per_test_suite(cls, project_code: str) -> set[UUID]:
        """Return the latest completed test run id per test suite for the
        project.

        Includes monitor suites (`suite_type='monitor'`). Used by data retention to
        protect at least one run per scope so each suite keeps a usable
        baseline when retention sweeps clear older history. Failed and
        in-flight runs are skipped.
        """
        rows = get_current_session().scalars(
            select(cls.id)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .join(JobExecution, cls.id == JobExecution.id)
            .where(
                TestSuite.project_code == project_code,
                JobExecution.status == JobStatus.COMPLETED,
            )
            .order_by(cls.test_suite_id, cls.test_starttime.desc())
            .distinct(cls.test_suite_id)
        ).all()
        return set(rows)

    @classmethod
    def delete_older_than(
        cls,
        cutoff: datetime,
        project_code: str,
        protected_ids: set[UUID],
        batch_size: int = 1000,
        dry_run: bool = False,
    ) -> int:
        """Batched delete of test runs (with cascading children) older than
        cutoff for the given project, excluding protected ids. Returns total
        parent rows deleted across all batches — or, with ``dry_run=True``,
        the number that would be deleted (for retention preview, no writes).

        Runs whose job has not reached a terminal status are never deleted —
        they may still be writing data.

        Each batch runs in its own transaction (committed before the next batch
        is selected), so locks on test_runs / test_results / etc. are released
        between batches and WAL growth stays bounded for large sweeps.
        """
        where_clauses = [
            TestSuite.project_code == project_code,
            cls.test_starttime < cutoff,
            JobExecution.status.in_(JobStatus.terminal()),
        ]
        if protected_ids:
            where_clauses.append(cls.id.notin_(protected_ids))

        base_select = (
            select(cls.id)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .join(JobExecution, cls.id == JobExecution.id)
        )

        if dry_run:
            return get_current_session().scalar(
                select(func.count()).select_from(base_select.where(*where_clauses).subquery())
            ) or 0

        total = 0
        while True:
            with database_session() as session:
                ids = session.scalars(base_select.where(*where_clauses).limit(batch_size)).all()
                if not ids:
                    break
                cls.cascade_delete([str(i) for i in ids])
                total += len(ids)
        return total


    def init_progress(self) -> None:
        self._progress = {
            "data_chars": {"label": "Refreshing data catalog"},
            "validation": {"label": "Validating test definitions"},
            "QUERY": {"label": "Running query tests"},
            "CAT": {"label": "Running aggregated tests"},
            "METADATA": {"label": "Running metadata tests"},
        }
        for key in self._progress:
            self._progress[key].update({"key": key, "status": "Pending"})

    def set_progress(self, key: ProgressKey, status: ProgressStatus, detail: str | None = None, error: str | None = None) -> None:
        self._progress[key]["status"] = status
        if detail:
            self._progress[key]["detail"] = detail
        if error:
            self._progress[key]["error"] = error

        self.progress = list(self._progress.values())
        flag_modified(self, "progress")
