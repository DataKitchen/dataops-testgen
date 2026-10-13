import concurrent.futures
import csv
import importlib
import logging
import math
import queue
import re
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, NotRequired, TypedDict, TypeVar, cast
from urllib.parse import quote_plus

import psycopg2.sql
from sqlalchemy import Connection, Engine, Row, create_engine, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import NullPool, PoolProxiedConnection

from testgen import settings
from testgen.common.credentials import (
    get_tg_db,
    get_tg_host,
    get_tg_password,
    get_tg_port,
    get_tg_schema,
    get_tg_username,
)
from testgen.common.database import FilteredStringIO
from testgen.common.database.file_declarations import FileDeclaration, parse_file_declarations
from testgen.common.database.flavor.flavor_service import (
    ConnectionParams,
    FlavorService,
    ResolvedConnectionParams,
    SQLFlavor,
    resolve_connection_params,
)
from testgen.common.read_file import get_template_files
from testgen.common.standalone_postgres import get_connection_string as get_standalone_connection_string
from testgen.common.standalone_postgres import is_standalone_mode
from testgen.utils import get_exception_message

if TYPE_CHECKING:
    from testgen.common.models.table_group import TableGroup

LOG = logging.getLogger("testgen")

# "normal": Log into database/schema for normal stuff
# "database_admin": Log into postgres/public to create database via override user/password
# "schema_admin": Log into database/public to create schema and run scripts via override user/password
UserType = Literal["normal", "database_admin", "schema_admin"]

@dataclass
class EngineCache:
    app_db: Engine | None = field(default=None)
    target_db: Engine | None = field(default=None)


@dataclass(frozen=True, slots=True)
class TargetDbParams:
    connection: ConnectionParams
    declarations: list[FileDeclaration]
    table_group_schema: str | None


# Initialize variables global to this script
target_db_params: TargetDbParams | None = None
engine_cache = EngineCache()


def quote_csv_items(csv_row: str, quote_character: str = '"') -> str:
    if csv_row:
        values = csv_row.split(",")
        # Process each value individually, quoting it if not already quoted
        quoted_values = ",".join(
            [
                (
                    f"{quote_character}{value}{quote_character}"
                    if not (value.startswith(quote_character) and value.endswith(quote_character))
                    else value
                )
                for value in values
            ]
        )
        return quoted_values
    return csv_row


def empty_cache() -> None:
    # dispose() closes all idle pool connections immediately, avoiding handing
    # out stale ones on the next checkout.
    if engine_cache.app_db is not None:
        engine_cache.app_db.dispose()
    if engine_cache.target_db is not None:
        engine_cache.target_db.dispose()
    engine_cache.app_db = None
    engine_cache.target_db = None


def set_target_db_params(connection_params: ConnectionParams, table_group: "TableGroup | None") -> None:
    global target_db_params
    target_db_params = TargetDbParams(
        connection_params.copy(),
        parse_file_declarations(table_group.file_declarations) if table_group else [],
        table_group.table_group_schema if table_group else None,
    )
    # The cache holds one unkeyed slot, so a cached engine built for the previous parameters
    # would otherwise be handed out for these.
    if engine_cache.target_db is not None:
        engine_cache.target_db.dispose()
        engine_cache.target_db = None


def cache_target_tables(table_names: Iterable[str]) -> None:
    """Have the target's flavor keep a local copy of the named tables for the rest of the run."""
    if not target_db_params:
        raise ValueError("Target database connection parameters were not set")
    flavor_service = get_flavor_service(target_db_params.connection["sql_flavor"])
    params = resolve_connection_params(target_db_params.connection)
    with _init_target_db_connection() as connection:
        flavor_service.cache_tables(connection, params, target_db_params.declarations, table_names)


def get_flavor_service(flavor: SQLFlavor) -> FlavorService:
    module_path = f"testgen.common.database.flavor.{flavor}_flavor_service"
    class_name = f"{flavor.replace('_', ' ').title().replace(' ', '')}FlavorService"
    module = importlib.import_module(module_path)
    flavor_class = getattr(module, class_name)
    return flavor_class()


class CreateDatabaseParams(TypedDict):
    TESTGEN_ADMIN_USER: str
    TESTGEN_ADMIN_PASSWORD: str

