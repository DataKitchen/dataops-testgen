import urllib.parse
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
import streamlit as st


def to_int(value: float | int) -> int:
    if pd.notnull(value):
        return int(value)
    return 0


def is_uuid4(value: str) -> bool:
    try:
        uuid = UUID(value, version=4)
    except Exception:
        return False
    
    return str(uuid) == value


# https://github.com/streamlit/streamlit/issues/798#issuecomment-1647759949
def get_base_url() -> str:
    session = st.runtime.get_instance()._session_mgr.list_active_sessions()[0]
    return urllib.parse.urlunparse([session.client.request.protocol, session.client.request.host, "", "", "", ""])


def format_field(field: Any) -> Any:
    defaults = {
        float: 0.0,
        int: 0,
    }
    if isinstance(field, UUID):
        return str(field)
    elif isinstance(field, pd.Timestamp):
        return field.value / 1_000_000
    elif pd.isnull(field):
        return defaults.get(type(field), None)
    elif isinstance(field, np.integer):
        return int(field)
    elif isinstance(field, np.floating):
        return float(field)
    return field


def chunk_queries(queries: list[str], join_string: str, max_query_length: int) -> list[str]:
    full_query = join_string.join(queries)
    if len(full_query) <= max_query_length:
        return [full_query]
    
    queries = iter(queries)
    chunked_queries = []
    current_chunk = next(queries)
    for query in queries:
        temp_chunk = join_string.join([current_chunk, query])
        if len(temp_chunk) <= max_query_length:
            current_chunk = temp_chunk
        else:
            chunked_queries.append(current_chunk)
            current_chunk = query
    chunked_queries.append(current_chunk)

    return chunked_queries


def friendly_score(score: float) -> str:
    if not score or pd.isnull(score):
        return "-"

    return str(int(score * 100))
