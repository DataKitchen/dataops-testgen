import signal
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen import settings
from testgen.commands.job_registry import JobConfig
from testgen.common.enums import JobKey, JobSource
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy
from testgen.scheduler.cli_scheduler import CliJob, CliScheduler, run_scheduler

pytestmark = pytest.mark.unit


@pytest.fixture
def scheduler_instance() -> CliScheduler:
    with patch("testgen.scheduler.cli_scheduler.threading.Timer"):
        yield CliScheduler()


@pytest.fixture
def popen_barrier():
    yield threading.Barrier(2)


@pytest.fixture
def popen_proc_mock(popen_barrier):
    mock = MagicMock()
    mock.wait.side_effect = popen_barrier.wait
    yield mock


@pytest.fixture
def popen_mock(popen_proc_mock):
    with patch("testgen.scheduler.cli_scheduler.subprocess.Popen", return_value=popen_proc_mock) as mock:
        yield mock


@pytest.fixture
def db_jobs(scheduler_instance):
    with (
        patch("testgen.scheduler.cli_scheduler.JobSchedule.select_runnable") as mock,
    ):
        yield mock


@pytest.fixture
def job_data():
    with patch.dict("testgen.commands.job_registry.JOB_DISPATCH", {"test-job": JobConfig(handler=Mock())}):
        yield {
            "cron_expr": "*/5 9-17 * * *",
            "cron_tz":  "UTC",
            "key":  "test-job",
            "kwargs":  {"b": "c"},
        }


@pytest.fixture
def job_sched(job_data):
    yield JobSchedule(**job_data)


@pytest.fixture
def cli_job(job_data):
    yield CliJob(**job_data, delayed_policy=DelayedPolicy.SKIP)


def test_get_jobs(scheduler_instance, db_jobs, job_sched):
    db_jobs.return_value = iter([job_sched])

    jobs = list(scheduler_instance.get_jobs())

    assert len(jobs) == 1
    assert isinstance(jobs[0], CliJob)
    for attr in ("cron_expr", "cron_tz", "key", "kwargs"):
        assert getattr(jobs[0], attr) == getattr(job_sched, attr), f"Attribute '{attr}' does not match"


def test_job_start(scheduler_instance, cli_job):
    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=mock_session):
        scheduler_instance.start_job(cli_job, datetime.now(UTC))

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.job_key == cli_job.key
    assert added.kwargs == cli_job.kwargs
    assert added.source == "scheduler"
    assert added.job_schedule_id == cli_job.job_schedule_id
    mock_session.commit.assert_called_once()


def test_job_start_tags_source_from_job_config(scheduler_instance, job_data):
    """Scheduled executions inherit `JobConfig.scheduler_source` as their
    `JobExecution.source`. Retention cleanup (registered with
    `scheduler_source="system"`) gets `source="system"` so MCP / REST /
    api/deps filters auto-hide it from user-facing surfaces."""
    from testgen.scheduler.cli_scheduler import CliJob

    system_job_data = {**job_data, "key": JobKey.run_data_cleanup}
    system_cli_job = CliJob(**system_job_data, delayed_policy=DelayedPolicy.SKIP)

    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with (
        patch.dict(
            "testgen.commands.job_registry.JOB_DISPATCH",
            {JobKey.run_data_cleanup: JobConfig(handler=Mock(), scheduler_source=JobSource.system)},
        ),
        patch("testgen.common.models.Session", return_value=mock_session),
    ):
        scheduler_instance.start_job(system_cli_job, datetime.now(UTC))

    added = mock_session.add.call_args[0][0]
    assert added.source == "system"


