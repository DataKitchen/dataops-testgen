import json
import logging
import zoneinfo
from collections import Counter
from datetime import date, datetime
from typing import NamedTuple

import numpy as np
import pandas as pd

from testgen.common.time_series_service import NotEnoughData, get_holiday_dates

LOG = logging.getLogger("testgen")

# Minimum completed gaps needed before freshness threshold is meaningful
MIN_FRESHNESS_GAPS = 5

# Default sliding window size — use only the most recent N gaps
MAX_FRESHNESS_GAPS = 40


class FreshnessThreshold(NamedTuple):
    lower: float | None
    upper: float
    staleness: float
    last_update: pd.Timestamp


class InferredSchedule(NamedTuple):
    stage: str                  # "training", "tentative", "active", "irregular"
    frequency: str              # "sub_daily", "daily", "weekly", "irregular"
    active_days: frozenset[int] # weekday numbers (0=Mon, 6=Sun)
    window_start: float | None  # hour of day (0-24), P10
    window_end: float | None    # hour of day (0-24), P90
    confidence: float           # fraction of events matching schedule
    num_events: int             # total update events used


def get_freshness_gap_threshold(
    history: pd.DataFrame,
    upper_percentile: float,
    floor_multiplier: float,
    lower_percentile: float,
    exclude_weekends: bool = False,
    holiday_codes: list[str] | None = None,
    tz: str | None = None,
    staleness_factor: float = 0.85,
    excluded_days: frozenset[int] | None = None,
    window_start: float | None = None,
    window_end: float | None = None,
) -> FreshnessThreshold:
    """Compute freshness thresholds from completed gap durations.

    Extracts gaps between consecutive table updates (points where result_signal == 0)
    and returns upper and lower thresholds based on percentiles, with a floor for the
    upper bound derived from the maximum observed gap.

    When exclusion flags are set, gap durations are normalized by subtracting
    excluded time (weekends/holidays) that fall within each gap.

    A sliding window limits the number of recent gaps used, so old outliers
    age out of the distribution over time.

    :param history: DataFrame with DatetimeIndex and a result_signal column.
    :param upper_percentile: Percentile for upper bound (e.g. 80, 95, 99).
    :param floor_multiplier: Multiplied by max gap to set an upper floor (e.g. 1.0, 1.25, 1.5).
    :param lower_percentile: Percentile for lower bound (e.g. 5, 10, 20).
    :param exclude_weekends: Subtract weekend days from gap durations.
    :param holiday_codes: Country/market codes for holidays to subtract from gap durations.
    :param tz: IANA timezone (e.g. "America/New_York") for weekday/holiday determination.
    :returns: FreshnessThreshold with lower (in business minutes, None if not computed),
              upper (in business minutes), and last_update timestamp.
    :raises NotEnoughData: If fewer than MIN_FRESHNESS_GAPS completed gaps are found.
    """
    signal = history.iloc[:, 0]
    update_times = signal.index[signal == 0]

    if len(update_times) - 1 < MIN_FRESHNESS_GAPS:
        raise NotEnoughData(
            f"Need at least {MIN_FRESHNESS_GAPS} completed gaps, found {max(len(update_times) - 1, 0)}."
        )

    has_exclusions = exclude_weekends or holiday_codes or excluded_days or (window_start is not None and window_end is not None)
    holiday_dates = resolve_holiday_dates(holiday_codes, history.index) if holiday_codes else None
    gaps_minutes = np.diff(update_times).astype("timedelta64[m]").astype(float)

    if has_exclusions:
        for i in range(len(gaps_minutes)):
            excluded_minutes = count_excluded_minutes(
                update_times[i], update_times[i + 1], exclude_weekends, holiday_dates,
                tz=tz, excluded_days=excluded_days,
                window_start=window_start, window_end=window_end,
            )
            gaps_minutes[i] = max(gaps_minutes[i] - excluded_minutes, 0)

    # Sliding window: keep only the most recent gaps
    if len(gaps_minutes) > MAX_FRESHNESS_GAPS:
        gaps_minutes = gaps_minutes[-MAX_FRESHNESS_GAPS:]

    upper = max(
        float(np.percentile(gaps_minutes, upper_percentile)),
        float(np.max(gaps_minutes)) * floor_multiplier,
    )

    lower = float(np.percentile(gaps_minutes, lower_percentile))
    if lower <= 0:
        lower = None

    staleness = float(np.median(gaps_minutes)) * staleness_factor

    return FreshnessThreshold(lower=lower, upper=upper, staleness=staleness, last_update=update_times[-1])


