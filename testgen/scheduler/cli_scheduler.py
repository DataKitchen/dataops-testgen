import logging
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from testgen import settings
from testgen.commands.exec_job import JOB_DISPATCH
from testgen.common.models import database_session, with_database_session
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy, Job, Scheduler

LOG = logging.getLogger("testgen")

@dataclass
class CliJob(Job):
    key: str
    args: Iterable[Any]
    kwargs: dict[str, Any]
    project_code: str | None = field(default=None)
    job_schedule_id: UUID | None = field(default=None)


class CliScheduler(Scheduler):

    def __init__(self):
        self._running_jobs: dict[UUID, subprocess.Popen] = {}
        self._running_jobs_cond = threading.Condition()
        self.reload_timer = None
        self._current_jobs = {}
        self._poll_interval = settings.JOB_POLL_INTERVAL
        self._poll_batch_size = 5
        LOG.info("Starting CLI Scheduler with registered jobs: %s", ", ".join(JOB_DISPATCH.keys()))
        super().__init__()

    @with_database_session
    def get_jobs(self) -> Iterable[CliJob]:

        # Scheduling the next reload to the next 50th second of a minute
        self.reload_timer = threading.Timer((110 - datetime.now().second) % 60 or 60, self.reload_jobs)
        self.reload_timer.start()

        jobs = {}
        for job_model in JobSchedule.select_where():
            if job_model.key not in JOB_DISPATCH:
                LOG.error("Job '%s' scheduled but not registered", job_model.key)
                continue

            jobs[job_model.id] = CliJob(
                cron_expr=job_model.cron_expr,
                cron_tz=job_model.cron_tz,
                delayed_policy=DelayedPolicy.SKIP,
                key=job_model.key,
                args=job_model.args,
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
            source="scheduler",
            project_code=job.project_code,
            job_schedule_id=job.job_schedule_id,
        )

    def start(self, base_time):
        self._poll_thread = threading.Thread(target=self._poll_loop, name="poll-loop")
        self._poll_thread.start()
        super().start(base_time)

    def wait(self, timeout=None):
        super().wait(timeout)
        self._poll_thread.join(timeout)

    def _poll_loop(self):
        skip_wait = False
        while skip_wait or not self._stopping.wait(timeout=self._poll_interval):
            try:
                with database_session():
                    actionable = JobExecution.claim_actionable(limit=self._poll_batch_size)
                skip_wait = len(actionable) >= self._poll_batch_size
            except Exception:
                LOG.exception("Error polling for actionable jobs")
                skip_wait = False
                continue
            for job_exec in actionable:
                try:
                    match job_exec.status:
                        case JobStatus.CLAIMED:
                            self._dispatch(job_exec)
                        case JobStatus.CANCEL_REQUESTED:
                            self._handle_cancellation(job_exec)
                        case _:
                            LOG.error("Unexpected status '%s' for job %s", job_exec.status, job_exec.id)
                except Exception:
                    LOG.exception("Error processing job execution %s", job_exec.id)
                    try:
                        with database_session():
                            job_exec.mark_interrupted("Processing failed")
                    except Exception:
                        LOG.exception("Error marking job execution %s as error", job_exec.id)

    def _handle_cancellation(self, job_exec: JobExecution):
        proc = self._running_jobs.get(job_exec.id)
        if proc:
            LOG.info("Terminating cancelled job %s (PID %d)", job_exec.id, proc.pid)
            try:
                proc.terminate()
            except OSError:
                pass  # Process already exited — _proc_wrapper will finalize
        else:
            with database_session():
                job_exec.mark_cancelled()

    def _dispatch(self, job_exec: JobExecution):
        if job_exec.job_key not in JOB_DISPATCH:
            with database_session():
                job_exec.mark_interrupted(f"Unknown job key: {job_exec.job_key}")
            return

        exec_cmd = [sys.executable, sys.argv[0], "exec-job", str(job_exec.id)]
        LOG.info("Dispatching job execution %s: %s", job_exec.id, " ".join(exec_cmd))

        proc = subprocess.Popen(
            exec_cmd,  # noqa: S603
            start_new_session=True,
        )
        threading.Thread(target=self._proc_wrapper, args=(proc, job_exec)).start()

    def _proc_wrapper(self, proc: subprocess.Popen, job_exec: JobExecution):
        """Monitor a subprocess and act as crash-recovery safety net.

        exec_job owns the full lifecycle (mark_running/completed/interrupted).
        This wrapper only intervenes on nonzero exit codes, which indicate exec_job
        itself crashed before it could update the DB (OOM, kill -9, etc.).
        _transition() guards make redundant calls safe.
        """
        with self._running_jobs_cond:
            self._running_jobs[job_exec.id] = proc
        try:
            ret_code = proc.wait()
            LOG.info("Job PID %d ended with code %d", proc.pid, ret_code)
            if ret_code != 0:
                with database_session():
                    job_exec.mark_interrupted(f"Process {proc.pid} exited with code {ret_code}")
        except Exception:
            LOG.exception("Error monitoring job PID %d", proc.pid)
            with database_session():
                job_exec.mark_interrupted(f"Process monitoring error for PID {proc.pid}")
        finally:
            with self._running_jobs_cond:
                del self._running_jobs[job_exec.id]
                self._running_jobs_cond.notify()

    def run(self):
        interrupted = threading.Event()

        def sig_handler(signum, _):
            sig = signal.Signals(signum)
            if interrupted.is_set():
                LOG.info("Received signal %s, propagating to %d running job(s)", sig.name, len(self._running_jobs))
                for proc in self._running_jobs.values():
                    proc.send_signal(signum)
            else:
                LOG.info("Received signal %s for the first time, starting the shutdown process.", sig.name)
                interrupted.set()

        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)

        try:
            self.start(datetime.now(UTC))
            interrupted.wait()
            if self.reload_timer:
                self.reload_timer.cancel()
            self.shutdown()
            self.wait()
        finally:
            LOG.info("The scheduler has been shut down. No new jobs will be started.")

            with self._running_jobs_cond:
                if self._running_jobs:
                    LOG.info("Waiting %d running job(s) to complete", len(self._running_jobs))
                    self._running_jobs_cond.wait_for(lambda: len(self._running_jobs) == 0)

            LOG.info("All jobs terminated")


@with_database_session
def check_db_is_ready() -> bool:
    try:
        count = JobSchedule.count()
    except Exception:
        LOG.info("Database is not ready yet.")
        return False
    else:
        LOG.info("Database is ready. A total of %d schedule(s) were found.", count)
        return True


def run_scheduler():
    while not check_db_is_ready():
        time.sleep(10)

    with database_session():
        stale_count = JobExecution.cancel_all_stale()
        if stale_count:
            LOG.info("Cancelled %d stale job execution(s) from previous session", stale_count)

    scheduler = CliScheduler()
    scheduler.run()


