from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.job_registry import JOB_DISPATCH, JobConfig
from testgen.common.enums import JobKey, JobStatus
from testgen.common.models.job_execution import JobExecution
from testgen.scheduler.cli_scheduler import CliScheduler

pytestmark = pytest.mark.unit

SCHEDULER_MODULE = "testgen.scheduler.cli_scheduler"


@pytest.fixture
def mock_session():
    """Provide a mock session via database_session context manager."""
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=session):
        yield session


@pytest.fixture
def scheduler_instance():
    with patch(f"{SCHEDULER_MODULE}.threading.Timer"):
        sched = CliScheduler()
        sched._poll_interval = 0
        yield sched


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


def test_dispatch_spawns_process(scheduler_instance, job_exec, mock_session):
    proc_mock = MagicMock()

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{SCHEDULER_MODULE}.subprocess.Popen", return_value=proc_mock) as popen_mock,
        patch(f"{SCHEDULER_MODULE}.threading.Thread") as thread_mock,
    ):
        scheduler_instance._dispatch(job_exec)

    call_args = popen_mock.call_args[0][0]
    assert "exec-job" in call_args
    assert str(job_exec.id) in call_args

    thread_mock.assert_called_once()


def test_dispatch_unknown_job_key(scheduler_instance, mock_session):
    job_exec = JobExecution(
        id=uuid4(),
        job_key="nonexistent",
        kwargs={},
        source="ui",
        status="claimed",
    )
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")

    with patch.dict(JOB_DISPATCH, {}, clear=True):
        scheduler_instance._dispatch(job_exec)

    # mark_failed tries error first (valid from claimed)
    assert job_exec.status == "error"


