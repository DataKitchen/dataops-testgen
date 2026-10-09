"""Wiring between the JobExecution engine and the concrete job handlers.

Two registries keyed by `job_key`:
  - `JOB_DISPATCH`: maps a job to its `JobConfig` (handler + per-job metadata).
    `exec_job` and the scheduler resolve this.
  - `JOB_FINAL_CALLBACKS`: maps a job to post-terminal-transition callbacks
    (notifications, follow-up job submissions). `run_final_callbacks` iterates.

`run_final_callbacks` is invoked wherever a JE reaches a terminal status:
`exec_job` after mark_completed/mark_failed, `_proc_wrapper`'s nonzero-exit
safety net, and `_handle_cancellation`'s no-subprocess branch.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select

from testgen.commands.run_catalog_refresh import run_catalog_refresh
from testgen.commands.run_data_cleanup import run_data_cleanup
from testgen.commands.run_profiling import report_profiling_run, run_profiling
from testgen.commands.run_recalculate_project_scores import run_recalculate_project_scores
from testgen.commands.run_refresh_score_cards_results import run_recalculate_score_card
from testgen.commands.run_rollup_scores import run_refresh_run_scores
from testgen.commands.run_score_update import run_score_update
from testgen.commands.run_test_execution import run_test_execution
from testgen.commands.test_generation import run_monitor_generation, run_test_generation
from testgen.common.enums import JobKey, JobSource, JobStatus
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_run import TestRun
from testgen.common.notifications.monitor_run import send_monitor_notifications
from testgen.common.notifications.profiling_run import send_profiling_run_notifications
from testgen.common.notifications.test_run import send_test_run_notifications

LOG = logging.getLogger("testgen")

FinalCallback = Callable[[JobExecution], None]


@dataclass(frozen=True)
class JobConfig:
    """Per-job-key registration metadata.

    `scheduler_source` is the value the scheduler tags `JobExecution.source`
    with when it spawns this job key — ``"scheduler"`` for user-facing jobs,
    ``"system"`` for system-internal jobs (e.g., retention cleanup). Read
    only by the scheduler; direct `JobExecution.submit(source=...)` callers
    (UI, follow-up enqueues, CLI) set their own source independently and do
    not consult this field.
    """

    handler: Callable
    scheduler_source: JobSource = JobSource.scheduler


JOB_DISPATCH: dict[JobKey, JobConfig] = {
    JobKey.run_profile:                JobConfig(handler=run_profiling),
    JobKey.refresh_data_catalog:       JobConfig(handler=run_catalog_refresh),
    JobKey.run_tests:                  JobConfig(handler=run_test_execution),
    JobKey.run_monitors:               JobConfig(handler=run_test_execution),
    JobKey.run_test_generation:        JobConfig(handler=run_test_generation),
    JobKey.run_monitor_generation:     JobConfig(handler=run_monitor_generation, scheduler_source=JobSource.system),
    JobKey.run_score_update:           JobConfig(handler=run_score_update, scheduler_source=JobSource.system),
    JobKey.recalculate_project_scores: JobConfig(handler=run_recalculate_project_scores, scheduler_source=JobSource.system),
    JobKey.run_data_cleanup:           JobConfig(handler=run_data_cleanup, scheduler_source=JobSource.system),
    JobKey.refresh_run_scores:         JobConfig(handler=run_refresh_run_scores, scheduler_source=JobSource.system),
    JobKey.recalculate_score_card:     JobConfig(handler=run_recalculate_score_card, scheduler_source=JobSource.system),
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
            select(ProfilingRun).where(ProfilingRun.id == job_exec.id)
        ).first()
        if not profiling_run:
            LOG.warning("No profiling_run found for job %s; skipping notification", job_exec.id)
            return
        send_profiling_run_notifications(profiling_run)


def _notify_test_run(job_exec: JobExecution) -> None:
    with database_session() as session:
        test_run = session.scalars(select(TestRun).where(TestRun.id == job_exec.id)).first()
        if not test_run:
            LOG.warning("No test_run found for job %s; skipping notification", job_exec.id)
            return
        if SuiteVersion.is_draft(test_run.version_id):
            LOG.info("Run %s verified a draft; no notification sent", job_exec.id)
            return
        send_test_run_notifications(test_run)


def _notify_monitor_run(job_exec: JobExecution) -> None:
    with database_session() as session:
        test_run = session.scalars(select(TestRun).where(TestRun.id == job_exec.id)).first()
        if not test_run:
            LOG.warning("No test_run found for job %s; skipping monitor notification", job_exec.id)
            return
        send_monitor_notifications(test_run)


def _enqueue_score_update(job_exec: JobExecution) -> None:
    """Enqueue a score rollup for the just-completed run.

    A run that verified a draft is skipped: the rollup writes a score-history entry per
    definition per category timestamped at that run and drives the score-drop notifications,
    neither of which a preview of an agreement not yet in force should cause.
    """
    if job_exec.status != JobStatus.COMPLETED:
        return

    with database_session() as session:
        if job_exec.job_key == JobKey.run_tests:
            test_run = session.scalars(select(TestRun).where(TestRun.id == job_exec.id)).first()
            if test_run and SuiteVersion.is_draft(test_run.version_id):
                LOG.info("Run %s verified a draft; no score rollup enqueued", job_exec.id)
                return
        JobExecution.submit(
            job_key=JobKey.run_score_update,
            kwargs={
                "parent_job_id": str(job_exec.id),
                "parent_job_key": job_exec.job_key,
            },
            source=JobSource.system,
            project_code=job_exec.project_code,
        )


JOB_FINAL_CALLBACKS: dict[JobKey, list[FinalCallback]] = {
    JobKey.run_profile: [_notify_profiling_run, report_profiling_run, _enqueue_score_update],
    JobKey.run_tests: [_notify_test_run, _enqueue_score_update],
    JobKey.run_monitors: [_notify_monitor_run],
}
