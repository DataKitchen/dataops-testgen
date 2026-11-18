from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen import settings
from testgen.commands.job_registry import JOB_DISPATCH, JOB_FINAL_CALLBACKS, JobConfig
from testgen.common.enums import STOPPABLE_JOB_KEYS, JobKey, JobStatus
from testgen.common.models.job_execution import JobExecution, process_failure_message
from testgen.scheduler.job_executor import JobExecutor, _has_exited, _run_final_callbacks_for, _RunningJob
from testgen.scheduler.job_process import run_job_process

pytestmark = pytest.mark.unit

EXECUTOR_MODULE = "testgen.scheduler.job_executor"


@pytest.fixture
def mock_session():
    """Provide a mock session via database_session context manager."""
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=session):
        yield session


@pytest.fixture
def executor_db_session():
    """Patch the executor module's session context manager, yielding a mock session."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=session)
    ctx.__exit__ = Mock(return_value=False)
    with patch(f"{EXECUTOR_MODULE}.database_session", return_value=ctx):
        yield session


@pytest.fixture
def executor():
    with patch(f"{EXECUTOR_MODULE}.threading.Timer"):
        instance = JobExecutor()
        instance._poll_interval = 0
        yield instance


@pytest.fixture
def job_exec():
    return JobExecution(
        id=uuid4(),
        job_key=JobKey.run_tests,
        kwargs={"test_suite_id": "suite-123"},
        source="scheduler",
        status="claimed",
    )


@pytest.fixture
def exited():
    """Whether each fake process has exited, as the executor checks it without reaping."""
    with patch(f"{EXECUTOR_MODULE}._has_exited", return_value=False) as has_exited:
        yield has_exited


def _returning_row(job_exec, **overrides):
    """Create a mock RETURNING row from a job execution with overrides."""
    row = Mock()
    for col in JobExecution.__table__.columns:
        setattr(row, col.key, overrides.get(col.key, getattr(job_exec, col.key, None)))
    return row


def _register(executor, job_id=None, job_key=JobKey.run_tests, exitcode=None, in_process=False):
    """Register a running job with a fake process, and return it."""
    job = _RunningJob(
        process=MagicMock(pid=555, exitcode=exitcode), doorbell=MagicMock(), job_key=job_key, in_process=in_process,
    )
    executor._running_jobs.setdefault(job_id or uuid4(), []).append(job)
    return job


# ---- dispatch ---------------------------------------------------------------------------


def _dispatch(executor, job_exec, **process_kwargs):
    process = MagicMock(**process_kwargs)
    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch.object(executor._context, "Process", return_value=process) as process_cls,
        patch(f"{EXECUTOR_MODULE}.threading.Thread") as thread_cls,
    ):
        executor._dispatch(job_exec)
    return process, process_cls, thread_cls


def test_dispatch_starts_a_job_process_with_its_doorbell(executor, job_exec):
    process, process_cls, thread_cls = _dispatch(executor, job_exec)

    kwargs = process_cls.call_args.kwargs
    assert kwargs["target"] is run_job_process
    job_id, doorbell, _verbose = kwargs["args"]
    assert job_id == job_exec.id
    process.start.assert_called_once()
    [job] = executor._running_jobs[job_exec.id]
    assert (job.process, job.doorbell, job.job_key) == (process, doorbell, job_exec.job_key)
    assert thread_cls.call_args.kwargs["args"] == (job_exec.id, job)
    thread_cls.return_value.start.assert_called_once()


def test_dispatch_unknown_job_key(executor, mock_session):
    job_exec = JobExecution(id=uuid4(), job_key="nonexistent", kwargs={}, source="ui", status="claimed")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")

    with patch.dict(JOB_DISPATCH, {}, clear=True):
        executor._dispatch(job_exec)

    assert job_exec.status == "error"


@pytest.mark.parametrize("in_process", [True, False])
def test_dispatch_records_whether_the_job_takes_an_in_process_slot(executor, job_exec, in_process):
    job_exec.in_process = in_process

    _dispatch(executor, job_exec)

    assert executor._running_jobs[job_exec.id][-1].in_process is in_process


def test_a_job_whose_process_fails_to_start_is_not_registered(executor, job_exec):
    with pytest.raises(OSError):
        _dispatch(executor, job_exec, **{"start.side_effect": OSError("no fork")})

    assert executor._running_jobs == {}


def test_a_job_whose_watcher_cannot_start_is_killed_and_forgotten(executor, job_exec):
    """The watcher settles the run and frees the slot, so a process without one must not keep running."""
    process = MagicMock()
    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch.object(executor._context, "Process", return_value=process),
        patch(f"{EXECUTOR_MODULE}.threading.Thread", side_effect=RuntimeError("can't start new thread")),
        pytest.raises(RuntimeError),
    ):
        executor._dispatch(job_exec)

    process.kill.assert_called_once()
    assert executor._running_jobs == {}


# ---- the watcher ------------------------------------------------------------------------


@pytest.mark.parametrize("exit_code", [0, 1, -9])
def test_the_watcher_reconciles_its_run_once_the_process_exits(executor, executor_db_session, exit_code):
    job_id = uuid4()
    job = _register(executor, job_id, exitcode=exit_code)

    with (
        patch.object(JobExecution, "reconcile", return_value=set()) as reconcile,
        patch(f"{EXECUTOR_MODULE}._run_final_callbacks_for") as callbacks,
    ):
        executor._watch(job_id, job)

    job.process.join.assert_called_once()
    id_clause, holder_clause = reconcile.call_args.args
    assert job_id in id_clause.compile().params.values()
    assert str(holder_clause.compile()) == str(JobExecution.not_held_by_another(executor._owner).compile())
    assert reconcile.call_args.kwargs["error_message"] == process_failure_message(555, exit_code, job.job_key)
    callbacks.assert_called_once_with(set())
    assert job_id not in executor._running_jobs


def test_the_watcher_fires_the_callbacks_of_the_run_it_ended(executor, job_exec, mock_session):
    job_exec.status = "running"
    job = _register(executor, job_exec.id, exitcode=-9)
    callback = Mock()

    with (
        patch.object(JobExecution, "reconcile", return_value={job_exec.id}),
        patch.object(JobExecution, "get", return_value=job_exec),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [callback]}),
    ):
        executor._watch(job_exec.id, job)

    callback.assert_called_once_with(job_exec)


def test_the_watcher_frees_the_slot_before_the_callbacks_run(executor, executor_db_session):
    """A notification can wait on its delivery timeout, and the slot is not the notification's to hold."""
    job_id = uuid4()
    job = _register(executor, job_id, exitcode=-9, in_process=True)
    seen = []

    with (
        patch.object(JobExecution, "reconcile", return_value={job_id}),
        patch(f"{EXECUTOR_MODULE}._run_final_callbacks_for", side_effect=lambda _: seen.append(dict(executor._running_jobs))),
    ):
        executor._watch(job_id, job)

    assert seen == [{}]


