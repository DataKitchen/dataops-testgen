"""Embedded PostgreSQL server for standalone (pip-only) installations.

When TestGen is installed with `pip install testgen[standalone]`, this module
manages an embedded PostgreSQL instance via `pixeltable-pgserver`. The server
stores its data under a configurable directory and runs as the current OS
user — no Docker, no system Postgres, no root access required.
"""

import atexit
import logging
import os
import platform
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from testgen import settings

LOG = logging.getLogger("testgen")

_server = None

STANDALONE_MODE_ENV_VAR = "TG_STANDALONE_MODE"
HOME_DIR_ENV_VAR = "TG_TESTGEN_HOME"
STANDALONE_URI_ENV_VAR = "_TG_STANDALONE_URI"


def get_home_dir() -> Path:
    env_dir = os.getenv(HOME_DIR_ENV_VAR)
    return Path(env_dir) if env_dir else Path.home() / ".testgen"


def is_standalone_mode() -> bool:
    return settings.getenv(STANDALONE_MODE_ENV_VAR, "no").lower() in ("yes", "true", "1")


def start_server(data_dir: Path | None = None) -> None:
    """Start the embedded PostgreSQL server.

    The server persists data across restarts in *data_dir* (default
    ``$TG_TESTGEN_HOME/pgdata`` or ``~/.testgen/pgdata``).

    Calling this multiple times is safe — the second call is a no-op
    if the server is already running.
    """
    global _server

    if _server is not None:
        return

    try:
        import pixeltable_pgserver as pgserver
    except ImportError:
        raise RuntimeError(
            "Standalone mode requires the 'standalone' extra. "
            "Install with: pip install testgen[standalone]"
        ) from None

    if data_dir is None:
        data_dir = get_home_dir() / "pgdata"
    data_dir.mkdir(parents=True, exist_ok=True)

    LOG.info("Starting embedded PostgreSQL (data: %s) ...", data_dir)
    _server = pgserver.get_server(data_dir)
    LOG.info("Embedded PostgreSQL ready: %s", _server.get_uri())

    _reinitialize_orm_engine()
    atexit.register(stop_server)


def get_server_uri() -> str | None:
    """Return the pgserver URI if the server is running in this process, else ``None``."""
    return _server.get_uri() if _server is not None else None


def ensure_standalone_setup(server_uri: str) -> None:
    """Reinitialize the ORM engine to connect to an already-running embedded instance.

    Called by child processes (e.g. Streamlit) that receive the URI from
    their parent — they should NOT start pgserver themselves.
    """
    if _server is not None:
        return
    _reinitialize_orm_engine(server_uri)


def _reinitialize_orm_engine(base_uri: str | None = None) -> None:
    """Recreate the ORM engine to use the embedded Unix socket URI.

    ``models/__init__`` creates its engine at import time from
    ``settings.DATABASE_*`` (TCP).  After the embedded server starts we
    must replace that engine so the ORM connects via Unix socket.
    """
    from sqlalchemy import create_engine
    from testgen.common import models

    uri = _build_connection_string(settings.DATABASE_NAME, base_uri)
    models.engine.dispose()
    models.engine = create_engine(
        url=uri,
        echo=False,
        connect_args={
            "application_name": platform.node(),
            # Keep in sync with models/__init__.py — UTC avoids silent tz shifts on TIMESTAMP inserts.
            "options": f"-csearch_path={settings.DATABASE_SCHEMA} -c TimeZone=UTC",
        },
    )
    models.Session.configure(bind=models.engine)


def stop_server() -> None:
    """Stop the embedded PostgreSQL server if running."""
    global _server
    if _server is not None:
        LOG.info("Stopping embedded PostgreSQL ...")
        _server.cleanup()
        _server = None


def get_connection_string(database_name: str) -> str:
    """Return a SQLAlchemy connection string for the given database on the embedded server."""
    return _build_connection_string(database_name)


def _build_connection_string(database_name: str, base_uri: str | None = None) -> str:
    """Build a Unix socket connection string, replacing the database in the path.

    Resolution order for the base URI:
    1. Caller-provided ``base_uri``.
    2. ``_server.get_uri()`` when pgserver is running in this process (parent CLI).
    3. ``STANDALONE_URI_ENV_VAR`` env var — set by the parent for child processes
       (Streamlit UI, scheduler) that share the already-running instance.
    """
    if base_uri is None:
        if _server is not None:
            base_uri = _server.get_uri()
        else:
            base_uri = os.environ.get(STANDALONE_URI_ENV_VAR)
        if not base_uri:
            raise RuntimeError("Embedded PostgreSQL server is not running")
    parsed = urlparse(base_uri)
    return urlunparse(parsed._replace(path=f"/{database_name}"))
