"""Cooperatively pausable, resumable job engine.

A :class:`PausableJob` declares an ordered list of :class:`Step` s and the base drives them.
Every step is invoked on every run; what makes a step resumable is that its work sits inside
a guard -- :meth:`PausableJob.fan_out` for work that spreads over many items, or
:meth:`PausableJob.once` for a single indivisible body. A guard whose tasks are already
recorded does nothing, so anything a step leaves *outside* a guard is setup it wants repeated
and anything inside is checkpointed work it wants skipped.

The checkpoint is an ordered list of task names plus a count of how many at the front of it
are done, stored on the job's ``job_executions`` row. Because the stored list defines the
order, a resume never re-sorts, so state that only affects ordering (table sizes, query row
order) cannot shift what a position means. Comparing the regenerated list against the stored
one is what decides whether a resume continues, extends, or starts over.

Three properties an adopter must uphold:

* Per-task writes are idempotent. A resume redoes up to ``max_threads - 1`` tasks that had
  already completed, because the pool finishes out of order and the count only advances over
  a contiguous run.
* Task lists come from state that does not change while the job is parked, or that only
  grows. Anything else is caught by the comparison and downgraded to a full restart. Use
  :meth:`PausableJob.pin` for inputs that must not drift but do not appear in a task name.
* A step that produces data later steps need produces it whether or not it ran here before.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select

from testgen import settings
from testgen.common.database.database_service import WorkerOutcome, run_keyed_worker_pool
from testgen.common.enums import JobStatus
from testgen.common.models import get_current_session
from testgen.common.models.job_execution import JobExecution
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")

K = TypeVar("K")
A = TypeVar("A")
R = TypeVar("R")

RESUME_STATE_VERSION = 1
# ASCII unit separator, between a task's step and its key. Chosen because it cannot occur in
# the schema, table, and column names that make up a key.
_TASK_SEPARATOR = "\x1f"


class JobSignal(BaseException):
    """Raised to unwind a job that is not finished and has not failed.

    Subclasses ``BaseException`` rather than ``Exception`` so it passes through every handler
    written to deal with failures: the blanket one this module wraps each step in, whatever a
    step wraps its own work in, and ``database_session``, which reads ``Exception`` as a
    rollback signal. None of those apply to a job that is stopping or starting over, and each
    one that intercepts a signal turns it into silence. The same reasoning makes Streamlit's
    ``RerunException`` a ``BaseException``.
    """


class JobParked(JobSignal):
    """A job stopped at a task boundary after a stop request, and can continue from it."""

    def __init__(self, step: str, resume_state: dict[str, Any]) -> None:
        super().__init__(f"Job parked in step '{step}'")
        self.step = step
        self.resume_state = resume_state


class WorkTasksChanged(JobSignal):
    """The regenerated task list cannot be reconciled with the stored one, so the checkpoint
    is unusable and the job has to start over."""


@dataclass(frozen=True)
class Step:
    """One stage of a job.

    ``fatal`` says whether a failure here ends the run or is recorded and stepped over.
    """

    name: str
    #: Taken unbound, so STEPS can be declared in the class body next to the methods it names.
    method: Callable[["PausableJob"], None]
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


# Membership, not equality: statuses that mean this run must not keep working. One cooperative
# stop serves both intents; where the run parks is decided when it gets there.
#
# The parked statuses are here too, not just the requests. A row can be parked by something
# other than its own process -- a restart settling a pause it found -- and that process may
# still be alive, since it is started in its own session and outlives the scheduler. Seeing its
# own row already parked, it has to stop: carrying on would run to a completion the lifecycle
# then refuses, leaving the work done, the row parked, and the final callbacks unfired. Parking
# again is a no-op, because a parked status is a source of itself.
_STOP_SIGNALLING_STATUSES: frozenset[JobStatus] = frozenset({
    JobStatus.INTERRUPT_REQUESTED, JobStatus.INTERRUPTED,
    JobStatus.PAUSE_REQUESTED, JobStatus.PAUSED,
})


class PauseSignal:
    """Tracks whether a pause has been requested for a job.

    ``check`` reads the job status and is called from the thread that owns the database
    session; workers only read :attr:`stopped`, which is thread-safe and needs no session.
    The answer is cached for a TTL and latches once set, so the cost is a function of how
    long the job runs rather than of how many tasks it has.
    """

    def __init__(self, job_id: UUID, ttl: int | None = None) -> None:
        self._job_id = job_id
        self._ttl = settings.JOB_PAUSE_CHECK_INTERVAL if ttl is None else ttl
        self._event = threading.Event()
        self._checked_at: float | None = None

    @property
    def stopped(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        """Set the signal without consulting the database. For tests and in-process callers."""
        self._event.set()

    def check(self) -> bool:
        """Refresh from the database if the cached answer has expired, and return it."""
        if self._event.is_set():
            return True

        # Only a negative answer is ever cached: a positive one sets the event and returns
        # above, so there is no earlier result to remember here.
        now = time.monotonic()
        if self._checked_at is not None and now - self._checked_at < self._ttl:
            return False
        self._checked_at = now

        # Read the column, not the row: the job's own JobExecution is already loaded in this
        # session, so fetching the entity would keep answering from the identity map and
        # never see the request, which arrives from somewhere else entirely.
        status = get_current_session().scalar(
            select(JobExecution.status).where(JobExecution.id == self._job_id)
        )
        if status in _STOP_SIGNALLING_STATUSES:
            LOG.info("Stop requested for job %s", self._job_id)
            self._event.set()
        return self._event.is_set()


class PausableJob(ABC, Generic[K]):
    """Base for a job that can stop at a task boundary and continue in a later process.

    The checkpoint lives on the job's ``job_executions`` row, so a job that has no id has
    nowhere to stop.
    """

    STEPS: ClassVar[tuple[Step, ...]] = ()

    def __init__(self, job_id: UUID, pause_signal: PauseSignal | None = None) -> None:
        self.job_id = job_id
        self._pause = pause_signal or PauseSignal(job_id)
        self._tasks: list[str] = []
        self._completed = 0
        self._pins: dict[str, Any] = {}
        self._out_of_order: set[int] = set()
        self._step: Step | None = None
        self._step_errors = 0
        self._errors: dict[str, int] = {}

    # ---- subclass contract ---------------------------------------------------------------

    @abstractmethod
    def canonical_key(self, key: K) -> str:
        """Stable identity of one work item, independent of run order or process."""

    # Observers, called for every step. What a job displays, and what it calls each state, is
    # entirely its own: the engine reports what happened, never how to describe it, and does
    # not assume a job surfaces every step it runs.

    def on_step_start(self, step: Step) -> None:
        """A step is about to run."""

    def on_step_progress(self, step: Step, done: int, total: int) -> None:
        """A fan-out advanced. ``done`` counts tasks this run skipped as well as ran."""

    def on_step_end(self, step: Step, errors: int) -> None:
        """A step returned. ``errors`` counts its individual tasks that failed."""

    def on_step_failed(self, step: Step, error: str) -> None:
        """A step raised. The run ends after this when the step is fatal."""

    def on_start(self) -> None:
        """Runs once per process before any step, on a fresh run and on a resume alike.

        Where a job prepares what every step needs -- entities, connections, the run's own row.
        Kept out of ``__init__`` so constructing the job has no side effects.
        """

    def on_restart(self) -> None:
        """Hook for state a restart must reset, such as the run timestamp."""

    def on_end(self) -> None:
        """Runs once after every step completes. Not called on a pause or a fatal failure."""

    # ---- guards, for use inside a step ----------------------------------------------------

    def once(self, body: Callable[[], None]) -> bool:
        """Run ``body`` unless the current step is already recorded as done.

        Returns whether it ran. An interrupted body restarts from its top, so it must be safe
        to re-run.
        """
        name = self._require_step().name
        self._register([name])
        if self._is_done(name):
            LOG.info("Step '%s' already completed; skipping", name)
            return False
        self._park_if_requested()

        body()
        self._advance(self._tasks.index(name))
        # Stage the checkpoint advance and commit it with the body's writes, the same as a
        # fan-out task: without staging, a kill after this commit would leave the body's effects
        # durable while the step reads as not-done, and the re-run would repeat them. A JobParked
        # unwinds the owning session without committing, so an uncommitted write is never marked
        # complete.
        self._stage_state(self._state_payload())
        get_current_session().commit()
        return True

    def no_work(self) -> None:
        """Declare that the current step has nothing to do.

        A step whose work list came back empty still has to say so: a stored list this leaves
        unaccounted for is a task that vanished, which the reconciliation reads as drift.
        """
        self._register([])

    def fan_out(
        self,
        keys: Sequence[K],
        build_arg: Callable[[K], A],
        process: Callable[[A], R],
        handle: Callable[[WorkerOutcome[K, R]], None],
        on_error: Callable[[K, str], None] | None = None,
        max_threads: int = 4,
    ) -> FanOutResult:
        """Spread ``keys`` across the worker pool, skipping whatever the checkpoint covers.

        ``build_arg`` and ``handle`` run on the calling thread, so they may use the database
        session; ``process`` runs on a worker thread and must be self-contained. ``handle``
        must not commit -- this method commits, so a task's writes and its place in the
        checkpoint land together.

        A task that fails, in the worker or in ``handle``, is counted and passed to
        ``on_error`` rather than ending the step: one bad item must not discard the rest.

        Raises :class:`JobParked` when a stop request cut the work short.
        """
        step = self._require_step()
        names = [self._task_name(step.name, key) for key in keys]
        if len(set(names)) != len(names):
            # Tasks are tracked by name, so two keys sharing one would collapse into a single
            # slot and silently drop the work of all but one of them.
            raise ValueError(f"Step '{step.name}' produced work keys that are not unique")
        self._register(names)

        by_name = dict(zip(names, keys, strict=True))
        position = {name: index for index, name in enumerate(self._tasks)}
        pending = [name for name in self._tasks[self._completed:] if name in by_name]
        result = FanOutResult(skipped=len(keys) - len(pending))
        if result.skipped:
            LOG.info("Step '%s': skipping %d task(s) done before the pause", step.name, result.skipped)
        if not pending:
            return result
        self._park_if_requested()

        session = get_current_session()
        items = [(by_name[name], build_arg(by_name[name])) for name in pending]

        for outcome in run_keyed_worker_pool(items, process, max_threads=max_threads, stop=lambda: self._pause.stopped):
            error = outcome.error
            if error is None:
                try:
                    handle(outcome)
                except Exception as e:
                    LOG.exception("Error handling the result of a work key")
                    error = get_exception_message(e)
            if error is not None:
                result.errors += 1
                self._step_errors += 1
                self._errors[step.name] = self._step_errors
                if on_error is not None:
                    on_error(outcome.key, error)
            # An errored task still counts as done: its error was recorded, and holding the
            # checkpoint back for it would make every later resume redo everything after it.
            self._advance(position[self._task_name(step.name, outcome.key)])
            self._park_if_requested()
            result.processed += 1
            # Progress writes onto this session, so it lands in the commit below.
            self.on_step_progress(step, result.processed + result.skipped, len(keys))
            session.commit()

        if result.processed < len(pending):
            # The pool stopped pulling on its own, so no per-task commit carried the final
            # checkpoint out. Persist it here, on the same terms as the in-loop stop.
            payload = self._state_payload()
            self._park_checkpoint(payload)
            raise JobParked(step.name, payload)
        return result

    def pin(self, key: str, value: Any) -> None:
        """Record a value that must be the same on a resume as it was on the original run.

        Signals a restart when it differs -- for inputs that change how work is done without
        changing which tasks exist, so nothing else would notice the drift.
        """
        if key not in self._pins:
            self._pins[key] = value
        elif self._pins[key] != value:
            raise WorkTasksChanged(f"Pinned value '{key}' changed since the checkpoint was written")

    def _should_pause(self) -> bool:
        return self._pause.check()

    # ---- driver --------------------------------------------------------------------------

    def execute(self) -> None:
        """Run every step in order, resuming from a checkpoint when there is one.

        A checkpoint that cannot be reconciled is discarded and the job runs once more from
        the top. That can happen at most once, since the discard clears what triggered it.
        """
        self._load_state()
        self.on_start()
        try:
            self._run_steps()
        except WorkTasksChanged as changed:
            LOG.warning("Restarting job %s from scratch: %s", self.job_id, changed)
            self._reset_state()
            self._stage_state(None)
            self.on_restart()
            self._run_steps()
        self.on_end()
        self._stage_state(None)

    def _run_steps(self) -> None:
        for step in self.STEPS:
            self._step = step
            self._step_errors = self._errors.get(step.name, 0)
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

    # ---- checkpoint ----------------------------------------------------------------------

    def _require_step(self) -> Step:
        if self._step is None:
            raise RuntimeError("Guards may only be used from inside a step")
        return self._step

    def _task_name(self, step: str, key: K) -> str:
        return f"{step}{_TASK_SEPARATOR}{self.canonical_key(key)}"

    def _is_done(self, name: str) -> bool:
        return name in self._tasks and self._tasks.index(name) < self._completed

    def _park_if_requested(self) -> None:
        """Commit the checkpoint and unwind, if a stop has been requested.

        Writes the checkpoint but not the status. A claimable status published here would offer
        the run to a new claimer while this process still holds it: the process is not finished
        when the checkpoint is, since unwinding still has to drain the worker pool and wait out
        every task already in flight. ``exec_job`` publishes the status once the process is
        genuinely done, and picks which parked status from what asked the run to stop.
        """
        if not self._should_pause():
            return
        payload = self._state_payload()
        self._park_checkpoint(payload)
        raise JobParked(self._require_step().name, payload)

    def _park_checkpoint(self, payload: dict[str, Any]) -> None:
        """Commit the checkpoint, unless the row is no longer one a resume can reach.

        A cancel that arrived first wins and the scheduler settles it, so a checkpoint written
        now would only outlive the run that wrote it. Both intents' statuses pass: a pause is
        just as resumable as an interrupt, and gating on the interrupt's alone would drop the
        checkpoint of every run stopped by request.
        """
        job_exec = get_current_session().get(JobExecution, self.job_id)
        if job_exec and job_exec.status in _STOP_SIGNALLING_STATUSES:
            self._stage_state(payload)
        get_current_session().commit()

    def _register(self, names: list[str]) -> None:
        """Reconcile a step's regenerated task names with the checkpoint.

        Extends the list when the step grew, and raises when the checkpoint cannot be
        trusted: a task that vanished means the world moved under the pause, and a step that
        grew after a later step already ran would leave the new tasks without the downstream
        work that step does.
        """
        step = self._require_step().name
        stored = [task for task in self._tasks if task == step or task.startswith(f"{step}{_TASK_SEPARATOR}")]
        if not stored:
            self._tasks.extend(names)
            return

        regenerated, recorded = set(names), set(stored)
        added = [name for name in names if name not in recorded]
        missing = [task for task in stored if task not in regenerated]
        LOG.info(
            "Step '%s' regenerated %d task(s) against %d recorded: %d added, %d missing",
            step, len(names), len(stored), len(added), len(missing),
        )
        if not added and not missing:
            return

        if missing:
            raise WorkTasksChanged(f"Step '{step}' lost {len(missing)} task(s) since the checkpoint was written")
        if self._has_later_step_tasks(step):
            raise WorkTasksChanged(f"Step '{step}' gained tasks after a later step already started")

        self._tasks.extend(added)
        LOG.info("Step '%s' gained %d task(s) since the checkpoint; extending", step, len(added))

    def _has_later_step_tasks(self, step: str) -> bool:
        names = [s.name for s in self.STEPS]
        later = set(names[names.index(step) + 1:])
        return any(task.split(_TASK_SEPARATOR, 1)[0] in later for task in self._tasks)

    def _advance(self, index: int) -> None:
        self._out_of_order.add(index)
        while self._completed in self._out_of_order:
            self._out_of_order.discard(self._completed)
            self._completed += 1

    def _load_state(self) -> None:
        job_exec = get_current_session().get(JobExecution, self.job_id)
        state = job_exec.resume_state if job_exec else None

        if isinstance(state, dict) and state.get("version") == RESUME_STATE_VERSION:
            self._tasks = list(state["tasks"])
            self._completed = int(state["completed"])
            self._pins = dict(state.get("pins", {}))
            self._errors = dict(state.get("errors", {}))
            LOG.info("Resuming job %s: %d of %d tasks already done", self.job_id, self._completed, len(self._tasks))
        else:
            if state:
                LOG.warning("Discarding resume state for job %s: unrecognized version", self.job_id)
            self._reset_state()

    def _reset_state(self) -> None:
        self._tasks = []
        self._completed = 0
        self._pins = {}
        self._errors = {}
        self._out_of_order = set()

    def _state_payload(self) -> dict[str, Any]:
        return {
            "version": RESUME_STATE_VERSION,
            "tasks": list(self._tasks),
            "completed": self._completed,
            "pins": dict(self._pins),
            "errors": dict(self._errors),
        }

    def _stage_state(self, payload: dict[str, Any] | None) -> None:
        """Write the checkpoint onto the session, for the owning transaction to commit.

        The job runs inside a session opened by its caller, so opening another here would
        nest and never commit on its own -- the write has to ride a commit the caller makes.
        """
        job_exec = get_current_session().get(JobExecution, self.job_id)
        if job_exec:
            job_exec.resume_state = payload
