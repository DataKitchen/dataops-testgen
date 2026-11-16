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
def clock():
    """A fake monotonic clock that ``time.sleep`` advances, so loops with deadlines run instantly."""
    now = [0.0]
    with (
        patch(f"{MODULE}.time.monotonic", side_effect=lambda: now[0]),
        patch(f"{MODULE}.time.sleep", side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)) as sleep,
    ):
        yield sleep


def test_the_job_runs_with_its_doorbell_and_a_scheduler_watcher():
    job_id, doorbell = uuid4(), MagicMock()

    with (
        patch(f"{MODULE}._detach_from_console"),
        patch(f"{MODULE}.signal.signal"),
        patch(f"{MODULE}.setup_process"),
        patch(f"{MODULE}.threading.Thread") as thread,
        patch(f"{MODULE}.exec_job") as exec_job,
    ):
        job_process.run_job_process(job_id, doorbell)

    exec_job.assert_called_once_with(job_id, doorbell)
    assert thread.call_args.kwargs["args"] == (job_id, doorbell)
    thread.return_value.start.assert_called_once()


def _watch_a_dead_scheduler(job_id, doorbell, **patches):
    exits = []
    with (
        patch(f"{MODULE}.multiprocessing.parent_process", return_value=MagicMock()),
        patch(f"{MODULE}.multiprocessing.connection.wait"),
        patch(f"{MODULE}.database_session", **patches.pop("session", {})),
        patch(f"{MODULE}.remove_own_spill_directories") as spill,
        patch(f"{MODULE}.os._exit", side_effect=exits.append),
        patch.object(JobExecution, "request_interrupt_bulk", **patches.pop("ask", {})) as ask,
    ):
        job_process._watch_scheduler(job_id, doorbell)
    return ask, spill, exits


def test_a_job_whose_scheduler_is_gone_is_asked_to_stop_until_its_deadline_then_ended(clock):
    """Asked repeatedly: a job still starting when its scheduler died cannot take the first request."""
    job_id, doorbell = uuid4(), MagicMock()

    ask, spill, exits = _watch_a_dead_scheduler(job_id, doorbell)

    assert ask.call_count == settings.JOB_SHUTDOWN_TIMEOUT
    assert ask.call_args == call([job_id], STOPPABLE_JOB_KEYS)
    assert doorbell.ring.call_count == settings.JOB_SHUTDOWN_TIMEOUT
    assert sum(sleep.args[0] for sleep in clock.call_args_list) == settings.JOB_SHUTDOWN_TIMEOUT
    spill.assert_called_once()
    assert exits == [1]


def test_a_job_whose_scheduler_is_gone_is_rung_even_when_the_database_fails(clock):
    doorbell = MagicMock()

    _, _, exits = _watch_a_dead_scheduler(uuid4(), doorbell, session={"side_effect": RuntimeError("no database")})

    assert doorbell.ring.called
    assert exits == [1]


_TERMINATED_JOB = textwrap.dedent("""
    import os, sys, time, uuid
    from pathlib import Path
    from unittest.mock import MagicMock, patch
    from testgen.common.database.flavor import duckdb_flavor_service
    from testgen.scheduler import job_process

    temp_directory = Path(sys.argv[1])

    def run(*_args):
        (temp_directory / f"{os.getpid()}-{uuid.uuid4().hex}").mkdir()
        (temp_directory / "ready").touch()
        time.sleep(60)

    with (
        patch.object(duckdb_flavor_service, "TEMP_DIRECTORY", temp_directory),
        patch.object(job_process, "setup_process"),
        patch.object(job_process, "exec_job", run),
    ):
        job_process.run_job_process(uuid.uuid4(), MagicMock())
""")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows terminates a job process without a signal")
def test_a_terminated_job_removes_its_spill(tmp_path):
    """A canceled job is sent SIGTERM, which ends the process before its exit hooks delete the run's local file copies."""
    spill = tmp_path / "spill"
    spill.mkdir()
    other_process = spill / f"1-{uuid4().hex}"
    other_process.mkdir()
    proc = subprocess.Popen([sys.executable, "-c", _TERMINATED_JOB, str(spill)])  # noqa: S603
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
