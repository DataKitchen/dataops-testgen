import logging
import tempfile
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine.base import Connection
from sqlalchemy.pool import NullPool

from testgen import settings
from testgen.common.database.flavor.flavor_service import (
    ConnectionParameter,
    FlavorConnectionError,
    FlavorService,
    ResolvedConnectionParams,
)

LOG = logging.getLogger("testgen")

DATABASE_FILE_PARAMETER = "database_file"

# Where DuckDB spills when a query exceeds its memory limit. Its own default is ".tmp" relative to
# the working directory, which lands spill files wherever the UI or scheduler happened to start.
TEMP_DIRECTORY = Path(tempfile.gettempdir()) / "testgen-duckdb"

# The customer's database is attached under a fixed alias and selected with USE, so that the
# two-part schema.table references the templates emit resolve inside it.
ATTACHED_CATALOG = "tg_target"

# DuckDB holds the file lock for as long as a writer is connected, so a conflict means another
# process is mid-write rather than that the database is unusable. These bound how long a run
# waits for a write window to close before giving up.
_LOCK_RETRY_ATTEMPTS = 3
_LOCK_RETRY_INITIAL_WAIT_SECONDS = 2.0


# Paths DuckDB accepts that TestGen cannot use. MotherDuck starts an interactive SSO flow, which
# on a server means opening a browser nobody sees and blocking for a minute before giving up.
UNSUPPORTED_PATH_PREFIXES = ("md:", "motherduck:")


class AttachFailure(StrEnum):
    LOCKED = "locked"
    VERSION_MISMATCH = "version_mismatch"
    FILE_MISSING = "file_missing"
    INVALID_FILE = "invalid_file"
    UNKNOWN = "unknown"


class DuckdbConnectionError(FlavorConnectionError):
    """A DuckDB connection failure that carries a message worth showing to the user."""

    def __init__(self, message: str, failure: AttachFailure = AttachFailure.UNKNOWN) -> None:
        super().__init__(message)
        self.failure = failure


def classify_attach_error(error: Exception) -> AttachFailure:
    lowered = str(error).lower()
    if "conflicting lock" in lowered or "could not set lock" in lowered:
        return AttachFailure.LOCKED
    if (
        "trying to read a database file with version number" in lowered
        or "storage version greater than the latest version supported" in lowered
    ):
        return AttachFailure.VERSION_MISMATCH
    if "database does not exist" in lowered or "no such file" in lowered:
        return AttachFailure.FILE_MISSING
    if (
        "is not a valid duckdb database file" in lowered
        # What DuckDB reports for a path whose extension it recognizes as another format.
        or "cannot launch in-memory database in read-only mode" in lowered
    ):
        return AttachFailure.INVALID_FILE
    return AttachFailure.UNKNOWN


def attach_error_message(failure: AttachFailure, error: Exception) -> str:
    if failure is AttachFailure.LOCKED:
        # DuckDB names the holding process's executable path, PID and username. That is somebody
        # else's environment, so the detail is dropped rather than shown.
        return (
            "The database is open for writing by another process. TestGen can only read a DuckDB "
            "database when no other process is writing to it."
        )
    if failure is AttachFailure.VERSION_MISMATCH:
        # Both of DuckDB's wordings name the versions involved, which the detail carries through.
        return f"This database was written by a newer version of DuckDB than TestGen supports. {error}"
    if failure is AttachFailure.FILE_MISSING:
        message = "The database file was not found at this path."
        if settings.CHECK_FOR_LATEST_VERSION == "docker":
            message += " The path is read inside the TestGen container, not on the host."
        return message
    if failure is AttachFailure.INVALID_FILE:
        return "This file is not a DuckDB database."
    # The driver's own text, without the SQLAlchemy wrapper and the statement it appends.
    return f"Could not open the DuckDB database. {getattr(error, 'orig', error)}"


