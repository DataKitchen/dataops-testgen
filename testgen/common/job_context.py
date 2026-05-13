"""Process-scoped job context, set by exec_job before dispatching."""

import contextvars
from dataclasses import dataclass
from uuid import UUID

from testgen.common.enums import JobSource


@dataclass(frozen=True)
class JobContext:
    job_id: UUID | None = None
    source: JobSource = JobSource.cli


job_context: contextvars.ContextVar[JobContext] = contextvars.ContextVar("job_context", default=JobContext())
