import json
import logging
import signal
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Select,
    String,
    Text,
    and_,
    case,
    delete,
    exists,
    false,
    func,
    literal,
    literal_column,
    not_,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from testgen.common.enums import (
    ONE_PER_PROJECT_JOB_KEYS,
    PAUSABLE_JOB_KEYS,
    WORKING_STATUSES,
    JobKey,
    JobSource,
    JobStatus,
)
from testgen.common.flavors import runs_in_process
from testgen.common.models import Base, database_session, get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

LOG = logging.getLogger("testgen")

# A run killed for memory records no error of its own, so these carry the whole explanation.
_RESOURCE_REMEDY = "Raise the memory available to TestGen, or reduce how much data the run reads."
_SAMPLING_REMEDY = (
    "Raise the memory available to TestGen, or reduce how much data the run reads by turning on"
    " sampling for the table group."
)

QUEUED_MESSAGE = (
    "Waiting for another run on a DuckDB or file connection to finish."
    " TestGen runs a limited number of these at once."
)

# What ``Popen.returncode`` reports for a process the kernel killed, which is how an out-of-memory
# kill arrives. Windows has no SIGKILL and reports positive codes, so there the check never matches.
_KILLED_EXIT_CODE = -getattr(signal, "SIGKILL", 9)


def process_failure_message(pid: int, exit_code: int, job_key: str | None = None) -> str:
    """Explain a job subprocess that exited non-zero, naming resource exhaustion when that is
    what the exit code shows.

    The pid and code stay in the text: they are what a support request needs, and nothing else
    records them.
    """
    if exit_code != _KILLED_EXIT_CODE:
        return f"Process {pid} exited with code {exit_code}."

    remedy = _SAMPLING_REMEDY if job_key == JobKey.run_profile else _RESOURCE_REMEDY
    return (
        "The run was stopped by the operating system before it could finish, which usually means"
        f" TestGen ran out of memory. {remedy}"
        f" (Process {pid} exited with code {exit_code}.)"
    )


def _merged_ids_sql(key: str) -> str:
    """SQL for the sorted union of the ``key`` id lists on a pending row and on its conflicting insert."""
    return f"""(
        SELECT COALESCE(jsonb_agg(DISTINCT merged.id ORDER BY merged.id), '[]'::jsonb)
          FROM jsonb_array_elements_text(
                   COALESCE(job_executions.kwargs -> '{key}', '[]'::jsonb)
                   || COALESCE(excluded.kwargs -> '{key}', '[]'::jsonb)
               ) AS merged(id)
    )"""


@dataclass(frozen=True)
class OnlyWhenTransitioningTo:
    """A column value that applies to one target of a multi-target transition.

    ``_transition`` picks its target from the row's current status. Wrapping a value binds it to
    the same condition that selects ``target``, writing NULL to the column, rather than leaving it
    unchanged, when a different target wins.
    """

    target: JobStatus
    value: Any


# Caller metadata is stored verbatim and rendered back to whoever opens the run, so it is bounded
# rather than validated: the shape belongs to the caller, the size belongs to the database.
CALLER_METADATA_MAX_KEYS = 50
CALLER_METADATA_MAX_BYTES = 10_240
EXTERNAL_URL_MAX_LENGTH = 2_048


