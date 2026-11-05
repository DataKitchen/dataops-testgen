"""Tracks the statements an engine is running, so a stopping job can cancel them."""

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, ExceptionContext

if TYPE_CHECKING:
    from testgen.common.database.flavor.flavor_service import FlavorService

LOG = logging.getLogger("testgen")

T = TypeVar("T")


class StatementsCanceled(Exception):
    """A statement was refused because its engine's statements were canceled."""

    def __init__(self) -> None:
        super().__init__("The run was stopped before this query started")


@dataclass(frozen=True)
class RunningStatement:
    """A statement a worker is running: the driver's connection and cursor that run it, and the
    engine they came from, for a connection type that cancels from a connection of its own."""
    engine: Engine
    dbapi_connection: Any
    cursor: Any


class StatementTracker:
    """The statements one engine is running, and whether they were canceled.

    Each thread runs one statement at a time, so the running statements are kept by thread: the
    error event does not always carry the cursor. Once canceled, the engine refuses to start
    another statement, on every thread.
    """

    def __init__(self, engine: Engine, flavor_service: "FlavorService") -> None:
        self._flavor_service = flavor_service
        self._lock = threading.Lock()
        self._running: dict[int, RunningStatement] = {}
        self._canceled = threading.Event()
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._forget)
        event.listen(engine, "handle_error", self._on_error)

    def cancel(self) -> int:
        """Cancel every statement the engine is running, and refuse any new one.

        Each connection type cancels in its own way; one that cannot leaves its statements to
        finish.

        :returns: How many statements were asked to cancel.
        """
        self._canceled.set()
        with self._lock:
            running = list(self._running.values())
        if not running:
            return 0
        asked = self._flavor_service.cancel_statements(running)
        LOG.info("Canceled %d of %d running queries on the data source", asked, len(running))
        return asked

    def _before(self, conn: Connection, cursor: Any, *_args: Any) -> None:
        if self._canceled.is_set():
            raise StatementsCanceled
        with self._lock:
            self._running[threading.get_ident()] = RunningStatement(conn.engine, conn.connection.dbapi_connection, cursor)

    def _forget(self, *_args: Any) -> None:
        with self._lock:
            self._running.pop(threading.get_ident(), None)

    def _on_error(self, _context: ExceptionContext) -> None:
        self._forget()


_trackers: "WeakKeyDictionary[Engine, StatementTracker]" = WeakKeyDictionary()


def track_statements(engine: Engine, flavor_service: "FlavorService") -> StatementTracker:
    """Keep a record of the statements ``engine`` runs, for :func:`cancel_statements`."""
    tracker = StatementTracker(engine, flavor_service)
    _trackers[engine] = tracker
    return tracker


def cancel_statements(engine: Engine) -> int:
    """Cancel the statements ``engine`` is running and refuse any new one, if it is tracked.

    :returns: How many statements were asked to cancel.
    """
    tracker = _trackers.get(engine)
    return tracker.cancel() if tracker else 0


def cancel_each(items: Sequence[T], cancel: Callable[[T], bool]) -> int:
    """Pass each item to ``cancel``, logging a failure rather than stopping at it.

    :param items: The running statements, or what identifies each to the data source.
    :param cancel: Cancels one, and returns whether the cancel was sent.
    :returns: How many cancels were sent.
    """
    asked = 0
    for item in items:
        try:
            if cancel(item):
                asked += 1
        except Exception:
            LOG.warning("Could not cancel a running query on the data source", exc_info=True)
    return asked
