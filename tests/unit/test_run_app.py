import signal
from unittest.mock import MagicMock, patch

import pytest

from testgen.__main__ import run_app

pytestmark = pytest.mark.unit

MODULE = "testgen.__main__"


class FakeChild:
    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, _timeout=None):
        return self.returncode


def _run_all(children, on_start=None):
    spawned = iter(children)
    handler = {}

    def forward(child, _signum):
        child.returncode = 0

    with (
        patch(f"{MODULE}.subprocess.Popen", side_effect=lambda *_args, **_kwargs: next(spawned)),
        patch(f"{MODULE}._subprocess_spawn_kwargs", return_value={}),
        patch(f"{MODULE}._install_shutdown_handler", side_effect=lambda fn: handler.setdefault("fn", fn)),
        patch(f"{MODULE}._forward_signal_to_child", side_effect=forward),
        patch(f"{MODULE}.CHILDREN_POLL_INTERVAL", 0),
    ):
        if on_start:
            on_start(handler)
        run_app.callback("all")


@pytest.mark.parametrize("returncode", [0, 1])
def test_a_module_that_dies_fails_the_app_and_stops_the_others(returncode):
    survivors = [FakeChild(), FakeChild()]

    with pytest.raises(SystemExit) as exit_info:
        _run_all([FakeChild(returncode), *survivors])

    assert exit_info.value.code == 1
    assert all(child.returncode == 0 for child in survivors)


def test_a_requested_shutdown_exits_cleanly():
    children = [FakeChild(), FakeChild(), FakeChild()]
    stop = MagicMock()

    def shutdown_on_first_wait(handler):
        def wait(_timeout=None):
            handler["fn"](signal.SIGTERM, None)
            stop()
            return 0

        children[0].wait = wait

    _run_all(children, on_start=shutdown_on_first_wait)

    stop.assert_called_once()
    assert all(child.returncode == 0 for child in children)
