import logging
import signal
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from testgen.commands.job_registry import JOB_DISPATCH
from testgen.commands.run_upgrade_db_config import is_db_revision_up_to_date
from testgen.common.models import database_session, with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy, Job, Scheduler
from testgen.scheduler.job_executor import JobExecutor

LOG = logging.getLogger("testgen")

@dataclass
class CliJob(Job):
    key: str
    kwargs: dict[str, Any]
    project_code: str | None = field(default=None)
    job_schedule_id: UUID | None = field(default=None)


class CliScheduler(Scheduler):

    def __init__(self):
        self.reload_timer = None
        self._current_jobs = {}
        LOG.info("Starting CLI Scheduler with registered jobs: %s", ", ".join(JOB_DISPATCH.keys()))
        self.executor = JobExecutor()
        super().__init__()

    @with_database_session
    def get_jobs(self) -> Iterable[CliJob]:

        # Scheduling the next reload to the next 50th second of a minute
        self.reload_timer = threading.Timer((110 - datetime.now().second) % 60 or 60, self.reload_jobs)
        self.reload_timer.start()

        jobs = {}
        for job_model in JobSchedule.select_runnable():
            if job_model.key not in JOB_DISPATCH:
                LOG.error("Job '%s' scheduled but not registered", job_model.key)
                continue

            jobs[job_model.id] = CliJob(
                cron_expr=job_model.cron_expr,
                cron_tz=job_model.cron_tz,
                delayed_policy=DelayedPolicy.SKIP,
                key=job_model.key,
                kwargs=job_model.kwargs,
                project_code=job_model.project_code,
                job_schedule_id=job_model.id,
            )

        for job_id in jobs.keys() - self._current_jobs.keys():
            LOG.info("Enabled job: %s", jobs[job_id])

        for job_id in self._current_jobs.keys() - jobs.keys():
            LOG.info("Disabled job: %s", self._current_jobs[job_id])

        self._current_jobs = jobs

        return jobs.values()

    @with_database_session
    def start_job(self, job: CliJob, triggering_time: datetime) -> None:
        LOG.info("Submitting job '%s' due '%s'", job.key, triggering_time)
        JobExecution.submit(
            job_key=job.key,
            kwargs=job.kwargs,
            source=JOB_DISPATCH[job.key].scheduler_source,
            project_code=job.project_code,
            job_schedule_id=job.job_schedule_id,
        )

    def start(self, base_time):
        self.executor.start()
        super().start(base_time)

    def shutdown(self):
        super().shutdown()
        self.executor.stop()

    def wait(self, timeout=None):
        super().wait(timeout)
        self.executor.wait(timeout)

    def run(self):
        interrupted = threading.Event()

        def sig_handler(signum, _):
            sig = signal.Signals(signum)
            if interrupted.is_set():
                self.executor.signal_running_jobs(signum)
            else:
                LOG.info("Received signal %s for the first time, starting the shutdown process.", sig.name)
                interrupted.set()

        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)
        # Windows: parent forwards CTRL_BREAK_EVENT (delivered as SIGBREAK) when the
        # child is spawned in its own process group, so handle it the same way.
        if sigbreak := getattr(signal, "SIGBREAK", None):
            signal.signal(sigbreak, sig_handler)

        try:
            self.start(datetime.now(UTC))
            interrupted.wait()
            if self.reload_timer:
                self.reload_timer.cancel()
            self.shutdown()
            self.wait()
        finally:
            # Already stopped on a clean shutdown; this covers a start or a wait that raised.
            self.executor.stop()
            LOG.info("The scheduler has been shut down. No new jobs will be started.")

            self.executor.drain()



def check_db_is_ready() -> bool:
    """Whether the database schema matches this version, so the scheduler's queries can run.

    An upgrade can start this version before it migrates the database, and runs the migration
    inside this same container, so the scheduler waits rather than exits.
    """
    try:
        is_current = is_db_revision_up_to_date()
    except Exception:
        LOG.info("Database is not ready yet.")
        return False
    if not is_current:
        LOG.info("Database schema is out of date. Waiting for testgen upgrade-system-version to update it.")
        return False
    LOG.info("Database is ready.")
    return True


def run_scheduler():
    while not check_db_is_ready():
        time.sleep(10)

    with database_session():
        settled = JobExecution.recover_stale()
    if settled:
        LOG.info("Settled %d job execution(s) left by a previous session", settled)

    scheduler = CliScheduler()
    scheduler.run()
