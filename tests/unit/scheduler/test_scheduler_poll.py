from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.exec_job import JOB_DISPATCH
from testgen.common.models.job_execution import JobExecution, JobStatus
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
        job_key="run-tests",
        args=[],
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
        patch.dict(JOB_DISPATCH, {"run-tests": Mock()}, clear=False),
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
        args=[],
        kwargs={},
        source="ui",
        status="claimed",
    )
    mock_session.execute.return_value.first.return_value = _returning_row(job_exec, status="error")

    with patch.dict(JOB_DISPATCH, {}, clear=True):
        scheduler_instance._dispatch(job_exec)

    # mark_interrupted tries error first (valid from claimed)
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
    mock_session.execute.return_value.first.return_value = _returning_row(job_exec, status="error")
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
    mock_session.execute.return_value.first.return_value = _returning_row(job_exec, status="error")
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

    claim_mock.assert_called_once_with(limit=scheduler_instance._poll_batch_size)
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
        job_key="run-tests",
        args=[],
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
        key="run-profile",
        args=[],
        kwargs={"table_group_id": "tg-123"},
        job_schedule_id=schedule_id,
    )

    scheduler_instance.start_job(job, datetime.now(UTC))

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.job_key == "run-profile"
    assert added.kwargs == {"table_group_id": "tg-123"}
    assert added.source == "scheduler"
    assert added.job_schedule_id == schedule_id
    mock_session.commit.assert_called_once()
