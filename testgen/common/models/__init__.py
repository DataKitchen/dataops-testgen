import contextlib
import functools
import platform
import threading
import urllib.parse

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm import sessionmaker

from testgen import settings

engine = create_engine(
    url=(
        f"postgresql://{settings.DATABASE_USER}:{urllib.parse.quote_plus(str(settings.DATABASE_PASSWORD))}"
        f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    ),
    echo=False,
    connect_args={
        "application_name": platform.node(),
        "options": f"-csearch_path={settings.DATABASE_SCHEMA}",
    },
)

Base = declarative_base()

Session = sessionmaker(
    engine,
    expire_on_commit=False,
)
_current_session_wrapper = threading.local()
_current_session_wrapper.value = None


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
        _current_session_wrapper.session_flushed = False
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


def get_current_session() -> SQLAlchemySession:
    return getattr(_current_session_wrapper, "value", None)


def session_had_writes() -> bool:
    """Check and reset the write-tracking flag.

    Returns True if the session flushed any writes since the flag was
    last reset (i.e. since the owning ``database_session()`` opened).
    """
    had_writes = getattr(_current_session_wrapper, "session_flushed", False)
    _current_session_wrapper.session_flushed = False
    return had_writes


@event.listens_for(Session, "after_flush")
def _track_writes(_session, _flush_context):
    _current_session_wrapper.session_flushed = True
