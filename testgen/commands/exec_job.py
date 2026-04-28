"""Subprocess entry point for the scheduler's `testgen exec-job <id>` command.

Owns the end-to-end lifecycle of a single claimed job: dispatch to its handler,
transition the JobExecution to a terminal state, and fire final callbacks.
Concrete wiring (which handler runs for which job_key, which callbacks fire
after termination) lives in `job_registry.py`.
"""

import logging
import sys
from uuid import UUID

from testgen.commands.job_registry import JOB_DISPATCH, run_final_callbacks
from testgen.common.job_context import JobContext, job_context
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")

FINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCELED})
POLL_INTERVAL = 2


def exec_job(job_execution_id: UUID) -> None:
    """Execute a queued job. Called as a subprocess by the scheduler.

    Owns the full lifecycle: mark_running -> dispatch -> mark_completed/mark_interrupted.
    Only exits non-zero for truly unrecoverable failures (DB unreachable, record not found).
    """
    try:
        with database_session():
            job_exec = JobExecution.get(job_execution_id)
            if not job_exec:
                LOG.error("Job execution %s not found", job_execution_id)
                sys.exit(1)

            handler = JOB_DISPATCH.get(job_exec.job_key)
            if not handler:
                job_exec.mark_interrupted(f"Unknown job key: {job_exec.job_key}")
                return

            if not job_exec.mark_running():
                LOG.info("Job %s could not transition to running (likely canceled), skipping", job_execution_id)
                return

        try:
            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                job_context.set(JobContext(job_id=job_execution_id, source=job_exec.source))
                handler(**job_exec.kwargs)

            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                transitioned = job_exec.mark_completed()
            if transitioned:
                run_final_callbacks(job_exec)
        except Exception as e:
            LOG.exception("Job %s failed", job_execution_id)
            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                transitioned = job_exec.mark_interrupted(get_exception_message(e))
            if transitioned:
                run_final_callbacks(job_exec)

    except Exception:
        LOG.exception("Unrecoverable error executing job %s", job_execution_id)
        sys.exit(1)
