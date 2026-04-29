"""Wiring between the JobExecution engine and the concrete job handlers.

Two registries keyed by `job_key`:
  - `JOB_DISPATCH`: maps a job to its handler (`exec_job` resolves this).
  - `JOB_FINAL_CALLBACKS`: maps a job to post-terminal-transition callbacks
    (notifications, follow-up job submissions). `run_final_callbacks` iterates.

`run_final_callbacks` is invoked wherever a JE reaches a terminal status:
`exec_job` after mark_completed/mark_interrupted, `_proc_wrapper`'s nonzero-exit
safety net, and `_handle_cancellation`'s no-subprocess branch.
"""

import logging
from collections.abc import Callable

from sqlalchemy import select

from testgen.commands.run_profiling import run_profiling
from testgen.commands.run_recalculate_project_scores import run_recalculate_project_scores
from testgen.commands.run_score_update import run_score_update
from testgen.commands.run_test_execution import run_test_execution
from testgen.commands.test_generation import run_test_generation
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.test_run import TestRun
from testgen.common.notifications.monitor_run import send_monitor_notifications
from testgen.common.notifications.profiling_run import send_profiling_run_notifications
from testgen.common.notifications.test_run import send_test_run_notifications

LOG = logging.getLogger("testgen")

FinalCallback = Callable[[JobExecution], None]

JOB_DISPATCH: dict[str, Callable] = {
    "run-profile": run_profiling,
    "run-tests": run_test_execution,
    "run-monitors": run_test_execution,
    "run-test-generation": run_test_generation,
    "run-score-update": run_score_update,
    "recalculate-project-scores": run_recalculate_project_scores,
}


def run_final_callbacks(job_exec: JobExecution) -> None:
    """Fire registered callbacks for a job that just settled into a final status.

    Callbacks are best-effort: failures are logged and do not propagate. The
    job execution is already in its final state regardless of callback outcomes.
    """
    for callback in JOB_FINAL_CALLBACKS.get(job_exec.job_key, []):
        try:
            callback(job_exec)
        except Exception:
            LOG.exception("Callback %s failed for job %s", callback.__name__, job_exec.id)


def _notify_profiling_run(job_exec: JobExecution) -> None:
    with database_session() as session:
        profiling_run = session.scalars(
            select(ProfilingRun).where(ProfilingRun.job_execution_id == job_exec.id)
        ).first()
        if not profiling_run:
            LOG.warning("No profiling_run found for job %s; skipping notification", job_exec.id)
            return
        send_profiling_run_notifications(profiling_run)


def _notify_test_run(job_exec: JobExecution) -> None:
    with database_session() as session:
        test_run = session.scalars(select(TestRun).where(TestRun.job_execution_id == job_exec.id)).first()
        if not test_run:
            LOG.warning("No test_run found for job %s; skipping notification", job_exec.id)
            return
        send_test_run_notifications(test_run)


def _notify_monitor_run(job_exec: JobExecution) -> None:
    with database_session() as session:
        test_run = session.scalars(select(TestRun).where(TestRun.job_execution_id == job_exec.id)).first()
        if not test_run:
            LOG.warning("No test_run found for job %s; skipping monitor notification", job_exec.id)
            return
        send_monitor_notifications(test_run)


def _enqueue_score_update(job_exec: JobExecution) -> None:
    """Enqueue a score rollup for the just-completed run."""
    if job_exec.status != JobStatus.COMPLETED:
        return

    with database_session():
        JobExecution.submit(
            job_key="run-score-update",
            kwargs={
                "parent_job_id": str(job_exec.id),
                "parent_job_key": job_exec.job_key,
            },
            source="system",
            project_code=job_exec.project_code,
        )


JOB_FINAL_CALLBACKS: dict[str, list[FinalCallback]] = {
    "run-profile": [_notify_profiling_run, _enqueue_score_update],
    "run-tests": [_notify_test_run, _enqueue_score_update],
    "run-monitors": [_notify_monitor_run],
}
