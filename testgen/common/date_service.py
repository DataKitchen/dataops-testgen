from datetime import datetime, timedelta

import pandas as pd


def get_today_as_string():
    return datetime.utcnow().strftime("%Y-%m-%d")


def get_now_as_string():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def get_now_as_string_with_offset(minutes_offset):
    ret = datetime.utcnow()
    if minutes_offset > 0:
        ret = ret + timedelta(minutes=minutes_offset)
    return ret.strftime("%Y-%m-%d %H:%M:%S")


def get_now_as_iso_timestamp():
    return as_iso_timestamp(datetime.utcnow())


def as_iso_timestamp(date: datetime) -> str | None:
    if date is None:
        return None
    return date.strftime("%Y-%m-%dT%H:%M:%SZ")


def accommodate_dataframe_to_timezone(df, streamlit_session, time_columns=None):
    if time_columns is None:
        time_columns = []
        for column_name in df.columns:
            if df[column_name].dtype == "datetime64[ns]":
                time_columns.append(column_name)

    if time_columns and "browser_timezone" in streamlit_session:
        timezone = streamlit_session["browser_timezone"]
        for time_column in time_columns:
            df[time_column] = pd.to_datetime(df[time_column], errors="coerce")
            df[time_column] = df[time_column].dt.tz_localize("UTC")
            df[time_column] = df[time_column].dt.tz_convert(timezone)
            df[time_column] = df[time_column].dt.strftime("%Y-%m-%d %H:%M:%S")


def create_timezoned_column_in_dataframe(streamlit_session, df, new_column_name, existing_column_name):
    if new_column_name and existing_column_name and "browser_timezone" in streamlit_session:
        timezone = streamlit_session["browser_timezone"]
        df[new_column_name] = (
            df[existing_column_name].dt.tz_localize("UTC").dt.tz_convert(timezone).dt.strftime("%Y-%m-%d %H:%M:%S")
        )


def get_timezoned_timestamp(streamlit_session, value, dateformat="%b %-d, %-I:%M %p"):
    ret = None
    if value and "browser_timezone" in streamlit_session:
        data = {"value": [value]}
        df = pd.DataFrame(data)
        timezone = streamlit_session["browser_timezone"]
        df["value"] = df["value"].dt.tz_localize("UTC").dt.tz_convert(timezone).dt.strftime(dateformat)
        ret = df.iloc[0, 0]
    return ret


def get_timezoned_now(streamlit_session):
    value = datetime.utcnow()
    return get_timezoned_timestamp(streamlit_session, value)


def get_formatted_duration(duration: str | None) -> str:
    if not duration:
        return "--"

    hour, minute, second = duration.split(":")
    formatted = ""
    if int(hour):
        formatted += f"{int(hour)!s}h"
    if int(minute):
        formatted += f" {int(minute)!s}m"
    if int(second):
        formatted += f" {int(second)!s}s"

    formatted = formatted.strip() or "< 1s"
    return formatted
