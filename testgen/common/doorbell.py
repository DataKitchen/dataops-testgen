"""A flag a scheduler and one of its job processes share, to tell the job to look at its row."""

import multiprocessing
from multiprocessing.context import BaseContext


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
