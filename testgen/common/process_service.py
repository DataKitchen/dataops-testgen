import logging
import os

import psutil

from testgen import settings

LOG = logging.getLogger("testgen")


def get_current_process_id():
    return os.getpid()


def kill_profile_run(process_id):
    keywords = ["run-profile"]
    status, message = kill_process(process_id, keywords)
    return status, message


def kill_test_run(process_id):
    keywords = ["run-tests"]
    status, message = kill_process(process_id, keywords)
    return status, message


def kill_process(process_id, keywords=None):
    if settings.IS_DEBUG:
        msg = "Cannot kill processes in debug mode (threads are used instead of new process)"
        LOG.warn(msg)
        return False, msg
    try:
        process = psutil.Process(process_id)
        if process.name().lower() != "testgen":
            message = f"The process was not killed because the process_id {process_id} is not a testgen process. Details: {process.name()}"
            LOG.error(f"kill_process: {message}")
            return False, message

        if keywords:
            for keyword in keywords:
                if keyword.lower() not in process.cmdline():
                    message = f"The process was not killed because the keyword {keyword} was not found. Details: {process.cmdline()}"
                    LOG.error(f"kill_process: {message}")
                    return False, message

        process.terminate()
        process.wait(timeout=10)
        message = f"Process {process_id} has been terminated."
    except psutil.NoSuchProcess:
        message = f"No such process with PID {process_id}."
        LOG.exception(f"kill_process: {message}")
        return False, message
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
