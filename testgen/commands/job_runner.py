"""CLI-facing job submission: `submit_and_wait` posts a job for the scheduler
to execute and (optionally) polls until it reaches a terminal state.
"""

import logging
import sys
import time
from uuid import UUID

import click
from sqlalchemy import select

from testgen.commands.exec_job import FINAL_STATUSES, POLL_INTERVAL
from testgen.common.models import database_session, get_current_session
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.test_run import TestRun

LOG = logging.getLogger("testgen")


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
            if job_exec and job_exec.status in FINAL_STATUSES:
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
