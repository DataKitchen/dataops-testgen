import signal
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy
from testgen.scheduler.cli_scheduler import CliJob, CliScheduler


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
def cmd_mock():
    opt_mock = Mock()
    opt_mock.opts = ["-b"]
    opt_mock.name = "b"

    cmd_mock = Mock()
    cmd_mock.params = [opt_mock]
    cmd_mock.name = "test-job"
    return cmd_mock


@pytest.fixture
def job_data(cmd_mock):
    with patch.dict("testgen.scheduler.cli_scheduler.JOB_REGISTRY", {"test-job": cmd_mock}):
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


@pytest.mark.unit
def test_get_jobs(scheduler_instance, db_jobs, job_sched):
    db_jobs.return_value = iter([job_sched])

    jobs = list(scheduler_instance.get_jobs())

    assert len(jobs) == 1
    assert isinstance(jobs[0], CliJob)
    for attr in ("cron_expr", "cron_tz", "key", "args", "kwargs"):
        assert getattr(jobs[0], attr) == getattr(job_sched, attr), f"Attribute '{attr}' does not match"


@pytest.mark.unit
def test_job_start(scheduler_instance, cli_job, cmd_mock, popen_mock, popen_proc_mock):
    with patch("testgen.scheduler.cli_scheduler.threading.Thread") as thread_mock:
        scheduler_instance.start_job(cli_job, datetime.now(UTC))

    call_args = popen_mock.call_args[0][0]
    assert call_args[2] == cmd_mock.name
    assert call_args[3] == cli_job.args[0]
    assert call_args[4], call_args[5] == cli_job.kwargs.items()[0]

    thread_mock.assert_called_once_with(target=scheduler_instance._proc_wrapper, args=(popen_proc_mock,))


@pytest.mark.unit
@pytest.mark.parametrize("proc_side_effect", (lambda: None, RuntimeError))
def test_proc_wrapper(proc_side_effect, scheduler_instance):
    with (
        patch.object(scheduler_instance, "_running_jobs_cond") as cond_mock,
        patch.object(scheduler_instance, "_running_jobs") as set_mock,
    ):
        cond_mock.__enter__.return_value = True
        proc_mock = Mock()
        proc_mock.pid = 555
        proc_mock.wait = Mock(side_effect=proc_side_effect)

        scheduler_instance._proc_wrapper(proc_mock)

        set_mock.add.assert_called_once()
        set_mock.remove.assert_called_once()
        cond_mock.notify.assert_called_once()


@pytest.mark.unit
def test_shutdown_no_jobs(scheduler_instance):
    with (
        patch.object(scheduler_instance, "start") as start_mock,
        patch.object(scheduler_instance, "shutdown") as shutdown_mock,
        patch.object(scheduler_instance, "wait") as wait_mock,
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


@pytest.mark.unit
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_shutdown(scheduler_instance, sig):
    with (
        patch.object(scheduler_instance, "start") as start_mock,
        patch.object(scheduler_instance, "shutdown") as shutdown_mock,
        patch.object(scheduler_instance, "wait") as wait_mock,
        patch("testgen.scheduler.cli_scheduler.signal.signal") as signal_mock,
    ):
        start_called = threading.Event()
        start_mock.side_effect = lambda *_: start_called.set()

        jobs = [MagicMock() for _ in range(5)]

        thread = threading.Thread(target=scheduler_instance.run)
        thread.start()

        start_called.wait()
        sig_handler = signal_mock.call_args[0][1]
        shutdown_mock.assert_not_called()

        for job in jobs:
            scheduler_instance._running_jobs.add(job)

        for send_sig_count in range(3):
            sig_handler(sig, None)
            time.sleep(0.05)
            for job in jobs:
                assert job.send_signal.call_count == send_sig_count
                if send_sig_count:
                    job.send_signal.assert_called_with(sig)

        scheduler_instance._running_jobs.clear()
        with scheduler_instance._running_jobs_cond:
            scheduler_instance._running_jobs_cond.notify()

        thread.join()

        shutdown_mock.assert_called_once()
        wait_mock.assert_called_once()
        assert not scheduler_instance._running_jobs