def test_proc_wrapper_success_is_noop(scheduler_instance, job_exec, mock_session):
    """On exit code 0, the wrapper does nothing — exec_job already handled lifecycle."""
    job_exec.status = "running"
    proc_mock = Mock()
    proc_mock.pid = 555
    proc_mock.wait.return_value = 0

    with (
        patch.object(scheduler_instance, "_running_jobs_cond") as cond_mock,
        patch.object(scheduler_instance, "_running_jobs") as dict_mock,
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        scheduler_instance._proc_wrapper(proc_mock, job_exec)

    # Status unchanged — exec_job handles mark_completed, not the wrapper
    assert job_exec.status == "running"
    mock_session.execute.assert_not_called()
    dict_mock.__setitem__.assert_called_once()
    dict_mock.__delitem__.assert_called_once()


def test_proc_wrapper_failure(scheduler_instance, job_exec, mock_session):
    job_exec.status = "running"
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock()
    proc_mock.pid = 555
    proc_mock.wait.return_value = 1

    with (
        patch.object(scheduler_instance, "_running_jobs_cond") as cond_mock,
        patch.object(scheduler_instance, "_running_jobs") as dict_mock,
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        scheduler_instance._proc_wrapper(proc_mock, job_exec)

    assert job_exec.status == "error"


def test_proc_wrapper_exception(scheduler_instance, job_exec, mock_session):
    job_exec.status = "running"
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock()
    proc_mock.pid = 555
    proc_mock.wait.side_effect = OSError("broken")

    with (
        patch.object(scheduler_instance, "_running_jobs_cond") as cond_mock,
        patch.object(scheduler_instance, "_running_jobs") as dict_mock,
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        scheduler_instance._proc_wrapper(proc_mock, job_exec)

    assert job_exec.status == "error"


def test_poll_loop_claims_and_dispatches(scheduler_instance, job_exec, mock_session):
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    scheduler_instance._stopping = Mock()
    scheduler_instance._stopping.wait.side_effect = stopping_side_effect

    with (
        patch.object(JobExecution, "claim_actionable", return_value=[job_exec]) as claim_mock,
        patch.object(scheduler_instance, "_dispatch") as dispatch_mock,
    ):
        scheduler_instance._poll_loop()

    claim_mock.assert_called_once_with(limit=scheduler_instance._poll_batch_size, in_process_slots=1)
    dispatch_mock.assert_called_once_with(job_exec)


def test_poll_loop_handles_claim_error(scheduler_instance, mock_session):
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    scheduler_instance._stopping = Mock()
    scheduler_instance._stopping.wait.side_effect = stopping_side_effect

    with patch.object(JobExecution, "claim_actionable", side_effect=RuntimeError("db down")):
        scheduler_instance._poll_loop()


def test_poll_loop_skips_wait_when_batch_full(scheduler_instance, mock_session):
    """When claim returns batch_size rows, skip the next wait to immediately re-poll."""
    batch_size = scheduler_instance._poll_batch_size
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

    scheduler_instance._stopping = Mock()
    scheduler_instance._stopping.wait.side_effect = stopping_side_effect

    with (
        patch.object(JobExecution, "claim_actionable", side_effect=claim_side_effect),
        patch.object(scheduler_instance, "_dispatch"),
    ):
        scheduler_instance._poll_loop()

    # Sequence: wait → claim(full) → claim(partial) → wait(exit)
    # The skip avoids a wait between the full-batch claim and the partial-batch claim
    assert call_log == ["wait", "claim", "claim", "wait"]


def test_poll_loop_routes_cancel_requested(scheduler_instance, mock_session):
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

    scheduler_instance._stopping = Mock()
    scheduler_instance._stopping.wait.side_effect = stopping_side_effect

    with (
        patch.object(JobExecution, "claim_actionable", return_value=[cancel_job]),
        patch.object(scheduler_instance, "_dispatch") as dispatch_mock,
        patch.object(scheduler_instance, "_handle_cancellation") as cancel_mock,
    ):
        scheduler_instance._poll_loop()

    dispatch_mock.assert_not_called()
    cancel_mock.assert_called_once_with(cancel_job)


def test_start_job_submits_execution(scheduler_instance, mock_session):
    from testgen.scheduler.base import DelayedPolicy
    from testgen.scheduler.cli_scheduler import CliJob

    schedule_id = uuid4()
    job = CliJob(
        cron_expr="*/5 * * * *",
        cron_tz="UTC",
        delayed_policy=DelayedPolicy.SKIP,
        key=JobKey.run_profile,
        kwargs={"table_group_id": "tg-123"},
        job_schedule_id=schedule_id,
    )

    scheduler_instance.start_job(job, datetime.now(UTC))

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.job_key == JobKey.run_profile
    assert added.kwargs == {"table_group_id": "tg-123"}
    assert added.source == "scheduler"
    assert added.job_schedule_id == schedule_id
    mock_session.commit.assert_called_once()


def _run_one_poll(scheduler_instance, actionable):
    """Run the poll loop for exactly one claim and return the claim mock."""
    call_count = 0

    def stopping_side_effect(timeout):
        nonlocal call_count
        call_count += 1
        return call_count > 1

    scheduler_instance._stopping = Mock()
    scheduler_instance._stopping.wait.side_effect = stopping_side_effect
    with (
        patch.object(JobExecution, "claim_actionable", return_value=actionable) as claim_mock,
        patch.object(scheduler_instance, "_dispatch"),
    ):
        scheduler_instance._poll_loop()
    return claim_mock


@pytest.mark.parametrize(("cap", "held", "expected_slots"), [(1, 0, 1), (1, 1, 0), (3, 1, 2), (2, 3, 0)])
def test_poll_offers_the_slots_left_under_the_cap(scheduler_instance, mock_session, cap, held, expected_slots):
    scheduler_instance._in_process_jobs = {uuid4() for _ in range(held)}

    with patch(f"{SCHEDULER_MODULE}.settings.MAX_CONCURRENT_IN_PROCESS_RUNS", cap):
        claim_mock = _run_one_poll(scheduler_instance, [])

    assert claim_mock.call_args.kwargs["in_process_slots"] == expected_slots


def test_claimed_in_process_rows_do_not_fill_the_batch(scheduler_instance, mock_session):
    """In-process rows are limited by the free slots, not by the batch, so a batch they fill says
    nothing about more rows waiting. Counting them would re-poll with no wait while the rest of
    the in-process queue is held."""
    batch_size = scheduler_instance._poll_batch_size
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

    scheduler_instance._stopping = Mock()
    scheduler_instance._stopping.wait.side_effect = stopping_side_effect
    with (
        patch(f"{SCHEDULER_MODULE}.settings.MAX_CONCURRENT_IN_PROCESS_RUNS", batch_size),
        patch.object(JobExecution, "claim_actionable", side_effect=claim_side_effect),
        patch.object(scheduler_instance, "_dispatch"),
    ):
        scheduler_instance._poll_loop()

    assert call_log == ["wait", "claim", "wait"]


def test_dispatch_takes_a_slot_for_an_in_process_job(scheduler_instance, job_exec, mock_session):
    job_exec.in_process = True

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{SCHEDULER_MODULE}.subprocess.Popen"),
        patch(f"{SCHEDULER_MODULE}.threading.Thread"),
    ):
        scheduler_instance._dispatch(job_exec)

    assert scheduler_instance._in_process_jobs == {job_exec.id}


def test_dispatch_takes_no_slot_for_a_server_job(scheduler_instance, job_exec, mock_session):
    job_exec.in_process = False

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{SCHEDULER_MODULE}.subprocess.Popen"),
        patch(f"{SCHEDULER_MODULE}.threading.Thread"),
    ):
        scheduler_instance._dispatch(job_exec)

    assert scheduler_instance._in_process_jobs == set()


def test_dispatch_takes_no_slot_when_the_process_fails_to_start(scheduler_instance, job_exec, mock_session):
    job_exec.in_process = True

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{SCHEDULER_MODULE}.subprocess.Popen", side_effect=OSError("no fork")),
        pytest.raises(OSError),
    ):
        scheduler_instance._dispatch(job_exec)

    assert scheduler_instance._in_process_jobs == set()