def create_database(
    database_name: str,
    params: CreateDatabaseParams,
    drop_existing: bool = False,
) -> None:
    LOG.debug("DB operation: create_database on App database (User type = database_admin)")

    # DDL like CREATE/DROP DATABASE cannot run inside a transaction.
    # Use AUTOCOMMIT isolation so each statement commits immediately.
    connection = _init_db_connection(
        user_override=params["TESTGEN_ADMIN_USER"],
        password_override=params["TESTGEN_ADMIN_PASSWORD"],
        user_type="database_admin",
    )
    connection = connection.execution_options(isolation_level="AUTOCOMMIT")

    with connection:
        if drop_existing:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = :database_name"
                ),
                {"database_name": database_name},
            )
            # pg_terminate_backend just killed any pooled connections to this DB.
            # Dispose the cached app/target engines so they don't hand out dead
            # connections on the next checkout.
            empty_cache()
            connection.execute(text(f"DROP DATABASE IF EXISTS {database_name}"))
        with suppress(ProgrammingError):
            connection.execute(text(f"CREATE DATABASE {database_name}"))


def execute_db_queries(
    queries: list[tuple[str, dict | None]],
    use_target_db: bool = False,
    user_override: str | None = None,
    password_override: str | None = None,
    user_type: UserType = "normal",
) -> tuple[list[Any], list[int]]:
    LOG.debug(f"DB operation: execute_db_queries ({len(queries)}) on {'Target' if use_target_db else 'App'} database (User type = {user_type})")

    with _init_db_connection(use_target_db, user_override, password_override, user_type) as connection:
        return_values: list[Any] = []
        row_counts: list[int] = []
        if not queries:
            LOG.debug("No queries to process")
        for index, (query, params) in enumerate(queries):
            LOG.debug(f"Query {index + 1} of {len(queries)}: {query}")
            result = connection.execute(text(query), params)
            row_counts.append(result.rowcount)
            if result.rowcount == -1:
                message = "No records processed"
            else:
                message = f"{result.rowcount} records processed"

                try:
                    return_values.append(result.fetchone()[0])
                except Exception:
                    return_values.append(None)

            connection.commit()
            LOG.debug(message)

    return return_values, row_counts


class ThreadedProgress(TypedDict):
    processed: int
    errors: int
    total: int
    indexes: NotRequired[list[int]]

def fetch_from_db_threaded(
    queries: list[tuple[str, dict | None]],
    use_target_db: bool = False,
    max_threads: int = 4,
    progress_callback: Callable[[ThreadedProgress], None] | None = None,
) -> tuple[list[RowMapping], list[str], dict[int, str]]:
    LOG.debug(f"DB operation: fetch_from_db_threaded ({len(queries)}) on {'Target' if use_target_db else 'App'} database (User type = normal)")

    def fetch_data(query: str, params: dict | None, index: int) -> tuple[list[RowMapping], list[str], int, str | None]:
        LOG.debug(f"Query: {query}")
        row_data: list[RowMapping] = []
        column_names: list[str] = []
        error = None

        try:
            with _init_db_connection(use_target_db) as connection:
                result = connection.execute(text(query), params)
                LOG.debug(f"{result.rowcount} records retrieved")
                row_data = result.mappings().fetchall()
                column_names = list(result.keys())
        except Exception as e:
            error = get_exception_message(e)
            LOG.exception(f"Failed to execute threaded query: {query}")

        return row_data, column_names, index, error

    result_data: list[RowMapping] = []
    result_columns: list[str] = []
    error_data: dict[int, str] = {}

    query_count = len(queries)
    processed_count = 0
    processed_indexes: list[int] = []
    max_threads = max(1, min(10, max_threads))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [
            executor.submit(fetch_data, query, params, index)
            for index, (query, params) in enumerate(queries)
        ]
        for future in concurrent.futures.as_completed(futures):
            row_data, column_names, index, error = future.result()
            if row_data:
                result_data.append(row_data)
                result_columns = column_names
            if error:
                error_data[index] = error

            processed_count += 1
            processed_indexes.append(index)
            if progress_callback:
                progress_callback({
                    "processed": processed_count,
                    "errors": len(error_data),
                    "total": query_count,
                    "indexes": processed_indexes,
                })
            LOG.debug(f"Processed {processed_count} of {query_count} threaded queries")

    # Flatten nested lists
    result_data = [element for sublist in result_data for element in sublist]
    return result_data, result_columns, error_data


K = TypeVar("K")
A = TypeVar("A")
R = TypeVar("R")


@dataclass(frozen=True)
class WorkerOutcome(Generic[K, R]):
    """One completed unit of work yielded by :func:`run_keyed_worker_pool`.

    ``key`` is the caller's correlation key, returned untouched. ``result`` holds the value
    returned by ``process`` on success; ``error`` holds the message when ``process`` raised.
    Exactly one of ``result`` / ``error`` is set.
    """
    key: K
    result: R | None
    error: str | None


