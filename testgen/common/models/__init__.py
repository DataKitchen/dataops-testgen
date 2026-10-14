import contextlib
import contextvars
import functools
import platform
import threading
import urllib.parse

import anyio
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.orm import Session as SQLAlchemySession

from testgen import settings

POOL_SIZE = 5
POOL_MAX_OVERFLOW = 10

engine = create_engine(
    url=(
        f"postgresql://{settings.DATABASE_USER}:{urllib.parse.quote_plus(str(settings.DATABASE_PASSWORD))}"
        f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    ),
    echo=False,
    pool_size=POOL_SIZE,
    max_overflow=POOL_MAX_OVERFLOW,
    connect_args={
        "application_name": platform.node(),
        # TimeZone=UTC so TIMESTAMP (no-tz) columns store aware UTC datetimes as-is.
        # Without this, pgserver inherits the OS TZ and silently shifts
        # timestamps on insert, which make_json_safe then re-reads as UTC.
        "options": f"-csearch_path={settings.DATABASE_SCHEMA} -c TimeZone=UTC",
        **settings.DATABASE_SSL_CONNECT_ARGS,
    },
)


@functools.cache
def session_limiter() -> anyio.CapacityLimiter:
    """Process-wide limit on the async requests that hold a database session at once, sized to the pool."""
    # Built on first use, because a limiter can only be created inside a running event loop.
    return anyio.CapacityLimiter(POOL_SIZE + POOL_MAX_OVERFLOW)


class Base(DeclarativeBase):
    # Allow legacy Column() + type-hint patterns without Mapped[].
    # Can be removed once all models use Mapped[] annotations.
    __allow_unmapped__ = True

    @classmethod
    def delete_where(cls, *clauses) -> int:
        """Single-statement DELETE on this model filtered by ``clauses``;
        returns the row count. Callers may ignore the return when not needed.
        """
        result = get_current_session().execute(delete(cls).where(*clauses))
        return result.rowcount or 0

Session = sessionmaker(
    engine,
    expire_on_commit=False,
)
_current_session_wrapper = threading.local()
_current_session_wrapper.value = None
# Takes precedence over the thread-local. Worker threads that asyncio and anyio start for a task
# receive a copy of the task's context, so a session bound here follows the task across threads.
_context_session: contextvars.ContextVar[SQLAlchemySession | None] = contextvars.ContextVar(
    "context_session", default=None
)


@contextlib.contextmanager
def database_session():
    """Provide a thread-local SQLAlchemy session.

    Nested: yields existing session, no lifecycle management.
    Owning: commits on clean exit, rolls back on Exception.

    Uses ``except Exception`` (not ``BaseException``) so that Streamlit's
    ``RerunException`` (a ``BaseException`` subclass) bypasses both rollback
    and auto-commit.  If ``safe_rerun()`` was called, it already committed.
    """
    existing = get_current_session()
    if existing:
        yield existing
        return
    with Session() as session:
        _current_session_wrapper.value = session
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
        finally:
            _current_session_wrapper.value = None


def with_database_session(func):
    """Decorator form of :func:`database_session`."""


    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with database_session():
            return func(*args, **kwargs)
    return wrapper


@contextlib.contextmanager
def bound_session(session: SQLAlchemySession):
    """Make ``session`` the current session in this context, and in every thread given a copy of it.

    Does not commit, roll back or close the session.
    """
    token = _context_session.set(session)
    try:
        yield session
    finally:
        _context_session.reset(token)


def get_current_session() -> SQLAlchemySession:
    session = _context_session.get()
    return session if session is not None else getattr(_current_session_wrapper, "value", None)
