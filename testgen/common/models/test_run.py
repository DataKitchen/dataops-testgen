from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import ClassVar, Literal, NamedTuple, Self, TypedDict
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    ForeignKey,
    Integer,
    Subquery,
    and_,
    delete,
    desc,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased, foreign, relationship
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import case

from testgen.common.enums import JOB_STATUS_LABEL, JobKey, JobStatus, SuiteType
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
    schema_override: str | None
    table_names_override: dict | None
    match_schema_override: str | None
    match_table_names_override: dict | None
    external_url: str | None
    caller_metadata: dict | None


@dataclass(frozen=True)
class RunVersion:
    """The contract version a run checked, with its state at read time."""

    number: int
    frozen_at: datetime | None
    active_number: int | None
    test_starttime: datetime | None
    checked_version_in_force: bool = False
    status: JobStatus | None = None

    @property
    def state(self) -> VersionState:
        return version_state(self.frozen_at, self.number == self.active_number)

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

    @property
    def is_out_of_force(self) -> bool:
        """Whether the run checked a frozen version already superseded when it started."""
        return not self.is_preview and not self.checked_version_in_force


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
    version_number: int | None = None
    version_frozen_at: datetime | None = None
    active_version_number: int | None = None
    test_starttime: datetime | None = None
    version_checked_in_force: bool = False
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
            self.version_checked_in_force,
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
    def is_out_of_force(self) -> bool:
        """Whether the run checked a frozen version already superseded when it started."""
        if self.version_discarded:
            return False
        return self.run_version is not None and self.run_version.is_out_of_force

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