def test_the_watcher_forgets_its_job_when_settling_fails(executor, executor_db_session):
    job_id = uuid4()
    job = _register(executor, job_id, exitcode=1)

    with patch.object(JobExecution, "reconcile", side_effect=RuntimeError("no database")):
        executor._watch(job_id, job)

    assert job_id not in executor._running_jobs


def test_the_watcher_cancels_its_job_s_pending_deadlines(executor, executor_db_session):
    job_id = uuid4()
    job = _register(executor, job_id, exitcode=0)
    job.cancel_deadline, job.force_kill = MagicMock(), MagicMock()

    with patch.object(JobExecution, "reconcile", return_value=set()):
        executor._watch(job_id, job)

    job.cancel_deadline.cancel.assert_called_once()
    job.force_kill.cancel.assert_called_once()


def test_a_process_that_exits_after_its_run_was_claimed_again_leaves_the_new_process_alone(
    executor, executor_db_session,
):
    """A run parked by one process can be claimed by the next before the first has exited. The first
    one's watcher must not forget the second process, nor settle the run it now holds."""
    job_id = uuid4()
    old = _register(executor, job_id, exitcode=0)
    new = _register(executor, job_id)

    with patch.object(JobExecution, "reconcile") as reconcile:
        executor._watch(job_id, old)

    reconcile.assert_not_called()
    assert executor._running_jobs[job_id] == [new]


