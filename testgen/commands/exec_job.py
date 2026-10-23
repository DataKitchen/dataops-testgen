"""Subprocess entry point for the scheduler's `testgen exec-job <id>` command.

Owns the end-to-end lifecycle of a single claimed job: dispatch to its handler,
then settle the JobExecution and fire final callbacks through `finalize`. A job
that stops at a checkpoint is parked instead, which is not terminal and fires no
callbacks. Concrete wiring (which handler runs for which job_key, which callbacks
fire after termination) lives in `job_registry.py`.
"""

import logging
import os
import signal
import sys
from collections.abc import Callable
from functools import partial
from uuid import UUID

from testgen.commands.job_registry import JOB_DISPATCH, finalize
from testgen.common.database.flavor.duckdb_flavor_service import sweep_stale_spill_directories
from testgen.common.enums import JobStatus
from testgen.common.job_context import JobContext, job_context
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.pausable_job import JobParked
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")


def exec_job(job_execution_id: UUID) -> None:
    """Execute a queued job. Called as a subprocess by the scheduler.

    Owns the full lifecycle: mark_running -> dispatch -> settle, parking when the handler stopped
    at a checkpoint. Every exit settles the job itself, as canceled when a cancellation was
    requested on the way. Only exits non-zero for truly unrecoverable failures (DB unreachable,
    record not found).
    """
    # Every module shares one temp directory and one pid namespace, so collecting here reaches
    # spill the UI and server processes left behind too. The walk stays off the paths they serve.
    sweep_stale_spill_directories()

    try:
        with database_session():
            job_exec = JobExecution.get(job_execution_id)
            if not job_exec:
                LOG.error("Job execution %s not found", job_execution_id)
                sys.exit(1)
            job_config = JOB_DISPATCH.get(job_exec.job_key)

        if not job_config:
            _settle(job_execution_id, lambda job: job.mark_failed(f"Unknown job key: {job.job_key}"))
            return

        started, job_exec = _settle(job_execution_id, lambda job: job.mark_running())
        if not started:
            LOG.info("Job %s could not transition to running, skipping", job_execution_id)
            return
        if job_exec.status != JobStatus.RUNNING:
            LOG.info("Job %s was canceled before it started", job_execution_id)
            return

        # Held until the job settles: its final callbacks read what the handler measured.
        context_token = job_context.set(JobContext(job_id=job_execution_id, source=job_exec.source))
        try:
            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                job_config.handler(**job_exec.kwargs)
            _settle(job_execution_id, lambda job: job.mark_completed())
        except JobParked as interrupted:
            # Publishing the status here rather than where the stop was detected is deliberate:
            # by now the handler has finished unwinding, so a run this hands to the next claimer
            # is one no process still holds. The checkpoint is already durable. Which parked
            # status it lands in follows from what asked it to stop, so a pause is held rather
            # than handed on, and a cancel that arrived meanwhile ends the run.
            # Returning exits 0, which the scheduler reads as a clean stop.
            LOG.info("Job %s stopped in step '%s'", job_execution_id, interrupted.step)
            resume_state = interrupted.resume_state
            _settle(job_execution_id, lambda job: job.park(resume_state))
        except Exception as e:
            LOG.exception("Job %s failed", job_execution_id)
            message = get_exception_message(e)
            _settle(job_execution_id, lambda job: job.mark_failed(message))
        finally:
            job_context.reset(context_token)

    except Exception:
        LOG.exception("Unrecoverable error executing job %s", job_execution_id)
        sys.exit(1)


def _settle(job_execution_id: UUID, transition: Callable[[JobExecution], bool]) -> tuple[bool, JobExecution]:
    """Reload the job and ``finalize`` it with ``transition``, holding any terminate signal meanwhile.

    The job is read afresh because a handler that raised has rolled back its session, which
    expires every instance it loaded. A terminate held here is delivered afterwards only if the
    job is still running; one that ended or parked exits normally, so its exit hooks run and send
    what its final callbacks queued. Killed by the signal, the process would skip them, and nothing
    reports the run again: its row is already final.

    :returns: Whether ``transition`` moved the job, and the job as it stands after.
    """
    with database_session():
        job_exec = JobExecution.get(job_execution_id)
    received: list[int] = []
    previous = signal.signal(signal.SIGTERM, lambda signum, _frame: received.append(signum))
    try:
        settled = finalize(job_exec, partial(transition, job_exec))
    finally:
        signal.signal(signal.SIGTERM, previous)
    if received and job_exec.status == JobStatus.RUNNING:
        os.kill(os.getpid(), signal.SIGTERM)
    return settled, job_exec
