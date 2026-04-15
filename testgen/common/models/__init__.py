import contextlib
import functools
import platform
import threading
import urllib.parse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session as SQLAlchemySession, sessionmaker

from testgen import settings

engine = create_engine(
    url=(
        f"postgresql://{settings.DATABASE_USER}:{urllib.parse.quote_plus(str(settings.DATABASE_PASSWORD))}"
        f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    ),
    echo=False,
    connect_args={
        "application_name": platform.node(),
        # TimeZone=UTC so TIMESTAMP (no-tz) columns store aware UTC datetimes as-is.
        # Without this, pgserver inherits the OS TZ and silently shifts
        # timestamps on insert, which make_json_safe then re-reads as UTC.
        "options": f"-csearch_path={settings.DATABASE_SCHEMA} -c TimeZone=UTC",
    },
)

class Base(DeclarativeBase):
    # Allow legacy Column() + type-hint patterns without Mapped[].
    # Can be removed once all models use Mapped[] annotations.
    __allow_unmapped__ = True

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