def test_a_run_s_exiting_process_still_counts_until_it_exits(executor):
    """It still holds its memory and must still be stopped at shutdown, though a newer process now
    holds the run."""
    job_id = uuid4()
    old = _register(executor, job_id, in_process=True)
    new = _register(executor, job_id, in_process=True)

    with patch(f"{EXECUTOR_MODULE}.settings.MAX_CONCURRENT_IN_PROCESS_RUNS", 2):
        claim_mock = _run_one_poll(executor, [])
    with patch.object(executor, "_terminate") as terminate:
        executor.terminate_running_jobs()

    assert claim_mock.call_args.kwargs["in_process_slots"] == 0
    assert [call.args[1] for call in terminate.call_args_list] == [old, new]
    assert executor._current(job_id) is new


# ---- ringing and leases -----------------------------------------------------------------


def test_the_poll_renews_its_leases_and_rings_every_job_whose_row_holds_a_request(executor, executor_db_session):
    jobs = {status: (job_id := uuid4(), _register(executor, job_id)) for status in JobStatus.stale_recoverable()}

    with (
        patch.object(JobExecution, "renew_leases") as renew,
        patch.object(
            JobExecution, "select_in_progress", return_value={job_id: status for status, (job_id, _) in jobs.items()},
        ),
    ):
        executor._ring_requested()

    assert renew.call_args.args[0] == executor._owner
    assert set(renew.call_args.args[1]) == {job_id for job_id, _ in jobs.values()}
    rung = {status for status, (_, job) in jobs.items() if job.doorbell.ring.called}
    assert rung == {JobStatus.PAUSE_REQUESTED, JobStatus.INTERRUPT_REQUESTED, JobStatus.CANCEL_REQUESTED}


def test_the_poll_touches_no_rows_without_running_jobs(executor, executor_db_session):
    with (
        patch.object(JobExecution, "renew_leases") as renew,
        patch.object(JobExecution, "select_in_progress") as select,
    ):
        executor._ring_requested()

    renew.assert_not_called()
    select.assert_not_called()


def test_ringing_survives_a_database_failure(executor, executor_db_session):
    job = _register(executor)

    with patch.object(JobExecution, "renew_leases", side_effect=RuntimeError("no database")):
        executor._ring_requested()

    job.doorbell.ring.assert_not_called()


# ---- reconcile --------------------------------------------------------------------------


def test_the_poll_settles_the_runs_no_live_process_holds(executor, executor_db_session):
    live = uuid4()
    _register(executor, live)
    settled = {uuid4()}

    with (
        patch.object(JobExecution, "held_by_no_live_process", return_value="clause") as held_by_none,
        patch.object(JobExecution, "reconcile", return_value=settled) as reconcile,
        patch(f"{EXECUTOR_MODULE}.threading.Thread") as thread_cls,
    ):
        executor._reconcile_without_process()

    assert held_by_none.call_args.args == (executor._owner, {live})
    reconcile.assert_called_once_with("clause")
    assert thread_cls.call_args.kwargs["args"] == (settled,)
    thread_cls.return_value.start.assert_called_once()


def test_nothing_settled_starts_no_callback_thread(executor, executor_db_session):
    with (
        patch.object(JobExecution, "reconcile", return_value=set()),
        patch(f"{EXECUTOR_MODULE}.threading.Thread") as thread_cls,
    ):
        executor._reconcile_without_process()

    thread_cls.assert_not_called()


