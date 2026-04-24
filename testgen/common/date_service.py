import calendar
import re
from datetime import UTC, date, datetime, timedelta

import pandas as pd

_RELATIVE_SINCE_RE = re.compile(
    r"^\s*(\d+)\s*(d|day|days|w|week|weeks|mo|month|months)\s*$",
    re.IGNORECASE,
)


def _subtract_months(d: date, months: int) -> date:
    """Subtract calendar months, clamping the day to the last valid day of the target month."""
    zero_indexed = d.month - 1 - months
    new_year = d.year + zero_indexed // 12
    new_month = zero_indexed % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    return date(new_year, new_month, min(d.day, last_day))


def parse_since(since: str, *, today: date | None = None) -> date:
    """Parse a relative expression or ISO date into a calendar ``date``.

    Accepted forms:
      - Relative: "7 days", "2 weeks", "30d", "1 month", "3mo"
      - ISO-8601 date: "2026-04-01"

    Raises ``ValueError`` on any other input.

    Relative expressions always represent a window ending today inclusive:
      - "N days" = N calendar days ending today (e.g. "14 days" → today - 13 days).
      - "N weeks" = N*7 calendar days ending today.
      - "N months" = same day-of-month N calendar months ago, clamped to the target
        month's last valid day (e.g. "1 month" on 03-31 → 02-28).

    The caller owns any time-of-day or timezone concerns (e.g. for SQL comparisons,
    Postgres coerces a ``date`` bind param to the start of that day).
    """
    if not isinstance(since, str) or not since.strip():
        raise ValueError("expected a non-empty string")

    anchor = today or datetime.now(UTC).date()
    match = _RELATIVE_SINCE_RE.match(since)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("d"):
            return anchor - timedelta(days=amount - 1)
        if unit.startswith("w"):
            return anchor - timedelta(days=amount * 7 - 1)
        return _subtract_months(anchor, amount)

    try:
        return date.fromisoformat(since.strip())
    except ValueError as err:
        raise ValueError(
            f"expected a relative expression like '7 days', '2 weeks', '1 month', "
            f"or an ISO-8601 date; got `{since}`"
        ) from err


def parse_fuzzy_date(value: str | int) -> datetime | None:
    if type(value) == str:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    elif type(value) == int or type(value) == float:
        ts = int(value)
        if ts >= 1e11:
            ts /= 1000
        return datetime.fromtimestamp(ts)
    return value


def get_now_as_iso_timestamp():
    return as_iso_timestamp(datetime.now(UTC))


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


def get_timezoned_timestamp(streamlit_session, value, dateformat="%b %-d, %-I:%M %p"):
    ret = None
    if value and "browser_timezone" in streamlit_session:
        data = {"value": [value]}
        df = pd.DataFrame(data)
        timezone = streamlit_session["browser_timezone"]
        df["value"] = df["value"].dt.tz_localize("UTC").dt.tz_convert(timezone).dt.strftime(dateformat)
        ret = df.iloc[0, 0]
    return ret
