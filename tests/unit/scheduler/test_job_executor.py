from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen import settings
from testgen.commands.job_registry import JOB_DISPATCH, JOB_FINAL_CALLBACKS, JobConfig
from testgen.common.enums import JobKey, JobStatus
from testgen.common.models.job_execution import JobExecution
from testgen.scheduler.job_executor import JobExecutor

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


def _returning_row(job_exec, **overrides):
    """Create a mock RETURNING row from a job execution with overrides."""
    from testgen.common.models.job_execution import JobExecution
    row = Mock()
    for col in JobExecution.__table__.columns:
        setattr(row, col.key, overrides.get(col.key, getattr(job_exec, col.key, None)))
    return row


def test_dispatch_spawns_process(executor, job_exec, mock_session):
    proc_mock = MagicMock()

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{EXECUTOR_MODULE}.subprocess.Popen", return_value=proc_mock) as popen_mock,
        patch(f"{EXECUTOR_MODULE}.threading.Thread") as thread_mock,
    ):
        executor._dispatch(job_exec)

    call_args = popen_mock.call_args[0][0]
    assert "exec-job" in call_args
    assert str(job_exec.id) in call_args

    thread_mock.assert_called_once()


def test_dispatch_unknown_job_key(executor, mock_session):
    job_exec = JobExecution(
        id=uuid4(),
        job_key="nonexistent",
        kwargs={},
        source="ui",
        status="claimed",
    )
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")

    with patch.dict(JOB_DISPATCH, {}, clear=True):
        executor._dispatch(job_exec)

    # mark_failed tries error first (valid from claimed)
    assert job_exec.status == "error"


def test_proc_wrapper_success_is_noop(executor, job_exec, mock_session):
    """On exit code 0, the wrapper does nothing — exec_job already handled lifecycle."""
    job_exec.status = "running"
    proc_mock = Mock()
    proc_mock.pid = 555
    proc_mock.wait.return_value = 0

    with (
        patch.object(executor, "_running_jobs_cond") as cond_mock,
        patch.object(executor, "_running_jobs") as dict_mock,
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        executor._proc_wrapper(proc_mock, job_exec)

    # Status unchanged — exec_job handles mark_completed, not the wrapper
    assert job_exec.status == "running"
    mock_session.execute.assert_not_called()
    dict_mock.__setitem__.assert_called_once()
    dict_mock.__delitem__.assert_called_once()


def test_proc_wrapper_failure(executor, job_exec, mock_session):
    job_exec.status = "running"
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock()
    proc_mock.pid = 555
    proc_mock.wait.return_value = 1

    with (
        patch.object(executor, "_running_jobs_cond") as cond_mock,
        patch.object(executor, "_running_jobs") as dict_mock,
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        executor._proc_wrapper(proc_mock, job_exec)

    assert job_exec.status == "error"


def test_proc_wrapper_exception(executor, job_exec, mock_session):
    job_exec.status = "running"
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock()
    proc_mock.pid = 555
    proc_mock.wait.side_effect = OSError("broken")

    with (
        patch.object(executor, "_running_jobs_cond") as cond_mock,
        patch.object(executor, "_running_jobs") as dict_mock,
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        executor._proc_wrapper(proc_mock, job_exec)

    assert job_exec.status == "error"


def test_poll_loop_claims_and_dispatches(executor, job_exec, mock_session):
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    executor._stopping = Mock()
    executor._stopping.wait.side_effect = stopping_side_effect

    with (
        patch.object(JobExecution, "claim_actionable", return_value=[job_exec]) as claim_mock,
        patch.object(executor, "_dispatch") as dispatch_mock,
    ):
        executor._poll_loop()

    claim_mock.assert_called_once_with(limit=executor._poll_batch_size, in_process_slots=1)
    dispatch_mock.assert_called_once_with(job_exec)


def test_poll_loop_handles_claim_error(executor, mock_session):
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    executor._stopping = Mock()
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
    executor._stopping.wait.side_effect = stopping_side_effect
    with (
        patch.object(JobExecution, "claim_actionable", return_value=actionable) as claim_mock,
        patch.object(executor, "_dispatch"),
    ):
        executor._poll_loop()
    return claim_mock


@pytest.mark.parametrize(("cap", "held", "expected_slots"), [(1, 0, 1), (1, 1, 0), (3, 1, 2), (2, 3, 0)])
def test_poll_offers_the_slots_left_under_the_cap(executor, mock_session, cap, held, expected_slots):
    executor._in_process_jobs = {uuid4() for _ in range(held)}

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
    executor._stopping.wait.side_effect = stopping_side_effect
    with (
        patch(f"{EXECUTOR_MODULE}.settings.MAX_CONCURRENT_IN_PROCESS_RUNS", batch_size),
        patch.object(JobExecution, "claim_actionable", side_effect=claim_side_effect),
        patch.object(executor, "_dispatch"),
    ):
        executor._poll_loop()

    assert call_log == ["wait", "claim", "wait"]


def test_dispatch_takes_a_slot_for_an_in_process_job(executor, job_exec, mock_session):
    job_exec.in_process = True

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{EXECUTOR_MODULE}.subprocess.Popen"),
        patch(f"{EXECUTOR_MODULE}.threading.Thread"),
    ):
        executor._dispatch(job_exec)

    assert executor._in_process_jobs == {job_exec.id}


def test_dispatch_takes_no_slot_for_a_server_job(executor, job_exec, mock_session):
    job_exec.in_process = False

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{EXECUTOR_MODULE}.subprocess.Popen"),
        patch(f"{EXECUTOR_MODULE}.threading.Thread"),
    ):
        executor._dispatch(job_exec)

    assert executor._in_process_jobs == set()


def test_dispatch_takes_no_slot_when_the_process_fails_to_start(executor, job_exec, mock_session):
    job_exec.in_process = True

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{EXECUTOR_MODULE}.subprocess.Popen", side_effect=OSError("no fork")),
        pytest.raises(OSError),
    ):
        executor._dispatch(job_exec)

    assert executor._in_process_jobs == set()


