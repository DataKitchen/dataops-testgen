import urllib.parse
from typing import Any, TypeVar
from uuid import UUID

import numpy as np
import pandas as pd
import streamlit as st

T = TypeVar("T")


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
    

def score(profiling_score_: float, tests_score_: float) -> float:
    tests_score = _pandas_default(tests_score_, 0.0)
    profiling_score = _pandas_default(profiling_score_, 0.0)
    final_score = profiling_score or tests_score or 0.0
    if profiling_score and tests_score:
        final_score = profiling_score * tests_score
    return final_score


def _pandas_default(value: Any, default: T) -> T:
    if pd.isnull(value):
        return default
    return value


def friendly_score(score: float) -> str:
    if not score or pd.isnull(score):
        return None

    score = 100 * score
    if score == 100:
        return "100"
    
    rounded = round(score, 1)
    if rounded == 0:
        return "< 0.1"
    elif rounded == 100:
        return "> 99.9"

    return str(rounded)


def friendly_score_impact(impact: float) -> str:
    if not impact or pd.isnull(impact):
        return "-"

    if impact == 100:
        return "100"
    
    rounded = round(impact, 2)
    if rounded == 0:
        return "< 0.01"
    elif rounded == 100:
        return "> 99.99"

    return str(rounded)
    