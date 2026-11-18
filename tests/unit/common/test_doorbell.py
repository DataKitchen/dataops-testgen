import subprocess
import sys
import textwrap

import pytest

from testgen.common.doorbell import Doorbell

pytestmark = pytest.mark.unit


def test_a_doorbell_stays_rung_until_cleared():
    doorbell = Doorbell()
    assert doorbell.is_rung() is False

    doorbell.ring()
    doorbell.ring()
    assert doorbell.is_rung() is True

    doorbell.clear()
    assert doorbell.is_rung() is False


# Spins on the doorbell in a child process, kills it at random moments, and rings after each kill.
_KILLED_MID_CHECK = textwrap.dedent("""
    import multiprocessing, os, random, signal, threading, time
    from testgen.common.doorbell import Doorbell

    def spin(doorbell, ready):
        ready.set()
        while True:
            doorbell.is_rung()
            doorbell.clear()

    if __name__ == "__main__":
        ctx = multiprocessing.get_context("spawn")
        for _ in range(3):
            doorbell, ready = Doorbell(ctx), ctx.Event()
            child = ctx.Process(target=spin, args=(doorbell, ready))
            child.start()
            ready.wait()
            time.sleep(random.random() * 0.05)
            os.kill(child.pid, signal.SIGKILL)
            child.join()
            rang = threading.Event()
            threading.Thread(target=lambda: (doorbell.ring(), rang.set()), daemon=True).start()
            if not rang.wait(5):
                raise SystemExit("a ring hung after the other process was killed")
""")


@pytest.mark.skipif(sys.platform == "win32", reason="Kills the child with SIGKILL")
def test_a_process_killed_while_checking_the_doorbell_leaves_it_usable(tmp_path):
    """Either process can be killed at any instant: a cancel timeout, an out-of-memory kill, a stop."""
    script = tmp_path / "killed_mid_check.py"
    script.write_text(_KILLED_MID_CHECK)

    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120)  # noqa: S603

    assert result.returncode == 0, result.stdout + result.stderr
