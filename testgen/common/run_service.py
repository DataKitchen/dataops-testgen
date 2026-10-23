from typing import Any

from testgen.common.audit.runs import RunOperation, record_run
from testgen.common.enums import JobSource
from testgen.common.models.job_execution import JobExecution


def launch_run(job_key: str, kwargs: dict[str, Any], source: JobSource, project_code: str, **options: Any) -> JobExecution:
    """Queue a job, recording its launch when it is a profiling or test run. Caller controls the commit.

    Arguments as in ``JobExecution.submit``; ``options`` are its optional ones.
    """
    job = JobExecution.submit(job_key=job_key, kwargs=kwargs, source=source, project_code=project_code, **options)
    record_run(RunOperation.LAUNCHED, job)
    return job


_REQUESTS = {
    RunOperation.CANCELED: "request_cancel",
    RunOperation.PAUSED: "request_pause",
    RunOperation.RESUMED: "request_resume",
}


def request_run_transition(job: JobExecution, operation: RunOperation) -> bool:
    """Ask ``job`` to cancel, pause, or resume, recording the request when it is a profiling or test run.

    A request that repeats one already made is accepted but not recorded again.

    :returns: whether the job accepted the request.
    """
    previous_status = job.status
    if not getattr(job, _REQUESTS[operation])():
        return False
    record_run(operation, job, previous_status)
    return True
