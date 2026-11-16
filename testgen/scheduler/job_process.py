"""What runs inside the process the scheduler starts for each job."""

import logging
import multiprocessing
import multiprocessing.connection
import os
import signal
import sys
import threading
import time
from uuid import UUID

from testgen import settings
from testgen.commands.exec_job import exec_job
from testgen.common import job_lock
from testgen.common.database.flavor.duckdb_flavor_service import remove_own_spill_directories
from testgen.common.doorbell import Doorbell
from testgen.common.enums import STOPPABLE_JOB_KEYS
from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.process_setup import setup_process

LOG = logging.getLogger("testgen")


def run_job_process(job_id: UUID, doorbell: Doorbell, verbose: bool = False) -> None:
    """Run job ``job_id`` in this process, which its scheduler started for it.

    The process holds the job's lock for as long as it lives, and stops the job when the scheduler
    that started it is gone.

    :param doorbell: Rung by the scheduler when the job's row holds a request.
    :param verbose: Log at DEBUG rather than INFO.
    """
    _detach_from_console()
    signal.signal(signal.SIGTERM, _terminate)
    # An earlier process of the same run can still be exiting after it parked the run.
    lock = job_lock.hold(job_id, timeout=settings.JOB_TERMINATE_TIMEOUT)
    setup_process(verbose=verbose)
    threading.Thread(target=_watch_scheduler, args=(job_id, doorbell), name="scheduler-watch", daemon=True).start()
    try:
        exec_job(job_id, doorbell)
    finally:
        os.close(lock)
        job_lock.remove(job_id)


def _detach_from_console() -> None:
    """Keep console interrupts (Ctrl+C, Ctrl+Break) away from the job: only its scheduler stops it."""
    if sys.platform != "win32":
        os.setsid()
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if sigbreak := getattr(signal, "SIGBREAK", None):
        signal.signal(sigbreak, signal.SIG_IGN)


def _terminate(signum: int, _frame: object) -> None:
    """Delete this process's local file copies and spill, then die of the signal."""
    # Ignored during cleanup: the scheduler can repeat the signal before the process is gone.
    signal.signal(signum, signal.SIG_IGN)
    try:
        remove_own_spill_directories()
    finally:
        # Dying of the signal rather than raising SystemExit keeps a terminated job from unwinding
        # through its handler's finally blocks, and leaves the exit status the scheduler settles it on.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)


def _watch_scheduler(job_id: UUID, doorbell: Doorbell) -> None:
    """Wait for the scheduler process to end, then stop the job, and end this process if the job
    has not stopped within ``JOB_SHUTDOWN_TIMEOUT``."""
    parent = multiprocessing.parent_process()
    if parent is None:
        return
    multiprocessing.connection.wait([parent.sentinel])

    LOG.warning("The scheduler is gone; stopping job %s", job_id)
    try:
        with database_session():
            JobExecution.request_interrupt_bulk([job_id], STOPPABLE_JOB_KEYS)
    except Exception:
        LOG.exception("Could not request an interrupt on job %s", job_id)
    doorbell.ring()

    time.sleep(settings.JOB_SHUTDOWN_TIMEOUT)
    LOG.warning("Job %s did not stop within %ds of its scheduler's exit; ending it", job_id, settings.JOB_SHUTDOWN_TIMEOUT)
    try:
        remove_own_spill_directories()
    finally:
        os._exit(1)
