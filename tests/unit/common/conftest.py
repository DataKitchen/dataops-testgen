from datetime import datetime, timedelta
from typing import NamedTuple

import pandas as pd

from testgen.commands.test_thresholds_prediction import compute_freshness_threshold
from testgen.common.freshness_service import count_excluded_minutes, get_schedule_params, is_excluded_day
from testgen.common.models.test_suite import PredictSensitivity


def _make_freshness_history(
    update_timestamps: list[str],
    check_interval_minutes: int = 120,
) -> pd.DataFrame:
    """Build a sawtooth freshness history from a list of update timestamps.

    Between updates, the signal grows by check_interval_minutes each step.
    At each update, the signal resets to 0.
    """
    updates = sorted(pd.Timestamp(ts) for ts in update_timestamps)
    rows: list[tuple[pd.Timestamp, float]] = []
    for i in range(len(updates) - 1):
        start = updates[i]
        end = updates[i + 1]
        # First segment starts at the exact update time with signal=0 (the update event).
        # Later segments start one check_interval after the update, with signal equal to
        # that interval — simulating the first monitoring check after the update landed.
        t = start if i == 0 else start + pd.Timedelta(minutes=check_interval_minutes)
        signal = 0.0 if i == 0 else float(check_interval_minutes)
        while t < end:
            rows.append((t, signal))
            t += pd.Timedelta(minutes=check_interval_minutes)
            signal += check_interval_minutes
        rows.append((end, 0.0))

    df = pd.DataFrame(rows, columns=["timestamp", "result_signal"])
    df = df.set_index("timestamp")
    return df


# ─── Scenario test infrastructure ────────────────────────────────────


class ScenarioPoint(NamedTuple):
    timestamp: pd.Timestamp
    value: float
    lower: float | None
    upper: float | None
    staleness: float | None
    prediction_json: str | None
    result_code: int        # -1 = training, 1 = passed, 0 = failed
    result_status: str      # "Log", "Passed", "Failed"


def _to_csv_rows(raw: list[tuple[str, str]]) -> list[tuple[pd.Timestamp, float]]:
    """Convert (str, str) tuples from generate_test_data to (Timestamp, float)."""
    return [(pd.Timestamp(ts), float(val)) for ts, val in raw]


