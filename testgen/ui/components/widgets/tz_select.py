import zoneinfo

import streamlit as st

HANDY_TIMEZONES = [
    "Africa/Abidjan",  # +00:00
    "Africa/Johannesburg",  # +02:00
    "Africa/Lagos",  # +01:00
    "America/Anchorage",  # -09:00
    "America/Argentina/Buenos_Aires",  # -03:00
    "America/Bogota",  # -05:00
    "America/Chicago",  # -06:00
    "America/Denver",  # -07:00
    "America/Halifax",  # -03:00
    "America/Los_Angeles",  # -08:00
    "America/Mexico_City",  # -06:00
    "America/New_York",  # -04:00 (during DST)
    "America/Phoenix",  # -07:00
    "America/Sao_Paulo",  # -03:00
    "America/Toronto",  # -04:00 (during DST)
    "America/Vancouver",  # -08:00
    "Asia/Almaty",  # +06:00
    "Asia/Baku",  # +04:00
    "Asia/Bangkok",  # +07:00
    "Asia/Colombo",  # +05:30
    "Asia/Dhaka",  # +06:00
    "Asia/Dubai",  # +04:00
    "Asia/Jakarta",  # +07:00
    "Asia/Kabul",  # +04:30
    "Asia/Kolkata",  # +05:30
    "Asia/Manila",  # +08:00
    "Asia/Riyadh",  # +03:00
    "Asia/Seoul",  # +09:00
    "Asia/Shanghai",  # +08:00
    "Asia/Singapore",  # +08:00
    "Asia/Tokyo",  # +09:00
    "Atlantic/Azores",  # -01:00
    "Atlantic/South_Georgia",  # -02:00
    "Australia/Sydney",  # +10:00
    "Europe/Amsterdam",  # +01:00
    "Europe/Athens",  # +02:00
    "Europe/Berlin",  # +01:00
    "Europe/Bucharest",  # +02:00
    "Europe/Helsinki",  # +02:00
    "Europe/Istanbul",  # +03:00
    "Europe/London",  # +00:00
    "Europe/Moscow",  # +03:00
    "Europe/Paris",  # +01:00
    "Pacific/Auckland",  # +12:00
    "Pacific/Honolulu",  # -10:00
    "Pacific/Noumea",  # +11:00
    "Pacific/Port_Moresby",  # +10:00
]


def tz_select(*, default="America/New_York", **kwargs):
    tz_options = HANDY_TIMEZONES[:]
    tz_options.extend(sorted(tz for tz in zoneinfo.available_timezones() if tz not in HANDY_TIMEZONES))

    if "index" in kwargs:
        raise ValueError("Use the Session State API instead.")

    # This is wierd, but apparently Streamlit likes it this way
    if "key" in kwargs and st.session_state.get(kwargs["key"], None) in tz_options:
        kwargs["index"] = tz_options.index(st.session_state[kwargs["key"]])
        del st.session_state[kwargs["key"]]
    else:
        kwargs["index"] = tz_options.index(st.session_state.get("browser_timezone", default))

    return st.selectbox(options=tz_options, format_func=lambda v: v.replace("_", " "), **kwargs)