class RunVersionScope(NamedTuple):
    has_contract: bool
    hidden_count: int


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
        # Each is set only when the run was submitted with that override. The two maps are JSONB
        # objects, so they are read as JSON rather than through astext.
        JobExecution.kwargs["schema_name"].astext.label("schema_override"),
        JobExecution.kwargs["table_names"].label("table_names_override"),
        JobExecution.kwargs["match_schema_name"].astext.label("match_schema_override"),
        JobExecution.kwargs["match_table_names"].label("match_table_names_override"),
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

    def checked_version_in_force(self) -> bool:
        """Whether the run checked the version in force when it started, as every run of a suite that keeps
        no versions does. A preview, a run of a draft since discarded, and a run of a version superseded
        before the run started did not."""
        if self.version_id is None:
            return True
        started_at = (self.test_starttime or datetime.now(UTC)).replace(tzinfo=UTC)
        return get_current_session().scalar(select(SuiteVersion.in_force_at(
            literal(self.version_id, postgresql.UUID(as_uuid=True)),
            literal(started_at, postgresql.TIMESTAMP(timezone=True)),
        )))

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
        all_versions: bool = True,
    ) -> tuple[list[TestRunSummary], int]:
        """The run-tests jobs matching the filters, queued or not, newest first.

        :param all_versions: when False, only runs of the version in force when they started, and
            queued runs of the version in force now
        """
        runs = cls._summary_rows(
            project_code, table_group_id, test_suite_id, test_run_ids, job_execution_id, schedule_id, statuses,
            suite_types, version_id,
        )
        if runs is None:
            return [], 0
        query = (
            select(*(runs.c[field.name] for field in fields(TestRunSummary)))
            .where(*([] if all_versions else [SuiteVersion.in_force_at(runs.c.checked_version, runs.c.checked_at)]))
            .order_by(runs.c.created_at.desc(), runs.c.job_execution_id)
        )
        return cls._paginate(query, page=page, limit=page_size, data_class=TestRunSummary)

    @classmethod
    def select_version_scope(
        cls,
        project_code: str,
        table_group_id: str | None = None,
        test_suite_id: str | None = None,
        *,
        suite_types: Sequence[SuiteType] = (SuiteType.REGULAR,),
    ) -> RunVersionScope:
        """Whether the runs the filters select include a contract's, and how many of them
        ``select_summary(all_versions=False)`` leaves out.
        """
        runs = cls._summary_rows(project_code, table_group_id, test_suite_id, None, None, None, None, suite_types, None)
        if runs is None:
            return RunVersionScope(False, 0)
        has_contract, hidden_count = get_current_session().execute(
            select(
                func.coalesce(func.bool_or(runs.c.suite_type == SuiteType.CONTRACT), False),
                func.count().filter(~SuiteVersion.in_force_at(runs.c.checked_version, runs.c.checked_at)),
            )
        ).one()
        return RunVersionScope(has_contract, hidden_count)

    @classmethod
    def _summary_rows(
        cls,
        project_code: str | None,
        table_group_id: str | None,
        test_suite_id: str | None,
        test_run_ids: list[str | UUID] | None,
        job_execution_id: str | UUID | None,
        schedule_id: str | None,
        statuses: list[JobStatus] | None,
        suite_types: Sequence[SuiteType],
        version_id: UUID | str | None,
    ) -> Subquery | None:
        """The run-tests jobs matching the filters as a subquery: the ``TestRunSummary`` columns, ``suite_type``,
        and ``checked_version`` / ``checked_at``, the version a run checks and when it started. None when an id
        filter is not a valid id.
        """
        if (
            (table_group_id and not is_uuid4(table_group_id))
            or (test_suite_id and not is_uuid4(test_suite_id))
            or (test_run_ids and not all(is_uuid4(run_id) for run_id in test_run_ids))
            or (job_execution_id and not is_uuid4(job_execution_id))
            or (schedule_id and not is_uuid4(schedule_id))
        ):
            return None

        confirmed = func.coalesce(TestResult.disposition, "Confirmed") == "Confirmed"
        results = select(
            TestResult.test_run_id,
            *(
                func.count().filter(confirmed, TestResult.status == status).label(f"{status.value.lower()}_ct")
                for status in TestResultStatus
            ),
            func.count()
            .filter(func.coalesce(TestResult.disposition, "Confirmed").in_(("Dismissed", "Inactive")))
            .label("dismissed_ct"),
        )
        # A test run shares its job's id. Postgres does not reliably push the outer filters into the grouped CTE.
        if test_run_ids:
            results = results.where(TestResult.test_run_id.in_(test_run_ids))
        elif job_execution_id:
            results = results.where(TestResult.test_run_id == job_execution_id)
        run_results = results.group_by(TestResult.test_run_id).cte("run_results")

        # A queued job has no test run yet: its kwargs name the suite and, optionally, the version it will check.
        queued_suite_id = JobExecution.kwargs["test_suite_id"].astext.cast(postgresql.UUID(as_uuid=True))
        queued_version_id = JobExecution.kwargs["version_id"].astext.cast(postgresql.UUID(as_uuid=True))
        started = cls.id.is_not(None)
        # A job that ended without creating its test run is judged once, as of when it was started or queued.
        ended = JobExecution.status.in_(JobStatus.terminal())
        # test_starttime is stored as UTC without a zone.
        starttime = func.timezone("UTC", cls.test_starttime)
        run_version, active, discarded = (aliased(SuiteVersion) for _ in range(3))

        query = (
            select(
                JobExecution.id.label("job_execution_id"),
                cls.id.label("test_run_id"),
                JobExecution.job_schedule_id,
                JobExecution.status,
                JobExecution.created_at,
                JobExecution.started_at,
                JobExecution.completed_at,
                JobExecution.active_seconds,
                JobExecution.error_message,
                func.coalesce(cls.progress, literal_column("'[]'::jsonb", postgresql.JSONB)).label("progress"),
                TableGroup.table_groups_name,
                TestSuite.test_suite,
                TestSuite.suite_type,
                JobExecution.project_code,
                Project.project_name,
                cls.test_ct,
                run_results.c.passed_ct,
                run_results.c.warning_ct,
                run_results.c.failed_ct,
                run_results.c.error_ct,
                run_results.c.log_ct,
                run_results.c.dismissed_ct,
                cls.dq_score_test_run.label("dq_score_testing"),
                run_version.version.label("version_number"),
                run_version.frozen_at.label("version_frozen_at"),
                select(func.max(active.version))
                .where(active.test_suite_id == TestSuite.id, active.frozen_at.is_not(None))
                .scalar_subquery()
                .label("active_version_number"),
                cls.test_starttime,
                SuiteVersion.in_force_at(cls.version_id, starttime).label("version_checked_in_force"),
                and_(cls.version_id.is_not(None), ~exists().where(discarded.id == cls.version_id)).label(
                    "version_discarded"
                ),
                case(
                    (started, cls.version_id),
                    (ended, queued_version_id),
                    else_=func.coalesce(queued_version_id, SuiteVersion.for_run(TestSuite.id)),
                ).label("checked_version"),
                case(
                    (started, starttime),
                    (ended, func.coalesce(JobExecution.started_at, JobExecution.created_at)),
                    else_=func.now(),
                ).label("checked_at"),
            )
            .select_from(JobExecution)
            .outerjoin(cls, cls.id == JobExecution.id)
            .outerjoin(run_version, and_(run_version.id == cls.version_id, run_version.test_suite_id.is_not(None)))
            .outerjoin(TestSuite, TestSuite.id == func.coalesce(cls.test_suite_id, queued_suite_id))
            .outerjoin(TableGroup, TableGroup.id == TestSuite.table_groups_id)
            .outerjoin(Project, Project.project_code == JobExecution.project_code)
            .outerjoin(run_results, run_results.c.test_run_id == cls.id)
            .where(
                JobExecution.job_key == JobKey.run_tests,
                or_(TestSuite.suite_type.in_(suite_types), TestSuite.id.is_(None)),
            )
        )
        for value, clause in (
            (project_code, JobExecution.project_code == project_code),
            (table_group_id, TestSuite.table_groups_id == table_group_id),
            (test_suite_id, TestSuite.id == test_suite_id),
            (test_run_ids, cls.id.in_(test_run_ids or [])),
            (version_id, cls.version_id == version_id),
            (job_execution_id, JobExecution.id == job_execution_id),
            (schedule_id, JobExecution.job_schedule_id == schedule_id),
            (statuses, JobExecution.status.in_(statuses or [])),
        ):
            if value:
                query = query.where(clause)
        return query.subquery("runs")

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
