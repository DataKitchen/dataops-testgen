"""A lock file each job process holds for as long as it lives.

The operating system releases the lock when the process dies, however it dies, so a lock that
can be taken means no live process is running that job.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import UUID

LOCK_DIRECTORY = Path(tempfile.gettempdir()) / "testgen-job-locks"
_RETRY_INTERVAL = 0.2

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class JobLockHeld(Exception):
    """Another live process holds the job's lock."""


def _open(job_id: UUID) -> int:
    LOCK_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    return os.open(LOCK_DIRECTORY / f"{job_id}.lock", os.O_RDWR | os.O_CREAT, 0o600)


def hold(job_id: UUID, timeout: float) -> int:
    """Take the job's lock and return the descriptor that keeps it. The lock lasts until the
    descriptor is closed or the process dies.

    :param timeout: Seconds to keep trying while another process holds it.
    :raises JobLockHeld: The lock was still held when ``timeout`` ran out.
    """
    fd = _open(job_id)
    deadline = time.monotonic() + timeout
    while not _try_lock(fd):
        if time.monotonic() >= deadline:
            os.close(fd)
            raise JobLockHeld(f"Another process still holds the lock of job {job_id}")
        time.sleep(_RETRY_INTERVAL)
    return fd


def is_held(job_id: UUID) -> bool:
    """Whether a live process holds the job's lock."""
    if not (LOCK_DIRECTORY / f"{job_id}.lock").exists():
        return False
    fd = _open(job_id)
    try:
        if _try_lock(fd):
            # Released explicitly: Windows frees a lock left on a closed handle only eventually.
            _unlock(fd)
            return False
        return True
    finally:
        os.close(fd)


def remove(job_id: UUID) -> None:
    """Delete the job's lock file, if no process holds it."""
    path = LOCK_DIRECTORY / f"{job_id}.lock"
    if path.exists() and not is_held(job_id):
        path.unlink(missing_ok=True)
