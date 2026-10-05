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
from testgen.commands.job_registry import JOB_DISPATCH, run_final_callbacks
from testgen.common.enums import PAUSABLE_JOB_KEYS, JobStatus
from testgen.common.models import database_session, with_database_session
from testgen.common.models.job_execution import JobExecution, process_failure_message
from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy, Job, Scheduler

LOG = logging.getLogger("testgen")

@dataclass
class CliJob(Job):
    key: str
    kwargs: dict[str, Any]
    project_code: str | None = field(default=None)
    job_schedule_id: UUID | None = field(default=None)


class CliScheduler(Scheduler):

    def __init__(self):
        self._running_jobs: dict[UUID, subprocess.Popen] = {}
        # The in-process jobs this scheduler has dispatched and not yet reaped, which hold the
        # slots ``MAX_CONCURRENT_IN_PROCESS_RUNS`` allows. Guarded by ``_running_jobs_cond``.
        self._in_process_jobs: set[UUID] = set()
        self._running_jobs_cond = threading.Condition()
        self._force_kills: dict[UUID, threading.Timer] = {}
        self.reload_timer = None
        self._current_jobs = {}
        self._poll_interval = settings.JOB_POLL_INTERVAL
        self._poll_batch_size = 5
        LOG.info("Starting CLI Scheduler with registered jobs: %s", ", ".join(JOB_DISPATCH.keys()))
        LOG.info("Runs on in-process connections limited to %d at a time", settings.MAX_CONCURRENT_IN_PROCESS_RUNS)
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
                with self._running_jobs_cond:
                    free_slots = settings.MAX_CONCURRENT_IN_PROCESS_RUNS - len(self._in_process_jobs)
                with database_session():
                    actionable = JobExecution.claim_actionable(
                        limit=self._poll_batch_size, in_process_slots=max(0, free_slots),
                    )
                # Claimed in-process rows are bounded by the free slots, not by ``limit``, so they
                # say nothing about more rows waiting. Counting them would re-poll without waiting
                # while the rest of the in-process queue is held.
                skip_wait = sum(
                    1 for job_exec in actionable
                    if not (job_exec.in_process and job_exec.status == JobStatus.CLAIMED)
                ) >= self._poll_batch_size
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
                # Scheduler-internal failure: force the JE terminal to avoid a hung row.
                # Skip final callbacks — we don't know the real run state, and a
                # still-live subprocess could legitimately complete after this.
                except Exception:
                    LOG.exception("Error processing job execution %s", job_exec.id)
                    try:
                        with database_session():
                            job_exec.mark_failed("Processing failed")
                    except Exception:
                        LOG.exception("Error marking job execution %s as error", job_exec.id)

    def _handle_cancellation(self, job_exec: JobExecution):
        proc = self._running_jobs.get(job_exec.id)
        if proc:
            LOG.info("Terminating canceled job %s (PID %d)", job_exec.id, proc.pid)
            try:
                proc.terminate()
            except OSError:
                pass  # Process already exited — _proc_wrapper will finalize
            else:
                self._schedule_force_kill(job_exec.id, proc)
        else:
            with database_session():
                if job_exec.mark_canceled():
                    run_final_callbacks(job_exec)

    def _schedule_force_kill(self, job_id: UUID, proc: subprocess.Popen) -> None:
        """Arm a SIGKILL for ``JOB_TERMINATE_TIMEOUT`` seconds from now, and return.

        Deadlines on a timer rather than inline: the poll loop must not block on a process that
        is ignoring the signal, and ``_proc_wrapper`` is already blocked waiting on this one.
        A cancel_requested row stays claimable until its process settles, so the poll asks again
        every cycle -- only the first ask arms a deadline.
        """
        if job_id in self._force_kills:
            return

        def escalate() -> None:
            # returncode rather than poll(): the waiting thread holds Popen's waitpid lock, and
            # poll() reports a reaped child as still running when it cannot take it.
            if proc.returncode is not None:
                return
            LOG.warning(
                "Job PID %d did not exit within %ds of terminate; killing it",
                proc.pid, settings.JOB_TERMINATE_TIMEOUT,
            )
            try:
                proc.kill()
            except OSError:
                pass  # Exited between the check and the signal

        timer = threading.Timer(settings.JOB_TERMINATE_TIMEOUT, escalate)
        timer.daemon = True
        self._force_kills[job_id] = timer
        timer.start()

    def _dispatch(self, job_exec: JobExecution):
        if job_exec.job_key not in JOB_DISPATCH:
            with database_session():
                job_exec.mark_failed(f"Unknown job key: {job_exec.job_key}")
            return

        exec_cmd = [sys.executable, sys.argv[0], "exec-job", str(job_exec.id)]
        LOG.info("Dispatching job execution %s: %s", job_exec.id, " ".join(exec_cmd))

        proc = subprocess.Popen(
            exec_cmd,  # noqa: S603
            start_new_session=True,
        )
        if job_exec.in_process:
            # Taken here rather than in the wrapper thread, so the next poll already counts it.
            with self._running_jobs_cond:
                self._in_process_jobs.add(job_exec.id)
        try:
            threading.Thread(target=self._proc_wrapper, args=(proc, job_exec)).start()
        except Exception:
            # The wrapper is what frees the slot, so a wrapper that never started must not keep it.
            with self._running_jobs_cond:
                self._in_process_jobs.discard(job_exec.id)
            raise

    def _proc_wrapper(self, proc: subprocess.Popen, job_exec: JobExecution):
        """Monitor a subprocess and act as crash-recovery safety net.

        exec_job owns the full lifecycle (mark_running/completed/interrupted/paused).
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
                    if job_exec.mark_failed(process_failure_message(proc.pid, ret_code, job_exec.job_key)):
                        run_final_callbacks(job_exec)
        except Exception:
            LOG.exception("Error monitoring job PID %d", proc.pid)
            with database_session():
                if job_exec.mark_failed(f"Process monitoring error for PID {proc.pid}"):
                    run_final_callbacks(job_exec)
        finally:
            with self._running_jobs_cond:
                del self._running_jobs[job_exec.id]
                self._in_process_jobs.discard(job_exec.id)
                # Cancel rather than drop: an armed timer keeps its thread, and the Popen it
                # closes over, alive for the rest of the deadline.
                if timer := self._force_kills.pop(job_exec.id, None):
                    timer.cancel()
                self._running_jobs_cond.notify_all()

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
            LOG.info("The scheduler has been shut down. No new jobs will be started.")

            self._request_interrupt_on_running_jobs()

            with self._running_jobs_cond:
                if self._running_jobs:
                    LOG.info("Waiting %d running job(s) to complete", len(self._running_jobs))
                    # Bounded, because the runtime's stop grace period is: waiting past it gets
                    # the whole container killed, which is worse than leaving a job to the next
                    # start. A step with no interior stop check cannot honor any deadline.
                    stopped = self._running_jobs_cond.wait_for(
                        lambda: len(self._running_jobs) == 0,
                        timeout=settings.JOB_SHUTDOWN_TIMEOUT,
                    )
                else:
                    stopped = True
                still_running = len(self._running_jobs)

            if stopped:
                LOG.info("All jobs terminated")
            else:
                LOG.warning(
                    "Exiting with %d job(s) still running after %ds; the next start will settle them",
                    still_running, settings.JOB_SHUTDOWN_TIMEOUT,
                )

    def _request_interrupt_on_running_jobs(self) -> set[UUID]:
        """Ask pausable running jobs to stop at a work-key boundary. Returns the ids asked.

        Only pausable job keys are asked, since no other handler can see the request. This
        does not wait: the jobs that honor it exit like any other, so the shutdown wait that
        follows covers them and asking adds no delay of its own. A job that stops writes its own
        INTERRUPTED and the next start claims it; one killed before it got there is canceled by
        ``recover_stale``, since nothing recorded where it had reached.
        """
        with self._running_jobs_cond:
            running_ids = set(self._running_jobs)
        if not running_ids:
            return set()
        try:
            with database_session():
                interrupting = JobExecution.request_interrupt_bulk(running_ids, PAUSABLE_JOB_KEYS)
        except Exception:
            LOG.exception("Could not request interrupt on running jobs")
            return set()
        if interrupting:
            LOG.info("Requested interrupt on %d running job(s)", len(interrupting))
        return interrupting


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
        settled = JobExecution.recover_stale()
    if settled:
        LOG.info("Settled %d job execution(s) left by a previous session", settled)

    scheduler = CliScheduler()
    scheduler.run()