def run_keyed_worker_pool(
    items: Sequence[tuple[K, A]],
    process: Callable[[A], R],
    max_threads: int = 4,
    stop: Callable[[], bool] | None = None,
) -> Iterator[WorkerOutcome[K, R]]:
    """Run ``process`` over ``items`` with a fixed pool of pull-based workers, yielding each
    item's outcome as it completes.

    Each item is a ``(key, arg)`` pair: a worker runs ``process(arg)`` and the ``key`` is
    returned untouched on the matching :class:`WorkerOutcome`, so the caller correlates a
    result back to its work without inspecting the payload. Each of ``max_threads`` workers
    repeatedly pulls the next pair from a shared ordered iterator. Workers run ``process`` and
    nothing else: the caller must hand them self-contained ``arg`` values and must not let
    ``process`` touch caller-thread state such as a thread-local database session. The caller
    consumes the yielded outcomes on its own thread, so all result handling (database writes,
    progress) stays single-threaded. Outcomes arrive in completion order, not item order.

    When ``stop`` is given and returns True, workers stop pulling new items and the iterator
    ends early, so fewer than ``len(items)`` outcomes are yielded. Items already in flight
    still run to completion and are yielded. ``stop`` is called on worker threads and must be
    cheap and thread-safe.

    A caller that stops consuming -- by raising, or by closing the iterator -- also stops the
    pool, so abandoning the results does not first pay for producing them.
    """
    max_threads = max(1, min(10, max_threads))
    work = iter(items)
    pull_lock = threading.Lock()
    # A worker enqueues the sentinel as it leaves, so the consumer knows the pool is drained
    # without counting items -- which it cannot do once `stop` cuts the run short.
    done = object()
    outcomes: queue.Queue[WorkerOutcome[K, R] | object] = queue.Queue()

    abandoned = threading.Event()

    def pull() -> tuple[K, A] | None:
        if abandoned.is_set() or (stop is not None and stop()):
            return None
        with pull_lock:
            return next(work, None)

    def worker() -> None:
        try:
            while (item := pull()) is not None:
                key, arg = item
                try:
                    result: R | None = process(arg)
                except Exception as e:
                    # The consumer expects one outcome per pulled item, so every item must
                    # enqueue one; get_exception_message never raises, so it always does.
                    LOG.exception("Error processing work key")
                    outcomes.put(WorkerOutcome(key, None, get_exception_message(e)))
                else:
                    outcomes.put(WorkerOutcome(key, result, None))
        finally:
            outcomes.put(done)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        workers = [executor.submit(worker) for _ in range(max_threads)]
        still_working = len(workers)
        try:
            while still_working:
                outcome = outcomes.get()
                if outcome is done:
                    still_working -= 1
                else:
                    yield cast(WorkerOutcome[K, R], outcome)
        finally:
            # Leaving early -- the caller raised, or closed the iterator -- means nothing will
            # read another outcome. Without this the pool would work through every remaining
            # item before the exit could proceed, since shutdown waits for the workers.
            abandoned.set()
        for future in workers:
            future.result()


def fetch_list_from_db(
    query: str, params: dict | None = None, use_target_db: bool = False
) -> tuple[list[Row], list[str]]:
    LOG.debug(f"DB operation: fetch_list_from_db on {'Target' if use_target_db else 'App'} database (User type = normal)")

    with _init_db_connection(use_target_db) as connection:
        LOG.debug(f"Query: {query}")
        result = connection.execute(text(query), params)
        row_data = result.fetchall()
        column_names = result.keys()
        LOG.debug(f"{result.rowcount} records retrieved")

        return row_data, column_names


def fetch_dict_from_db(
    query: str, params: dict | None = None, use_target_db: bool = False
) -> list[RowMapping]:
    LOG.debug(f"DB operation: fetch_dict_from_db on {'Target' if use_target_db else 'App'} database (User type = normal)")

    with _init_db_connection(use_target_db) as connection:
        LOG.debug(f"Query: {query}")
        result = connection.execute(text(query), params)
        LOG.debug(f"{result.rowcount} records retrieved")
        return result.mappings().all()


def probe_target_capability(query: str, capability: str, connectivity_query: str) -> bool:
    """Run a capability probe against the target database and report whether the function exists.

    A failed probe is evidence of an absent function only if the target was reachable, so a
    failure is retested with ``connectivity_query``: if that fails too, the target is unreachable
    and the original error is raised. ``capability`` names the function in the log lines.
    """
    try:
        fetch_dict_from_db(query, {}, use_target_db=True)
    except Exception as probe_error:
        try:
            fetch_dict_from_db(connectivity_query, {}, use_target_db=True)
        except Exception:
            LOG.warning(f"Target unreachable while probing for {capability}.")
            raise probe_error from None
        LOG.warning(f"Capability probe failed ({capability}); going without it. {probe_error}")
        return False
    LOG.info(f"Capability probe succeeded ({capability}).")
    return True


