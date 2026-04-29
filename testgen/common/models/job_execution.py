import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, case, func, select, text, update
from sqlalchemy.dialects import postgresql

from testgen.common.models import Base, get_current_session

LOG = logging.getLogger("testgen")


class JobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"


_VALID_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.CLAIMED, JobStatus.CANCEL_REQUESTED}),
    JobStatus.CLAIMED: frozenset({JobStatus.RUNNING, JobStatus.ERROR, JobStatus.CANCEL_REQUESTED}),
    JobStatus.RUNNING: frozenset({JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCEL_REQUESTED}),
    JobStatus.CANCEL_REQUESTED: frozenset({JobStatus.CANCELED}),
}


class JobExecution(Base):
    __tablename__ = "job_executions"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_key: str = Column(String(100), nullable=False)
    # args and kwargs are internal dispatch details passed to the job handler.
    # Do not query or filter on them — external code should not depend on their structure.
    args: list[Any] = Column(postgresql.JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    kwargs: dict[str, Any] = Column(postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    source: str = Column(String(20), nullable=False)
    status: str = Column(String(20), nullable=False, default=JobStatus.PENDING, server_default=text("'pending'"))
    project_code: str = Column(String(30), nullable=False)
    job_schedule_id: UUID | None = Column(postgresql.UUID(as_uuid=True), nullable=True)
    error_message: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    claimed_at: datetime | None = Column(postgresql.TIMESTAMP(timezone=True), nullable=True)
    started_at: datetime | None = Column(postgresql.TIMESTAMP(timezone=True), nullable=True)
    completed_at: datetime | None = Column(postgresql.TIMESTAMP(timezone=True), nullable=True)

    @classmethod
    def submit(
        cls,
        job_key: str,
        kwargs: dict[str, Any],
        source: str,
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

    @classmethod
    def claim_actionable(cls, limit: int = 5) -> list[Self]:
        """Claim pending rows and fetch cancel_requested rows in one query.

        Pending rows are transitioned to claimed. Cancel_requested rows
        are returned as-is for the scheduler to act on.
        Uses SELECT FOR UPDATE SKIP LOCKED to prevent concurrent processing.
        """
        session = get_current_session()
        query = (
            select(cls)
            .where(cls.status.in_([JobStatus.PENDING, JobStatus.CANCEL_REQUESTED]))
            .order_by(cls.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        rows = session.scalars(query).all()
        now = datetime.now(UTC)
        claimed = 0
        for row in rows:
            if row.status == JobStatus.PENDING:
                row.status = JobStatus.CLAIMED.value
                row.claimed_at = now
                claimed += 1
        if claimed:
            LOG.info("Claimed %d pending job execution(s)", claimed)
        return rows

    @classmethod
    def find_stale(cls) -> list[Self]:
        """Return job executions left in non-terminal states from a previous process."""
        session = get_current_session()
        return list(session.scalars(
            select(cls).where(
                cls.status.in_([JobStatus.PENDING, JobStatus.CLAIMED, JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED])
            )
        ).all())

    @classmethod
    def get(cls, execution_id: UUID) -> Self | None:
        """Fetch a job execution by primary key."""
        session = get_current_session()
        return session.get(cls, execution_id)

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
        for target in targets:
            valid_from = {s for s, t in _VALID_TRANSITIONS.items() if target in t} - consumed
            if valid_from:
                cases.append((cls.status.in_([s.value for s in valid_from]), target.value))
                all_valid_from.extend(s.value for s in valid_from)
                consumed |= valid_from

        row = session.execute(
            update(cls)
            .where(cls.id == self.id, cls.status.in_(all_valid_from))
            .values(status=case(*cases), **values)
            .returning(cls)
        ).scalar_one_or_none()
        if row is not None:
            for col in cls.__table__.columns:
                setattr(self, col.key, getattr(row, col.key))
            return True
        LOG.warning("Transition to %s failed for job %s (in-memory status: '%s')", [t.value for t in targets], self.id, self.status)
        return False

    def mark_running(self) -> bool:
        return self._transition(JobStatus.RUNNING, started_at=datetime.now(UTC))

    def mark_canceled(self) -> bool:
        return self._transition(JobStatus.CANCELED, completed_at=datetime.now(UTC))

    def request_cancel(self) -> bool:
        return self._transition(JobStatus.CANCEL_REQUESTED)

    def mark_completed(self) -> bool:
        return self._transition(JobStatus.COMPLETED, completed_at=datetime.now(UTC))

    def mark_interrupted(self, error_message: str) -> bool:
        """Mark as ERROR, or CANCELED if a cancellation was requested concurrently."""
        return self._transition(JobStatus.ERROR, JobStatus.CANCELED, completed_at=datetime.now(UTC), error_message=error_message)
