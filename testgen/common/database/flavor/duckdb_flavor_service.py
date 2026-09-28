import logging
import os
import re
import shutil
import tempfile
import time
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine.base import Connection
from sqlalchemy.pool import NullPool, QueuePool

from testgen import settings
from testgen.common.database.file_declarations import (
    BASE_PATH_PARAMETER,
    FileDeclaration,
    create_view_statement,
    file_count_query,
    skip_reason,
)
from testgen.common.database.flavor.flavor_service import (
    ConnectionField,
    FlavorConnectionError,
    FlavorService,
    ResolvedConnectionParams,
)
from testgen.common.flavors import SqlFlavorCode, declares_files, fixed_table_group_schema

LOG = logging.getLogger("testgen")

DATABASE_FILE_PARAMETER = "database_file"

# Where view-creation failures are left for the caller. The connection is the only thing shared
# between building the views and running the queries that then cannot find them.
_DECLARATION_FAILURES_KEY = "file_declaration_failures"

# How many files Test Connection counts before it stops walking and reports a floor instead. A
# mounted data directory can hold far more than anyone wants counted to answer "is the mount wired
# up?".
_FILE_COUNT_LIMIT = 10_000

# Where DuckDB spills when a query exceeds its memory limit. Its own default is ".tmp" relative to
# the working directory, which lands spill files wherever the UI or scheduler happened to start.
TEMP_DIRECTORY = Path(tempfile.gettempdir()) / "testgen-duckdb"

# Leaf directories are named <pid>-<hex>, so the sweep can tell an orphan from one a live process
# is still writing to, and so it only ever considers directories this module created. Age alone
# cannot tell them apart: DuckDB grows its spill files in place, so a long run's directory can go
# untouched indefinitely. The pid run is bounded because it reaches os.kill, which rejects a value
# too wide for a C int.
_SPILL_DIRECTORY_PATTERN = re.compile(r"(\d{1,7})-[0-9a-f]{32}")

# Reached only once the owning pid is gone, so within one pid namespace it guards little. It earns
# its place where pids cannot be trusted to mean anything -- a spill root shared between containers
# -- by keeping the sweep off anything recent enough to still be in use.
_STALE_SPILL_AGE = timedelta(hours=1)

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


def expand_path(value: str | None) -> str:
    """The path with surrounding whitespace dropped and a leading ``~`` expanded.

    DuckDB expands ``~`` itself, so a path only TestGen inspects has to be expanded the same way
    or the two disagree about which file a connection names.
    """
    text_value = (value or "").strip()
    return str(Path(text_value).expanduser()) if text_value.startswith("~") else text_value


# A URL DuckDB opens through an extension rather than from the filesystem, so the rule below
# does not apply to it.
_REMOTE_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def _require_absolute_path(value: str | None, label: str) -> None:
    """Raise ``ValueError`` unless ``value`` names an absolute path once ``~`` is expanded.

    A relative path resolves against whatever directory the process was started in, which is the
    repository root in development and ``/dk`` in the container, so the same connection reads a
    different place depending on who opened it. A remote URL is left alone.
    """
    path = expand_path(value)
    if _REMOTE_URL.match(path):
        return
    if not Path(path).is_absolute():
        raise ValueError(f"{label} must be an absolute path.")


def container_path_note() -> str:
    if settings.CHECK_FOR_LATEST_VERSION != "docker":
        return ""
    return " The path is read inside the TestGen container, not on the host."


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
        return "The database file was not found at this path." + container_path_note()
    if failure is AttachFailure.INVALID_FILE:
        return "This file is not a DuckDB database."
    # The driver's own text, without the SQLAlchemy wrapper and the statement it appends.
    return f"Could not open the DuckDB database. {getattr(error, 'orig', error)}"


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # Refused rather than undeliverable, which means there is a process there to refuse it.
        return True
    return True