def resolve_holiday_dates(codes: list[str], index: pd.DatetimeIndex) -> set[date]:
    return {d.date() if isinstance(d, datetime) else d for d in get_holiday_dates(codes, index)}


class ScheduleParams(NamedTuple):
    excluded_days: frozenset[int] | None
    window_start: float | None
    window_end: float | None


def get_schedule_params(prediction: dict | str | None) -> ScheduleParams:
    empty = ScheduleParams(excluded_days=None, window_start=None, window_end=None)
    if not prediction:
        return empty
    prediction = prediction if isinstance(prediction, dict) else json.loads(prediction)

    if prediction.get("schedule_stage") != "active":
        return empty

    active_days = prediction.get("active_days")
    excluded_days = frozenset(range(7)) - frozenset(active_days) if active_days else None

    window_start: float | None = None
    window_end: float | None = None
    if prediction.get("frequency") == "sub_daily":
        if (ws := prediction.get("window_start")) is not None and (we := prediction.get("window_end")) is not None:
            window_start = float(ws)
            window_end = float(we)

    return ScheduleParams(excluded_days=excluded_days, window_start=window_start, window_end=window_end)


def is_excluded_day(
    dt: pd.Timestamp,
    exclude_weekends: bool,
    holiday_dates: set[date] | None,
    tz: str | None = None,
    excluded_days: frozenset[int] | None = None,
    window_start: float | None = None,
    window_end: float | None = None,
) -> bool:
    """Check if a timestamp falls on excluded time.

    Excluded time includes:
    - Weekends (if exclude_weekends is True)
    - Holidays (if holiday_dates is provided)
    - Inferred inactive days (if excluded_days is provided)
    - Hours outside the active window on active days (if window_start/window_end are provided)

    When tz is provided, naive timestamps are interpreted as UTC and converted
    to the given timezone for the weekday/holiday/hour check.
    """
    if tz:
        local_ts = _to_local(dt, tz)
        date_ = local_ts.date()
    else:
        local_ts = dt
        date_ = dt.date()

    if exclude_weekends and date_.weekday() >= 5:
        return True
    if excluded_days and date_.weekday() in excluded_days:
        return True
    if holiday_dates and date_ in holiday_dates:
        return True

    if window_start is not None and window_end is not None:
        hour = local_ts.hour + local_ts.minute / 60.0
        if not _is_in_time_window(hour, window_start, window_end):
            return True
    return False


def next_business_day_start(
    dt: pd.Timestamp,
    exclude_weekends: bool,
    holiday_dates: set[date] | None,
    tz: str | None = None,
    excluded_days: frozenset[int] | None = None,
) -> pd.Timestamp:
    day = (pd.Timestamp(dt) + pd.DateOffset(days=1)).normalize()
    while is_excluded_day(day, exclude_weekends, holiday_dates, tz=tz, excluded_days=excluded_days):
        day += pd.DateOffset(days=1)
    return day