@pytest.mark.parametrize("exit_code", [0, -9])
def test_proc_wrapper_frees_the_slot_however_the_process_ends(executor, job_exec, mock_session, exit_code):
    job_exec.status = "running"
    job_exec.in_process = True
    executor._in_process_jobs = {job_exec.id}
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock(pid=555)
    proc_mock.wait.return_value = exit_code

    executor._proc_wrapper(proc_mock, job_exec)

    assert executor._in_process_jobs == set()
    assert job_exec.id not in executor._running_jobs


def test_proc_wrapper_frees_the_slot_when_monitoring_fails(executor, job_exec, mock_session):
    job_exec.status = "running"
    job_exec.in_process = True
    executor._in_process_jobs = {job_exec.id}
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock(pid=555)
    proc_mock.wait.side_effect = OSError("broken")

    executor._proc_wrapper(proc_mock, job_exec)

    assert executor._in_process_jobs == set()


def test_dispatch_frees_the_slot_when_the_wrapper_cannot_start(executor, job_exec, mock_session):
    job_exec.in_process = True

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{EXECUTOR_MODULE}.subprocess.Popen"),
        patch(f"{EXECUTOR_MODULE}.threading.Thread") as thread_mock,
        pytest.raises(RuntimeError),
    ):
        thread_mock.return_value.start.side_effect = RuntimeError("can't start new thread")
        executor._dispatch(job_exec)

    assert executor._in_process_jobs == set()


def _wrapped(executor, proc_mock, job_exec):
    with (
        patch.object(executor, "_running_jobs_cond") as cond_mock,
        patch.object(executor, "_running_jobs"),
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        executor._proc_wrapper(proc_mock, job_exec)


def test_a_cancel_with_no_process_fires_the_callbacks_once(executor, mock_session):
    job_exec = JobExecution(id=uuid4(), job_key=JobKey.run_tests, kwargs={}, source="ui", status="cancel_requested")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="canceled")
    callback = Mock()

    with patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [callback]}):
        executor._handle_cancellation(job_exec)

    assert job_exec.status == "canceled"
    callback.assert_called_once_with(job_exec)


def test_a_crashed_job_process_fires_the_callbacks_once(executor, job_exec, mock_session):
    job_exec.status = "running"
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock(pid=555)
    proc_mock.wait.return_value = -9
    callback = Mock()

    with patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [callback]}):
        _wrapped(executor, proc_mock, job_exec)

    callback.assert_called_once_with(job_exec)


def test_a_cleanly_exited_job_process_fires_no_callbacks(executor, job_exec, mock_session):
    """The job process settled its own row and fired its own callbacks."""
    job_exec.status = "running"
    proc_mock = Mock(pid=555)
    proc_mock.wait.return_value = 0
    callback = Mock()

    with patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [callback]}):
        _wrapped(executor, proc_mock, job_exec)

    callback.assert_not_called()


def test_a_processing_failure_settles_the_row_without_callbacks(executor, job_exec, mock_session):
    """The real run state is unknown here, and a live job process may still finish and settle it."""
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    executor._stopping = Mock()
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



