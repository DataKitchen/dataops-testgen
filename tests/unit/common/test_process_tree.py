import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest

from testgen.common import process_tree
from testgen.common.process_tree import end_with_this_process

pytestmark = pytest.mark.unit

# Starts a grandchild, binds it to this process, then waits to be ended. The grandchild reports its own PID:
# in a Windows venv, sys.executable is a redirector that runs the interpreter as a further process, so
# Popen.pid would name the redirector rather than the interpreter that must end.
_PARENT_SCRIPT = """
import subprocess, sys, time
from testgen.common.process_tree import end_with_this_process
grandchild = subprocess.Popen([sys.executable, "-c", "import os, time; print(os.getpid(), flush=True); time.sleep(120)"])
end_with_this_process(grandchild)
time.sleep(120)
"""


def _is_running(pid: int) -> bool:
    tasks = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],  # noqa: S603, S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return str(pid) in tasks


@pytest.mark.skipif(sys.platform != "win32", reason="Job objects are Windows-only")
def test_a_bound_process_ends_when_its_parent_is_terminated():
    parent = subprocess.Popen([sys.executable, "-c", _PARENT_SCRIPT], stdout=subprocess.PIPE, text=True)  # noqa: S603
    grandchild_pid = None
    try:
        grandchild_pid = int(parent.stdout.readline())
        assert _is_running(grandchild_pid)

        parent.terminate()
        parent.wait()

        deadline = time.monotonic() + 10
        while _is_running(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _is_running(grandchild_pid)
    finally:
        parent.kill()
        parent.wait()
        parent.stdout.close()
        if grandchild_pid is not None:
            subprocess.run(["taskkill", "/F", "/PID", str(grandchild_pid)], capture_output=True, check=False)  # noqa: S603, S607


def test_a_failure_to_bind_leaves_the_child_running_and_is_logged(monkeypatch, caplog):
    child = MagicMock(pid=1234)
    monkeypatch.setattr(
        process_tree, "_bind_to_this_process", MagicMock(side_effect=PermissionError("Access is denied"))
    )

    end_with_this_process(child)

    child.kill.assert_not_called()
    child.terminate.assert_not_called()
    assert "1234" in caplog.text
    assert "Access is denied" in caplog.text