def _to_history_df(rows: list[tuple[pd.Timestamp, float]]) -> pd.DataFrame:
    """Convert a list of (timestamp, value) tuples to a DataFrame with DatetimeIndex."""
    df = pd.DataFrame(rows, columns=["timestamp", "value"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def _evaluate_freshness_point(
    timestamp: pd.Timestamp,
    value: float,
    lower: float | None,
    upper: float | None,
    staleness: float | None,
    prediction_json: str | None,
    freshness_last_update: pd.Timestamp | None,
    exclude_weekends: bool,
    tz: str | None,
) -> tuple[int, str]:
    """Evaluate a single freshness observation against thresholds.

    Mirrors the 3-branch decision in simulate_monitor.py (lines 421-476)
    and the SQL template logic. Returns (result_code, result_status).
    """
    effective_staleness = staleness if staleness is not None else upper
    sched = get_schedule_params(prediction_json) if prediction_json else None
    inferred_excluded = sched.excluded_days if sched else None
    win_s = sched.window_start if sched else None
    win_e = sched.window_end if sched else None

    # Training: thresholds not yet available
    if upper is None:
        return -1, "Log"

    # Update point: check completed gap against [lower, upper]
    if value == 0 and freshness_last_update is not None:
        completed_gap = (timestamp - freshness_last_update).total_seconds() / 60
        has_exclusions = exclude_weekends or inferred_excluded or win_s is not None
        if has_exclusions:
            excluded = count_excluded_minutes(
                freshness_last_update, timestamp, exclude_weekends, holiday_dates=None,
                tz=tz, excluded_days=inferred_excluded,
                window_start=win_s, window_end=win_e,
            )
            completed_gap = max(completed_gap - excluded, 0)
        if (lower is not None and completed_gap < lower) or completed_gap > upper:
            return 0, "Failed"
        return 1, "Passed"

    # Between updates: check growing interval against staleness
    if value > 0:
        has_exclusions = exclude_weekends or inferred_excluded or win_s is not None
        is_excl = has_exclusions and is_excluded_day(
            timestamp, exclude_weekends, holiday_dates=None, tz=tz,
            excluded_days=inferred_excluded, window_start=win_s, window_end=win_e,
        )
        if is_excl:
            return 1, "Passed"

        excluded = count_excluded_minutes(
            freshness_last_update, timestamp, exclude_weekends, holiday_dates=None,
            tz=tz, excluded_days=inferred_excluded,
            window_start=win_s, window_end=win_e,
        ) if has_exclusions and freshness_last_update else 0
        business_interval = value - excluded
        if business_interval > effective_staleness:
            return 0, "Failed"
        return 1, "Passed"

    # First update point (value == 0, no prior update)
    return 1, "Passed"


def _run_scenario(
    csv_rows: list[tuple[pd.Timestamp, float]],
    sensitivity: PredictSensitivity,
    exclude_weekends: bool = False,
    tz: str | None = None,
) -> list[ScenarioPoint]:
    """Iterate through csv_rows calling compute_freshness_threshold at each step."""
    results: list[ScenarioPoint] = []
    freshness_last_update: pd.Timestamp | None = None

    for i, (timestamp, value) in enumerate(csv_rows):
        history_df = _to_history_df(csv_rows[:i])

        lower, upper, staleness, prediction_json = compute_freshness_threshold(
            history_df, sensitivity, min_lookback=30,
            exclude_weekends=exclude_weekends, schedule_tz=tz,
        )

        result_code, result_status = _evaluate_freshness_point(
            timestamp, value, lower, upper, staleness, prediction_json,
            freshness_last_update, exclude_weekends, tz,
        )

        results.append(ScenarioPoint(
            timestamp=timestamp,
            value=value,
            lower=lower,
            upper=upper,
            staleness=staleness,
            prediction_json=prediction_json,
            result_code=result_code,
            result_status=result_status,
        ))

        if value == 0:
            freshness_last_update = timestamp

    return results


# ─── Scenario data generators (from generate_test_data.py) ───────────


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _make_observations(
    start: datetime,
    end: datetime,
    interval_hours: int | float,
    update_times: set[datetime],
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    last_update: datetime | None = None
    current = start
    while current <= end:
        if current in update_times:
            rows.append((_ts(current), "0"))
            last_update = current
        elif last_update is not None:
            minutes = int((current - last_update).total_seconds() / 60)
            rows.append((_ts(current), str(minutes)))
        current += timedelta(hours=interval_hours)
    return rows


def _weekday_updates(
    hour: int,
    start: datetime,
    end: datetime,
    skip_dates: set | None = None,
) -> set[datetime]:
    updates: set[datetime] = set()
    d = start.replace(hour=0, minute=0, second=0)
    while d <= end:
        if d.weekday() < 5 and (skip_dates is None or d.date() not in skip_dates):
            updates.add(d.replace(hour=hour, minute=0, second=0))
        d += timedelta(days=1)
    return updates


def _gen_daily_regular() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 7, 0)
    end = datetime(2025, 11, 9, 19, 0)
    updates = _weekday_updates(7, start, end)
    return _to_csv_rows(_make_observations(start, end, 12, updates))


def _gen_daily_late_gap_phase() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 7, 0)
    end = datetime(2025, 11, 16, 19, 0)
    skip = {
        datetime(2025, 10, 29).date(),
        datetime(2025, 10, 30).date(),
        datetime(2025, 10, 31).date(),
    }
    updates = _weekday_updates(7, start, end, skip_dates=skip)
    return _to_csv_rows(_make_observations(start, end, 12, updates))


def _gen_daily_late_schedule_phase() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 7, 0)
    end = datetime(2025, 11, 30, 19, 0)
    skip = {
        datetime(2025, 11, 12).date(),
        datetime(2025, 11, 13).date(),
        datetime(2025, 11, 14).date(),
    }
    updates = _weekday_updates(7, start, end, skip_dates=skip)
    return _to_csv_rows(_make_observations(start, end, 12, updates))


