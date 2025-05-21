import functools
import platform
import threading
import urllib.parse

from sqlalchemy import create_engine
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


def with_database_session(func):
    """
    Set up a thread-global SQLAlchemy session to be accessed
    calling `get_current_session()` from any place.

    NOTE: Call once on the main entry point.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            session = get_current_session()
            if session:
                return func(*args, **kwargs)

            with Session() as session:
                _current_session_wrapper.value = session
                return func(*args, **kwargs)
        finally:
            _current_session_wrapper.value = None
    return wrapper


def get_current_session() -> SQLAlchemySession:
    return getattr(_current_session_wrapper, "value", None)
