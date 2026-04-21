import logging
import os

import psutil

from testgen import settings

LOG = logging.getLogger("testgen")


def get_current_process_id():
    return os.getpid()


def kill_profile_run(process_id):
    status, message = kill_process(process_id, subcommand="run-profile")
    return status, message


def kill_test_run(process_id):
    status, message = kill_process(process_id, subcommand="run-tests")
    return status, message


def _is_testgen_process(process) -> bool:
    """A process is ours if any cmdline argument references the testgen entry point.

    The executable name varies by platform (e.g. macOS reports "Python" for the
    framework binary, Linux "python3.13", Docker "testgen") so we match on the
    command line instead.
    """
    return any("testgen" in arg.lower() for arg in process.cmdline())


def kill_process(process_id, subcommand: str | None = None):
    if settings.IS_DEBUG:
        msg = "Cannot kill processes in debug mode (threads are used instead of new process)"
        LOG.warn(msg)
        return False, msg
    try:
        process = psutil.Process(process_id)
        cmdline = process.cmdline()
        if not _is_testgen_process(process):
            message = f"The process was not killed because the process_id {process_id} is not a testgen process. Details: {process.name()} {cmdline}"
            LOG.error(f"kill_process: {message}")
            return False, message

        if subcommand and subcommand not in cmdline:
            message = f"The process was not killed because the subcommand {subcommand} was not found. Details: {cmdline}"
            LOG.error(f"kill_process: {message}")
            return False, message

        process.terminate()
        process.wait(timeout=10)
        message = f"Process {process_id} has been terminated."
    except psutil.NoSuchProcess:
        message = f"No such process with PID {process_id}."
        LOG.exception(f"kill_process: {message}")
        # Return "True" anyway so that run status is set to "Canceled"
        return True, message
    except psutil.AccessDenied:
        message = f"Access denied when trying to terminate process {process_id}."
        LOG.exception(f"kill_process: {message}")
        return False, message
    except psutil.TimeoutExpired:
        message = f"Process {process_id} did not terminate within the timeout period."
        LOG.exception(f"kill_process: {message}")
        return False, message
    LOG.info(f"kill_process: Success. {message}")
    return True, message
