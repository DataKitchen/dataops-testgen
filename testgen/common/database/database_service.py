import concurrent.futures
import csv
import importlib
import logging
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from urllib.parse import quote_plus

import psycopg2.sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import LegacyRow, RowMapping
from sqlalchemy.engine.base import Connection, Engine
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.pool.base import _ConnectionFairy

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
from testgen.common.database.flavor.flavor_service import ConnectionParams, FlavorService, SQLFlavor
from testgen.common.read_file import get_template_files
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")

# "normal": Log into database/schema for normal stuff
# "database_admin": Log into postgres/public to create database via override user/password
# "schema_admin": Log into database/public to create schema and run scripts via override user/password
UserType = Literal["normal", "database_admin", "schema_admin"]

@dataclass
class EngineCache:
    app_db: Engine | None = field(default=None)
    target_db: Engine | None = field(default=None)

# Initialize variables global to this script
target_db_params: ConnectionParams | None = None
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
    engine_cache.app_db = None
    engine_cache.target_db = None


def set_target_db_params(connection_params: ConnectionParams) -> None:
    global target_db_params
    target_db_params = dict(connection_params)


def get_flavor_service(flavor: SQLFlavor) -> FlavorService:
    module_path = f"testgen.common.database.flavor.{flavor}_flavor_service"
    class_name = f"{flavor.replace('_', ' ').title().replace(' ', '')}FlavorService"
    module = importlib.import_module(module_path)
    flavor_class = getattr(module, class_name)
    return flavor_class()


class CreateDatabaseParams(TypedDict):
    TESTGEN_ADMIN_USER: str
    TESTGEN_ADMIN_PASSWORD: str
    TESTGEN_USER: str | None
    TESTGEN_REPORT_USER: str | None

def create_database(
    database_name: str,
    params: CreateDatabaseParams,
    drop_existing: bool = False,
    drop_users_and_roles: bool = False,
) -> None:
    LOG.debug("DB operation: create_database on App database (User type = database_admin)")

    connection = _init_db_connection(
        user_override=params["TESTGEN_ADMIN_USER"],
        password_override=params["TESTGEN_ADMIN_PASSWORD"],
        user_type="database_admin",
    )
    connection.execute("commit")

    with connection:
        if drop_existing:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = :database_name"
                ),
                {"database_name": database_name},
            )
            connection.execute("commit")
            connection.execute(f"DROP DATABASE IF EXISTS {database_name}")
            connection.execute("commit")
            if drop_users_and_roles:
                if user := params.get("TESTGEN_USER"):
                    connection.execute(f"DROP USER IF EXISTS {user}")
                if report_user := params.get("TESTGEN_REPORT_USER"):
                    connection.execute(f"DROP USER IF EXISTS {report_user}")
                connection.execute("DROP ROLE IF EXISTS testgen_execute_role")
                connection.execute("DROP ROLE IF EXISTS testgen_report_role")
                connection.execute("commit")
        with suppress(ProgrammingError):
            connection.execute(f"CREATE DATABASE {database_name}")
            connection.close()


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
            transaction = connection.begin()
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

            transaction.commit()
            LOG.debug(message)

    return return_values, row_counts


class ThreadedProgress(TypedDict):
    processed: int
    errors: int
    total: int
    indexes: list[int]

def fetch_from_db_threaded(
    queries: list[tuple[str, dict | None]],
    use_target_db: bool = False,
    max_threads: int = 4,
    progress_callback: Callable[[ThreadedProgress], None] | None = None,
) -> tuple[list[LegacyRow], list[str], dict[int, str]]:
    LOG.debug(f"DB operation: fetch_from_db_threaded ({len(queries)}) on {'Target' if use_target_db else 'App'} database (User type = normal)")

    def fetch_data(query: str, params: dict | None, index: int) -> tuple[list[LegacyRow], list[str], int, str | None]:
        LOG.debug(f"Query: {query}")
        row_data: list[LegacyRow] = []
        column_names: list[str] = []
        error = None

        try:
            with _init_db_connection(use_target_db) as connection:
                result = connection.execute(text(query), params)
                LOG.debug(f"{result.rowcount} records retrieved")
                row_data = result.fetchall()
                column_names = list(result.keys())
        except Exception as e:
            error = get_exception_message(e)
            LOG.exception(f"Failed to execute threaded query: {query}")

        return row_data, column_names, index, error
    
    result_data: list[LegacyRow] = []
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


