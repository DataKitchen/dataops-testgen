import logging
import signal
import subprocess
import sys
import threading
from functools import partial
from uuid import UUID

from testgen import settings
from testgen.commands.job_registry import JOB_DISPATCH, finalize
from testgen.common.enums import PAUSABLE_JOB_KEYS, JobStatus
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution, process_failure_message

LOG = logging.getLogger("testgen")


class JobExecutor:
    """Runs queued jobs: claims them, starts a process for each, watches it, and stops it on request.

    Polls on a thread of its own between ``start`` and ``stop``.
    """

    def __init__(self) -> None:
        self._running_jobs: dict[UUID, subprocess.Popen] = {}
        # The in-process jobs this executor has dispatched and not yet reaped, which hold the
        # slots ``MAX_CONCURRENT_IN_PROCESS_RUNS`` allows. Guarded by ``_running_jobs_cond``.
        self._in_process_jobs: set[UUID] = set()
        self._running_jobs_cond = threading.Condition()
        self._force_kills: dict[UUID, threading.Timer] = {}
        self._poll_interval = settings.JOB_POLL_INTERVAL
        self._poll_batch_size = 5
        self._stopping = threading.Event()
        self._poll_thread: threading.Thread | None = None
        LOG.info("Runs on in-process connections limited to %d at a time", settings.MAX_CONCURRENT_IN_PROCESS_RUNS)

    def start(self) -> None:
        self._poll_thread = threading.Thread(target=self._poll_loop, name="poll-loop")
        self._poll_thread.start()

    def stop(self) -> None:
        """Stop claiming jobs. Jobs already running are left to finish."""
        self._stopping.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._poll_thread:
            self._poll_thread.join(timeout)

    def signal_running_jobs(self, signum: int) -> None:
        """Send ``signum`` to every running job process."""
        LOG.info("Received signal %s, propagating to %d running job(s)", signal.Signals(signum).name, len(self._running_jobs))
        # A snapshot: this runs in a signal handler, which cannot take the lock, while job
        # watcher threads add and remove entries.
        for proc in list(self._running_jobs.values()):
            proc.send_signal(signum)

    def drain(self) -> None:
        """Ask pausable running jobs to stop, then wait for every running job to exit, up to
        ``JOB_SHUTDOWN_TIMEOUT``."""
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

    def _poll_loop(self):
        skip_wait = False
        # Checked on its own as well: a full batch skips the wait, and with it the stop check.
        while not self._stopping.is_set() and (skip_wait or not self._stopping.wait(timeout=self._poll_interval)):
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
            finalize(job_exec, job_exec.mark_canceled)

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
            finalize(job_exec, partial(job_exec.mark_failed, f"Unknown job key: {job_exec.job_key}"))
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
        """Watch a job process and settle its job when the process exits non-zero.

        A process that exits cleanly has settled its own job. A non-zero exit means it was
        terminated or killed (a cancel, a force-kill, the operating system) or crashed before it
        could, and this settles the job as failed, or as canceled when a cancel was requested.
        The guarded transition makes this a no-op for a job the process did settle.
        """
        with self._running_jobs_cond:
            self._running_jobs[job_exec.id] = proc
        try:
            ret_code = proc.wait()
            LOG.info("Job PID %d ended with code %d", proc.pid, ret_code)
            if ret_code != 0:
                message = process_failure_message(proc.pid, ret_code, job_exec.job_key)
                finalize(job_exec, partial(job_exec.mark_failed, message))
        except Exception:
            LOG.exception("Error monitoring job PID %d", proc.pid)
            message = f"Process monitoring error for PID {proc.pid}"
            finalize(job_exec, partial(job_exec.mark_failed, message))
        finally:
            with self._running_jobs_cond:
                del self._running_jobs[job_exec.id]
                self._in_process_jobs.discard(job_exec.id)
                # Cancel rather than drop: an armed timer keeps its thread, and the Popen it
                # closes over, alive for the rest of the deadline.
                if timer := self._force_kills.pop(job_exec.id, None):
                    timer.cancel()
                self._running_jobs_cond.notify_all()

    def _request_interrupt_on_running_jobs(self) -> set[UUID]:
        """Ask pausable running jobs to stop at a work-key boundary. Returns the ids asked.

        Only pausable job keys are asked, since no other handler can see the request. This
        does not wait: the jobs that honor it exit like any other, so the shutdown wait that
        follows covers them and asking adds no delay of its own. A job that stops writes its own
        INTERRUPTED and the next start claims it; one killed before it got there is ended as an
        error by ``recover_stale``, since nothing recorded where it had reached.
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

