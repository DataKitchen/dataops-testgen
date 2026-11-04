"""Tracks the target-database statements this process is running, so a stopping job can cancel them.

A job process runs one job, and every target statement goes through the process's one target
engine, so tracking per process is tracking per job.
"""

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, ExceptionContext

if TYPE_CHECKING:
    from testgen.common.database.flavor.flavor_service import FlavorService

LOG = logging.getLogger("testgen")


class StatementsCanceled(Exception):
    """A target statement was refused because this process canceled its statements."""

    def __init__(self) -> None:
        super().__init__("The run was stopped before this query started")


@dataclass(frozen=True)
class RunningStatement:
    """A statement a worker is running: the driver's connection and cursor that run it, and the
    engine they came from, for a connection type that cancels from a connection of its own."""
    engine: Engine
    dbapi_connection: Any
    cursor: Any


_lock = threading.Lock()
_running: dict[int, tuple[RunningStatement, "FlavorService"]] = {}
_canceled = threading.Event()


def track_statements(engine: Engine, flavor_service: "FlavorService") -> None:
    """Keep a record of the statements ``engine`` runs, for :func:`cancel_target_statements`.

    Once statements were canceled, the engine refuses to start another.
    """

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn: Connection, cursor: Any, *_args: Any) -> None:
        if _canceled.is_set():
            raise StatementsCanceled
        with _lock:
            _running[threading.get_ident()] = (
                RunningStatement(conn.engine, conn.connection.dbapi_connection, cursor),
                flavor_service,
            )

    # Keyed by thread: a thread runs one statement at a time, and the error event does not always
    # carry the cursor.
    @event.listens_for(engine, "after_cursor_execute")
    def _after(*_args: Any) -> None:
        with _lock:
            _running.pop(threading.get_ident(), None)

    @event.listens_for(engine, "handle_error")
    def _error(_context: ExceptionContext) -> None:
        with _lock:
            _running.pop(threading.get_ident(), None)


def cancel_target_statements() -> int:
    """Cancel every target statement this process is running, and refuse any new one.

    Each connection type cancels in its own way; one that cannot leaves its statements to finish.
    A failure to cancel one statement is logged and does not stop the others.

    :returns: How many statements were asked to cancel.
    """
    _canceled.set()
    with _lock:
        running = list(_running.values())
    asked = 0
    for statement, flavor_service in running:
        try:
            if flavor_service.cancel_statement(statement):
                asked += 1
        except Exception:
            LOG.warning("Could not cancel a running query on the data source", exc_info=True)
    if running:
        LOG.info("Canceled %d of %d running queries on the data source", asked, len(running))
    return asked


def statements_canceled() -> bool:
    """Whether this process canceled its target statements."""
    return _canceled.is_set()


def reset() -> None:
    """Forget the cancel and every tracked statement. For tests."""
    _canceled.clear()
    with _lock:
        _running.clear()