def write_to_app_db(data: list[Row], column_names: Iterable[str], table_name: str) -> None:
    LOG.debug("DB operation: write_to_app_db on App database (User type = normal)")

    columns = list(column_names)

    # use_raw is required to make use of the copy_expert method for fast batch ingestion
    connection = _init_db_connection(use_raw=True)
    cursor = connection.cursor()

    # Write List to CSV in memory
    # Sanitize NaN → None: some DB connectors (e.g. Databricks via Arrow) return
    # float('nan') for NULL integers. CSV would serialize these as "nan" which
    # PostgreSQL rejects for numeric columns.
    # COPY is positional, so a RowMapping is looked up by name rather than iterated:
    # rows from separate queries can share one header while ordering their SELECT
    # lists differently, and iterating would write those values into the wrong columns.
    def _row_values(row):
        values = [row[column] for column in columns] if isinstance(row, RowMapping) else row
        return tuple(None if isinstance(v, float) and math.isnan(v) else v for v in values)

    sanitized = [_row_values(row) for row in data]
    buffer = FilteredStringIO(["\x00"])
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerows(sanitized)
    buffer.seek(0)

    # List should have same column names as destination table, though not all columns in table are required
    query = psycopg2.sql.SQL("COPY {table_name} ({column_names}) FROM STDIN WITH (FORMAT CSV)").format(
        table_name=psycopg2.sql.Identifier(table_name),
        column_names=psycopg2.sql.SQL(", ").join([psycopg2.sql.Identifier(column) for column in columns]),
    )
    LOG.debug(f"Query: {query}")
    cursor.copy_expert(query, buffer)
    connection.commit()
    connection.close()


def apply_params(query: str, params: dict[str, Any]) -> str:
    query = process_conditionals(query, params)
    query = replace_params(query, params)
    return query


def replace_params(query: str, params: dict[str, Any]) -> str:
    for key, value in params.items():
        query = query.replace(f"{{{key}}}", "" if value is None else str(value))
    return query


def process_conditionals(query: str, params: dict[str, Any]) -> str:
    re_pattern = re.compile(r"^--\s+TG-(IF|ELSE|ENDIF)(?:\s+(\w+))?\s*$")
    condition = None
    updated_query = []
    for line in query.splitlines(True):
        if re_match := re_pattern.match(line):
            match re_match.group(1):
                case "IF" if condition is None and (variable := re_match.group(2)) is not None:
                    condition = bool(params.get(variable))
                case "ELSE" if condition is not None:
                    condition = not condition
                case "ENDIF" if condition is not None:
                    condition = None
                case _:
                    raise ValueError("Template conditional misused")
        elif condition is not False:
            updated_query.append(line)

    if condition is not None:
        raise ValueError("Template conditional misused")

    return "".join(updated_query)


def get_queries_for_command(
    sub_directory: str, params: dict[str, Any], mask: str = r"^.*sql$", path: str | None = None
) -> list[str]:
    files = sorted(get_template_files(mask=mask, sub_directory=sub_directory, path=path), key=lambda key: str(key))

    queries = []
    for file in files:
        query = file.read_text("utf-8")
        template = replace_params(query, params)

        queries.append(template)

    if len(queries) == 0:
        LOG.warning(f"No sql files were found for the mask {mask} in subdirectory {sub_directory}")

    return queries


def _init_db_connection(
    use_target_db: bool = False,
    user_override: str | None = None,
    password_override: str | None = None,
    user_type: UserType = "normal",
    use_raw: bool = False,
) -> Connection:
    if use_target_db:
        return _init_target_db_connection()
    return _init_app_db_connection(user_override, password_override, user_type, use_raw)


