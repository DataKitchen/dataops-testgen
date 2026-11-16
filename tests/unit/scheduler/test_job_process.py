import signal
import subprocess
import sys
import textwrap
import time
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from testgen import settings
from testgen.common.enums import STOPPABLE_JOB_KEYS
from testgen.common.models.job_execution import JobExecution
from testgen.scheduler import job_process

pytestmark = pytest.mark.unit

MODULE = "testgen.scheduler.job_process"


@pytest.fixture
def process_setup():
    with (
        patch(f"{MODULE}._detach_from_console"),
        patch(f"{MODULE}.signal.signal"),
        patch(f"{MODULE}.setup_process"),
        patch(f"{MODULE}.threading.Thread") as thread,
        patch(f"{MODULE}.job_lock") as lock,
        patch(f"{MODULE}.os.close") as close,
    ):
        lock.hold.return_value = 42
        yield lock, close, thread


def test_the_job_runs_holding_its_lock(process_setup):
    lock, close, thread = process_setup
    job_id, doorbell = uuid4(), MagicMock()

    with patch(f"{MODULE}.exec_job") as exec_job:
        exec_job.side_effect = lambda *_args: close.assert_not_called()
        job_process.run_job_process(job_id, doorbell)

    lock.hold.assert_called_once_with(job_id, timeout=settings.JOB_TERMINATE_TIMEOUT)
    exec_job.assert_called_once_with(job_id, doorbell)
    assert thread.call_args.kwargs["args"] == (job_id, doorbell)
    close.assert_called_once_with(42)
    lock.remove.assert_called_once_with(job_id)


def test_the_lock_is_released_when_the_job_raises(process_setup):
    lock, close, _ = process_setup

    with patch(f"{MODULE}.exec_job", side_effect=RuntimeError("database unreachable")), pytest.raises(RuntimeError):
        job_process.run_job_process(uuid4(), MagicMock())

    close.assert_called_once_with(42)


def test_a_job_whose_scheduler_is_gone_is_asked_to_stop_then_ended():
    job_id, doorbell = uuid4(), MagicMock()
    events = []

    with (
        patch(f"{MODULE}.multiprocessing.parent_process", return_value=MagicMock()),
        patch(f"{MODULE}.multiprocessing.connection.wait"),
        patch(f"{MODULE}.database_session"),
        patch.object(JobExecution, "request_interrupt_bulk", side_effect=lambda *_: events.append("interrupt")) as ask,
        patch(f"{MODULE}.time.sleep", side_effect=lambda seconds: events.append(("sleep", seconds))),
        patch(f"{MODULE}.remove_own_spill_directories", side_effect=lambda: events.append("spill")),
        patch(f"{MODULE}.os._exit", side_effect=lambda code: events.append(("exit", code))),
    ):
        doorbell.ring.side_effect = lambda: events.append("ring")
        job_process._watch_scheduler(job_id, doorbell)

    assert ask.call_args == call([job_id], STOPPABLE_JOB_KEYS)
    assert events == ["interrupt", "ring", ("sleep", settings.JOB_SHUTDOWN_TIMEOUT), "spill", ("exit", 1)]


def test_a_job_whose_scheduler_is_gone_is_rung_even_when_the_database_fails():
    doorbell = MagicMock()

    with (
        patch(f"{MODULE}.multiprocessing.parent_process", return_value=MagicMock()),
        patch(f"{MODULE}.multiprocessing.connection.wait"),
        patch(f"{MODULE}.database_session", side_effect=RuntimeError("no database")),
        patch(f"{MODULE}.time.sleep"),
        patch(f"{MODULE}.remove_own_spill_directories"),
        patch(f"{MODULE}.os._exit") as exit_,
    ):
        job_process._watch_scheduler(uuid4(), doorbell)

    doorbell.ring.assert_called_once()
    exit_.assert_called_once_with(1)


_TERMINATED_JOB = textwrap.dedent("""
    import os, sys, time, uuid
    from pathlib import Path
    from unittest.mock import MagicMock, patch
    from testgen.common import job_lock
    from testgen.common.database.flavor import duckdb_flavor_service
    from testgen.scheduler import job_process

    temp_directory = Path(sys.argv[1])

    def run(*_args):
        (temp_directory / f"{os.getpid()}-{uuid.uuid4().hex}").mkdir()
        (temp_directory / "ready").touch()
        time.sleep(60)

    with (
        patch.object(duckdb_flavor_service, "TEMP_DIRECTORY", temp_directory),
        patch.object(job_lock, "LOCK_DIRECTORY", Path(sys.argv[2])),
        patch.object(job_process, "setup_process"),
        patch.object(job_process, "exec_job", run),
    ):
        job_process.run_job_process(uuid.uuid4(), MagicMock())
""")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows terminates a job process without a signal")
def test_a_terminated_job_removes_its_spill(tmp_path):
    """A canceled job is sent SIGTERM, which ends the process before its exit hooks delete the run's local file copies."""
    spill, locks = tmp_path / "spill", tmp_path / "locks"
    spill.mkdir()
    other_process = spill / f"1-{uuid4().hex}"
    other_process.mkdir()
    proc = subprocess.Popen([sys.executable, "-c", _TERMINATED_JOB, str(spill), str(locks)])  # noqa: S603
    try:
        deadline = time.monotonic() + 60
        while not (spill / "ready").exists():
            assert proc.poll() is None, "the job process exited before it was ready"
            assert time.monotonic() < deadline, "the job process never became ready"
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == -signal.SIGTERM
    finally:
        proc.kill()
        proc.wait()

    assert sorted(path.name for path in spill.iterdir()) == sorted([other_process.name, "ready"])