def _gen_subdaily_regular() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 0, 0)
    end = datetime(2025, 11, 2, 23, 0)
    updates: set[datetime] = set()
    d = start.replace(hour=0)
    while d <= end:
        if d.weekday() < 5:
            for h in range(8, 19, 2):
                updates.add(d.replace(hour=h))
        d += timedelta(days=1)
    return _to_csv_rows(_make_observations(start, end, 2, updates))


def _gen_subdaily_gap_phase() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 0, 0)
    end = datetime(2025, 11, 2, 23, 0)
    gap_date = datetime(2025, 10, 22).date()
    updates: set[datetime] = set()
    d = start.replace(hour=0)
    while d <= end:
        if d.weekday() < 5:
            for h in range(8, 19, 2):
                dt = d.replace(hour=h)
                if dt.date() == gap_date and h >= 12:
                    continue
                updates.add(dt)
        d += timedelta(days=1)
    return _to_csv_rows(_make_observations(start, end, 2, updates))


def _gen_subdaily_gap_schedule_phase() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 0, 0)
    end = datetime(2025, 11, 9, 23, 0)
    gap_date = datetime(2025, 10, 29).date()
    updates: set[datetime] = set()
    d = start.replace(hour=0)
    while d <= end:
        if d.weekday() < 5:
            for h in range(8, 19, 2):
                dt = d.replace(hour=h)
                if dt.date() == gap_date and h >= 12:
                    continue
                updates.add(dt)
        d += timedelta(days=1)
    return _to_csv_rows(_make_observations(start, end, 2, updates))


def _gen_weekly_early() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 8, 7, 10, 0)
    end = datetime(2025, 11, 6, 22, 0)
    updates: set[datetime] = set()
    d = start.replace(hour=0)
    while d <= end:
        if d.weekday() == 3:
            updates.add(d.replace(hour=10, minute=0))
        d += timedelta(days=1)
    updates.add(datetime(2025, 10, 21, 10, 0))
    updates.discard(datetime(2025, 10, 23, 10, 0))
    return _to_csv_rows(_make_observations(start, end, 12, updates))


def _gen_training_only() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 7, 0)
    end = datetime(2025, 11, 2, 19, 0)
    updates = {
        datetime(2025, 10, 6, 7, 0),
        datetime(2025, 10, 13, 7, 0),
        datetime(2025, 10, 20, 7, 0),
        datetime(2025, 10, 27, 7, 0),
    }
    return _to_csv_rows(_make_observations(start, end, 12, updates))


def _gen_mwf_regular() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 7, 0)
    end = datetime(2025, 12, 1, 19, 0)
    updates: set[datetime] = set()
    d = start.replace(hour=0)
    while d <= end:
        if d.weekday() in {0, 2, 4}:
            updates.add(d.replace(hour=7, minute=0, second=0))
        d += timedelta(days=1)
    return _to_csv_rows(_make_observations(start, end, 12, updates))


def _gen_mwf_late() -> list[tuple[pd.Timestamp, float]]:
    start = datetime(2025, 10, 6, 7, 0)
    end = datetime(2025, 12, 15, 19, 0)
    skip = {
        datetime(2025, 11, 26).date(),
        datetime(2025, 11, 28).date(),
    }
    updates: set[datetime] = set()
    d = start.replace(hour=0)
    while d <= end:
        if d.weekday() in {0, 2, 4} and d.date() not in skip:
            updates.add(d.replace(hour=7, minute=0, second=0))
        d += timedelta(days=1)
    return _to_csv_rows(_make_observations(start, end, 12, updates))
