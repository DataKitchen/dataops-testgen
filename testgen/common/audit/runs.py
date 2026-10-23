from collections.abc import Collection
from enum import StrEnum

from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.recorder import record
from testgen.common.enums import JobKey
from testgen.common.models.job_execution import JobExecution


class RunOperation(StrEnum):
    LAUNCHED = "launched"
    PAUSED = "paused"
    RESUMED = "resumed"
    CANCELED = "canceled"
    DELETED = "deleted"


_TARGET_TYPES: dict[str, AuditTargetType] = {
    JobKey.run_profile: AuditTargetType.PROFILING_RUN,
    JobKey.run_tests: AuditTargetType.TEST_RUN,
}

_ACTIONS: dict[tuple[str, RunOperation], AuditAction] = {
    (JobKey.run_profile, RunOperation.LAUNCHED): AuditAction.PROFILING_RUN_LAUNCHED,
    (JobKey.run_profile, RunOperation.PAUSED): AuditAction.PROFILING_RUN_PAUSED,
    (JobKey.run_profile, RunOperation.RESUMED): AuditAction.PROFILING_RUN_RESUMED,
    (JobKey.run_profile, RunOperation.CANCELED): AuditAction.PROFILING_RUN_CANCELED,
    (JobKey.run_profile, RunOperation.DELETED): AuditAction.PROFILING_RUN_DELETED,
    (JobKey.run_tests, RunOperation.LAUNCHED): AuditAction.TEST_RUN_LAUNCHED,
    (JobKey.run_tests, RunOperation.CANCELED): AuditAction.TEST_RUN_CANCELED,
    (JobKey.run_tests, RunOperation.DELETED): AuditAction.TEST_RUN_DELETED,
}


def record_run(operation: RunOperation, job: JobExecution, previous_status: str | None = None) -> None:
    """Record ``operation`` on the run ``job`` executes. A job that is not a profiling or test run records nothing.

    :param previous_status: the run's status before a requested transition. When the run is still in it, the request
        repeated one already made, and nothing is recorded.
    """
    if previous_status is not None and job.status == previous_status:
        return
    record_runs(operation, job.job_key, job.project_code, [job.id])


def record_runs(operation: RunOperation, job_key: str, project_code: str, run_ids: Collection[object]) -> None:
    """Record ``operation`` on several runs of one kind, as a single record.

    :param job_key: the kind of job the runs are. Nothing is recorded unless it is a profiling or test run.
    :param run_ids: ids of the runs, which are their job execution ids. Nothing is recorded when it is empty.
    """
    if not run_ids or (action := _ACTIONS.get((job_key, operation))) is None:
        return
    record(action, project_code=project_code, target_type=_TARGET_TYPES[job_key], targets=run_ids)
