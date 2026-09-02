"""Subprocess entry point for the scheduler's `testgen exec-job <id>` command.

Owns the end-to-end lifecycle of a single claimed job: dispatch to its handler,
settle the JobExecution, and fire final callbacks. A job that stops at a
checkpoint is recorded as interrupted instead, which is not terminal and fires
no callbacks. Concrete wiring (which handler runs for which job_key, which
callbacks fire after termination) lives in `job_registry.py`.
"""

import logging
import sys
from uuid import UUID

from testgen.commands.job_registry import JOB_DISPATCH, run_final_callbacks
from testgen.common.job_context import JobContext, job_context
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.pausable_job import JobParked
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")

POLL_INTERVAL = 2


def exec_job(job_execution_id: UUID) -> None:
    """Execute a queued job. Called as a subprocess by the scheduler.

    Owns the full lifecycle: mark_running -> dispatch -> mark_completed/mark_failed,
    or park when the handler stopped at a checkpoint.
    Only exits non-zero for truly unrecoverable failures (DB unreachable, record not found).
    """
    try:
        with database_session():
            job_exec = JobExecution.get(job_execution_id)
            if not job_exec:
                LOG.error("Job execution %s not found", job_execution_id)
                sys.exit(1)

            job_config = JOB_DISPATCH.get(job_exec.job_key)
            if not job_config:
                job_exec.mark_failed(f"Unknown job key: {job_exec.job_key}")
                return

            if not job_exec.mark_running():
                LOG.info("Job %s could not transition to running (likely canceled), skipping", job_execution_id)
                return

        try:
            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                job_context.set(JobContext(job_id=job_execution_id, source=job_exec.source))
                job_config.handler(**job_exec.kwargs)

            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                transitioned = job_exec.mark_completed()
            if transitioned:
                run_final_callbacks(job_exec)
        except JobParked as interrupted:
            # Publishing the status here rather than where the stop was detected is deliberate:
            # by now the handler has finished unwinding, so a run this hands to the next claimer
            # is one no process still holds. The checkpoint is already durable. Which parked
            # status it lands in follows from what asked it to stop, so a pause is held rather
            # than handed on.
            # No final callbacks: the run has not settled, so nothing should notify on it or
            # roll up its scores. Returning exits 0, which the scheduler reads as a clean stop.
            LOG.info("Job %s stopped in step '%s'", job_execution_id, interrupted.step)
            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                job_exec.park(interrupted.resume_state)
        except Exception as e:
            LOG.exception("Job %s failed", job_execution_id)
            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                transitioned = job_exec.mark_failed(get_exception_message(e))
            if transitioned:
                run_final_callbacks(job_exec)

    except Exception:
        LOG.exception("Unrecoverable error executing job %s", job_execution_id)
        sys.exit(1)
