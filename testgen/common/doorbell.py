"""A flag a scheduler and one of its job processes share, to tell the job to look at its row."""

import multiprocessing
import time
from multiprocessing.context import BaseContext

_WAIT_STEP = 0.05


class Doorbell:
    """Rung by the scheduler when a job's row holds a request, cleared by the job before it reads.

    Created in the scheduler and handed to the job process as an argument when the process starts.
    """

    def __init__(self, context: BaseContext | None = None) -> None:
        # A single shared byte with no lock: either process can be killed at any instant, and a
        # lock it held would stay held for good.
        self._flag = (context or multiprocessing.get_context("spawn")).RawValue("b", 0)

    def ring(self) -> None:
        self._flag.value = 1

    def clear(self) -> None:
        self._flag.value = 0

    def is_rung(self) -> bool:
        return self._flag.value == 1

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the doorbell is rung or ``timeout`` passes. Returns whether it was rung."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_rung():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(_WAIT_STEP)
        return True