def test_reconciling_survives_a_database_failure(executor, executor_db_session):
    with patch.object(JobExecution, "reconcile", side_effect=RuntimeError("no database")):
        executor._reconcile_without_process()


def test_a_reconciled_run_that_cannot_be_read_does_not_stop_the_others():
    unreadable, deleted, readable = uuid4(), uuid4(), uuid4()
    row = MagicMock(id=readable)

    def get(job_id):
        if job_id == unreadable:
            raise RuntimeError("connection reset")
        return row if job_id == readable else None

    with (
        patch(f"{EXECUTOR_MODULE}.database_session"),
        patch.object(JobExecution, "get", side_effect=get),
        patch(f"{EXECUTOR_MODULE}.run_final_callbacks") as callbacks,
    ):
        _run_final_callbacks_for([unreadable, deleted, readable])

    callbacks.assert_called_once_with(row)


# ---- poll loop --------------------------------------------------------------------------


def test_poll_loop_claims_and_dispatches(executor, job_exec, mock_session):
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = stopping_side_effect

    with (
        patch.object(JobExecution, "claim_actionable", return_value=[job_exec]) as claim_mock,
        patch.object(executor, "_dispatch") as dispatch_mock,
    ):
        executor._poll_loop()

    claim_mock.assert_called_once_with(limit=executor._poll_batch_size, in_process_slots=1, owner=executor._owner)
    dispatch_mock.assert_called_once_with(job_exec)


def test_poll_loop_handles_claim_error(executor, mock_session):
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = stopping_side_effect

    with patch.object(JobExecution, "claim_actionable", side_effect=RuntimeError("db down")):
        executor._poll_loop()


def test_poll_loop_skips_wait_when_batch_full(executor, mock_session):
    """When claim returns batch_size rows, skip the next wait to immediately re-poll."""
    batch_size = executor._poll_batch_size
    full_batch = [Mock() for _ in range(batch_size)]
    partial_batch = [Mock()]

    # Track the interleaving of waits and claims
    call_log = []

    def stopping_side_effect(timeout):
        call_log.append("wait")
        # Stop after we've seen both claims
        return len([c for c in call_log if c == "claim"]) >= 2

    def claim_side_effect(**_kwargs):
        call_log.append("claim")
        if len([c for c in call_log if c == "claim"]) == 1:
            return full_batch
        return partial_batch

    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = stopping_side_effect

    with (
        patch.object(JobExecution, "claim_actionable", side_effect=claim_side_effect),
        patch.object(executor, "_dispatch"),
    ):
        executor._poll_loop()

    # Sequence: wait → claim(full) → claim(partial) → wait(exit)
    # The skip avoids a wait between the full-batch claim and the partial-batch claim
    assert call_log == ["wait", "claim", "claim", "wait"]


def test_poll_loop_routes_cancel_requested(executor, mock_session):
    """Cancel_requested rows are routed to _handle_cancellation, not _dispatch."""
    cancel_job = JobExecution(
        id=uuid4(),
        job_key=JobKey.run_tests,
        kwargs={},
        source="ui",
        status=JobStatus.CANCEL_REQUESTED,
    )

    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = stopping_side_effect

    with (
        patch.object(JobExecution, "claim_actionable", return_value=[cancel_job]),
        patch.object(executor, "_dispatch") as dispatch_mock,
        patch.object(executor, "_handle_cancellation") as cancel_mock,
    ):
        executor._poll_loop()

    dispatch_mock.assert_not_called()
    cancel_mock.assert_called_once_with(cancel_job)


def _run_one_poll(executor, actionable):
    """Run the poll loop for exactly one claim and return the claim mock."""
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = stopping_side_effect
    with (
        patch.object(JobExecution, "claim_actionable", return_value=actionable) as claim_mock,
        patch.object(executor, "_dispatch"),
    ):
        executor._poll_loop()
    return claim_mock


