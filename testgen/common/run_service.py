from collections.abc import Callable
from typing import Any
from uuid import UUID

from testgen.common.audit.runs import RunOperation, record_run
from testgen.common.enums import JobSource
from testgen.common.models.job_execution import JobExecution


def launch_run(
    job_key: str,
    kwargs: dict[str, Any],
    source: JobSource,
    project_code: str,
    job_schedule_id: UUID | None = None,
    external_url: str | None = None,
    caller_metadata: dict[str, Any] | None = None,
) -> JobExecution:
    """Queue a job, recording its launch when it is a profiling or test run. Caller controls the commit.

    Arguments as in ``JobExecution.submit``.
    """
    job = JobExecution.submit(
        job_key=job_key,
        kwargs=kwargs,
        source=source,
        project_code=project_code,
        job_schedule_id=job_schedule_id,
        external_url=external_url,
        caller_metadata=caller_metadata,
    )
    record_run(RunOperation.LAUNCHED, job)
    return job


_REQUESTS: dict[RunOperation, Callable[[JobExecution], bool]] = {
    RunOperation.CANCELED: lambda job: job.request_cancel(),
    RunOperation.PAUSED: lambda job: job.request_pause(),
    RunOperation.RESUMED: lambda job: job.request_resume(),
}


def request_run_transition(job: JobExecution, operation: RunOperation) -> bool:
    """Ask ``job`` to cancel, pause, or resume, recording the request when it is a profiling or test run.

    A request that repeats one already made is accepted but not recorded again.

    :returns: whether the job accepted the request.
    """
    previous_status = job.status
    if not _REQUESTS[operation](job):
        return False
    record_run(operation, job, previous_status)
    return True
