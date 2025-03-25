import zoneinfo

import streamlit as st


def tz_select(*, default="America/New_York", **kwargs):
    tz_options = sorted(zoneinfo.available_timezones())
    index = tz_options.index(st.session_state.get("browser_timezone", default))
    return st.selectbox(options=tz_options, index=index, format_func=lambda v: v.replace("_", " "), **kwargs)
