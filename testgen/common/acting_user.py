"""The user acting in the current unit of work, for records that name their author."""

import logging
from collections.abc import Callable

from testgen.common.models import get_current_session

LOG = logging.getLogger("testgen")

_SESSION_KEY = "acting_username"
_fallbacks: list[Callable[[], str | None]] = []


def set_acting_username(username: str | None) -> None:
    """Record ``username`` as the acting user on the current database session. No-op without one."""
    session = get_current_session()
    if session is not None:
        session.info[_SESSION_KEY] = username


def register_acting_user_fallback(fallback: Callable[[], str | None]) -> None:
    """Register a lookup consulted when the current database session names no acting user."""
    if fallback not in _fallbacks:
        _fallbacks.append(fallback)


def acting_username() -> str | None:
    """The acting user recorded on the current database session, else the first a fallback returns, else None."""
    session = get_current_session()
    if session is not None and (username := session.info.get(_SESSION_KEY)):
        return username
    for fallback in _fallbacks:
        try:
            if username := fallback():
                return username
        except Exception:
            LOG.debug("Acting user fallback failed", exc_info=True)
    return None