def count_excluded_minutes(
    start: pd.Timestamp,
    end: pd.Timestamp,
    exclude_weekends: bool,
    holiday_dates: set[date] | None,
    tz: str | None = None,
    excluded_days: frozenset[int] | None = None,
    window_start: float | None = None,
    window_end: float | None = None,
) -> float:
    """Count excluded minutes between two timestamps, including partial days.

    Iterates day-by-day from start to end, counting the overlap between each
    excluded day (weekend or holiday) and the [start, end] interval. Partial
    excluded days at the boundaries are correctly prorated.

    When window_start/window_end are provided (sub-daily active schedules),
    hours outside the [window_start, window_end] range on active days are also
    counted as excluded. Fully excluded days (weekends, holidays, inactive days)
    still count their entire overlap as excluded — the window only applies to
    days that are otherwise active.

    When tz is provided, naive timestamps are converted to the local timezone
    for weekday/holiday determination. The overlap is computed in naive local
    time (timezone stripped after conversion) so that every calendar day is
    exactly 24 h — this keeps excluded minutes consistent with UTC-based raw
    gaps and avoids DST distortion (fall-back days counting 25 h, spring-forward
    days counting 23 h).
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)

    if tz:
        # Convert to local, then strip timezone → naive local time so each day
        # is exactly 24 h. This prevents DST transitions from inflating/deflating
        # excluded time relative to the UTC-based raw gap that callers subtract from.
        start = _to_local(start, tz).tz_localize(None)
        end = _to_local(end, tz).tz_localize(None)

    if start >= end:
        return 0.0

    has_window = window_start is not None and window_end is not None

    total_minutes = 0.0
    day_start = start.normalize()

    while day_start < end:
        next_day = day_start + pd.Timedelta(days=1)

        if is_excluded_day(day_start, exclude_weekends, holiday_dates, excluded_days=excluded_days):
            # Full day excluded (weekend, holiday, inactive day)
            overlap_start = max(start, day_start)
            overlap_end = min(end, next_day)
            total_minutes += (overlap_end - overlap_start).total_seconds() / 60
        elif has_window:
            # Active day but with window exclusion: exclude hours outside the window
            # Compute the active window boundaries for this calendar day
            win_open = day_start + pd.Timedelta(hours=window_start)
            win_close = day_start + pd.Timedelta(hours=window_end)

            # Clip to the [start, end] interval
            overlap_start = max(start, day_start)
            overlap_end = min(end, next_day)

            # Excluded = time in [overlap_start, overlap_end] that is outside [win_open, win_close]
            # = total overlap - time inside window
            total_overlap = (overlap_end - overlap_start).total_seconds() / 60

            # Compute overlap with the active window
            active_start = max(overlap_start, win_open)
            active_end = min(overlap_end, win_close)
            active_minutes = max((active_end - active_start).total_seconds() / 60, 0)

            excluded_on_day = total_overlap - active_minutes
            if excluded_on_day > 0:
                total_minutes += excluded_on_day

        day_start = next_day

    return total_minutes


def add_business_minutes(
    start: pd.Timestamp | datetime,
    business_minutes: float,
    exclude_weekends: bool,
    holiday_dates: set[date] | None,
    tz: str | None = None,
    excluded_days: frozenset[int] | None = None,
) -> pd.Timestamp:
    """Advance wall-clock time by N business minutes, skipping excluded days.

    Inverse of count_excluded_minutes: given a start time and a number of
    business minutes to elapse, returns the wall-clock timestamp at which
    those minutes will have passed, skipping weekends and holidays.

    When tz is provided, naive timestamps are interpreted as UTC and day
    boundary checks use the local timezone.
    """
    start = pd.Timestamp(start)
    if business_minutes <= 0:
        return start

    has_exclusions = exclude_weekends or bool(holiday_dates) or bool(excluded_days)
    if not has_exclusions:
        return start + pd.Timedelta(minutes=business_minutes)

    cursor = start
    if tz:
        cursor = _to_local(cursor, tz)

    remaining = business_minutes

    while remaining > 0:
        day_start = cursor.normalize()
        next_day = (day_start + pd.DateOffset(days=1)).normalize()

        if is_excluded_day(cursor, exclude_weekends, holiday_dates, excluded_days=excluded_days):
            cursor = next_day
            # Skip consecutive excluded days
            for _ in range(365):
                if not is_excluded_day(cursor, exclude_weekends, holiday_dates, excluded_days=excluded_days):
                    break
                cursor = (cursor + pd.DateOffset(days=1)).normalize()
            continue

        minutes_left_today = (next_day - cursor).total_seconds() / 60

        if remaining <= minutes_left_today:
            cursor = cursor + pd.Timedelta(minutes=remaining)
            remaining = 0
        else:
            remaining -= minutes_left_today
            cursor = next_day

    if tz and start.tzinfo is None:
        cursor = cursor.tz_convert("UTC").tz_localize(None)

    return cursor


def _is_in_time_window(hour: float, window_start: float, window_end: float) -> bool:
    if window_start <= window_end:
        return window_start <= hour <= window_end
    return hour >= window_start or hour <= window_end


def _to_local(ts: pd.Timestamp, tz: str) -> pd.Timestamp:
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(zoneinfo.ZoneInfo(tz))


def _next_active_day(start: pd.Timestamp, active_days: frozenset[int], max_days: int = 14) -> pd.Timestamp | None:
    candidate = start
    for _ in range(max_days):
        if candidate.weekday() in active_days:
            return candidate
        candidate += pd.Timedelta(days=1)
    return None


def _set_fractional_hour(ts: pd.Timestamp, fractional_hour: float) -> pd.Timestamp:
    hour = int(fractional_hour)
    minute = int((fractional_hour - hour) * 60)
    return ts.replace(hour=hour, minute=minute, second=0, microsecond=0)


def classify_frequency(gaps_hours: np.ndarray) -> str:
    """Classify table update frequency from inter-update gaps.

    Frequency does NOT gate the schedule stage — stage is determined by
    confidence (>= 0.75 → "active").  However, frequency does affect which
    threshold path is used: "sub_daily" enables within-window gap thresholds,
    while other values use deadline-based thresholds.

    Multi-day cadences (median 36-120h, e.g. Mon/Wed/Fri or Tue/Thu) classify
    as "irregular" because they fall between the daily and weekly bands, but
    they can still reach "active" stage when ``detect_active_days`` finds a
    consistent day-of-week and time-of-day pattern.

    Bands:
      - sub_daily: median < 6h
      - daily:     6h <= median < 36h
      - weekly:    120h < median < 240h  (roughly 5-10 days)
      - irregular: everything else (0 gaps, 36-120h, 240h+)

    :param gaps_hours: Array of gap durations in hours between consecutive updates.
    :returns: One of "sub_daily", "daily", "weekly", "irregular".
    """
    if len(gaps_hours) == 0:
        return "irregular"
    median_gap = float(np.median(gaps_hours))
    if median_gap < 6:
        return "sub_daily"
    elif median_gap < 36:
        return "daily"
    elif 120 < median_gap < 240:
        return "weekly"
    else:
        return "irregular"


def detect_active_days(
    update_times: list[pd.Timestamp],
    tz: str,
    min_weeks: int = 3,
) -> frozenset[int] | None:
    """Detect which days of the week have updates.

    :param update_times: Sorted list of update timestamps (UTC or naive-UTC).
    :param tz: IANA timezone for local day-of-week mapping.
    :param min_weeks: Minimum weeks of data needed.
    :returns: frozenset of weekday numbers (0=Mon, 6=Sun) or None if insufficient data.
    """
    if len(update_times) < 2:
        return None

    local_times = [_to_local(t, tz) for t in update_times]

    date_range_days = (local_times[-1] - local_times[0]).days
    if date_range_days < min_weeks * 7:
        return None

    day_counts: Counter[int] = Counter(t.weekday() for t in local_times)
    weeks_observed = max(1, date_range_days // 7)

    active_days: set[int] = set()
    for day in range(7):
        count = day_counts.get(day, 0)
        hit_rate = count / weeks_observed
        if hit_rate >= 0.5:
            active_days.add(day)

    return frozenset(active_days) if active_days else None


def detect_update_window(
    update_times: list[pd.Timestamp],
    active_days: frozenset[int],
    tz: str,
) -> tuple[float, float] | None:
    """Detect the time-of-day window when updates arrive on active days.

    :returns: (window_start, window_end) as hours 0-24, or None.
    """
    local_times = [_to_local(t, tz) for t in update_times]

    hours_on_active_days = [
        t.hour + t.minute / 60.0
        for t in local_times
        if t.weekday() in active_days
    ]

    if len(hours_on_active_days) < 10:
        return None

    # Handle midnight-wrapping clusters (e.g., 23:00-01:00)
    shifted = False
    late = sum(1 for h in hours_on_active_days if h >= 22) / len(hours_on_active_days)
    early = sum(1 for h in hours_on_active_days if h < 3) / len(hours_on_active_days)
    if late > 0.25 and early > 0.25:
        hours_on_active_days = [(h + 12) % 24 for h in hours_on_active_days]
        shifted = True

    p10 = float(np.percentile(hours_on_active_days, 10))
    p90 = float(np.percentile(hours_on_active_days, 90))

    if shifted:
        p10 = (p10 - 12) % 24
        p90 = (p90 - 12) % 24

    return (p10, p90)


def compute_schedule_confidence(
    update_times: list[pd.Timestamp],
    schedule: InferredSchedule,
    tz: str,
) -> float:
    """Fraction of historical updates that match the detected schedule.

    An update "matches" if it falls on an active day and (if a window is defined)
    within the P10-P90 time window.
    """
    if not update_times:
        return 0.0

    matching = 0
    for t in update_times:
        lt = _to_local(t, tz)
        if lt.weekday() not in schedule.active_days:
            continue
        if schedule.window_start is not None and schedule.window_end is not None:
            hour = lt.hour + lt.minute / 60.0
            if not _is_in_time_window(hour, schedule.window_start, schedule.window_end):
                continue
        matching += 1
    return matching / len(update_times)


def infer_schedule(
    history: pd.DataFrame,
    tz: str,
) -> InferredSchedule | None:
    """Attempt to infer a table's update schedule from its freshness history.

    :param history: DataFrame with DatetimeIndex and result_signal column (0 = update).
    :param tz: IANA timezone for local time analysis.
    :returns: InferredSchedule or None if insufficient data for any inference.
    """
    signal = history.iloc[:, 0]
    update_times = list(signal.index[signal == 0])

    if len(update_times) < 10:
        return None

    # Compute gaps in hours
    gaps_hours = np.diff(update_times).astype("timedelta64[m]").astype(float) / 60.0

    frequency = classify_frequency(gaps_hours)
    num_events = len(update_times)

    # Determine stage based on data quantity
    local_times = [_to_local(t, tz) for t in update_times]
    date_range_days = (local_times[-1] - local_times[0]).days

    if date_range_days < 21 or num_events < 10:
        return None  # Not enough data for any inference

    # Detect active days
    active_days = detect_active_days(update_times, tz)
    if active_days is None:
        active_days = frozenset(range(7))

    # Detect update window
    window_result = detect_update_window(update_times, active_days, tz)
    window_start = window_result[0] if window_result else None
    window_end = window_result[1] if window_result else None

    # Build preliminary schedule for confidence scoring
    preliminary = InferredSchedule(
        frequency=frequency,
        active_days=active_days,
        window_start=window_start,
        window_end=window_end,
        confidence=0.0,
        num_events=num_events,
        stage="training",
    )

    confidence = compute_schedule_confidence(update_times, preliminary, tz)

    # Determine stage
    if num_events < 20:
        stage = "tentative"
    elif confidence >= 0.75:
        stage = "active"
    elif confidence < 0.60:
        stage = "irregular"
    else:
        stage = "tentative"

    return preliminary._replace(confidence=confidence, stage=stage)


def minutes_to_next_deadline(
    last_update: pd.Timestamp,
    schedule: InferredSchedule,
    exclude_weekends: bool,
    holiday_dates: set[date] | None,
    tz: str,
    buffer_hours: float,
    excluded_days: frozenset[int] | None = None,
) -> float | None:
    if schedule.window_end is None:
        return None

    deadline_hour = (schedule.window_end + buffer_hours) % 24
    local_last = _to_local(last_update, tz)

    # Find the next active day after last_update
    candidate = _next_active_day(local_last.normalize() + pd.Timedelta(days=1), schedule.active_days)
    if candidate is None:
        return None

    # Set the deadline time on that day
    deadline_ts = _set_fractional_hour(candidate, deadline_hour)

    # If the deadline is already past relative to now, move to next active day
    if deadline_ts <= local_last:
        candidate = _next_active_day(candidate + pd.Timedelta(days=1), schedule.active_days)
        if candidate is None:
            return None
        deadline_ts = _set_fractional_hour(candidate, deadline_hour)

    # Convert both to UTC for consistent gap calculation
    utc_last = local_last.tz_convert("UTC").tz_localize(None)
    utc_deadline = deadline_ts.tz_convert("UTC").tz_localize(None)

    wall_minutes = (utc_deadline - utc_last).total_seconds() / 60.0
    if wall_minutes <= 0:
        return None

    if exclude_weekends or holiday_dates or excluded_days:
        excl = count_excluded_minutes(utc_last, utc_deadline, exclude_weekends, holiday_dates, tz=tz, excluded_days=excluded_days)
        return max(wall_minutes - excl, 0)

    return wall_minutes
