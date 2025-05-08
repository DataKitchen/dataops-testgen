import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import chain
from typing import Any

from click import Command

from testgen.common.models import with_database_session
from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy, Job, Scheduler

LOG = logging.getLogger("testgen")

JOB_REGISTRY: dict[str, Command] = {}

@dataclass
class CliJob(Job):
    key: str
    args: Iterable[Any]
    kwargs: dict[str, Any]


class CliScheduler(Scheduler):

    def __init__(self):
        self._running_jobs: set[subprocess.Popen] = set()
        self._running_jobs_cond = threading.Condition()
        self.reload_timer = None
        self._current_jobs = {}
        LOG.info("Starting CLI Scheduler with registered jobs: %s", ", ".join(JOB_REGISTRY.keys()))
        super().__init__()

    @with_database_session
    def get_jobs(self) -> Iterable[CliJob]:

        # Scheduling the next reload to the next 50th second of a minute
        self.reload_timer = threading.Timer((110 - datetime.now().second) % 60 or 60, self.reload_jobs)
        self.reload_timer.start()

        jobs = {}
        for (job_model,) in JobSchedule.select_where():
            if job_model.key not in JOB_REGISTRY:
                LOG.error("Job '%s' scheduled but not registered", job_model.key)
                continue

            jobs[job_model.id] = CliJob(
                cron_expr=job_model.cron_expr,
                cron_tz=job_model.cron_tz,
                delayed_policy=DelayedPolicy.SKIP,
                key=job_model.key,
                args=job_model.args,
                kwargs=job_model.kwargs
            )

        for job_id in jobs.keys() - self._current_jobs.keys():
            LOG.info("Enabled job: %s", jobs[job_id])

        for job_id in self._current_jobs.keys() - jobs.keys():
            LOG.info("Disabled job: %s", self._current_jobs[job_id])

        self._current_jobs = jobs

        return jobs.values()

    def start_job(self, job: CliJob, triggering_time: datetime) -> None:
        cmd = JOB_REGISTRY[job.key]

        LOG.info("Starting job '%s' due '%s'", job.key, triggering_time)

        exec_cmd = [
            sys.executable,
            sys.argv[0],
            cmd.name,
            *map(str, job.args),
            *chain(*chain((opt.opts[0], str(job.kwargs[opt.name])) for opt in cmd.params if opt.name in job.kwargs)),
        ]

        LOG.info("Executing  '%s'", " ".join(exec_cmd))

        proc = subprocess.Popen(exec_cmd, start_new_session=True, env={**os.environ, "TG_JOB_SOURCE": "SCHEDULER"})  # noqa: S603
        threading.Thread(target=self._proc_wrapper, args=(proc,)).start()

    def _proc_wrapper(self, proc: subprocess.Popen):
        with self._running_jobs_cond:
            self._running_jobs.add(proc)
        try:
            ret_code = proc.wait()
            LOG.info("Job PID %d ended with code %d", proc.pid, ret_code)
        except Exception:
            LOG.exception("Error running job PID %d", proc.pid)
        finally:
            with self._running_jobs_cond:
                self._running_jobs.remove(proc)
                self._running_jobs_cond.notify()

    def run(self):
        interrupted = threading.Event()

        def sig_handler(signum, _):
            sig = signal.Signals(signum)
            if interrupted.is_set():
                LOG.info("Received signal %s, propagating to %d running job(s)", sig.name, len(self._running_jobs))
                for job in self._running_jobs:
                    job.send_signal(signum)
            else:
                LOG.info("Received signal %s for the fist time, starting the shutdown process.", sig.name)
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
    scheduler = CliScheduler()
    scheduler.run()


def register_scheduler_job(cmd: Command):
    if cmd.name in JOB_REGISTRY:
        raise ValueError(f"A job with the '{cmd.name}' key is already registered.")

    JOB_REGISTRY[cmd.name] = cmd
    return cmd
