"""Process-scoped job context, set by exec_job before dispatching."""

import contextvars
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class JobContext:
    job_id: UUID | None = None
    source: str = "CLI"


job_context: contextvars.ContextVar[JobContext] = contextvars.ContextVar("job_context", default=JobContext())
