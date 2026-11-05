"""Cooperatively stoppable job engine.

A :class:`StoppableJob` declares an ordered list of :class:`Step` s and the base drives them.
Between steps, between the outcomes of a fan-out, and while a fan-out waits on long work, the
job asks its :class:`StopSignal` whether the run was asked to stop. When it was, the job cancels
its in-flight statements if the reason calls for it, and unwinds.

The job's own thread is the only one that reads the request: it owns the database session, and
an answer read anywhere else would need a session of its own.
"""

import logging
import threading
import time
from abc import ABC
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import RowMapping

from testgen import settings
from testgen.common.database.database_service import (
    ThreadedProgress,
    WorkerOutcome,
    cancel_target_statements,
    fetch_dict_from_db,
    run_keyed_worker_pool,
)
from testgen.common.enums import JobStatus
from testgen.common.models import get_current_session
from testgen.common.models.job_execution import JobExecution
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")

K = TypeVar("K")
A = TypeVar("A")
R = TypeVar("R")


class JobSignal(BaseException):
    """Raised to unwind a job that is not finished and has not failed.

    Subclasses ``BaseException`` rather than ``Exception`` so it passes through every handler
    written to deal with failures: the blanket one this module wraps each step in, whatever a
    step wraps its own work in, and ``database_session``, which reads ``Exception`` as a
    rollback signal. None of those apply to a job that is stopping or starting over, and each
    one that intercepts a signal turns it into silence. The same reasoning makes Streamlit's
    ``RerunException`` a ``BaseException``.
    """


class StopReason(StrEnum):
    """What a run was asked to stop for."""
    PAUSE = "pause"
    INTERRUPT = "interrupt"
    CANCEL = "cancel"


class JobStopped(JobSignal):
    """A job stopped after a stop request, and cannot continue from where it stopped."""

    def __init__(self, step: str | None, reason: StopReason) -> None:
        super().__init__(f"Job stopped in step '{step}' ({reason})")
        self.step = step
        self.reason = reason


# Membership, not equality: statuses that mean this run must not keep working.
#
# The parked statuses are here too, not just the requests. A row can be parked by something
# other than its own process -- a restart settling a pause it found -- and that process may
# still be alive, since it is started in its own session and outlives the scheduler. Seeing its
# own row already parked, it has to stop: carrying on would run to a completion the lifecycle
# then refuses, leaving the work done, the row parked, and the final callbacks unfired.
_STOP_REASONS: dict[JobStatus, StopReason] = {
    JobStatus.INTERRUPT_REQUESTED: StopReason.INTERRUPT,
    JobStatus.INTERRUPTED: StopReason.INTERRUPT,
    JobStatus.PAUSE_REQUESTED: StopReason.PAUSE,
    JobStatus.PAUSED: StopReason.PAUSE,
    JobStatus.CANCEL_REQUESTED: StopReason.CANCEL,
    JobStatus.CANCELED: StopReason.CANCEL,
}


