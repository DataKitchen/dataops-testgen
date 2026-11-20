import logging
import subprocess
import sys

if sys.platform == "win32":
    import pywintypes
    import win32api
    import win32con
    import win32job

LOG = logging.getLogger("testgen")

# pywin32 closes a job's handle when its object is garbage-collected, which would end the processes in it
_held_jobs: list[object] = []


def end_with_this_process(child: subprocess.Popen) -> None:
    """Make Windows end *child* when this process ends, however it ends.

    On Windows, *child* goes into a job object that ends every process in it when its only handle
    closes, which happens when this process ends. That covers this process being ended with
    TerminateProcess, which runs no handler that could stop *child*. On other platforms this does
    nothing.

    A failure is logged, and leaves *child* running outside the job.
    """
    try:
        _bind_to_this_process(child.pid)
    except _BIND_ERRORS as error:
        LOG.warning(f"Process {child.pid} may outlive this process: {error}")


if sys.platform == "win32":
    _BIND_ERRORS: tuple[type[Exception], ...] = (OSError, pywintypes.error)

    def _bind_to_this_process(pid: int) -> None:
        # Created without security attributes, so not inheritable: no process in the job holds it open
        # The types-pywin32 stub declares no return value, but the call returns the job's handle
        job = win32job.CreateJobObject(None, "")  # type: ignore[func-returns-value]
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        process = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        win32job.AssignProcessToJobObject(job, process)
        _held_jobs.append(job)

else:
    _BIND_ERRORS: tuple[type[Exception], ...] = (OSError,)

    def _bind_to_this_process(_pid: int) -> None:
        pass