def validate_caller_metadata(value: object) -> str | None:
    """Return an error message if ``value`` is not a valid ``caller_metadata`` payload, else ``None``."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return "must be a JSON object of key-value pairs"
    if len(value) > CALLER_METADATA_MAX_KEYS:
        return f"must have at most {CALLER_METADATA_MAX_KEYS} keys"
    try:
        serialized = json.dumps(value)
    except (TypeError, ValueError):
        return "must be JSON-serializable"
    if len(serialized) > CALLER_METADATA_MAX_BYTES:
        return f"must be at most {CALLER_METADATA_MAX_BYTES} bytes when serialized as JSON"
    return None


class JobExecution(Base):
    __tablename__ = "job_executions"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_key: str = Column(String(100), nullable=False)
    # kwargs is the internal dispatch payload passed to the job handler.
    # Do not query or filter on it — external code should not depend on its structure.
    kwargs: dict[str, Any] = Column(postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    source: str = Column(String(20), nullable=False)
    status: str = Column(String(30), nullable=False, default=JobStatus.PENDING, server_default=text("'pending'"))
    project_code: str = Column(String(30), nullable=False)
    job_schedule_id: UUID | None = Column(postgresql.UUID(as_uuid=True), nullable=True)
    error_message: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    claimed_at: datetime | None = Column(postgresql.TIMESTAMP(timezone=True), nullable=True)
    started_at: datetime | None = Column(postgresql.TIMESTAMP(timezone=True), nullable=True)
    completed_at: datetime | None = Column(postgresql.TIMESTAMP(timezone=True), nullable=True)
    # Checkpoint written by a pausable job so a later run can continue where it stopped.
    # Shape is owned by the job; NULL means the next claim is a fresh start, not a resume.
    # none_as_null, so clearing a checkpoint writes SQL NULL rather than a JSON null that
    # every IS NULL test would miss.
    resume_state: dict[str, Any] | None = Column(postgresql.JSONB(none_as_null=True), nullable=True)
    # Seconds this job spent actually working, summed over however many processes ran it, and
    # the only answer any display gives for how long a run took. Every route out of a working
    # status records a segment, so NULL means the run never worked rather than that nobody
    # looked -- which is what lets the displays read this alone.
    #
    # A process that dies alone is reaped by the scheduler and billed then and there. Only a
    # death that takes the scheduler with it waits for the next start to settle the row, and
    # that segment runs to the recovery, so it carries the downtime with it. A run that was
    # claimed but never started records nothing at all, since none of that time was work.
    active_seconds: float | None = Column(Float, nullable=True)
    # Whether the job runs a target engine inside the TestGen process. Stamped at submit and not
    # revisited, so a queued run keeps it even if its connection's type changes before the run
    # starts.
    in_process: bool = Column(Boolean, nullable=False, default=False, server_default=false())
    # A link back to whatever triggered the run, rendered on the results page.
    external_url: str | None = Column(String, nullable=True)
    # Free-form detail from whoever triggered the run, stored verbatim beside it. The shape is the
    # caller's and nothing here reads it.
    # Named for its origin rather than `metadata`, which Declarative reserves.
    caller_metadata: dict[str, Any] | None = Column(postgresql.JSONB(none_as_null=True), nullable=True)

    @classmethod
    def submit(
        cls,
        job_key: str,
        kwargs: dict[str, Any],
        source: JobSource,
        project_code: str,
        job_schedule_id: UUID | None = None,
        external_url: str | None = None,
        caller_metadata: dict[str, Any] | None = None,
    ) -> Self:
        """Create a pending job execution row. Caller controls the commit."""
        session = get_current_session()
        job_exec = cls(
            job_key=job_key,
            kwargs=kwargs,
            source=source,
            project_code=project_code,
            job_schedule_id=job_schedule_id,
            in_process=cls._reads_in_process_target(job_key, kwargs),
            external_url=external_url,
            caller_metadata=caller_metadata,
        )
        session.add(job_exec)
        session.flush([job_exec])
        LOG.info("Submitted job execution %s: job_key=%s, source=%s", job_exec.id, job_key, source)
        return job_exec

    @classmethod
    def request_project_score_refresh(
        cls,
        project_code: str,
        *,
        profile_table_group_ids: Iterable[str] = (),
        test_table_group_ids: Iterable[str] = (),
        refresh_date: datetime | None = None,
    ) -> UUID:
        """Queue a score refresh for the project, or merge into the one already pending.

        A pending refresh absorbs the request: its table group lists gain the given ids and its
        ``refresh_date`` becomes the later of the two. Caller controls the commit.

        :param project_code: Project whose scores are refreshed.
        :param profile_table_group_ids: Table groups whose profiling scores are rolled up.
        :param test_table_group_ids: Table groups whose test scores are rolled up.
        :param refresh_date: Date of the scorecard history entry the refresh adds.
        :returns: Id of the pending refresh job execution.
        """
        kwargs = {
            "project_code": project_code,
            "profile_table_group_ids": sorted({str(id_) for id_ in profile_table_group_ids}),
            "test_table_group_ids": sorted({str(id_) for id_ in test_table_group_ids}),
            "refresh_date": refresh_date.isoformat() if refresh_date else None,
        }
        merged_kwargs = literal_column(f"""
            jsonb_build_object(
                'project_code', job_executions.kwargs -> 'project_code',
                'profile_table_group_ids', {_merged_ids_sql("profile_table_group_ids")},
                'test_table_group_ids', {_merged_ids_sql("test_table_group_ids")},
                'refresh_date', to_jsonb(GREATEST(
                    (job_executions.kwargs ->> 'refresh_date')::timestamptz,
                    (excluded.kwargs ->> 'refresh_date')::timestamptz
                ))
            )
        """)
        statement = (
            postgresql.insert(cls)
            .values(
                id=uuid4(),
                job_key=JobKey.refresh_project_scores,
                kwargs=kwargs,
                source=JobSource.system,
                project_code=project_code,
                in_process=False,
            )
            .on_conflict_do_update(
                index_elements=[cls.project_code],
                index_where=and_(
                    cls.job_key == JobKey.refresh_project_scores,
                    cls.status == JobStatus.PENDING,
                ),
                set_={"kwargs": merged_kwargs},
            )
            .returning(cls.id)
        )
        job_id = get_current_session().execute(statement).scalar_one()
        LOG.info("Requested score refresh %s for project %s: %s", job_id, project_code, kwargs)
        return job_id

    @classmethod
    def _reads_in_process_target(cls, job_key: str, kwargs: dict[str, Any]) -> bool:
        """Whether the job's handler opens a target connection whose engine runs in-process.

        Only profiling, catalog refreshes, test runs and monitor runs open a target connection. A run whose table
        group or suite id is missing, is not a UUID, or matches no row resolves to False.
        """
        match job_key:
            case JobKey.run_profile | JobKey.refresh_data_catalog:
                id_key = "table_group_id"
            case JobKey.run_tests | JobKey.run_monitors:
                id_key = "test_suite_id"
            case _:
                return False
        # Parsed, not checked with is_uuid4, which accepts only lowercase: the id arrives as the
        # caller typed it, and Postgres matches it in any case.
        try:
            target_id = UUID(str(kwargs[id_key]))
        except (KeyError, ValueError):
            return False

        query = select(Connection.sql_flavor_code).join(
            TableGroup, TableGroup.connection_id == Connection.connection_id
        )
        if id_key == "table_group_id":
            query = query.where(TableGroup.id == target_id)
        else:
            # The table group's connection, not the suite's own column, is the one the run opens.
            query = query.join(TestSuite, TestSuite.table_groups_id == TableGroup.id).where(
                TestSuite.id == target_id
            )
        return runs_in_process(get_current_session().scalar(query))

    # What a poll acts on: everything it can start, plus the one status it settles instead.
    ACTIONABLE_STATUSES: ClassVar[tuple[JobStatus, ...]] = (*JobStatus.claimable(), JobStatus.CANCEL_REQUESTED)

    @classmethod
    def _select_actionable(cls, *clauses: ColumnElement[bool]) -> Select:
        # The status list must stay exactly ACTIONABLE_STATUSES, which is the predicate of the
        # partial index the poll scans; ``*clauses`` narrow it further.
        return (
            select(cls)
            .where(cls.status.in_(cls.ACTIONABLE_STATUSES), *clauses)
            .order_by(cls.created_at, cls.id)
            .with_for_update(skip_locked=True)
        )

    @classmethod
    def claim_actionable(cls, limit: int, in_process_slots: int) -> list[Self]:
        """Claim startable rows and fetch cancel_requested rows.

        PENDING (fresh start), INTERRUPTED (a shutdown stopped it), RESUME_REQUESTED (a resume
        was requested) and QUEUED (waiting for an in-process slot) all transition to claimed; the
        resume state on the row is what tells a fresh start from a continuation, so the dispatch
        path is identical for all four.
        Cancel_requested rows are returned as-is for the scheduler to act on.

        Startable ``in_process`` rows are claimed separately, at most ``in_process_slots`` of
        them, oldest first, and every startable ``in_process`` row left over moves to QUEUED.
        Every other row counts toward ``limit``. Every query here, including the one that picks
        rows to queue, uses FOR UPDATE SKIP LOCKED to prevent concurrent processing. Every returned row is claimed or cancel_requested.
        """
        session = get_current_session()
        rows = list(session.scalars(
            cls._select_actionable(
                or_(cls.status == JobStatus.CANCEL_REQUESTED, cls.in_process.is_(False)),
                not_(cls._waits_for_same_project_job()),
            ).limit(limit)
        ).all())
        if in_process_slots > 0:
            rows += session.scalars(
                cls._select_actionable(
                    cls.status != JobStatus.CANCEL_REQUESTED, cls.in_process.is_(True)
                ).limit(in_process_slots)
            ).all()
        rows.sort(key=lambda row: (row.created_at, row.id))
        actionable: list[Self] = []
        claimed = 0
        one_per_project_claims: set[tuple[str, str]] = set()
        for row in rows:
            if row.status in JobStatus.claimable():
                if row.job_key in ONE_PER_PROJECT_JOB_KEYS:
                    if (row.job_key, row.project_code) in one_per_project_claims:
                        continue
                    one_per_project_claims.add((row.job_key, row.project_code))
                if not row.claim():
                    continue
                claimed += 1
            actionable.append(row)
        if claimed:
            LOG.info("Claimed %d job execution(s)", claimed)
        # After the claims, so only rows this poll could not take are left to queue. Skips rows
        # another scheduler holds, as the claims do: waiting on them while holding this poll's
        # own claims would let two schedulers deadlock on each other's rows.
        held = (
            select(cls.id)
            .where(cls.in_process.is_(True), cls.status.in_(JobStatus.sources_for(JobStatus.QUEUED)))
            .with_for_update(skip_locked=True)
        )
        if queued := cls._transition_bulk_where(JobStatus.QUEUED, cls.id.in_(held)):
            LOG.info("Queued %d job execution(s) for an in-process slot", len(queued))
        return actionable

    @classmethod
    def _waits_for_same_project_job(cls) -> ColumnElement[bool]:
        """True for a startable row whose key allows one per project while another row of that key
        and project is working."""
        other = aliased(cls)
        return and_(
            cls.job_key.in_(ONE_PER_PROJECT_JOB_KEYS),
            cls.status.in_(JobStatus.claimable()),
            exists().where(
                other.job_key == cls.job_key,
                other.project_code == cls.project_code,
                other.id != cls.id,
                other.status.in_(JobStatus.ordered({*WORKING_STATUSES, JobStatus.CANCEL_REQUESTED})),
            ),
        )

    @classmethod
    def select_active_by_kwargs(
        cls,
        *clauses: ColumnElement[bool],
        project_code: str,
        job_key: str,
        kwargs_match: dict[str, str | list[str]],
        statuses: list[JobStatus] | None = None,
    ) -> list[Self]:
        """Find JE rows whose ``kwargs`` JSONB matches the given (key, value) pairs.

        Values may be a single string or a list of strings (which becomes an ``IN`` filter).
        Additional caller-supplied WHERE expressions may be passed as ``*clauses``.
        Defaults to active (non-terminal) statuses.
        """
        statuses = statuses or list(JobStatus.active())
        query = select(cls).where(
            cls.project_code == project_code,
            cls.job_key == job_key,
            cls.status.in_(statuses),
            *clauses,
        )
        for k, v in kwargs_match.items():
            if isinstance(v, list):
                if not v:
                    return []
                query = query.where(cls.kwargs[k].astext.in_([str(x) for x in v]))
            else:
                query = query.where(cls.kwargs[k].astext == str(v))
        query = query.order_by(cls.created_at.desc())
        return list(get_current_session().scalars(query).all())

    @classmethod
    def recover_stale(cls) -> int:
        """Settle rows left behind by a dead process. Returns how many were settled.

        A row that was asked to stop and carries a checkpoint continues instead of being
        canceled. The job commits that checkpoint as the last write it makes before unwinding,
        so its presence means the work is accounted for and only the process's exit went
        unrecorded. A stopping status on its own is not enough: inferring a continue from it
        would claim a run whose process is merely unreachable -- ``exec-job`` is started in its
        own session and outlives its scheduler -- and hand a second worker the same run.

        Where it continues from follows what stopped it. A run someone asked to pause is held at
        PAUSED, because releasing it is a decision rather than a consequence, and one that was
        interrupted is queued at INTERRUPTED for the next poll. Parking runs first, so a pause
        carrying a checkpoint is settled before the cancel pass can reach it. Everything else
        the passes reach is canceled, a checkpoint it never got to signal included.
        """
        # Each pass ends a working period, so each bills what the dead process worked. Rows only
        # reach here when the scheduler died too -- one that merely lost its subprocess was
        # billed when the wrapper reaped it -- so the segment runs to this restart and carries
        # the downtime. Recording nothing would instead read as no work at all. A row that was
        # claimed and never started is the exception, and records nothing because that is true.
        paused = cls._transition_bulk_where(
            JobStatus.PAUSED,
            cls.status == JobStatus.PAUSE_REQUESTED,
            cls.resume_state.isnot(None),
        )
        resumable = cls._transition_bulk_where(
            JobStatus.INTERRUPTED,
            cls.status.in_(JobStatus.stale_recoverable()),
            cls.resume_state.isnot(None),
        )
        canceled = cls._transition_bulk_where(
            JobStatus.CANCEL_REQUESTED,
            cls.status.in_(JobStatus.stale_recoverable()),
        )
        if paused:
            LOG.info("Parked %d job execution(s) that a previous session was pausing", len(paused))
        if resumable:
            LOG.info("Queued %d job execution(s) to continue from their checkpoint", len(resumable))
        return len(paused) + len(resumable) + len(canceled)

    @classmethod
    def get(cls, execution_id: UUID) -> Self | None:
        """Fetch a job execution by primary key."""
        session = get_current_session()
        return session.get(cls, execution_id)

    @classmethod
    def delete_older_than(
        cls,
        cutoff: datetime,
        project_code: str,
        protected_ids: set[UUID],
        batch_size: int = 1000,
    ) -> int:
        """Batched delete of terminal-state job executions older than cutoff for
        the given project, excluding protected ids. Returns total rows deleted.

        Skips rows in non-terminal states — those represent live work and must not be
        removed regardless of age.

        Each batch runs in its own transaction (committed before the next batch
        is selected), so locks on job_executions are released between batches
        and WAL growth stays bounded for large sweeps.
        """
        where_clauses = [
            cls.project_code == project_code,
            cls.completed_at < cutoff,
            cls.status.in_(JobStatus.terminal()),
        ]
        if protected_ids:
            where_clauses.append(cls.id.notin_(protected_ids))

        total = 0
        while True:
            with database_session() as session:
                ids = session.scalars(select(cls.id).where(*where_clauses).limit(batch_size)).all()
                if not ids:
                    break
                session.execute(delete(cls).where(cls.id.in_(ids)))
                total += len(ids)
        return total

    @classmethod
    def list_for_project(
        cls,
        project_code: str,
        *extra_filters,
        job_key: str | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Self], int]:
        """List job executions for a project with optional filters and pagination."""
        session = get_current_session()
        query = select(cls).where(cls.project_code == project_code, *extra_filters)
        if job_key:
            query = query.where(cls.job_key == job_key)
        if status:
            query = query.where(cls.status == status)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        items = session.scalars(query.order_by(cls.created_at.desc()).offset((page - 1) * limit).limit(limit)).all()
        return list(items), total or 0

    @classmethod
    def _transition_bulk_where(cls, target: JobStatus, *clauses: ColumnElement[bool]) -> set[UUID]:
        """Move every row matching ``*clauses`` to ``target`` in one statement.

        Returns the ids that actually moved. Callers narrow with ``*clauses`` but can never
        widen the lifecycle guard.
        """
        session = get_current_session()
        billable = (
            set() if target in WORKING_STATUSES
            else set(JobStatus.sources_for(target)) & WORKING_STATUSES
        )
        return set(session.scalars(
            update(cls)
            .where(cls.status.in_(JobStatus.sources_for(target)), *clauses)
            .values(status=target.value, **cls._bill_worked_from(billable))
            .returning(cls.id)
        ).all())

    @classmethod
    def request_interrupt_bulk(cls, ids: Iterable[UUID], job_keys: Iterable[str]) -> set[UUID]:
        """Ask running jobs to stop at a work-key boundary, restricted to keys that honor it.

        Narrowed to RUNNING even though the guard would also accept a job already stopping, so
        this reports only the jobs it asked itself.
        """
        ids, job_keys = list(ids), list(job_keys)
        if not ids or not job_keys:
            return set()
        return cls._transition_bulk_where(
            JobStatus.INTERRUPT_REQUESTED,
            cls.id.in_(ids),
            cls.job_key.in_(job_keys),
            cls.status == JobStatus.RUNNING,
        )

    @classmethod
    def _worked_segment(cls) -> ColumnElement[float]:
        """Seconds this process worked, added to whatever earlier processes recorded.

        Measured from ``claimed_at``, which every claim restamps, so it marks where the current
        process began rather than where the run did and the sum across resumes needs no other
        bookkeeping.

        Both ends come from an application clock rather than the database's, which is also what
        wrote ``claimed_at``. Not always the same process -- a cancel is asked for wherever the
        request arrives -- but the same host in every topology this ships in, where taking one
        end from the database would instead fold app-to-database skew into every answer.
        """
        return func.coalesce(cls.active_seconds, 0.0) + func.extract(
            "epoch", literal(datetime.now(UTC)) - cls.claimed_at
        )

    @classmethod
    def _bill_worked_from(cls, sources: set[JobStatus]) -> dict[str, Any]:
        """The ``active_seconds`` write for a transition out of ``sources``, or nothing at all.

        ``sources`` is the set a transition bills from, and it is read off the lifecycle rather
        than chosen: a row bills when it leaves the working period, meaning it was in a status
        where a process was doing the work and the status it moves to is not one of those.

        Both halves matter. The segment runs from the claim, not from the previous transition,
        so billing it again on a step taken *within* the working period -- CLAIMED to RUNNING is
        one -- would add the whole span a second time. And a row arriving from a status that was
        not working has either done nothing yet or been billed already.

        A claim that never dispatched is excluded as well: work happens in RUNNING, which is
        where ``mark_running`` moves the row, so the span from a claim the row is still sitting
        on is nobody's work. Keyed on the status rather than on ``started_at``, which
        ``mark_running`` coalesces -- after the first segment that column says the run has
        started, not that this claim did.
        """
        sources = sources - {JobStatus.CLAIMED}
        if not sources:
            return {}
        ordered = JobStatus.ordered(sources)
        return {
            "active_seconds": case(
                (cls.status.in_(ordered), cls._worked_segment()),
                else_=cls.active_seconds,
            )
        }

    def _transition(self, *targets: JobStatus, **values: Any) -> bool:
        """Transition to a new status, guarded by the valid-transitions map.

        Accepts one or more candidate targets. Builds a CASE WHEN that
        atomically picks the right one based on the current DB status.
        Earlier targets get first pick of source states (priority order).

        A value wrapped in ``OnlyWhenTransitioningTo`` is written only if the row lands on that
        target, and NULL otherwise. Plain values are written whichever target is selected.

        Returns True if the row was updated, False if the current status
        did not allow any of the transitions.
        """
        cls = type(self)
        session = get_current_session()

        cases = []
        all_valid_from = []
        selected_by: dict[JobStatus, ColumnElement[bool]] = {}
        consumed: set[JobStatus] = set()
        billable: set[JobStatus] = set()
        for target in targets:
            valid_from = set(JobStatus.sources_for(target)) - consumed
            if valid_from:
                selects_target = cls.status.in_([s.value for s in valid_from])
                cases.append((selects_target, target.value))
                selected_by[target] = selects_target
                all_valid_from.extend(s.value for s in valid_from)
                consumed |= valid_from
                if target not in WORKING_STATUSES:
                    billable |= valid_from & WORKING_STATUSES

        resolved: dict[str, Any] = {}
        for key, value in values.items():
            if not isinstance(value, OnlyWhenTransitioningTo):
                resolved[key] = value
            elif value.target not in targets:
                raise ValueError(f"{key} is bound to {value.target}, which this transition does not offer")
            elif value.target in selected_by:
                resolved[key] = case((selected_by[value.target], value.value), else_=None)
            else:
                # An earlier target claimed every source state that could have reached this one,
                # so no row can land on it.
                resolved[key] = None

        row = session.execute(
            update(cls)
            .where(cls.id == self.id, cls.status.in_(all_valid_from))
            .values(status=case(*cases), **cls._bill_worked_from(billable), **resolved)
            .returning(cls)
        ).scalar_one_or_none()
        if row is not None:
            for col in cls.__table__.columns:
                setattr(self, col.key, getattr(row, col.key))
            return True
        LOG.warning("Transition to %s failed for job %s (in-memory status: '%s')", [t.value for t in targets], self.id, self.status)
        return False

    def claim(self) -> bool:
        return self._transition(JobStatus.CLAIMED, claimed_at=datetime.now(UTC))

    def mark_running(self) -> bool:
        # A resumed run passes through RUNNING again, and started_at anchors the run's begin
        # time, so it must not be restamped.
        return self._transition(
            JobStatus.RUNNING,
            started_at=func.coalesce(type(self).started_at, datetime.now(UTC)),
        )

    def park(self, resume_state: dict[str, Any]) -> bool:
        """Stop the run and persist its checkpoint in one statement.

        Which parked status it lands in follows from the request that stopped it, so the job
        never has to be told which intent it is serving: an interrupted run is queued for the
        next poll, a paused one waits to be asked back.
        """
        return self._transition(JobStatus.INTERRUPTED, JobStatus.PAUSED, resume_state=resume_state)

    def request_pause(self) -> bool:
        """Ask a running job to stop at a work-key boundary and stay stopped.

        Refused for a job key with no cooperative machinery behind it, since nothing would ever
        park the row: it would read as pausing forever, with no process looking at the request.
        """
        if self.job_key not in PAUSABLE_JOB_KEYS:
            LOG.warning("Job %s (%s) cannot be paused", self.id, self.job_key)
            return False
        return self._transition(JobStatus.PAUSE_REQUESTED)

    def request_resume(self) -> bool:
        """Hand a paused job back to the poll."""
        return self._transition(JobStatus.RESUME_REQUESTED)

    def mark_canceled(self) -> bool:
        return self._transition(JobStatus.CANCELED, completed_at=datetime.now(UTC))

    def request_cancel(self) -> bool:
        return self._transition(JobStatus.CANCEL_REQUESTED)

    def mark_completed(self) -> bool:
        return self._transition(JobStatus.COMPLETED, completed_at=datetime.now(UTC))

    def mark_failed(self, error_message: str) -> bool:
        """Mark as ERROR, or CANCELED if a cancellation was requested concurrently.

        The message is written only on the ERROR branch.
        """
        transitioned = self._transition(
            JobStatus.ERROR,
            JobStatus.CANCELED,
            completed_at=datetime.now(UTC),
            error_message=OnlyWhenTransitioningTo(JobStatus.ERROR, error_message),
        )
        if transitioned and self.status == JobStatus.CANCELED:
            # An out-of-memory kill and a cancel escalated to SIGKILL are the same exit code, so
            # this is the only record of which one a support request is looking at.
            LOG.info("Job %s settled as canceled, so it does not carry this failure: %s", self.id, error_message)
        return transitioned
