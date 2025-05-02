import zoneinfo

import streamlit as st

MOST_RELEVANT_TIMEZONES = [
    "Africa/Johannesburg",  # +02:00
    "America/Chicago",  # -05:00
    "America/Denver",  # -06:00
    "America/Halifax",  # -03:00
    "America/Los_Angeles",  # -07:00
    "America/Mexico_City",  # -06:00
    "America/New_York",  # -04:00
    "America/Phoenix",  # -07:00
    "America/Sao_Paulo",  # -03:00
    "America/Vancouver",  # -07:00
    "Asia/Bangkok",  # +07:00
    "Asia/Dubai",  # +04:00
    "Asia/Kolkata",  # +05:30
    "Asia/Riyadh",  # +03:00
    "Asia/Seoul",  # +09:00
    "Asia/Shanghai",  # +08:00
    "Asia/Singapore",  # +08:00
    "Asia/Tokyo",  # +09:00
    "Australia/Sydney",  # +10:00
    "Europe/Berlin",  # +02:00
    "Europe/Istanbul",  # +03:00
    "Europe/London",  # +01:00
    "Europe/Moscow",  # +03:00
    "Europe/Paris",  # +02:00
    "Pacific/Auckland",  # +12:00
]


def tz_select(*, default="America/New_York", **kwargs):
    tz_options = MOST_RELEVANT_TIMEZONES[:]
    tz_options.extend(sorted(tz for tz in zoneinfo.available_timezones() if tz not in MOST_RELEVANT_TIMEZONES))

    if "index" in kwargs:
        raise ValueError("Use the Session State API instead.")

    if "key" not in kwargs or kwargs["key"] not in st.session_state:
        kwargs["index"] = tz_options.index(st.session_state.get("browser_timezone", default))
    return st.selectbox(options=tz_options, format_func=lambda v: v.replace("_", " "), **kwargs)