def _init_app_db_connection(
    user_override: str | None = None,
    password_override: str | None = None,
    user_type: UserType = "normal",
    use_raw: bool = False,
) -> Connection | PoolProxiedConnection:
    database_name = "postgres" if user_type == "database_admin" else get_tg_db()
    is_admin = user_type == "database_admin" or user_type == "schema_admin"

    engine = None
    if user_type == "normal":
        engine = engine_cache.app_db

    if not engine:
        if is_standalone_mode():
            connection_string = get_standalone_connection_string(database_name)
        else:
            user = user_override if is_admin else get_tg_username()
            password = password_override if (is_admin or password_override is not None) else get_tg_password()

            # STANDARD FORMAT: flavor://username:password@host:port/database
            connection_string = (
                f"postgresql://{user}:{quote_plus(password)}@{get_tg_host()}:{get_tg_port()}/{database_name}"
            )
        try:
            engine: Engine = create_engine(
                connection_string,
                connect_args={
                    "connect_timeout": 3600,
                    # Force UTC so TIMESTAMP-without-tz inserts aren't silently shifted.
                    "options": "-c TimeZone=UTC",
                    **settings.DATABASE_SSL_CONNECT_ARGS,
                },
                # Admin operations (schema_admin / database_admin) are one-shot.
                # NullPool closes the connection on `.close()` instead of parking
                # it in a pool we never dispose — avoids leaking idle PG
                # connections across a long CLI run.
                poolclass=None if user_type == "normal" else NullPool,
            )
            if user_type == "normal":
                engine_cache.app_db = engine

        except SQLAlchemyError as e:
            raise ValueError(f"Failed to create engine for App database '{database_name}' (User type = {user_type})") from e

    try:
        schema_name = "public" if is_admin else get_tg_schema()
        if use_raw:
            connection: PoolProxiedConnection = engine.raw_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET SEARCH_PATH = %(schema_name)s",
                    {"schema_name": schema_name},
                )
            connection.commit()
        else:
            connection: Connection = engine.connect()
            if user_type == "normal":
                connection.execute(
                    text("SET SEARCH_PATH = :schema_name;"),
                    {"schema_name": schema_name},
                )
    except SQLAlchemyError as e:
        raise ValueError(f"Failed to connect to App database '{database_name}'") from e

    return connection


_FLAVOR_INITIALIZED_KEY = "flavor_initialized"


def initialize_connection(
    flavor_service: FlavorService,
    connection: Connection,
    params: ResolvedConnectionParams,
    declarations: list[FileDeclaration],
) -> None:
    """Run the flavor's ``init`` the first time this physical connection is handed out.

    ``Connection.info`` belongs to the pooled DBAPI connection rather than to the checkout, so a
    pool that reuses one connection initializes it once. What ``init`` establishes is state on the
    database, not on the session, and running it twice is not merely wasteful: DuckDB refuses any
    ``SET`` once a configuration is locked, and that refusal aborts the transaction, leaving the
    connection unusable for what follows.
    """
    if connection.info.get(_FLAVOR_INITIALIZED_KEY):
        return
    flavor_service.init(connection, params, declarations)
    connection.info[_FLAVOR_INITIALIZED_KEY] = True


def _init_target_db_connection() -> Connection:
    if not target_db_params:
        raise ValueError("Target database connection parameters were not set")

    connection_params = target_db_params.connection
    table_group_schema = target_db_params.table_group_schema
    flavor_service = get_flavor_service(connection_params["sql_flavor"])
    params = resolve_connection_params(connection_params, table_group_schema)

    engine = engine_cache.target_db
    if not engine:
        try:
            engine: Engine = flavor_service.create_engine(connection_params, table_group_schema)
        except SQLAlchemyError as e:
            raise ValueError(f"Failed to create engine for Target database '{params.dbname}' (User type = normal)") from e
        else:
            engine_cache.target_db = engine

    try:
        connection: Connection = engine.connect()
    except PoolTimeoutError as error:
        # A flavor whose pool holds one connection expects no contention at all, so waiting for a
        # turn means one was never returned. The pool's own message names the pool and not that.
        raise ValueError(
            "Timed out waiting for a connection to the data source. "
            "A previous connection was not released."
        ) from error

    try:
        for query, query_params in flavor_service.get_pre_connection_queries(params):
            try:
                connection.execute(text(query), query_params)
            except Exception:
                LOG.warning(
                    f"Failed to execute preconnection query on Target database: {query}",
                    exc_info=settings.IS_DEBUG,
                    stack_info=settings.IS_DEBUG,
                )

        initialize_connection(flavor_service, connection, params, target_db_params.declarations)
    except BaseException:
        # Nothing has the connection yet, so failing here would strand it. A flavor whose pool
        # holds a single connection has no second one to hand out, and the next caller waits for
        # the pool timeout and then reports the pool rather than what actually went wrong.
        #
        # Invalidated rather than closed: a DuckDB SET is not transactional and outlives the
        # rollback the pool performs on return, so a connection that reached
        # `SET lock_configuration = true` before failing comes back out still locked, and every
        # later attempt to initialize it fails on a configuration it cannot change.
        connection.invalidate()
        raise

    return connection
