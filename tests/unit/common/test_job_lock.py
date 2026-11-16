import os
import subprocess
import sys
import textwrap
import time
from uuid import uuid4

import pytest

from testgen.common import job_lock

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def lock_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(job_lock, "LOCK_DIRECTORY", tmp_path)
    return tmp_path


_HOLDER = textwrap.dedent("""
    import sys, time, uuid
    from pathlib import Path
    from testgen.common import job_lock

    job_lock.LOCK_DIRECTORY = Path(sys.argv[1])
    job_lock.hold(uuid.UUID(sys.argv[2]), timeout=0)
    (Path(sys.argv[1]) / "held").touch()
    time.sleep(60)
""")


def _start_holder(lock_directory, job_id):
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, str(lock_directory), str(job_id)])  # noqa: S603
    deadline = time.monotonic() + 60
    while not (lock_directory / "held").exists():
        assert proc.poll() is None, "the holder exited before it took the lock"
        assert time.monotonic() < deadline, "the holder never took the lock"
        time.sleep(0.05)
    return proc


def test_a_job_with_no_lock_file_has_no_live_process():
    assert job_lock.is_held(uuid4()) is False


def test_a_lock_held_by_a_live_process_reads_as_held_until_the_process_is_killed(lock_directory):
    job_id = uuid4()
    proc = _start_holder(lock_directory, job_id)
    try:
        assert job_lock.is_held(job_id) is True
        with pytest.raises(job_lock.JobLockHeld):
            job_lock.hold(job_id, timeout=0)
    finally:
        proc.kill()
        proc.wait()

    assert job_lock.is_held(job_id) is False


def test_probing_a_lock_does_not_take_it():
    job_id = uuid4()
    assert job_lock.is_held(job_id) is False
    assert job_lock.is_held(job_id) is False

    os.close(job_lock.hold(job_id, timeout=0))


def test_removing_a_lock_spares_one_a_live_process_holds(lock_directory):
    job_id = uuid4()
    proc = _start_holder(lock_directory, job_id)
    try:
        job_lock.remove(job_id)
        assert (lock_directory / f"{job_id}.lock").exists()
    finally:
        proc.kill()
        proc.wait()

    job_lock.remove(job_id)
    assert not (lock_directory / f"{job_id}.lock").exists()
