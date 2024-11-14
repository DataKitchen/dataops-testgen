import math
import urllib.parse
from uuid import UUID

import pandas as pd
import streamlit as st


def to_int(value: float | int) -> int:
    if pd.notnull(value):
        return int(value)
    return 0


def truncate(value: float, decimals: int = 0) -> int | float:
    if not isinstance(value, float | int):
        return value

    if decimals > 0:
        integer, decimal = str(value).split(".")
        return float(f"{integer}.{decimal[:decimals]}")

    if 0 < value < 1:
        return 1
    return math.trunc(value)


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
