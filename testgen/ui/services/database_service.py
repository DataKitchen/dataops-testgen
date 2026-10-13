from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from testgen.utils import to_dataframe

if TYPE_CHECKING:
    from testgen.common.models.connection import Connection
    from testgen.common.models.table_group import TableGroup

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection as SAConnection
from sqlalchemy.engine import RowMapping
from sqlalchemy.engine.cursor import CursorResult

from testgen.common.database.database_service import get_flavor_service, initialize_connection
from testgen.common.database.file_declarations import parse_file_declarations
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.models import get_current_session


def execute_db_query(query: str, params: dict | None = None) -> Any:
    db_session = get_current_session()
    cursor: CursorResult = db_session.execute(text(query), params)
    try:
        result = cursor.fetchone()[0]
    except:
        result = None
    db_session.commit()
    return result


def fetch_all_from_db(query: str, params: dict | None = None) -> list[RowMapping]:
    db_session = get_current_session()
    cursor: CursorResult = db_session.execute(text(query), params)
    return cursor.mappings().all()


# Only use this for old parts of the app that still use dataframes
# Prefer to use fetch_all_from_db instead and avoid usage of pandas
def fetch_df_from_db(query: str, params: dict | None = None) -> pd.DataFrame:
    db_session = get_current_session()
    cursor: CursorResult = db_session.execute(text(query), params)
    results = cursor.mappings().all()
    columns = cursor.keys()
    return to_dataframe(results, columns)


def fetch_one_from_db(query: str, params: dict | None = None) -> RowMapping | None:
    db_session = get_current_session()
    cursor: CursorResult = db_session.execute(text(query), params)
    result = cursor.first()
    return result._mapping if result else None


@dataclass
class TargetQuery:
    """Runs queries on an open target-database connection.

    ``declaration_failures`` maps the name of each file declaration that could not be made
    queryable to the reason, and is empty for a flavor that reads tables rather than files.
    ``connection`` is the open connection the queries run on.
    """

    _run: Callable[[str, dict | None], list[RowMapping]]
    declaration_failures: dict[str, str]
    connection: SAConnection

    def __call__(self, query: str, params: dict | None = None) -> list[RowMapping]:
        return self._run(query, params)


@contextmanager
def target_db_session(
    connection: Connection, table_group: TableGroup | None
) -> Iterator[TargetQuery]:
    """Open one target-database connection and yield a callable that runs queries on it.

    ``table_group`` is the group whose tables the queries read, or None when they read none. A
    flavor that reads files has no tables at all without its declarations.
    """
    connection_params = connection.to_dict()
    declarations = parse_file_declarations(table_group.file_declarations) if table_group else []
    table_group_schema = table_group.table_group_schema if table_group else None
    flavor_service = get_flavor_service(connection.sql_flavor)
    resolved = resolve_connection_params(connection_params, table_group_schema)
    engine = flavor_service.create_engine(connection_params, table_group_schema)

    # Each call creates a fresh engine for ad-hoc target-DB access (test connection,
    # preview, data catalog reads). Dispose on exit so the engine's pool doesn't
    # leak an idle connection until GC — these add up over a long Streamlit session.
    try:
        with engine.connect() as conn:
            for pre_query, pre_params in flavor_service.get_pre_connection_queries(resolved):
                conn.execute(text(pre_query), pre_params)
            initialize_connection(flavor_service, conn, resolved, declarations)

            def run(query: str, params: dict | None = None) -> list[RowMapping]:
                try:
                    cursor: CursorResult = conn.execute(text(query), params)
                except Exception:
                    # A failed statement aborts the transaction, so without this every later
                    # query on this session reports that abort instead of its own outcome.
                    conn.rollback()
                    raise
                return cursor.mappings().fetchall()

            yield TargetQuery(run, flavor_service.declaration_failures(conn), conn)
    finally:
        engine.dispose()


def fetch_from_target_db(
    connection: Connection,
    query: str,
    params: dict | None = None,
    *,
    table_group: TableGroup | None,
) -> list[RowMapping]:
    """Run one query against the target database on a connection opened just for it."""
    with target_db_session(connection, table_group) as run:
        return run(query, params)
