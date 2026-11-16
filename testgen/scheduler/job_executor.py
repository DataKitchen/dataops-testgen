import logging
import multiprocessing
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from multiprocessing.process import BaseProcess
from uuid import UUID

from sqlalchemy import not_

from testgen import settings
from testgen.commands.job_registry import JOB_DISPATCH, finalize, run_final_callbacks
from testgen.common import job_lock
from testgen.common.doorbell import Doorbell
from testgen.common.enums import STOPPABLE_JOB_KEYS, JobStatus
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution, process_failure_message
from testgen.scheduler.job_process import run_job_process

LOG = logging.getLogger("testgen")

# Statuses that ask a running job to do something, which its doorbell tells it to look at.
_REQUEST_STATUSES = frozenset({
    JobStatus.PAUSE_REQUESTED, JobStatus.INTERRUPT_REQUESTED, JobStatus.CANCEL_REQUESTED,
})


@dataclass
class _RunningJob:
    process: BaseProcess
    doorbell: Doorbell
    job_key: str


class JobExecutor:
    """Runs queued jobs: claims them, starts a process for each, tells it about requests on its
    row, and settles the runs no live process will.

    Owns its job processes: none outlives it by more than its shutdown. Polls on a thread of its
    own between ``start`` and ``stop``.
    """

    def __init__(self) -> None:
        self._context = multiprocessing.get_context("spawn")
        self._running_jobs: dict[UUID, _RunningJob] = {}
        # The in-process jobs this executor has dispatched and not yet reaped, which hold the
        # slots ``MAX_CONCURRENT_IN_PROCESS_RUNS`` allows. Guarded by ``_running_jobs_cond``.
        self._in_process_jobs: set[UUID] = set()
        self._running_jobs_cond = threading.Condition()
        self._cancel_deadlines: dict[UUID, threading.Timer] = {}
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

    def terminate_running_jobs(self) -> None:
        """Terminate every running job process, and kill the ones still alive after
        ``JOB_TERMINATE_TIMEOUT``."""
        # A snapshot: this can run in a signal handler, which cannot take the lock, while job
        # watcher threads add and remove entries.
        running = list(self._running_jobs.items())
        LOG.info("Terminating %d running job(s)", len(running))
        for job_id, job in running:
            self._terminate(job_id, job.process)

    def drain(self) -> None:
        """Stop every running job: ask the ones that can stop to stop, wait for every job process
        to exit up to ``JOB_SHUTDOWN_TIMEOUT``, then terminate the rest."""
        self._ask_running_jobs_to_stop()

        with self._running_jobs_cond:
            if self._running_jobs:
                LOG.info("Waiting for %d running job(s) to stop", len(self._running_jobs))
            # Bounded, because the runtime's stop grace period is: waiting past it gets the whole
            # container killed, which is worse than terminating a job and leaving it to the next start.
            stopped = self._running_jobs_cond.wait_for(
                lambda: len(self._running_jobs) == 0,
                timeout=settings.JOB_SHUTDOWN_TIMEOUT,
            )
            still_running = len(self._running_jobs)

        if not stopped:
            LOG.warning(
                "%d job(s) still running after %ds; terminating them", still_running, settings.JOB_SHUTDOWN_TIMEOUT,
            )
            self.terminate_running_jobs()
            with self._running_jobs_cond:
                # The kill lands at the terminate timeout, and the watcher still has to settle the run.
                self._running_jobs_cond.wait_for(
                    lambda: len(self._running_jobs) == 0,
                    timeout=settings.JOB_TERMINATE_TIMEOUT + 5,
                )
        LOG.info("All jobs stopped")

    def _poll_loop(self):
        # Runs left by an earlier scheduler are settled before anything is claimed.
        self._reconcile_without_process()
        skip_wait = False
        # Checked on its own as well: a full batch skips the wait, and with it the stop check.
        while not self._stopping.is_set() and (skip_wait or not self._stopping.wait(timeout=self._poll_interval)):
            self._ring_requested()
            self._reconcile_without_process()
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

    def _ring_requested(self) -> None:
        """Ring the doorbell of every running job whose row holds a request.

        Rung on every poll while the request stands, so a ring the job cleared before its read
        saw the request is repeated.
        """
        with self._running_jobs_cond:
            running = dict(self._running_jobs)
        if not running:
            return
        try:
            with database_session():
                statuses = JobExecution.select_in_progress(JobExecution.id.in_(running))
        except Exception:
            LOG.exception("Could not read the status of running jobs")
            return
        for job_id, status in statuses.items():
            if status in _REQUEST_STATUSES:
                running[job_id].doorbell.ring()

    def _reconcile_without_process(self) -> None:
        """Settle the runs in progress that no live process holds: none of this executor's, and
        none that holds the run's lock."""
        try:
            with self._running_jobs_cond:
                own = set(self._running_jobs)
            with database_session():
                candidates = JobExecution.select_in_progress(not_(JobExecution.id.in_(own)))
            dead = [job_id for job_id in candidates if not job_lock.is_held(job_id)]
            if not dead:
                return
            with database_session():
                settled = JobExecution.reconcile(JobExecution.id.in_(dead))
            for job_id in dead:
                job_lock.remove(job_id)
        except Exception:
            LOG.exception("Could not settle runs with no process")
            return
        if settled:
            # On a thread, because a notification can wait on its delivery timeout.
            threading.Thread(
                target=_run_final_callbacks_for, args=(settled,), name="reconcile-callbacks", daemon=True,
            ).start()

    def _ask_running_jobs_to_stop(self) -> None:
        """Ask every running job that can stop to stop at once, and ring them all. Does not wait."""
        with self._running_jobs_cond:
            running = dict(self._running_jobs)
        if not running:
            return
        try:
            with database_session():
                interrupting = JobExecution.request_interrupt_bulk(running, STOPPABLE_JOB_KEYS)
        except Exception:
            LOG.exception("Could not request interrupt on running jobs")
            interrupting = set()
        if interrupting:
            LOG.info("Requested interrupt on %d running job(s)", len(interrupting))
        for job in running.values():
            job.doorbell.ring()

    def _handle_cancellation(self, job_exec: JobExecution):
        """Leave a canceled job to stop on its own, and terminate it if it has not stopped within
        ``JOB_CANCEL_TIMEOUT``. A job that cannot stop on its own is terminated at once. A run with
        no process is left to the reconcile step.

        A cancel_requested row stays claimable until it settles, so the poll asks again every
        cycle -- only the first ask arms a deadline.
        """
        job = self._running_jobs.get(job_exec.id)
        if not job:
            return
        if job_exec.job_key not in STOPPABLE_JOB_KEYS:
            self._terminate(job_exec.id, job.process)
            return
        with self._running_jobs_cond:
            if job_exec.id in self._cancel_deadlines:
                return
            LOG.info(
                "Job %s (PID %s) was canceled; terminating it if it has not stopped within %ds",
                job_exec.id, job.process.pid, settings.JOB_CANCEL_TIMEOUT,
            )
            timer = threading.Timer(
                settings.JOB_CANCEL_TIMEOUT, self._terminate_late, args=(job_exec.id, job.process),
            )
            timer.daemon = True
            self._cancel_deadlines[job_exec.id] = timer
        timer.start()

    def _terminate_late(self, job_id: UUID, process: BaseProcess) -> None:
        """Terminate a canceled job that did not stop on its own within ``JOB_CANCEL_TIMEOUT``."""
        if process.exitcode is None:
            LOG.warning("Job %s did not stop within %ds of its cancel", job_id, settings.JOB_CANCEL_TIMEOUT)
        self._terminate(job_id, process)

    def _terminate(self, job_id: UUID, process: BaseProcess) -> None:
        """Terminate a job's process, and arm the kill that follows."""
        if process.exitcode is not None:
            return
        LOG.info("Terminating job %s (PID %s)", job_id, process.pid)
        try:
            process.terminate()
        except OSError:
            pass  # Already exited; its watcher settles it
        else:
            self._schedule_force_kill(job_id, process)

    def _schedule_force_kill(self, job_id: UUID, process: BaseProcess) -> None:
        """Arm a kill for ``JOB_TERMINATE_TIMEOUT`` seconds from now, and return.

        Deadlines on a timer rather than inline: the caller must not block on a process that is
        ignoring the signal, and the job's watcher is already blocked waiting on this one.
        """
        if job_id in self._force_kills:
            return

        def escalate() -> None:
            if process.exitcode is not None:
                return
            LOG.warning(
                "Job PID %s did not exit within %ds of terminate; killing it",
                process.pid, settings.JOB_TERMINATE_TIMEOUT,
            )
            try:
                process.kill()
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

        doorbell = Doorbell(self._context)
        process = self._context.Process(
            target=run_job_process,
            args=(job_exec.id, doorbell, LOG.isEnabledFor(logging.DEBUG)),
            name=f"job-{job_exec.id}",
        )
        LOG.info("Dispatching job execution %s (%s)", job_exec.id, job_exec.job_key)
        process.start()
        # Registered here rather than in the watcher thread, so the next poll already counts it.
        with self._running_jobs_cond:
            self._running_jobs[job_exec.id] = _RunningJob(process, doorbell, job_exec.job_key)
            if job_exec.in_process:
                self._in_process_jobs.add(job_exec.id)
        try:
            threading.Thread(target=self._watch, args=(job_exec.id,), name=f"watch-{job_exec.id}").start()
        except Exception:
            # The watcher is what settles the run and frees the slot, so without one the process
            # must not keep running.
            process.kill()
            self._forget(job_exec.id)
            raise

    def _watch(self, job_id: UUID):
        """Wait for a job process to exit, then settle its run if the process did not.

        A process that settled or parked its run leaves nothing to do: the guarded transitions
        make this a no-op. Otherwise it was terminated or killed (a cancel, a shutdown, the
        operating system) or crashed, and the run ends as the reconcile step decides.
        """
        job = self._running_jobs[job_id]
        try:
            job.process.join()
            exit_code = job.process.exitcode
            LOG.info("Job PID %s ended with code %s", job.process.pid, exit_code)
            message = process_failure_message(job.process.pid, exit_code, job.job_key)
            with database_session():
                settled = JobExecution.reconcile(JobExecution.id == job_id, error_message=message)
            _run_final_callbacks_for(settled)
        except Exception:
            LOG.exception("Error settling job %s after its process exited", job_id)
        finally:
            job_lock.remove(job_id)
            self._forget(job_id)

    def _forget(self, job_id: UUID) -> None:
        with self._running_jobs_cond:
            self._running_jobs.pop(job_id, None)
            self._in_process_jobs.discard(job_id)
            # Cancel rather than drop: an armed timer keeps its thread, and the process it closes
            # over, alive for the rest of the deadline.
            for timers in (self._cancel_deadlines, self._force_kills):
                if timer := timers.pop(job_id, None):
                    timer.cancel()
            self._running_jobs_cond.notify_all()


def _run_final_callbacks_for(job_ids: Iterable[UUID]) -> None:
    """Fire the final callbacks of each job execution in ``job_ids`` that can still be read."""
    for job_id in job_ids:
        try:
            with database_session():
                job_exec = JobExecution.get(job_id)
        except Exception:
            LOG.exception("Could not read job execution %s to fire its final callbacks", job_id)
            continue
        if job_exec:
            run_final_callbacks(job_exec)