def sweep_stale_spill_directories() -> None:
    """Remove spill directories orphaned by a process killed before it could clean up.

    Best effort: it runs to make room for work, and no directory it cannot handle stops it or
    reaches the caller.
    """
    try:
        if TEMP_DIRECTORY.is_symlink():
            # The path is predictable and its parent is world-writable on a standalone install, so
            # following a link here would empty out whatever it was pointed at.
            LOG.warning(f"The DuckDB spill directory {TEMP_DIRECTORY} is a symlink, so it is left alone")
            return
        entries = list(TEMP_DIRECTORY.iterdir())
    except OSError:
        return

    cutoff = (datetime.now(UTC) - _STALE_SPILL_AGE).timestamp()
    for entry in entries:
        try:
            owner = _SPILL_DIRECTORY_PATTERN.fullmatch(entry.name)
            if not owner or entry.is_symlink() or _process_is_alive(int(owner.group(1))):
                continue
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry)
        except Exception as error:
            LOG.warning(f"Could not remove stale DuckDB spill directory {entry}: {error}")


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

    # The engine ships inside the package, so the pinned version decides and nothing needs probing.
    supports_approx_percentile = True

    def parameters_schema(self, sql_flavor_code: str) -> tuple[ConnectionField, ...]:
        if sql_flavor_code == SqlFlavorCode.FILES:
            return (ConnectionField(key=BASE_PATH_PARAMETER, label="Base Path", required=True),)
        return (ConnectionField(key=DATABASE_FILE_PARAMETER, label="Database File", required=True),)

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:  # noqa: ARG002
        # TestGen always opens its own in-memory database and attaches the customer's file to it,
        # so that the file is never opened as the default database and never written to.
        return f"{self.url_scheme}:///:memory:"

    def get_connection_string(self, params: ResolvedConnectionParams) -> str:
        # DuckDB offers no URL-mode connection, so a stored url is ignored rather than honored.
        return self.get_connection_string_from_fields(params)

    def get_engine_args(self, params: ResolvedConnectionParams) -> dict[str, Any]:
        if params.sql_flavor_code == SqlFlavorCode.FILES:
            # One database for the engine's lifetime, so the declaration views are built once
            # rather than on every checkout. Building them reads the head of every file the
            # declaration matches, which on a remote filesystem is a request per file, and a run
            # opens a connection per column. ``set_target_db_params`` disposes the engine whenever
            # the target changes, so the views never outlive the declarations they came from.
            #
            # A pool of one rather than StaticPool: StaticPool hands the same connection to every
            # caller at once, and two checkouts each opening a transaction on it fail with
            # "cannot start a transaction within a transaction". A pool lends it exclusively.
            #
            # The timeout is the wait for a turn. A run fans out across
            # ``Connection.effective_max_threads``, which is 1 here, so nothing should ever queue
            # and a wait means a connection was leaked or a caller is holding two at once. Short
            # enough to say so while the cause is still findable.
            return {"poolclass": QueuePool, "pool_size": 1, "max_overflow": 0, "pool_timeout": 30}
        # A read-only ATTACH held for the engine's lifetime locks the customer's file against
        # their own writer for the whole run, where attaching per checkout leaves gaps between
        # queries.
        #
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

    def validate_parameters(self, parameters: dict[str, Any] | None, sql_flavor_code: str) -> None:
        super().validate_parameters(parameters, sql_flavor_code)
        values = parameters or {}

        if sql_flavor_code == SqlFlavorCode.FILES:
            _require_absolute_path(values.get(BASE_PATH_PARAMETER), "Base Path")
            return

        database_file = (values.get(DATABASE_FILE_PARAMETER) or "").strip()
        if database_file.lower().startswith(UNSUPPORTED_PATH_PREFIXES):
            raise ValueError(
                "MotherDuck databases are not supported. Enter the path of a DuckDB database file."
            )
        _require_absolute_path(database_file, "Database File")

    def get_database_file(self, params: ResolvedConnectionParams) -> str:
        # Trimmed here because a pasted path routinely carries whitespace, and the failure it
        # produces otherwise is an unhelpful "file was not found".
        return expand_path((params.parameters or {}).get(DATABASE_FILE_PARAMETER))

    def get_base_path(self, params: ResolvedConnectionParams) -> str:
        return expand_path((params.parameters or {}).get(BASE_PATH_PARAMETER))

    def test_connection_details(self, params: ResolvedConnectionParams) -> str | None:
        if params.sql_flavor_code != SqlFlavorCode.FILES:
            return None
        count, capped = self._count_files(Path(self.get_base_path(params)))
        if capped:
            return f"More than {_FILE_COUNT_LIMIT:,} files found under the base path."
        if not count:
            return "No files found under the base path."
        noun = "file" if count == 1 else "files"
        return f"{count:,} {noun} found under the base path."

    @staticmethod
    def _count_files(base_path: Path) -> tuple[int, bool]:
        count = 0
        for _, _, filenames in os.walk(base_path):
            count += len(filenames)
            if count > _FILE_COUNT_LIMIT:
                return _FILE_COUNT_LIMIT, True
        return count, False

    def init(
        self, connection: Connection, params: ResolvedConnectionParams, declarations: list[FileDeclaration]
    ) -> None:
        # Ahead of either branch: the files branch locks the configuration, and no SET is
        # accepted after that.
        self._set_spill_directory(connection)
        if params.sql_flavor_code == SqlFlavorCode.FILES:
            self._init_files(connection, params, declarations)
        else:
            self._init_attached_database(connection, params)

    def _init_attached_database(self, connection: Connection, params: ResolvedConnectionParams) -> None:
        database_file = self.get_database_file(params)
        if not database_file:
            raise DuckdbConnectionError("This connection has no database file configured.")

        self._attach(connection, database_file)
        connection.execute(text(f'USE "{ATTACHED_CATALOG}"'))
        # ATTACH participates in the transaction, so without this any later rollback on this
        # connection drops the catalog and every subsequent query fails on a name that no longer
        # resolves rather than on whatever actually went wrong.
        connection.commit()

    def _set_spill_directory(self, connection: Connection) -> None:
        """Point this connection's spill at a directory no other connection writes to.

        DuckDB creates the directory only if a query spills and removes it when the connection
        closes; it does not create the parent.
        """
        try:
            TEMP_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as error:
            # The engine-level temp_directory is this same path, so there is nothing else to set.
            LOG.warning(f"Could not create the DuckDB spill directory {TEMP_DIRECTORY}: {error}")
            return

        # Spill filenames carry a size class and a counter but no instance identifier, so two
        # instances sharing a directory overwrite each other's files and the process crashes.
        spill_directory = str(TEMP_DIRECTORY / f"{os.getpid()}-{uuid4().hex}").replace("'", "''")
        connection.execute(text(f"SET temp_directory = '{spill_directory}'"))

    def _init_files(
        self, connection: Connection, params: ResolvedConnectionParams, declarations: list[FileDeclaration]
    ) -> None:
        base_path = self.get_base_path(params)
        if not base_path:
            raise DuckdbConnectionError("This connection has no base path configured.")
        if not Path(base_path).is_dir():
            raise DuckdbConnectionError("The base path was not found." + container_path_note())

        self._confine_reads(connection, base_path)
        connection.info[_DECLARATION_FAILURES_KEY] = self.build_declaration_views(
            connection,
            base_path,
            declarations,
            fixed_table_group_schema(params.sql_flavor_code),
        )

    def declaration_failures(self, connection: Connection) -> dict[str, str]:
        return connection.info.get(_DECLARATION_FAILURES_KEY, {})

    def file_count_queries(self, params: ResolvedConnectionParams, declarations: list[FileDeclaration]) -> list[str]:
        if not declares_files(params.sql_flavor_code):
            return []
        base_path = self.get_base_path(params)
        # The counts are unioned, and one unreadable declaration would fail every count in its query,
        # so a declaration that cannot be read stays out.
        return [
            file_count_query(base_path, declaration)
            for declaration in declarations
            if skip_reason(base_path, declaration) is None
        ]

    def _confine_reads(self, connection: Connection, base_path: str) -> None:
        """Restrict this connection to reading inside the base path.

        The order is the whole mechanism. The allow-list cannot be set once external access is
        closed, and on its own it enforces nothing at all -- a read outside it still succeeds.
        Locking the configuration afterwards stops anything later widening either one.
        """
        quoted_base_path = base_path.replace("'", "''")
        for statement in (
            f"SET allowed_directories = ['{quoted_base_path}']",
            "SET enable_external_access = false",
            "SET lock_configuration = true",
        ):
            connection.execute(text(statement))
        connection.commit()

    def build_declaration_views(
        self,
        connection: Connection,
        base_path: str,
        declarations: list[FileDeclaration],
        schema: str,
    ) -> dict[str, str]:
        """Create one view per declaration. Returns the message for each one that failed.

        A declaration naming a file that is not there fails when its view is created rather than
        when it is queried, so each is committed on its own and a failure rolled back -- DuckDB
        aborts the transaction, and without the rollback every later declaration reports that
        abort instead of its own outcome.
        """
        failures: dict[str, str] = {}
        for declaration in declarations:
            if reason := skip_reason(base_path, declaration):
                failures[declaration.name] = reason
                LOG.error(f"Declaration {declaration.name!r} skipped: {reason}")
                continue
            try:
                connection.execute(text(create_view_statement(base_path, declaration, schema)))
                connection.commit()
            except Exception as error:
                connection.rollback()
                message = str(getattr(error, "orig", error)).splitlines()[0]
                failures[declaration.name] = message
                LOG.error(  # noqa: TRY400 -- the driver's text is already in the message
                    f"Declaration {declaration.name} could not be read: {message}"
                )
        return failures

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
