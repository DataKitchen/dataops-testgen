import functools
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from testgen.common.models import get_current_session

LOG = logging.getLogger("testgen")


def never_raises(fallback: Callable[[], Any] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Make an audit function log any exception it raises and return ``fallback()`` instead, or ``None``.

    :param fallback: builds the value returned when the function fails.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception:
                LOG.exception("Audit %s failed", fn.__name__)
                return fallback() if fallback else None

        return wrapper

    return decorator


@contextmanager
def isolated_read() -> Iterator[Session]:
    """The current session, for a read an audit record needs.

    The read never flushes the session's pending changes, and a statement that fails rolls back only to a savepoint,
    so the transaction of the action being recorded stays usable.
    """
    session = get_current_session()
    with session.no_autoflush, session.connection().begin_nested():
        yield session
