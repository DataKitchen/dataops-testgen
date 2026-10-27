"""Process-scoped job context, set by exec_job before dispatching."""

import contextvars
from dataclasses import dataclass, field
from uuid import UUID

from testgen.common.enums import JobSource


@dataclass(frozen=True)
class JobContext:
    job_id: UUID | None = None
    source: JobSource = JobSource.cli
    # Values the job's handler measured that only its own process knows, kept for the final
    # callbacks that report on the run.
    measurements: dict[str, float] = field(default_factory=dict)


job_context: contextvars.ContextVar[JobContext] = contextvars.ContextVar("job_context", default=JobContext())


def record_measurement(name: str, value: float) -> None:
    """Keep ``value`` for the final callbacks of the job this process is running, if it runs one."""
    context = job_context.get()
    if context.job_id is not None:
        context.measurements[name] = value


def measurements_for(job_id: UUID) -> dict[str, float]:
    """What this process measured while running ``job_id``, or nothing if it ran a different job."""
    context = job_context.get()
    return dict(context.measurements) if context.job_id == job_id else {}