@pytest.mark.parametrize("exit_code", [0, -9])
def test_proc_wrapper_frees_the_slot_however_the_process_ends(scheduler_instance, job_exec, mock_session, exit_code):
    job_exec.status = "running"
    job_exec.in_process = True
    scheduler_instance._in_process_jobs = {job_exec.id}
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock(pid=555)
    proc_mock.wait.return_value = exit_code

    scheduler_instance._proc_wrapper(proc_mock, job_exec)

    assert scheduler_instance._in_process_jobs == set()
    assert job_exec.id not in scheduler_instance._running_jobs


def test_proc_wrapper_frees_the_slot_when_monitoring_fails(scheduler_instance, job_exec, mock_session):
    job_exec.status = "running"
    job_exec.in_process = True
    scheduler_instance._in_process_jobs = {job_exec.id}
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job_exec, status="error")
    proc_mock = Mock(pid=555)
    proc_mock.wait.side_effect = OSError("broken")

    scheduler_instance._proc_wrapper(proc_mock, job_exec)

    assert scheduler_instance._in_process_jobs == set()


def test_dispatch_frees_the_slot_when_the_wrapper_cannot_start(scheduler_instance, job_exec, mock_session):
    job_exec.in_process = True

    with (
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}, clear=False),
        patch(f"{SCHEDULER_MODULE}.subprocess.Popen"),
        patch(f"{SCHEDULER_MODULE}.threading.Thread") as thread_mock,
        pytest.raises(RuntimeError),
    ):
        thread_mock.return_value.start.side_effect = RuntimeError("can't start new thread")
        scheduler_instance._dispatch(job_exec)

    assert scheduler_instance._in_process_jobs == set()