@pytest.mark.parametrize(("cap", "held", "expected_slots"), [(1, 0, 1), (1, 1, 0), (3, 1, 2), (2, 3, 0)])
def test_poll_offers_the_slots_left_under_the_cap(executor, mock_session, cap, held, expected_slots):
    for _ in range(held):
        _register(executor, in_process=True)
    _register(executor, in_process=False)

    with patch(f"{EXECUTOR_MODULE}.settings.MAX_CONCURRENT_IN_PROCESS_RUNS", cap):
        claim_mock = _run_one_poll(executor, [])

    assert claim_mock.call_args.kwargs["in_process_slots"] == expected_slots


def test_claimed_in_process_rows_do_not_fill_the_batch(executor, mock_session):
    """In-process rows are limited by the free slots, not by the batch, so a batch they fill says
    nothing about more rows waiting. Counting them would re-poll with no wait while the rest of
    the in-process queue is held."""
    batch_size = executor._poll_batch_size
    in_process_batch = [
        JobExecution(id=uuid4(), job_key=JobKey.run_profile, status=JobStatus.CLAIMED, in_process=True)
        for _ in range(batch_size)
    ]
    call_log = []

    def stopping_side_effect(timeout):
        call_log.append("wait")
        return call_log.count("claim") >= 1

    def claim_side_effect(**_kwargs):
        call_log.append("claim")
        return in_process_batch

    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = stopping_side_effect
    with (
        patch(f"{EXECUTOR_MODULE}.settings.MAX_CONCURRENT_IN_PROCESS_RUNS", batch_size),
        patch.object(JobExecution, "claim_actionable", side_effect=claim_side_effect),
        patch.object(executor, "_dispatch"),
    ):
        executor._poll_loop()

    assert call_log == ["wait", "claim", "wait"]


def test_a_processing_failure_settles_the_row_without_callbacks(executor, job_exec, mock_session):
    """The real run state is unknown here, and a live job process may still finish and settle it."""
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = [False, True]
    callback = Mock()

    with (
        patch.object(JobExecution, "claim_actionable", return_value=[job_exec]),
        patch.object(executor, "_dispatch", side_effect=RuntimeError("boom")),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [callback]}),
    ):
        executor._poll_loop()

    assert job_exec.status == "error"
    callback.assert_not_called()



def test_the_poll_stops_even_while_batches_come_back_full(executor, mock_session):
    """A backlog keeps every batch full, and a full batch skips the wait that checks for a stop."""
    full_batch = [
        JobExecution(id=uuid4(), job_key=JobKey.run_tests, kwargs={}, source="ui", status="claimed", in_process=False)
        for _ in range(executor._poll_batch_size)
    ]
    polls = 0

    def claim(**_kwargs):
        nonlocal polls
        polls += 1
        if polls == 2:
            executor.stop()
        return full_batch

    with (
        patch.object(JobExecution, "claim_actionable", side_effect=claim),
        patch.object(executor, "_dispatch"),
    ):
        executor._poll_loop()

    assert polls == 2


def test_the_poll_reconciles_before_its_first_wait_and_rings_before_claiming(executor, mock_session):
    calls = []
    executor._stopping = Mock()
    executor._stopping.is_set.return_value = False
    executor._stopping.wait.side_effect = lambda **_: calls.append("wait") or len(calls) > 3

    with (
        patch.object(executor, "_ring_requested", side_effect=lambda: calls.append("ring")),
        patch.object(executor, "_reconcile_without_process", side_effect=lambda: calls.append("reconcile")),
        patch.object(JobExecution, "claim_actionable", side_effect=lambda **_: calls.append("claim") or []),
    ):
        executor._poll_loop()

    assert calls[:5] == ["reconcile", "wait", "ring", "reconcile", "claim"]


# ---- cancel -----------------------------------------------------------------------------


def _armed_escalation(executor, job):
    """Arm the kill escalation and hand back (delay, the callback the timer would fire)."""
    with patch(f"{EXECUTOR_MODULE}.threading.Timer") as timer:
        executor._schedule_force_kill(job)
        delay, escalate = timer.call_args[0]
    return delay, escalate