@pytest.fixture
def executor_db_session():
    """Patch the executor module's session context manager, yielding a mock session."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=session)
    ctx.__exit__ = Mock(return_value=False)
    with patch(f"{EXECUTOR_MODULE}.database_session", return_value=ctx):
        yield session


@pytest.mark.parametrize("proc_exit_code", [0, 1])
def test_proc_wrapper_status(proc_exit_code, executor):
    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with (
        patch.object(executor, "_running_jobs_cond") as cond_mock,
        patch.object(executor, "_running_jobs") as dict_mock,
        patch("testgen.common.models.Session", return_value=mock_session),
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        proc_mock = Mock()
        proc_mock.pid = 555
        proc_mock.wait.return_value = proc_exit_code
        job_exec_mock = Mock(spec=JobExecution)

        executor._proc_wrapper(proc_mock, job_exec_mock)

        dict_mock.__setitem__.assert_called_once()
        dict_mock.__delitem__.assert_called_once()
        cond_mock.notify_all.assert_called_once()
        if proc_exit_code == 0:
            # exec_job owns mark_completed — wrapper is a no-op on success
            job_exec_mock.mark_completed.assert_not_called()
        else:
            # Crash recovery: wrapper calls mark_failed on nonzero exit
            job_exec_mock.mark_failed.assert_called_once()


def test_proc_wrapper_unregisters_a_job_whose_monitoring_failed(executor):
    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with (
        patch.object(executor, "_running_jobs_cond") as cond_mock,
        patch.object(executor, "_running_jobs") as dict_mock,
        patch("testgen.common.models.Session", return_value=mock_session),
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        proc_mock = Mock()
        proc_mock.pid = 555
        proc_mock.wait.side_effect = RuntimeError
        job_exec_mock = Mock(spec=JobExecution)

        executor._proc_wrapper(proc_mock, job_exec_mock)

        dict_mock.__setitem__.assert_called_once()
        dict_mock.__delitem__.assert_called_once()
        job_exec_mock.mark_failed.assert_called_once()


def test_pause_request_skipped_without_running_jobs(executor, executor_db_session):
    with patch.object(JobExecution, "request_interrupt_bulk") as request_pause:
        assert executor._request_interrupt_on_running_jobs() == set()

    request_pause.assert_not_called()


def test_pause_request_only_asks_pausable_keys(executor, executor_db_session):
    job_id = uuid4()
    executor._running_jobs[job_id] = MagicMock()

    with (
        patch.object(JobExecution, "request_interrupt_bulk", return_value={job_id}) as request_pause,
        patch(f"{EXECUTOR_MODULE}.PAUSABLE_JOB_KEYS", frozenset({JobKey.run_profile})),
    ):
        assert executor._request_interrupt_on_running_jobs() == {job_id}

    assert request_pause.call_args[0][0] == {job_id}
    assert request_pause.call_args[0][1] == frozenset({JobKey.run_profile})


def test_pause_request_does_not_wait(executor, executor_db_session):
    """Requesting a pause must not block: the shutdown wait that follows covers these jobs."""
    job_id = uuid4()
    executor._running_jobs[job_id] = MagicMock()

    with patch.object(JobExecution, "request_interrupt_bulk", return_value={job_id}):
        executor._request_interrupt_on_running_jobs()

    # The job is still registered, so nothing waited on it clearing.
    assert executor._running_jobs


def test_pause_request_survives_a_database_failure(executor, executor_db_session):
    executor._running_jobs[uuid4()] = MagicMock()

    with patch.object(JobExecution, "request_interrupt_bulk", side_effect=RuntimeError("no database")):
        assert executor._request_interrupt_on_running_jobs() == set()


def _armed_escalation(executor, proc, job_id=None):
    """Arm the kill escalation and hand back (delay, the callback the timer would fire)."""
    with patch(f"{EXECUTOR_MODULE}.threading.Timer") as timer:
        executor._schedule_force_kill(job_id or uuid4(), proc)
        delay, escalate = timer.call_args[0]
    return delay, escalate


def test_a_canceled_job_that_ignores_terminate_is_killed(executor):
    proc = MagicMock(returncode=None)

    delay, escalate = _armed_escalation(executor, proc)
    escalate()

    assert delay == settings.JOB_TERMINATE_TIMEOUT
    proc.kill.assert_called_once()


def test_a_canceled_job_that_exited_in_time_is_not_killed(executor):
    proc = MagicMock(returncode=0)

    _, escalate = _armed_escalation(executor, proc)
    escalate()

    proc.kill.assert_not_called()


def test_cancellation_arms_the_kill_escalation(executor, executor_db_session):
    job_exec = JobExecution(id=uuid4(), status="cancel_requested", job_key="run-profile")
    proc = MagicMock(returncode=None)
    executor._running_jobs[job_exec.id] = proc

    with patch.object(executor, "_schedule_force_kill") as escalation:
        executor._handle_cancellation(job_exec)

    proc.terminate.assert_called_once()
    escalation.assert_called_once_with(job_exec.id, proc)


def test_the_kill_deadline_is_armed_once_however_often_the_poll_asks(executor):
    """A cancel_requested row stays claimable until its process settles, so the poll re-enters
    the cancellation path every cycle -- without a guard each pass would arm its own SIGKILL."""
    job_id, proc = uuid4(), MagicMock(returncode=None)

    with patch(f"{EXECUTOR_MODULE}.threading.Timer") as timer:
        for _ in range(3):
            executor._schedule_force_kill(job_id, proc)

    assert timer.call_count == 1
