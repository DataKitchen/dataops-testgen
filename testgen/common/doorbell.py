"""A flag a scheduler and one of its job processes share, to tell the job to look at its row."""

import multiprocessing
from multiprocessing.context import BaseContext


class Doorbell:
    """Rung by the scheduler when a job's row holds a request, cleared by the job before it reads.

    Created in the scheduler and handed to the job process as an argument when the process starts.
    """

    def __init__(self, context: BaseContext | None = None) -> None:
        self._event = (context or multiprocessing.get_context("spawn")).Event()

    def ring(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    def is_rung(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the doorbell is rung or ``timeout`` passes. Returns whether it was rung."""
        return self._event.wait(timeout)
