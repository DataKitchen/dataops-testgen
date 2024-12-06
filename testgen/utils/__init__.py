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
