import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

from sqlalchemy import Column, Float, String, Text, case, delete, func, literal, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ColumnElement

from testgen.common.enums import PAUSABLE_JOB_KEYS, WORKING_STATUSES, JobSource, JobStatus
from testgen.common.models import Base, database_session, get_current_session

LOG = logging.getLogger("testgen")


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

    @classmethod
    def submit(
        cls,
        job_key: str,
        kwargs: dict[str, Any],
        source: JobSource,
        project_code: str,
        job_schedule_id: UUID | None = None,
    ) -> Self:
        """Create a pending job execution row. Caller controls the commit."""
        session = get_current_session()
        job_exec = cls(
            job_key=job_key,
            kwargs=kwargs,
            source=source,
            project_code=project_code,
            job_schedule_id=job_schedule_id,
        )
        session.add(job_exec)
        session.flush([job_exec])
        LOG.info("Submitted job execution %s: job_key=%s, source=%s", job_exec.id, job_key, source)
        return job_exec

    # What a poll acts on: everything it can start, plus the one status it settles instead.
    ACTIONABLE_STATUSES: ClassVar[tuple[JobStatus, ...]] = (*JobStatus.claimable(), JobStatus.CANCEL_REQUESTED)

    @classmethod
    def claim_actionable(cls, limit: int = 5) -> list[Self]:
        """Claim startable rows and fetch cancel_requested rows in one query.

        PENDING (fresh start), INTERRUPTED (a shutdown stopped it) and RESUME_REQUESTED (a resume
        was requested) all transition to claimed; the resume state on the row is what tells
        a fresh start from a continuation, so the dispatch path is identical for all three.
        Cancel_requested rows are returned as-is for the scheduler to act on.
        Uses SELECT FOR UPDATE SKIP LOCKED to prevent concurrent processing. Every returned
        row is claimed or cancel_requested.
        """
        session = get_current_session()
        query = (
            select(cls)
            .where(cls.status.in_(cls.ACTIONABLE_STATUSES))
            .order_by(cls.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        rows = session.scalars(query).all()
        actionable: list[Self] = []
        claimed = 0
        for row in rows:
            if row.status in JobStatus.claimable():
                if not row.claim():
                    continue
                claimed += 1
            actionable.append(row)
        if claimed:
            LOG.info("Claimed %d job execution(s)", claimed)
        return actionable

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

        Returns True if the row was updated, False if the current status
        did not allow any of the transitions.
        """
        cls = type(self)
        session = get_current_session()

        cases = []
        all_valid_from = []
        consumed: set[JobStatus] = set()
        billable: set[JobStatus] = set()
        for target in targets:
            valid_from = set(JobStatus.sources_for(target)) - consumed
            if valid_from:
                cases.append((cls.status.in_([s.value for s in valid_from]), target.value))
                all_valid_from.extend(s.value for s in valid_from)
                consumed |= valid_from
                if target not in WORKING_STATUSES:
                    billable |= valid_from & WORKING_STATUSES

        row = session.execute(
            update(cls)
            .where(cls.id == self.id, cls.status.in_(all_valid_from))
            .values(status=case(*cases), **cls._bill_worked_from(billable), **values)
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
        """Mark as ERROR, or CANCELED if a cancellation was requested concurrently."""
        return self._transition(
            JobStatus.ERROR, JobStatus.CANCELED, completed_at=datetime.now(UTC), error_message=error_message
        )
