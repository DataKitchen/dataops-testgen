from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from testgen.utils import to_dataframe

if TYPE_CHECKING:
    from testgen.common.models.connection import Connection

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.engine.cursor import CursorResult

from testgen.common.database.database_service import get_flavor_service
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


def fetch_from_target_db(connection: Connection, query: str, params: dict | None = None) -> list[RowMapping]:
    connection_params = connection.to_dict()
    flavor_service = get_flavor_service(connection.sql_flavor)
    resolved = resolve_connection_params(connection_params)
    engine = flavor_service.create_engine(connection_params)

    with engine.connect() as conn:
        for pre_query, pre_params in flavor_service.get_pre_connection_queries(resolved):
            conn.execute(text(pre_query), pre_params)
        cursor: CursorResult = conn.execute(text(query), params)
        return cursor.mappings().fetchall()