def test_a_cancel_with_no_process_is_left_to_the_reconcile_step(executor, mock_session):
    job_exec = JobExecution(id=uuid4(), job_key=JobKey.run_tests, kwargs={}, source="ui", status="cancel_requested")

    executor._handle_cancellation(job_exec)

    mock_session.execute.assert_not_called()
    assert job_exec.status == "cancel_requested"


def test_a_job_that_ignores_terminate_is_killed(executor, exited):
    job = _register(executor)

    delay, escalate = _armed_escalation(executor, job)
    escalate()

    assert delay == settings.JOB_TERMINATE_TIMEOUT
    job.process.kill.assert_called_once()


def test_a_job_that_exited_in_time_is_not_killed(executor, exited):
    job = _register(executor)
    exited.return_value = True

    _, escalate = _armed_escalation(executor, job)
    escalate()

    job.process.kill.assert_not_called()


def test_a_canceled_job_is_left_to_stop_until_the_cancel_timeout(executor):
    job_exec = JobExecution(id=uuid4(), status="cancel_requested", job_key="run-tests")
    job = _register(executor, job_exec.id)

    with patch(f"{EXECUTOR_MODULE}.threading.Timer") as timer:
        executor._handle_cancellation(job_exec)

    job.process.terminate.assert_not_called()
    delay, terminate = timer.call_args[0]
    assert delay == settings.JOB_CANCEL_TIMEOUT
    assert terminate == executor._terminate_late


def test_a_canceled_job_that_cannot_stop_is_terminated_at_once(executor, exited):
    """Waiting gains nothing for a job that never looks for the request, and a job that finishes
    in the wait would settle as canceled with its work committed."""
    job_exec = JobExecution(id=uuid4(), status="cancel_requested", job_key=JobKey.run_test_generation)
    job = _register(executor, job_exec.id, job_key=JobKey.run_test_generation)

    with (
        patch(f"{EXECUTOR_MODULE}.threading.Timer") as timer,
        patch.object(executor, "_schedule_force_kill") as escalation,
    ):
        executor._handle_cancellation(job_exec)

    job.process.terminate.assert_called_once()
    escalation.assert_called_once_with(job)
    timer.assert_not_called()


def test_the_cancel_deadline_is_armed_once_however_often_the_poll_asks(executor):
    """A cancel_requested row stays claimable until it settles, so the poll re-enters the
    cancellation path every cycle."""
    job_exec = JobExecution(id=uuid4(), status="cancel_requested", job_key="run-tests")
    _register(executor, job_exec.id)

    with patch(f"{EXECUTOR_MODULE}.threading.Timer") as timer:
        for _ in range(3):
            executor._handle_cancellation(job_exec)

    assert timer.call_count == 1


def test_a_job_still_running_at_the_cancel_timeout_is_terminated_then_escalated(executor, exited):
    job = _register(executor)

    with patch.object(executor, "_schedule_force_kill") as escalation:
        executor._terminate(uuid4(), job)

    job.process.terminate.assert_called_once()
    escalation.assert_called_once_with(job)


def test_a_job_that_stopped_within_the_cancel_timeout_is_not_terminated(executor, exited):
    job = _register(executor)
    exited.return_value = True

    with patch.object(executor, "_schedule_force_kill") as escalation:
        executor._terminate(uuid4(), job)

    job.process.terminate.assert_not_called()
    escalation.assert_not_called()


def test_the_kill_deadline_is_armed_once_however_often_the_poll_asks(executor):
    job = _register(executor)

    with patch(f"{EXECUTOR_MODULE}.threading.Timer") as timer:
        for _ in range(3):
            executor._schedule_force_kill(job)

    assert timer.call_count == 1