class StopSignal:
    """Tracks whether a job has been asked to stop, and why.

    ``check`` reads the job status and is called from the thread that owns the database
    session; workers only read :attr:`stopped`, which is thread-safe and needs no session.
    The answer is cached for a TTL and latches once set, so the cost is a function of how
    long the job runs rather than of how many tasks it has.
    """

    def __init__(self, job_id: UUID | None, ttl: float | None = None) -> None:
        self._job_id = job_id
        self.ttl = settings.JOB_PAUSE_CHECK_INTERVAL if ttl is None else ttl
        self._event = threading.Event()
        self._reason: StopReason | None = None
        self._checked_at: float | None = None

    @property
    def stopped(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> StopReason | None:
        return self._reason

    def request(self, reason: StopReason = StopReason.PAUSE) -> None:
        """Set the signal without consulting the database. For tests and in-process callers."""
        self._reason = reason
        self._event.set()

    def check(self) -> bool:
        """Refresh from the database if the cached answer has expired, and return it.

        A job with no id has no row anyone could ask through, so it never reads.
        """
        if self._event.is_set():
            return True
        if self._job_id is None:
            return False

        # Only a negative answer is ever cached: a positive one sets the event and returns
        # above, so there is no earlier result to remember here.
        now = time.monotonic()
        if self._checked_at is not None and now - self._checked_at < self.ttl:
            return False
        self._checked_at = now

        # Read the column, not the row: the job's own JobExecution is already loaded in this
        # session, so fetching the entity would keep answering from the identity map and
        # never see the request, which arrives from somewhere else entirely.
        status = get_current_session().scalar(
            select(JobExecution.status).where(JobExecution.id == self._job_id)
        )
        if (reason := _STOP_REASONS.get(status)) is not None:
            LOG.info("Stop requested for job %s (%s)", self._job_id, reason)
            self.request(reason)
        return self._event.is_set()


@dataclass(frozen=True)
class Step:
    """One stage of a job.

    ``fatal`` says whether a failure here ends the run or is recorded and stepped over.
    """

    name: str
    #: Taken unbound, so STEPS can be declared in the class body next to the methods it names.
    method: Callable[[Any], None]
    fatal: bool = True


@dataclass
class FanOutResult:
    """What a fan-out did in this process, as opposed to what a resumed run had already done."""
    processed: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def all_failed(self) -> bool:
        """Every task this process ran failed, and none carried over from an earlier one.

        Counting the carried-over ones is what keeps one bad task at the tail of a resumed run
        from reading as a total failure and discarding everything already done.
        """
        return self.processed > 0 and self.errors == self.processed and self.skipped == 0


class StoppableJob(ABC, Generic[K]):
    """Base for a job that stops at a step or work-key boundary when asked to.

    A stop raises :class:`JobStopped`, which the job's caller settles. Reasons in
    ``CANCELS_IN_FLIGHT_ON`` also cancel the job's running target-database statements, so the
    job stops within seconds; any other reason lets them finish first.
    """

    STEPS: ClassVar[tuple[Step, ...]] = ()
    CANCELS_IN_FLIGHT_ON: ClassVar[frozenset[StopReason]] = frozenset({StopReason.INTERRUPT, StopReason.CANCEL})

    def __init__(self, job_id: UUID | None, stop_signal: StopSignal | None = None) -> None:
        self.job_id = job_id
        self._stop_signal = stop_signal or StopSignal(job_id)
        self._step: Step | None = None
        self._step_errors = 0

    # ---- observers ------------------------------------------------------------------------
    # Called for every step. What a job displays, and what it calls each state, is entirely its
    # own: the engine reports what happened, never how to describe it, and does not assume a
    # job surfaces every step it runs.

    def on_step_start(self, step: Step) -> None:
        """A step is about to run."""

    def on_step_progress(self, step: Step, done: int, total: int) -> None:
        """A fan-out advanced. ``done`` counts tasks this run skipped as well as ran."""

    def on_step_end(self, step: Step, errors: int) -> None:
        """A step returned. ``errors`` counts its individual tasks that failed."""

    def on_step_failed(self, step: Step, error: str) -> None:
        """A step raised. The run ends after this when the step is fatal."""

    def on_start(self) -> None:
        """Runs once per process before any step.

        Where a job prepares what every step needs -- entities, connections, the run's own row.
        Kept out of ``__init__`` so constructing the job has no side effects.
        """

    def on_end(self) -> None:
        """Runs once after every step completes. Not called on a stop or a fatal failure."""

    # ---- driver ---------------------------------------------------------------------------

    def execute(self) -> None:
        """Run every step in order."""
        self.on_start()
        self._run_steps()
        self.on_end()

    def _run_steps(self) -> None:
        for step in self.STEPS:
            self._step = step
            self._step_errors = self._errors_before(step)
            self.stop_if_requested()
            self.on_step_start(step)
            try:
                step.method(self)
            except Exception as e:
                LOG.exception("Step '%s' failed for job %s", step.name, self.job_id)
                self.on_step_failed(step, get_exception_message(e))
                if step.fatal:
                    raise
            else:
                # A step can finish having lost individual tasks. Whether that reads as a
                # warning is the job's call; the count is what lets it decide and word it.
                self.on_step_end(step, self._step_errors)
            finally:
                self._step = None

    def _errors_before(self, step: Step) -> int:  # noqa: ARG002
        """Errors the step had already recorded before this process ran it."""
        return 0

    # ---- stopping -------------------------------------------------------------------------

    @property
    def stopped(self) -> bool:
        """Whether a stop was seen. Thread-safe."""
        return self._stop_signal.stopped

    def stop_if_requested(self) -> None:
        """Stop the job if it was asked to: cancel its in-flight statements when the reason
        calls for it, then unwind. Call it from the thread that owns the database session."""
        if not self._stop_signal.check():
            return
        reason = self._stop_signal.reason or StopReason.PAUSE
        if reason in self.CANCELS_IN_FLIGHT_ON:
            cancel_target_statements()
        self._stop(reason)

    def _stop(self, reason: StopReason) -> None:
        """Unwind a job that was asked to stop."""
        raise JobStopped(self._step.name if self._step else None, reason)

    # ---- fan-out --------------------------------------------------------------------------

    def fan_out(
        self,
        keys: Sequence[K],
        build_arg: Callable[[K], A],
        process: Callable[[A], R],
        handle: Callable[[WorkerOutcome[K, R]], None],
        on_error: Callable[[K, str], None] | None = None,
        max_threads: int = 4,
    ) -> FanOutResult:
        """Spread ``keys`` across the worker pool, stopping the job when it is asked to.

        ``build_arg`` and ``handle`` run on the calling thread, so they may use the database
        session; ``process`` runs on a worker thread and must be self-contained.

        A task that fails, in the worker or in ``handle``, is counted and passed to
        ``on_error`` rather than ending the step: one bad item must not discard the rest.
        Outcomes still in flight when the job stops are never handled.
        """
        return self._fan_out(keys, build_arg, process, handle, on_error, max_threads, observe=True)

    def _fan_out(
        self,
        keys: Sequence[K],
        build_arg: Callable[[K], A],
        process: Callable[[A], R],
        handle: Callable[[WorkerOutcome[K, R]], None],
        on_error: Callable[[K, str], None] | None,
        max_threads: int,
        observe: bool,
    ) -> FanOutResult:
        step = self._require_step()
        result = FanOutResult()
        if not keys:
            return result
        self.stop_if_requested()

        items = [(key, build_arg(key)) for key in keys]
        for outcome in self._worker_pool(items, process, max_threads):
            self._handle_outcome(step, outcome, handle, on_error, result, count_errors=observe)
            self.stop_if_requested()
            if observe:
                self.on_step_progress(step, result.processed, len(keys))

        if result.processed < len(items):
            # The pool stopped dispatching before every task ran: a stop was seen on another path.
            self._stop(self._stop_signal.reason or StopReason.PAUSE)
        return result

    def fetch_threaded(
        self,
        queries: Sequence[tuple[str, dict | None]],
        use_target_db: bool = False,
        max_threads: int = 4,
        on_progress: Callable[[ThreadedProgress], None] | None = None,
    ) -> tuple[list[RowMapping], dict[int, str]]:
        """Run ``queries`` across the worker pool and return their rows, and the errors by
        query index. Stops the job when it is asked to, like :meth:`fan_out`.

        :param on_progress: Called on this thread after each query returns.
        """
        rows: list[RowMapping] = []
        errors: dict[int, str] = {}
        processed: list[int] = []

        def report(index: int) -> None:
            processed.append(index)
            if on_progress:
                on_progress({
                    "processed": len(processed),
                    "errors": len(errors),
                    "total": len(queries),
                    "indexes": processed,
                })

        def handle(outcome: WorkerOutcome[int, list[RowMapping]]) -> None:
            rows.extend(outcome.result or [])
            report(outcome.key)

        def on_error(index: int, error: str) -> None:
            errors[index] = error
            report(index)

        # Not observed: the queries are a part of the step, so their progress and errors are the caller's
        # to report.
        self._fan_out(
            list(range(len(queries))),
            lambda index: queries[index],
            lambda query: fetch_dict_from_db(query[0], query[1], use_target_db=use_target_db),
            handle,
            on_error,
            max_threads,
            observe=False,
        )
        return rows, errors

    def _worker_pool(self, items: Sequence[tuple[K, A]], process: Callable[[A], R], max_threads: int):
        return run_keyed_worker_pool(
            items,
            process,
            max_threads=max_threads,
            stop=lambda: self._stop_signal.stopped,
            # Every worker can be inside a long statement at once, and then no outcome arrives to
            # check after. Waking up on the signal's own interval is what still notices the request.
            on_idle=self.stop_if_requested,
            idle_interval=max(self._stop_signal.ttl, 0.05),
        )

    def _handle_outcome(
        self,
        step: Step,
        outcome: WorkerOutcome[K, R],
        handle: Callable[[WorkerOutcome[K, R]], None],
        on_error: Callable[[K, str], None] | None,
        result: FanOutResult,
        count_errors: bool = True,
    ) -> None:
        error = outcome.error
        if error is None:
            try:
                handle(outcome)
            except Exception as e:
                LOG.exception("Error handling the result of a work key in step '%s'", step.name)
                error = get_exception_message(e)
        if error is not None:
            result.errors += 1
            if count_errors:
                self._step_errors += 1
            if on_error is not None:
                on_error(outcome.key, error)
        result.processed += 1

    def _require_step(self) -> Step:
        if self._step is None:
            raise RuntimeError("Guards may only be used from inside a step")
        return self._step
