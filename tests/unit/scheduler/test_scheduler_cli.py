import signal
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy
from testgen.scheduler.cli_scheduler import CliJob, CliScheduler

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
        patch("testgen.scheduler.cli_scheduler.JobSchedule.select_where") as mock,
    ):
        yield mock


@pytest.fixture
def job_data():
    with patch.dict("testgen.commands.exec_job.JOB_DISPATCH", {"test-job": Mock()}):
        yield {
            "cron_expr": "*/5 9-17 * * *",
            "cron_tz":  "UTC",
            "key":  "test-job",
            "args":  ["a"],
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
    for attr in ("cron_expr", "cron_tz", "key", "args", "kwargs"):
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
        cond_mock.notify.assert_called_once()
        if proc_exit_code == 0:
            # exec_job owns mark_completed — wrapper is a no-op on success
            job_exec_mock.mark_completed.assert_not_called()
        else:
            # Crash recovery: wrapper calls mark_interrupted on nonzero exit
            job_exec_mock.mark_interrupted.assert_called_once()


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
        job_exec_mock.mark_interrupted.assert_called_once()


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
