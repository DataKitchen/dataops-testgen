from typing import Literal, NoReturn

import streamlit as st

from testgen.common.models import get_current_session


def safe_rerun(*, scope: Literal["app", "fragment"] = "app") -> NoReturn:
    """Commit any pending database changes, then trigger a Streamlit rerun.

    Prevents data loss when RerunException propagates through the
    session context manager in app.py:render().  Clears the Streamlit
    data cache when a database session is active (writes may have occurred).
    """
    session = get_current_session()
    if session:
        session.commit()
        st.cache_data.clear()
    st.rerun(scope=scope)
