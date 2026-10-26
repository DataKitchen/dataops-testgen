import functools
import logging
from collections.abc import Callable
from typing import Any

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
