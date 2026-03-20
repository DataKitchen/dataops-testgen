from typing import Literal, NoReturn

import streamlit as st

from testgen.common.models import get_current_session


def safe_rerun(*, scope: Literal["app", "fragment"] = "app") -> NoReturn:
    """Commit any pending database changes, then trigger a Streamlit rerun.

    Prevents data loss when RerunException propagates through the
    session context manager in app.py:render().
    """
    session = get_current_session()
    if session:
        session.commit()
    st.rerun(scope=scope)
