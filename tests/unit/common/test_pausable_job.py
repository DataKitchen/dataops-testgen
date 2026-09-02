import logging
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus
from testgen.common.pausable_job import (
    RESUME_STATE_VERSION,
    JobParked,
    JobSignal,
    PausableJob,
    PauseSignal,
    Step,
    WorkTasksChanged,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.common.pausable_job"


_PARK_TARGET = {
    JobStatus.INTERRUPT_REQUESTED: JobStatus.INTERRUPTED,
    JobStatus.INTERRUPTED: JobStatus.INTERRUPTED,
    JobStatus.PAUSE_REQUESTED: JobStatus.PAUSED,
    JobStatus.PAUSED: JobStatus.PAUSED,
}


class _FakeJobExecution:
    def __init__(self, status="running", resume_state=None):
        self.status = status
        self.resume_state = resume_state
        self.interrupt_attempts = 0

    def park(self, resume_state):
        """Mirror the real lifecycle guard: only a stopping or stopped row parks, and it lands
        wherever the request that stopped it points."""
        self.interrupt_attempts += 1
        if self.status not in _PARK_TARGET:
            return False
        self.status = _PARK_TARGET[self.status]
        self.resume_state = resume_state
        return True


@pytest.fixture
def job_exec():
    return _FakeJobExecution()


@pytest.fixture
def session(job_exec):
    """Stand in for the session the job runs inside, returning the fake row from get()."""
    mock = MagicMock()
    mock.get.return_value = job_exec

    mock.scalar.side_effect = lambda *_a, **_k: job_exec.status

    with patch(f"{MODULE}.get_current_session", return_value=mock):
        yield mock


class _Job(PausableJob[str]):
    """Two steps: a fan-out over string keys, then an indivisible body."""

    def __init__(self, keys, delays=None, pause_after=None, max_threads=1, fail=False, **kwargs):
        super().__init__(**kwargs)
        self.keys = keys
        self.delays = delays or {}
        self.pause_after = pause_after
        self.max_threads = max_threads
        self.fail = fail
        self.handled = []
        self.built = []
        self.wrapped_ran = 0
        self.restarts = 0
        self.reported = []
        self.lifecycle = []

    def canonical_key(self, key):
        return key

    def on_start(self):
        self.lifecycle.append("start")

    def on_end(self):
        self.lifecycle.append("end")

    def on_restart(self):
        self.restarts += 1
        self.lifecycle.append("restart")

    def on_step_start(self, step):
        self.reported.append(("start", step.name, None))

    def on_step_progress(self, step, done, total):
        self.reported.append(("progress", step.name, f"{done} of {total}"))

    def on_step_end(self, step, errors):
        self.reported.append(("end", step.name, errors))

    def on_step_failed(self, step, error):
        self.reported.append(("failed", step.name, error))

    def _build(self, key):
        self.built.append(key)
        return key

    def _process(self, arg):
        if delay := self.delays.get(arg):
            time.sleep(delay)
        if self.fail:
            raise ValueError("boom")
        return arg.upper()

    def _handle(self, outcome):
        self.handled.append(outcome.key)
        if self.pause_after is not None and len(self.handled) >= self.pause_after:
            self._pause.request()

    def spread(self):
        return self.fan_out(self.keys, self._build, self._process, self._handle, max_threads=self.max_threads)

    def wrap(self):
        self.once(self._body)

    def _body(self):
        self.wrapped_ran += 1


def _state(tasks, completed, pins=None):
    return {
        "version": RESUME_STATE_VERSION,
        "tasks": tasks,
        "completed": completed,
        "pins": pins or {},
    }


def _spread(*keys):
    return [f"spread\x1f{key}" for key in keys]


_Job.STEPS = (
    Step("spread", _Job.spread),
    Step("wrap", _Job.wrap, fatal=False),
)


def _run(job):
    job.execute()
    return job


# ---- fresh run ---------------------------------------------------------------------------


def test_every_step_runs_on_a_fresh_job(session, job_exec):
    job = _run(_Job(["a", "b"], job_id=uuid4()))

    assert job.handled == ["a", "b"]
    assert job.wrapped_ran == 1
    assert job_exec.resume_state is None


def test_fresh_run_commits_every_completed_task(session):
    # Three fan-out tasks plus the one once-body, each committed with its checkpoint advance.
    job = _run(_Job(["a", "b", "c"], job_id=uuid4()))

    assert session.commit.call_count == 4


def test_a_once_body_is_committed_with_its_checkpoint(session):
    """A pause after a once-body records it done; its write must be durable by then, not
    riding an owning transaction that JobParked discards."""
    committed_when_body_ran = []
    job = _Job(["a"], job_id=uuid4())

    def body():
        job.wrapped_ran += 1
        committed_when_body_ran.append(session.commit.call_count)

    job.STEPS = (Step("wrap", lambda self: self.once(body)),)
    _run(job)

    # The commit lands after the body runs, not before.
    assert session.commit.call_count == committed_when_body_ran[0] + 1


# ---- lifecycle hooks --------------------------------------------------------------------


def test_on_start_runs_before_any_step_and_on_end_after(session):
    job = _run(_Job(["a"], job_id=uuid4()))

    assert job.lifecycle == ["start", "end"]
    # on_start precedes the first step's report, on_end follows the last.
    assert job.reported[0][0] == "start"  # first thing a step does is announce itself
    assert job.lifecycle[0] == "start"


def test_on_end_does_not_run_on_a_pause(session):
    job = _Job(["a", "b", "c"], delays=_SLOW, pause_after=1, job_id=uuid4())

    with pytest.raises(JobParked):
        _run(job)

    assert job.lifecycle == ["start"]  # started, never ended


def test_a_restart_runs_on_restart_then_finishes_with_on_end(session, job_exec):
    # Stored checkpoint the regenerated list cannot match -> WorkTasksChanged -> restart.
    job_exec.resume_state = _state(_spread("a", "b", "c"), 1)
    job = _run(_Job(["a", "c"], job_id=uuid4()))

    assert job.restarts == 1
    assert job.lifecycle == ["start", "restart", "end"]


# ---- pause ------------------------------------------------------------------------------


# Tasks need to be slower than the consumer, or a worker drains the whole list before the
# consumer gets far enough to notice the pause -- which is the real-world shape too, where a
# task is a target-database query and handling one is a local upsert.
_SLOW = dict.fromkeys("abcde", 0.05)


def test_pause_stops_dispatch_and_raises(session):
    job = _Job(["a", "b", "c", "d", "e"], delays=_SLOW, pause_after=2, job_id=uuid4())

    with pytest.raises(JobParked) as raised:
        _run(job)

    assert raised.value.step == "spread"
    assert len(job.handled) < 5
    assert raised.value.resume_state["completed"] == len(job.handled)


def _stopping_after(job_exec, job, handled_count, requesting=JobStatus.INTERRUPT_REQUESTED):
    """Flip the row to a stop-requesting status once ``handled_count`` outcomes have landed.

    Mirrors a request arriving mid-run: it is made from another session, and the job notices it
    on its next check rather than up front.
    """
    handle = job._handle

    def flip(outcome):
        handle(outcome)
        if len(job.handled) >= handled_count:
            job_exec.status = requesting

    job._handle = flip
    return job


def _stoppable(keys, job_exec, after, requesting=JobStatus.INTERRUPT_REQUESTED, **kwargs):
    job_id = uuid4()
    job = _Job(keys, delays=_SLOW, job_id=job_id, pause_signal=PauseSignal(job_id, ttl=0), **kwargs)
    return _stopping_after(job_exec, job, after, requesting)


@pytest.mark.parametrize(
    "requesting", [JobStatus.INTERRUPT_REQUESTED, JobStatus.PAUSE_REQUESTED]
)
def test_a_detected_stop_commits_the_checkpoint_before_unwinding(session, job_exec, requesting):
    """The checkpoint has to be durable by the time JobParked leaves: unwinding still has to
    drain the pool, and a kill during that drain would otherwise lose the run's progress.

    Both intents, because the durability gate reads the row's status: an interrupt and a pause
    are equally resumable, and admitting only one would silently drop the other's progress."""
    committed = []
    session.commit.side_effect = lambda: committed.append((job_exec.status, job_exec.resume_state))
    job = _stoppable(["a", "b", "c", "d", "e"], job_exec, after=2, requesting=requesting)

    with pytest.raises(JobParked):
        _run(job)

    assert 0 < len(job.handled) < 5
    assert committed[-1][1]["completed"] == len(job.handled)
    assert job_exec.resume_state["completed"] == len(job.handled)


def test_a_detected_stop_leaves_the_status_for_the_caller_to_publish(session, job_exec):
    """INTERRUPTED is claimable the moment it lands, and this process still holds the run until
    the unwind drains the pool. Publishing here would offer it to a second worker meanwhile."""
    job = _stoppable(["a", "b", "c", "d", "e"], job_exec, after=2)

    with pytest.raises(JobParked):
        _run(job)

    assert job_exec.status == JobStatus.INTERRUPT_REQUESTED


def test_a_detected_stop_leaves_the_outcomes_behind_it_unhandled(session, job_exec):
    """Detection is the exit. Consuming the rest of the pool is what held the row in a status
    nothing would claim, and the tasks it covers are redone on resume anyway."""
    job = _stoppable(["a", "b", "c", "d", "e"], job_exec, after=2, max_threads=3)

    with pytest.raises(JobParked):
        _run(job)

    assert len(job.handled) == 2


def test_a_cancel_that_arrived_first_is_not_overwritten(session, job_exec):
    """A stop already noticed, then a cancel reaching the row before the job can park. The
    lifecycle refuses the transition -- the cancel wins and the scheduler settles it -- and the
    run still unwinds rather than carrying on."""
    job_exec.status = JobStatus.CANCEL_REQUESTED
    job = _Job(["a", "b"], job_id=uuid4())
    job._pause.request()

    with pytest.raises(JobParked):
        _run(job)

    assert job_exec.status == JobStatus.CANCEL_REQUESTED
    assert job_exec.resume_state is None


def test_pause_is_a_base_exception_not_an_error(session):
    """A pause must pass through the blanket except Exception that wraps each step."""
    job = _Job(["a", "b", "c"], delays=_SLOW, pause_after=1, job_id=uuid4())

    with pytest.raises(JobParked):
        try:
            _run(job)
        except Exception as e:
            pytest.fail(f"JobParked was caught as an Exception: {e!r}")


def test_every_signal_passes_through_a_failure_handler():
    """Engine signals unwind a job that is stopping or starting over, so a handler written
    for failures -- the engine's own, or one a step wraps its own work in -- must not see
    them. Anything that does intercept one turns it into silence."""
    assert set(JobSignal.__subclasses__()) == {JobParked, WorkTasksChanged}, (
        "a signal that is not a JobSignal can be swallowed as an error; add it here once it is one"
    )
    for signal in (JobParked, WorkTasksChanged):
        assert not issubclass(signal, Exception), f"{signal.__name__} can be swallowed as an error"


def test_a_step_that_survives_its_own_failures_still_restarts_the_run(session, job_exec):
    """A step declared non-fatal absorbs its own errors, but an unusable checkpoint is the
    run's problem, not the step's -- so it must reach the driver rather than be stepped over."""
    # The checkpoint covers "a", this run offers only "b", so "a" reads as work that vanished.
    job_exec.resume_state = _state(_spread("a"), 1)
    job = _Job(["b"], job_id=uuid4())
    job.STEPS = (Step("spread", _Job.spread, fatal=False), Step("wrap", _Job.wrap, fatal=False))

    _run(job)

    assert job.restarts == 1
    assert job.handled == ["b"]


def test_pause_before_a_guard_does_no_work(session):
    job = _Job(["a", "b"], job_id=uuid4())
    job._pause.request()

    with pytest.raises(JobParked):
        _run(job)

    assert job.built == []
    assert job.handled == []


# ---- resume -----------------------------------------------------------------------------


def test_resume_skips_the_completed_prefix(session, job_exec):
    job_exec.resume_state = _state(_spread("a", "b", "c", "d"), 2)

    job = _run(_Job(["a", "b", "c", "d"], job_id=uuid4()))

    assert job.handled == ["c", "d"]
    assert job.built == ["c", "d"]


def test_completed_guard_is_skipped_but_its_step_still_runs(session, job_exec):
    job_exec.resume_state = _state([*_spread("a"), "wrap"], 2)

    job = _run(_Job(["a"], job_id=uuid4()))

    assert job.wrapped_ran == 0


def test_interrupted_guard_restarts_from_its_top(session, job_exec):
    job_exec.resume_state = _state([*_spread("a"), "wrap"], 1)

    job = _run(_Job(["a"], job_id=uuid4()))

    assert job.wrapped_ran == 1


def test_unrecognized_state_version_starts_fresh(session, job_exec):
    job_exec.resume_state = {"version": RESUME_STATE_VERSION + 1, "tasks": _spread("a"), "completed": 1}

    job = _run(_Job(["a", "b"], job_id=uuid4()))

    assert job.handled == ["a", "b"]


# ---- contiguous pointer -----------------------------------------------------------------


def test_pointer_advances_only_over_a_contiguous_run(session):
    job = _Job([], job_id=uuid4())
    job._tasks = _spread("a", "b", "c", "d")

    job._advance(1)
    job._advance(2)
    assert job._completed == 0

    job._advance(0)
    assert job._completed == 3


def test_out_of_order_completion_never_skips_an_unfinished_task(session):
    job = _Job(
        ["a", "b", "c", "d"], delays={"a": 0.20, "b": 0.15, "c": 0.10, "d": 0.0}, max_threads=4, job_id=uuid4()
    )

    _run(job)

    assert job.handled == ["d", "c", "b", "a"]
    assert job._completed == 5  # four spread tasks plus the wrapped one


def test_errored_task_advances_the_pointer(session, job_exec):
    job = _run(_Job(["a", "b"], fail=True, job_id=uuid4()))

    assert job._completed == 3
    assert job_exec.resume_state is None


def test_failed_tasks_make_the_step_warn_with_a_count(session):
    """A step that finished having lost individual tasks warns; the job words the message."""
    job = _run(_Job(["a", "b"], fail=True, job_id=uuid4()))

    assert ("end", "spread", 2) in job.reported


def test_the_error_tally_carries_across_a_resume(session, job_exec):
    """The count a step reports is the run's, not this process's. Failures before a stop would
    otherwise vanish from the message while their rows still carry the error."""
    job_exec.resume_state = _state(_spread("a", "b", "c", "d"), 2)
    job_exec.resume_state["errors"] = {"spread": 3}

    job = _run(_Job(["a", "b", "c", "d"], fail=True, job_id=uuid4()))

    # Two more failed here, on top of the three the checkpoint carried.
    assert ("end", "spread", 5) in job.reported


def test_duplicate_work_keys_are_rejected(session):
    with pytest.raises(ValueError, match="not unique"):
        _run(_Job(["a", "b", "a"], job_id=uuid4()))


# ---- extend vs restart ------------------------------------------------------------------


def test_step_that_grew_is_extended(session, job_exec):
    job_exec.resume_state = _state(_spread("a", "b"), 1)

    job = _run(_Job(["a", "b", "c"], job_id=uuid4()))

    assert job.restarts == 0
    assert job.handled == ["b", "c"]


def test_step_that_lost_a_task_restarts(session, job_exec):
    job_exec.resume_state = _state(_spread("a", "b", "c"), 1)

    job = _run(_Job(["a", "c"], job_id=uuid4()))

    assert job.restarts == 1
    assert job.handled == ["a", "c"]


@pytest.mark.parametrize(
    ("stored", "regenerated", "added", "missing"),
    [
        (["a", "b"], ["a", "b"], 0, 0),
        (["a", "b"], ["a", "b", "c", "d"], 2, 0),
        (["a", "b", "c"], ["a", "c"], 0, 1),
        (["a", "b"], ["b", "c"], 1, 1),
    ],
    ids=["no drift", "grew by two", "lost one", "lost one and gained one"],
)
def test_a_resume_says_how_the_work_list_drifted(
    session, job_exec, caplog, stored, regenerated, added, missing
):
    """Reported however it drifted, not only when it cannot be reconciled -- a list that
    drifts benignly reads as working right up until the drift loses a task."""
    job_exec.resume_state = _state(_spread(*stored), 1)

    with caplog.at_level(logging.INFO, logger="testgen"):
        _run(_Job(regenerated, job_id=uuid4()))

    drift = next(r for r in caplog.records if "regenerated" in r.message and "against" in r.message)
    assert drift.args == ("spread", len(regenerated), len(stored), added, missing)


def test_a_reordered_task_list_resumes_rather_than_restarting(session, job_exec):
    """The same tasks in a different sequence is not drift. The stored order decides, so a step
    whose query does not sort its rows cannot cost the run everything done before the stop."""
    job_exec.resume_state = _state([*_spread("a", "b"), "wrap"], 1)

    job = _run(_Job(["b", "a"], job_id=uuid4()))

    assert job.restarts == 0
    assert job.handled == ["b"]


def test_step_growing_after_a_later_step_started_restarts(session, job_exec):
    job_exec.resume_state = _state([*_spread("a"), "wrap"], 1)

    job = _run(_Job(["a", "b"], job_id=uuid4()))

    assert job.restarts == 1
    assert job.handled == ["a", "b"]


# ---- pins -------------------------------------------------------------------------------


def test_pin_records_the_value_and_accepts_it_again_unchanged(session):
    job = _Job([], job_id=uuid4())

    job.pin("sampling", {"percent": 30})
    job.pin("sampling", {"percent": 30})

    assert job._pins == {"sampling": {"percent": 30}}


def test_pin_survives_a_resume(session, job_exec):
    """A pin written before the pause is compared against, not overwritten by, the new value."""
    job_exec.resume_state = _state(_spread("a"), 0, pins={"sampling": {"percent": 30}})
    job = _Job(["a"], job_id=uuid4())
    job._load_state()

    job.pin("sampling", {"percent": 30})

    assert job._pins == {"sampling": {"percent": 30}}


def test_pin_that_drifted_restarts_the_job(session, job_exec):
    """Config that changes how work is done, without changing which tasks exist."""
    job_exec.resume_state = _state(_spread("a"), 0, pins={"sampling": {"percent": 30}})

    job = _Job(["a"], job_id=uuid4())
    job.STEPS = (
        Step("spread", lambda self: (self.pin("sampling", {"percent": 50}), self.spread())[1]),
        Step("wrap", _Job.wrap, fatal=False),
    )
    job.execute()

    assert job.restarts == 1


# ---- error policy -----------------------------------------------------------------------


def test_a_non_fatal_step_failure_is_reported_and_stepped_over(session, job_exec):
    job = _Job(["a"], job_id=uuid4())
    job.STEPS = (
        Step("spread", _Job.spread),
        Step("wrap", lambda _self: (_ for _ in ()).throw(RuntimeError("nope")), fatal=False),
    )

    job.execute()

    assert ("failed", "wrap", "nope") in job.reported
    assert job_exec.resume_state is None


def test_a_fatal_step_failure_ends_the_run(session):
    job = _Job(["a"], job_id=uuid4())
    job.STEPS = (
        Step("spread", lambda _self: (_ for _ in ()).throw(RuntimeError("nope")), fatal=True),
    )

    with pytest.raises(RuntimeError, match="nope"):
        job.execute()

    assert ("failed", "spread", "nope") in job.reported


def test_every_step_is_announced(session):
    """The engine has no opinion on which steps a job surfaces -- it announces them all."""
    job = _run(_Job(["a"], job_id=uuid4()))

    assert {name for _event, name, _ in job.reported} == {"spread", "wrap"}
    assert ("start", "spread", None) in job.reported
    assert ("end", "spread", 0) in job.reported
    assert ("start", "wrap", None) in job.reported
    assert ("end", "wrap", 0) in job.reported


def test_fan_out_reports_running_totals(session):
    job = _run(_Job(["a", "b"], job_id=uuid4()))

    details = [detail for event, _name, detail in job.reported if event == "progress"]
    assert details == ["1 of 2", "2 of 2"]


# ---- pause signal -----------------------------------------------------------------------


def test_pause_signal_latches_after_the_status_is_seen(session, job_exec):
    signal = PauseSignal(uuid4(), ttl=0)
    job_exec.status = "interrupt_requested"

    assert signal.check() is True
    job_exec.status = "running"
    assert signal.check() is True


def test_pause_signal_caches_within_its_ttl(session, job_exec):
    signal = PauseSignal(uuid4(), ttl=3600)

    assert signal.check() is False
    job_exec.status = "interrupt_requested"
    assert signal.check() is False
    assert session.scalar.call_count == 1


def test_pause_signal_reads_the_column_not_the_cached_row(session, job_exec):
    """The job's own row is already in this session, so loading the entity would answer
    from the identity map and never see a request made from another session."""
    signal = PauseSignal(uuid4(), ttl=0)
    job_exec.status = "interrupt_requested"

    assert signal.check() is True
    session.get.assert_not_called()


def test_guards_refuse_to_run_outside_a_step(session):
    job = _Job(["a"], job_id=uuid4())

    with pytest.raises(RuntimeError, match="inside a step"):
        job.once(lambda: None)
