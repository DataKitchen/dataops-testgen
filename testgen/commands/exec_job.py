"""Central job dispatch: exec_job() for subprocess execution, submit_and_wait() for CLI wrappers."""

import logging
import sys
import time
from collections.abc import Callable
from uuid import UUID

from testgen.commands.run_profiling import run_profiling
from testgen.commands.run_test_execution import run_test_execution
from testgen.commands.test_generation import run_test_generation
from testgen.common.job_context import JobContext, job_context
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")

TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCELED})
POLL_INTERVAL = 2

JOB_DISPATCH: dict[str, Callable] = {
    "run-profile": run_profiling,
    "run-tests": run_test_execution,
    "run-monitors": run_test_execution,
    "run-test-generation": run_test_generation,
}


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
                job_context.set(JobContext(job_id=job_execution_id, source=job_exec.source.upper()))
                handler(**job_exec.kwargs)

            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                job_exec.mark_completed()
        except Exception as e:
            LOG.exception("Job %s failed", job_execution_id)
            with database_session():
                job_exec = JobExecution.get(job_execution_id)
                job_exec.mark_interrupted(get_exception_message(e))

    except Exception:
        LOG.exception("Unrecoverable error executing job %s", job_execution_id)
        sys.exit(1)


def submit_and_wait(
    job_key: str,
    kwargs: dict,
    project_code: str,
    no_wait: bool = False,
) -> None:
    """Submit a job to the queue and optionally wait for completion.

    Manages its own session lifecycle — callers must NOT wrap this in @with_database_session.
    The submit is committed in its own session so the scheduler can see the row immediately.
    """
    import click

    with database_session():
        job_exec = JobExecution.submit(
            job_key=job_key,
            kwargs=kwargs,
            source="cli",
            project_code=project_code,
        )
        job_id = job_exec.id

    click.echo(f"Submitted job {job_id} ({job_key})")

    if no_wait:
        return

    click.echo("Waiting for completion...")
    while True:
        time.sleep(POLL_INTERVAL)
        with database_session():
            job_exec = JobExecution.get(job_id)
            if job_exec and job_exec.status in TERMINAL_STATUSES:
                break

    match job_exec.status:
        case JobStatus.COMPLETED:
            _print_run_summary(job_id, job_key)
        case JobStatus.ERROR:
            _print_run_summary(job_id, job_key)
            click.echo(f"Job {job_id} failed: {job_exec.error_message}", err=True)
            sys.exit(1)
        case JobStatus.CANCELED:
            click.echo(f"Job {job_id} was canceled.", err=True)
            sys.exit(1)


def _print_run_summary(job_id: UUID, job_key: str) -> None:
    """Print the linked run record summary, matching the old CLI output format."""
    import click
    from sqlalchemy import select

    from testgen.common.models import get_current_session
    from testgen.common.models.profiling_run import ProfilingRun
    from testgen.common.models.test_run import TestRun

    with database_session():
        session = get_current_session()
        match job_key:
            case "run-profile":
                run = session.scalars(select(ProfilingRun).where(ProfilingRun.job_execution_id == job_id)).first()
                if run:
                    status_msg = "Profiling encountered an error. Check log for details." if run.status == "Error" else "Profiling completed."
                    click.echo(f"\n        {status_msg}\n        Run ID: {run.id}\n    ")
            case "run-tests" | "run-monitors":
                run = session.scalars(select(TestRun).where(TestRun.job_execution_id == job_id)).first()
                if run:
                    status_msg = "Test execution encountered an error. Check log for details." if run.status == "Error" else "Test execution completed."
                    click.echo(f"\n        {status_msg}\n        Run ID: {run.id}\n    ")
            case "run-test-generation":
                click.echo("Test generation completed.")