class DuckdbFlavorService(FlavorService):

    concat_operator = "||"
    quote_character = '"'
    escaped_single_quote = "''"
    escaped_underscore = "\\_"
    varchar_type = "VARCHAR"
    row_limiting_clause = "limit"
    default_uppercase = False
    url_scheme = "duckdb"
    qualifies_table_refs_with_schema = True

    parameters_schema = (
        ConnectionParameter(key=DATABASE_FILE_PARAMETER, label="Database File", required=True),
    )

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:  # noqa: ARG002
        # TestGen always opens its own in-memory database and attaches the customer's file to it,
        # so that the file is never opened as the default database and never written to.
        return f"{self.url_scheme}:///:memory:"

    def get_connection_string(self, params: ResolvedConnectionParams) -> str:
        # DuckDB offers no URL-mode connection, so a stored url is ignored rather than honored.
        return self.get_connection_string_from_fields(params)

    def get_engine_args(self, params: ResolvedConnectionParams) -> dict[str, Any]:  # noqa: ARG002
        # duckdb-engine defaults to SingletonThreadPool, under which ":memory:" is not shared
        # across checkouts and two concurrent connections collide on one DBAPI connection.
        # NullPool gives every checkout its own database, and with it a freshly read catalog.
        return {"poolclass": NullPool}

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        # Deliberately not the base class's connect_timeout, which DuckDB rejects.
        config: dict[str, str] = {"temp_directory": str(TEMP_DIRECTORY)}
        if settings.DUCKDB_EXTENSION_DIRECTORY:
            config["extension_directory"] = settings.DUCKDB_EXTENSION_DIRECTORY
        return {"config": config}

    def validate_parameters(self, parameters: dict[str, Any] | None) -> None:
        super().validate_parameters(parameters)
        database_file = ((parameters or {}).get(DATABASE_FILE_PARAMETER) or "").strip()
        if database_file.lower().startswith(UNSUPPORTED_PATH_PREFIXES):
            raise ValueError(
                "MotherDuck databases are not supported. Enter the path of a DuckDB database file."
            )

    def get_database_file(self, params: ResolvedConnectionParams) -> str:
        # Trimmed here because a pasted path routinely carries whitespace, and the failure it
        # produces otherwise is an unhelpful "file was not found".
        return ((params.parameters or {}).get(DATABASE_FILE_PARAMETER) or "").strip()

    def init(self, connection: Connection, params: ResolvedConnectionParams) -> None:
        database_file = self.get_database_file(params)
        if not database_file:
            raise DuckdbConnectionError("This connection has no database file configured.")

        self._attach(connection, database_file)
        connection.execute(text(f'USE "{ATTACHED_CATALOG}"'))
        # ATTACH participates in the transaction, so without this any later rollback on this
        # connection drops the catalog and every subsequent query fails on a name that no longer
        # resolves rather than on whatever actually went wrong.
        connection.commit()

    def _attach(self, connection: Connection, database_file: str) -> None:
        # ATTACH takes the path as a literal, not a bind parameter, and the path arrives from a
        # connection form, so the quote that would end the literal is escaped here.
        quoted_path = database_file.replace("'", "''")
        statement = text(f"ATTACH '{quoted_path}' AS \"{ATTACHED_CATALOG}\" (READ_ONLY)")
        wait = _LOCK_RETRY_INITIAL_WAIT_SECONDS
        for attempt in range(1, _LOCK_RETRY_ATTEMPTS + 1):
            try:
                connection.execute(statement)
            except Exception as error:
                failure = classify_attach_error(error)
                if failure is not AttachFailure.LOCKED or attempt == _LOCK_RETRY_ATTEMPTS:
                    raise DuckdbConnectionError(attach_error_message(failure, error), failure) from error
                # The failed ATTACH aborted the transaction. Without this the next attempt
                # raises "transaction is aborted" instead, which classifies as UNKNOWN and
                # replaces the message written for this case.
                connection.rollback()
                LOG.warning(
                    f"DuckDB database {database_file} is locked by a writer; "
                    f"retrying in {wait:.0f}s (attempt {attempt} of {_LOCK_RETRY_ATTEMPTS})"
                )
                time.sleep(wait)
                wait *= 2
            else:
                return