def test_checking_whether_a_job_exited_does_not_reap_it():
    """Only the watcher reaps, so the exit code it records is the process's own."""
    process = MagicMock(sentinel=7)

    with patch(f"{EXECUTOR_MODULE}.multiprocessing.connection.wait", return_value=[7]) as wait:
        assert _has_exited(process) is True

    wait.assert_called_once_with([7], timeout=0)
    process.poll.assert_not_called()
    process.join.assert_not_called()


# ---- shutdown ---------------------------------------------------------------------------


def test_shutdown_asks_every_stoppable_job_to_stop_and_rings_them_all(executor, executor_db_session):
    jobs = {job_id: _register(executor, job_id) for job_id in (uuid4(), uuid4())}

    with (
        patch.object(JobExecution, "request_interrupt_bulk", return_value=set()) as request,
        patch.object(JobExecution, "renew_leases") as renew,
    ):
        executor._ask_running_jobs_to_stop()

    # Renewed every time it asks: a job that outlives this scheduler counts its deadline from the last renewal.
    assert renew.call_args.args[0] == executor._owner
    assert set(renew.call_args.args[1]) == set(jobs)

    assert set(request.call_args.args[0]) == set(jobs)
    assert request.call_args.args[1] == STOPPABLE_JOB_KEYS
    for job in jobs.values():
        job.doorbell.ring.assert_called_once()


def test_shutdown_still_rings_the_jobs_when_the_database_fails(executor, executor_db_session):
    job = _register(executor)

    with patch.object(JobExecution, "request_interrupt_bulk", side_effect=RuntimeError("no database")):
        executor._ask_running_jobs_to_stop()

    job.doorbell.ring.assert_called_once()


def test_shutdown_asks_nothing_without_running_jobs(executor, executor_db_session):
    with patch.object(JobExecution, "request_interrupt_bulk") as request:
        executor._ask_running_jobs_to_stop()

    request.assert_not_called()


@pytest.fixture
def clock():
    """A fake monotonic clock that waiting on the running-jobs condition advances."""
    now = [0.0]
    with patch(f"{EXECUTOR_MODULE}.time.monotonic", side_effect=lambda: now[0]):
        yield now


def _drain(executor, clock, stops_after=None):
    """Drain with a condition whose waits advance the clock, and that reports every job gone after
    ``stops_after`` seconds."""
    def wait_for(predicate, timeout):
        clock[0] += timeout
        if stops_after is not None and clock[0] >= stops_after:
            executor._running_jobs.clear()
        return predicate()

    with (
        patch.object(executor, "_ask_running_jobs_to_stop") as ask,
        patch.object(executor, "terminate_running_jobs") as terminate,
        patch.object(executor, "_running_jobs_cond") as cond,
    ):
        cond.__enter__ = Mock(return_value=cond)
        cond.__exit__ = Mock(return_value=False)
        cond.wait_for.side_effect = wait_for
        executor.drain()
    return ask, terminate, cond


def test_shutdown_asks_again_until_its_timeout(executor, clock):
    """A job still starting when shutdown began cannot take the first request, so it is asked again."""
    _register(executor)

    ask, terminate, cond = _drain(executor, clock)

    assert ask.call_count == settings.JOB_SHUTDOWN_TIMEOUT
    terminate.assert_called_once()
    assert cond.wait_for.call_args.kwargs["timeout"] == settings.JOB_TERMINATE_TIMEOUT + 5


def test_shutdown_stops_asking_once_every_job_stopped(executor, clock):
    _register(executor)

    ask, terminate, _ = _drain(executor, clock, stops_after=3)

    assert ask.call_count == 3
    terminate.assert_not_called()


def test_terminating_running_jobs_survives_a_job_exiting_meanwhile(executor, exited):
    """It can run in a signal handler while watcher threads remove the jobs that exit."""
    first, second = _register(executor), _register(executor)
    first.process.terminate.side_effect = lambda: executor._running_jobs.pop(next(iter(executor._running_jobs)))

    with patch.object(executor, "_schedule_force_kill"):
        executor.terminate_running_jobs()

    first.process.terminate.assert_called_once()
    second.process.terminate.assert_called_once()