def fetch_list_from_db(
    query: str, params: dict | None = None, use_target_db: bool = False
) -> tuple[list[LegacyRow], list[str]]:
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
        # Creates list of dictionaries so records are addressible by column name
        return [row._mapping for row in result]


def write_to_app_db(data: list[LegacyRow], column_names: Iterable[str], table_name: str) -> None:
    LOG.debug("DB operation: write_to_app_db on App database (User type = normal)")

    # use_raw is required to make use of the copy_expert method for fast batch ingestion
    connection = _init_db_connection(use_raw=True)
    cursor = connection.cursor()

    # Write List to CSV in memory
    buffer = FilteredStringIO(["\x00"])
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerows(data)
    buffer.seek(0)

    # List should have same column names as destination table, though not all columns in table are required
    query = psycopg2.sql.SQL("COPY {table_name} ({column_names}) FROM STDIN WITH (FORMAT CSV)").format(
        table_name=psycopg2.sql.Identifier(table_name),
        column_names=psycopg2.sql.SQL(", ").join([psycopg2.sql.Identifier(column) for column in column_names]),
    )
    LOG.debug(f"Query: {query}")
    cursor.copy_expert(query, buffer)
    connection.commit()
    connection.close()


def replace_params(query: str, params: dict[str, Any]) -> str:
    for key, value in params.items():
        query = query.replace(f"{{{key}}}", "" if value is None else str(value))
    return query


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
) -> Connection | _ConnectionFairy:
    database_name = "postgres" if user_type == "database_admin" else get_tg_db()
    is_admin = user_type == "database_admin" or user_type == "schema_admin"

    engine = None
    if user_type == "normal":
        engine = engine_cache.app_db

    if not engine:
        user = user_override if is_admin else get_tg_username()
        password = password_override if (is_admin or password_override is not None) else get_tg_password()

        # STANDARD FORMAT: flavor://username:password@host:port/database
        connection_string = (
            f"postgresql://{user}:{quote_plus(password)}@{get_tg_host()}:{get_tg_port()}/{database_name}"
        )
        try:
            engine: Engine = create_engine(connection_string, connect_args={"connect_timeout": 3600})
            engine_cache.app_db = engine

        except SQLAlchemyError as e:
            raise ValueError(f"Failed to create engine for App database '{database_name}' (User type = {user_type})") from e

    try:
        schema_name = "public" if is_admin else get_tg_schema()
        if use_raw:
            connection: _ConnectionFairy = engine.raw_connection()
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


def _init_target_db_connection() -> Connection:
    if not target_db_params:
        raise ValueError("Target database connection parameters were not set")

    flavor_service = get_flavor_service(target_db_params["sql_flavor"])
    flavor_service.init(target_db_params)

    engine = engine_cache.target_db
    if not engine:
        try:
            engine: Engine = create_engine(
                flavor_service.get_connection_string(),
                connect_args=flavor_service.get_connect_args(),
                **flavor_service.get_engine_args(),
            )
        except SQLAlchemyError as e:
            raise ValueError(f"Failed to create engine for Target database '{flavor_service.dbname}' (User type = normal)") from e
        else:
            engine_cache.target_db = engine


    connection: Connection = engine.connect()

    for query, params in flavor_service.get_pre_connection_queries():
        try:
            connection.execute(text(query), params)
        except Exception:
            LOG.warning(
                f"Failed to execute preconnection query on Target database: {query}",
                exc_info=settings.IS_DEBUG,
                stack_info=settings.IS_DEBUG,
            )

    return connection