@pytest.mark.parametrize("proc_exit_code", [0, 1])
def test_proc_wrapper_status(proc_exit_code, scheduler_instance):
    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with (
        patch.object(scheduler_instance, "_running_jobs_cond") as cond_mock,
        patch.object(scheduler_instance, "_running_jobs") as dict_mock,
        patch("testgen.common.models.Session", return_value=mock_session),
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        proc_mock = Mock()
        proc_mock.pid = 555
        proc_mock.wait.return_value = proc_exit_code
        job_exec_mock = Mock(spec=JobExecution)

        scheduler_instance._proc_wrapper(proc_mock, job_exec_mock)

        dict_mock.__setitem__.assert_called_once()
        dict_mock.__delitem__.assert_called_once()
        cond_mock.notify_all.assert_called_once()
        if proc_exit_code == 0:
            # exec_job owns mark_completed — wrapper is a no-op on success
            job_exec_mock.mark_completed.assert_not_called()
        else:
            # Crash recovery: wrapper calls mark_failed on nonzero exit
            job_exec_mock.mark_failed.assert_called_once()


def test_proc_wrapper_exception(scheduler_instance):
    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with (
        patch.object(scheduler_instance, "_running_jobs_cond") as cond_mock,
        patch.object(scheduler_instance, "_running_jobs") as dict_mock,
        patch("testgen.common.models.Session", return_value=mock_session),
    ):
        cond_mock.__enter__ = Mock(return_value=True)
        cond_mock.__exit__ = Mock(return_value=False)
        proc_mock = Mock()
        proc_mock.pid = 555
        proc_mock.wait.side_effect = RuntimeError
        job_exec_mock = Mock(spec=JobExecution)

        scheduler_instance._proc_wrapper(proc_mock, job_exec_mock)

        dict_mock.__setitem__.assert_called_once()
        dict_mock.__delitem__.assert_called_once()
        job_exec_mock.mark_failed.assert_called_once()


def test_shutdown_no_jobs(scheduler_instance):
    with (
        patch.object(scheduler_instance, "start") as start_mock,
        patch.object(scheduler_instance, "shutdown") as shutdown_mock,
        patch.object(scheduler_instance, "wait") as wait_mock,
        patch.object(scheduler_instance, "_poll_loop"),
        patch("testgen.scheduler.cli_scheduler.signal.signal") as signal_mock,
    ):
        start_called = threading.Event()
        start_mock.side_effect = lambda *_: start_called.set()

        thread = threading.Thread(target=scheduler_instance.run)
        thread.start()

        start_called.wait()
        sig_hanlder = signal_mock.call_args[0][1]
        shutdown_mock.assert_not_called()

        sig_hanlder(15, None)

        thread.join()

        shutdown_mock.assert_called_once()
        wait_mock.assert_called_once()
        assert not scheduler_instance._running_jobs


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_shutdown(scheduler_instance, sig):
    with (
        patch.object(scheduler_instance, "start") as start_mock,
        patch.object(scheduler_instance, "shutdown") as shutdown_mock,
        patch.object(scheduler_instance, "wait") as wait_mock,
        patch.object(scheduler_instance, "_poll_loop"),
        # Covered on its own below; here it would only reach for a database.
        patch.object(scheduler_instance, "_request_interrupt_on_running_jobs", return_value=set()),
        patch("testgen.scheduler.cli_scheduler.signal.signal") as signal_mock,
    ):
        start_called = threading.Event()
        start_mock.side_effect = lambda *_: start_called.set()

        procs = [MagicMock() for _ in range(5)]

        thread = threading.Thread(target=scheduler_instance.run)
        thread.start()

        start_called.wait()
        sig_handler = signal_mock.call_args[0][1]
        shutdown_mock.assert_not_called()

        for proc in procs:
            scheduler_instance._running_jobs[uuid4()] = proc

        for send_sig_count in range(3):
            sig_handler(sig, None)
            time.sleep(0.05)
            for proc in procs:
                assert proc.send_signal.call_count == send_sig_count
                if send_sig_count:
                    proc.send_signal.assert_called_with(sig)

        scheduler_instance._running_jobs.clear()
        with scheduler_instance._running_jobs_cond:
            scheduler_instance._running_jobs_cond.notify()

        thread.join()

        shutdown_mock.assert_called_once()
        wait_mock.assert_called_once()
        assert not scheduler_instance._running_jobs


@pytest.fixture
def scheduler_db_session():
    """Patch the scheduler module's session context manager, yielding a mock session."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=session)
    ctx.__exit__ = Mock(return_value=False)
    with patch("testgen.scheduler.cli_scheduler.database_session", return_value=ctx):
        yield session


def test_pause_request_skipped_without_running_jobs(scheduler_instance, scheduler_db_session):
    with patch.object(JobExecution, "request_interrupt_bulk") as request_pause:
        assert scheduler_instance._request_interrupt_on_running_jobs() == set()

    request_pause.assert_not_called()


def test_pause_request_only_asks_pausable_keys(scheduler_instance, scheduler_db_session):
    job_id = uuid4()
    scheduler_instance._running_jobs[job_id] = MagicMock()

    with (
        patch.object(JobExecution, "request_interrupt_bulk", return_value={job_id}) as request_pause,
        patch("testgen.scheduler.cli_scheduler.PAUSABLE_JOB_KEYS", frozenset({JobKey.run_profile})),
    ):
        assert scheduler_instance._request_interrupt_on_running_jobs() == {job_id}

    assert request_pause.call_args[0][0] == {job_id}
    assert request_pause.call_args[0][1] == frozenset({JobKey.run_profile})


def test_pause_request_does_not_wait(scheduler_instance, scheduler_db_session):
    """Requesting a pause must not block: the shutdown wait that follows covers these jobs."""
    job_id = uuid4()
    scheduler_instance._running_jobs[job_id] = MagicMock()

    with patch.object(JobExecution, "request_interrupt_bulk", return_value={job_id}):
        scheduler_instance._request_interrupt_on_running_jobs()

    # The job is still registered, so nothing waited on it clearing.
    assert scheduler_instance._running_jobs


def test_pause_request_survives_a_database_failure(scheduler_instance, scheduler_db_session):
    scheduler_instance._running_jobs[uuid4()] = MagicMock()

    with patch.object(JobExecution, "request_interrupt_bulk", side_effect=RuntimeError("no database")):
        assert scheduler_instance._request_interrupt_on_running_jobs() == set()


def _armed_escalation(scheduler_instance, proc, job_id=None):
    """Arm the kill escalation and hand back (delay, the callback the timer would fire)."""
    with patch("testgen.scheduler.cli_scheduler.threading.Timer") as timer:
        scheduler_instance._schedule_force_kill(job_id or uuid4(), proc)
        delay, escalate = timer.call_args[0]
    return delay, escalate


def test_a_canceled_job_that_ignores_terminate_is_killed(scheduler_instance):
    proc = MagicMock(returncode=None)

    delay, escalate = _armed_escalation(scheduler_instance, proc)
    escalate()

    assert delay == settings.JOB_TERMINATE_TIMEOUT
    proc.kill.assert_called_once()


def test_a_canceled_job_that_exited_in_time_is_not_killed(scheduler_instance):
    proc = MagicMock(returncode=0)

    _, escalate = _armed_escalation(scheduler_instance, proc)
    escalate()

    proc.kill.assert_not_called()


def test_cancellation_arms_the_kill_escalation(scheduler_instance, scheduler_db_session):
    job_exec = JobExecution(id=uuid4(), status="cancel_requested", job_key="run-profile")
    proc = MagicMock(returncode=None)
    scheduler_instance._running_jobs[job_exec.id] = proc

    with patch.object(scheduler_instance, "_schedule_force_kill") as escalation:
        scheduler_instance._handle_cancellation(job_exec)

    proc.terminate.assert_called_once()
    escalation.assert_called_once_with(job_exec.id, proc)


def test_the_kill_deadline_is_armed_once_however_often_the_poll_asks(scheduler_instance):
    """A cancel_requested row stays claimable until its process settles, so the poll re-enters
    the cancellation path every cycle -- without a guard each pass would arm its own SIGKILL."""
    job_id, proc = uuid4(), MagicMock(returncode=None)

    with patch("testgen.scheduler.cli_scheduler.threading.Timer") as timer:
        for _ in range(3):
            scheduler_instance._schedule_force_kill(job_id, proc)

    assert timer.call_count == 1


def test_the_shutdown_wait_is_bounded(scheduler_instance):
    """Waiting past the runtime's stop grace period gets the whole container killed, so a job
    that will not stop must cost the scheduler its deadline, not its clean exit."""
    with patch.object(scheduler_instance, "_running_jobs_cond") as cond:
        cond.__enter__ = Mock(return_value=cond)
        cond.__exit__ = Mock(return_value=False)
        cond.wait_for.return_value = False
        scheduler_instance._running_jobs[uuid4()] = MagicMock()
        with (
            patch.object(scheduler_instance, "start"),
            patch.object(scheduler_instance, "shutdown"),
            patch.object(scheduler_instance, "wait"),
            patch.object(scheduler_instance, "_poll_loop"),
            patch.object(scheduler_instance, "_request_interrupt_on_running_jobs", return_value=set()),
            patch("testgen.scheduler.cli_scheduler.signal.signal"),
            patch("testgen.scheduler.cli_scheduler.threading.Event") as event,
        ):
            event.return_value.wait.return_value = None
            scheduler_instance.run()

    assert cond.wait_for.call_args.kwargs["timeout"] == settings.JOB_SHUTDOWN_TIMEOUT


def test_run_scheduler_settles_stale_jobs_before_starting(scheduler_db_session):
    with (
        patch("testgen.scheduler.cli_scheduler.check_db_is_ready", return_value=True),
        patch.object(JobExecution, "recover_stale", return_value=2) as recover,
        patch("testgen.scheduler.cli_scheduler.CliScheduler") as scheduler_cls,
    ):
        run_scheduler()

    recover.assert_called_once()
    scheduler_cls.return_value.run.assert_called_once()


@pytest.mark.parametrize(
    ("revision_check", "ready"),
    [
        ({"return_value": True}, True),
        ({"return_value": False}, False),
        ({"side_effect": RuntimeError('relation "tg_revision" does not exist')}, False),
    ],
)
def test_the_scheduler_starts_only_on_a_schema_this_version_matches(revision_check, ready):
    from testgen.scheduler.cli_scheduler import check_db_is_ready

    with patch("testgen.scheduler.cli_scheduler.is_db_revision_up_to_date", **revision_check):
        assert check_db_is_ready() is ready


def test_the_scheduler_waits_for_the_upgrade_instead_of_exiting(scheduler_db_session):
    with (
        patch("testgen.scheduler.cli_scheduler.is_db_revision_up_to_date", side_effect=[False, False, True]),
        patch("testgen.scheduler.cli_scheduler.time.sleep") as sleep,
        patch.object(JobExecution, "recover_stale", return_value=0) as recover,
        patch("testgen.scheduler.cli_scheduler.CliScheduler"),
    ):
        run_scheduler()

    assert sleep.call_count == 2
    recover.assert_called_once()
