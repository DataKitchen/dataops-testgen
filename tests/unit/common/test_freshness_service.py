import json
import zoneinfo

import numpy as np
import pandas as pd

from testgen.commands.test_thresholds_prediction import compute_freshness_threshold
from testgen.common.freshness_service import (
    MAX_FRESHNESS_GAPS,
    InferredSchedule,
    add_business_minutes,
    classify_frequency,
    compute_schedule_confidence,
    count_excluded_minutes,
    detect_active_days,
    detect_update_window,
    get_freshness_gap_threshold,
    get_schedule_params,
    infer_schedule,
    is_excluded_day,
    minutes_to_next_deadline,
)
from testgen.common.models.test_suite import PredictSensitivity

from .conftest import _make_freshness_history

TZ = "America/New_York"


def _make_schedule(**kwargs) -> InferredSchedule:
    """Build an InferredSchedule with sensible defaults, overridable via kwargs."""
    defaults = {
        "frequency": "daily",
        "active_days": frozenset(range(5)),
        "window_start": 9.0,
        "window_end": 13.0,
        "confidence": 0.0,
        "num_events": 20,
        "stage": "active",
    }
    defaults.update(kwargs)
    return InferredSchedule(**defaults)


def _utc_timestamps(local_strings: list[str], tz: str = TZ) -> list[pd.Timestamp]:
    """Convert local time strings to naive UTC timestamps (as stored in DB)."""
    zi = zoneinfo.ZoneInfo(tz)
    result = []
    for s in local_strings:
        local_ts = pd.Timestamp(s, tz=zi)
        utc_ts = local_ts.tz_convert("UTC").tz_localize(None)
        result.append(utc_ts)
    return result


# ---------------------------------------------------------------------------
# Sliding Window Tests
# ---------------------------------------------------------------------------

class Test_SlidingWindow:
    def test_outlier_ages_out(self):
        # Build history: 1 big outlier gap followed by many normal gaps
        updates = ["2026-01-01T00:00"]
        # Outlier gap: 72h
        updates.append("2026-01-04T00:00")
        # Then 50 normal gaps of ~10h each (well beyond MAX_FRESHNESS_GAPS)
        for i in range(50):
            base = pd.Timestamp("2026-01-04T00:00") + pd.Timedelta(hours=10 * (i + 1))
            updates.append(str(base))

        history = _make_freshness_history(updates)

        result = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10,
        )

        # Sliding window drops the 72h outlier — threshold should be near 10h (600 min)
        assert result.upper < 1000

    def test_window_size_respected(self):
        # Create exactly MAX_FRESHNESS_GAPS + 5 gaps, first 5 are big outliers
        updates = ["2026-01-01T00:00"]
        for idx in range(5):
            # 5 outlier gaps of 100h
            updates.append(str(pd.Timestamp("2026-01-01T00:00") + pd.Timedelta(hours=100 * (idx + 1))))
        base = pd.Timestamp(updates[-1])
        for _ in range(MAX_FRESHNESS_GAPS):
            base += pd.Timedelta(hours=10)
            updates.append(str(base))

        history = _make_freshness_history(updates)

        result = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.0, lower_percentile=10,
        )
        # With window, P95 should be close to 600 min (10h gaps)
        # Without window, P95 would be inflated by 100h gaps
        assert result.upper < 1000  # Well below the 6000-min outlier gaps


# ---------------------------------------------------------------------------
# classify_frequency Tests
# ---------------------------------------------------------------------------

class Test_ClassifyFrequency:
    def test_sub_daily(self):
        gaps = np.array([1.0, 2.0, 1.5, 2.5, 1.0])
        assert classify_frequency(gaps) == "sub_daily"

    def test_daily(self):
        gaps = np.array([24.0, 23.0, 25.0, 24.0, 22.0])
        assert classify_frequency(gaps) == "daily"

    def test_weekly(self):
        gaps = np.array([168.0, 167.0, 169.0, 168.0])
        assert classify_frequency(gaps) == "weekly"

    def test_irregular_empty(self):
        assert classify_frequency(np.array([])) == "irregular"

    def test_irregular_mixed(self):
        # Median around 50h — doesn't fit daily or weekly
        gaps = np.array([40.0, 50.0, 60.0, 45.0, 55.0])
        assert classify_frequency(gaps) == "irregular"

    def test_boundary_36h_daily_to_irregular(self):
        # Median exactly at 36h — boundary of daily band (< 36 → daily)
        gaps = np.array([35.0, 36.0, 37.0, 35.5, 36.5])
        assert classify_frequency(gaps) == "irregular"

    def test_boundary_just_under_36h(self):
        # Median just under 36h — still daily
        gaps = np.array([34.0, 35.0, 35.5, 34.5, 35.0])
        assert classify_frequency(gaps) == "daily"

    def test_every_other_day_48h(self):
        # Median ~48h (every other day, e.g. MWF cadence) → irregular
        gaps = np.array([48.0, 47.0, 49.0, 48.0, 47.5])
        assert classify_frequency(gaps) == "irregular"

    def test_boundary_120h(self):
        # Median at 120h — still in the irregular band (not weekly)
        gaps = np.array([118.0, 120.0, 122.0, 119.0, 121.0])
        assert classify_frequency(gaps) == "irregular"

    def test_boundary_240h_and_above(self):
        # Median at 240h — boundary of weekly band (weekly < 240)
        gaps = np.array([238.0, 240.0, 242.0, 239.0, 241.0])
        assert classify_frequency(gaps) == "irregular"


# ---------------------------------------------------------------------------
# detect_active_days Tests
# ---------------------------------------------------------------------------

class Test_DetectActiveDays:
    def test_weekday_only(self):
        # 4 weeks of weekday-only updates (Mon-Fri)
        timestamps = []
        for week in range(4):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)  # Monday
            for day in range(5):  # Mon-Fri
                ts = base + pd.Timedelta(days=day, hours=10)
                timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        result = detect_active_days(utc_times, TZ)

        assert result is not None
        assert result == frozenset({0, 1, 2, 3, 4})

    def test_mon_wed_fri(self):
        # 4 weeks of Mon/Wed/Fri updates
        timestamps = []
        for week in range(4):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day_offset in [0, 2, 4]:  # Mon, Wed, Fri
                ts = base + pd.Timedelta(days=day_offset, hours=10)
                timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        result = detect_active_days(utc_times, TZ)

        assert result is not None
        assert 0 in result  # Monday
        assert 2 in result  # Wednesday
        assert 4 in result  # Friday

    def test_all_days(self):
        # 4 weeks of daily updates (7 days/week)
        timestamps = []
        for day in range(28):
            ts = pd.Timestamp("2026-01-05") + pd.Timedelta(days=day, hours=10)
            timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        result = detect_active_days(utc_times, TZ)

        assert result is not None
        assert len(result) == 7

    def test_insufficient_data(self):
        # Only 2 weeks of data (below min_weeks=3)
        timestamps = []
        for day in range(14):
            ts = pd.Timestamp("2026-01-05") + pd.Timedelta(days=day, hours=10)
            timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        result = detect_active_days(utc_times, TZ)

        assert result is None


# ---------------------------------------------------------------------------
# detect_update_window Tests
# ---------------------------------------------------------------------------

class Test_DetectUpdateWindow:
    def test_morning_cluster(self):
        # 15 updates around 10-12 AM on weekdays
        timestamps = []
        for day in range(15):
            hour = 10 + (day % 3)  # 10, 11, 12 cycling
            ts = pd.Timestamp("2026-01-05") + pd.Timedelta(days=day, hours=hour)
            timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        active_days = frozenset(range(7))
        result = detect_update_window(utc_times, active_days, TZ)

        assert result is not None
        window_start, window_end = result
        assert 9.0 <= window_start <= 11.0
        assert 11.0 <= window_end <= 13.0

    def test_insufficient_data(self):
        # Only 5 updates — below threshold of 10
        timestamps = [
            pd.Timestamp("2026-01-05T10:00"),
            pd.Timestamp("2026-01-06T10:00"),
            pd.Timestamp("2026-01-07T10:00"),
            pd.Timestamp("2026-01-08T10:00"),
            pd.Timestamp("2026-01-09T10:00"),
        ]
        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        result = detect_update_window(utc_times, frozenset(range(7)), TZ)
        assert result is None

    def test_midnight_wrap(self):
        # Updates around midnight (23:00-01:00)
        timestamps = []
        for day in range(15):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(days=day)
            if day % 3 == 0:
                ts = base + pd.Timedelta(hours=23)
            elif day % 3 == 1:
                ts = base + pd.Timedelta(hours=23, minutes=30)
            else:
                ts = base + pd.Timedelta(hours=0, minutes=30)
            timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        result = detect_update_window(utc_times, frozenset(range(7)), TZ)

        assert result is not None
        # Window should wrap around midnight



# ---------------------------------------------------------------------------
# compute_schedule_confidence Tests
# ---------------------------------------------------------------------------

class Test_ComputeScheduleConfidence:
    def test_high_confidence(self):
        # All updates on weekdays 10-12 AM
        schedule = _make_schedule()
        timestamps = []
        for day in range(20):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(days=day)
            if base.weekday() < 5:
                ts = base + pd.Timedelta(hours=10 + (day % 3))
                timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        confidence = compute_schedule_confidence(utc_times, schedule, TZ)
        assert confidence >= 0.7

    def test_low_confidence(self):
        # Updates scattered across all hours and days
        schedule = _make_schedule()
        timestamps = []
        for i in range(20):
            ts = pd.Timestamp("2026-01-05") + pd.Timedelta(hours=i * 17)  # irregular spacing
            timestamps.append(ts)

        utc_times = [ts.tz_localize(TZ).tz_convert("UTC").tz_localize(None) for ts in timestamps]
        confidence = compute_schedule_confidence(utc_times, schedule, TZ)
        assert confidence < 0.7


# ---------------------------------------------------------------------------
# infer_schedule Tests
# ---------------------------------------------------------------------------

class Test_InferSchedule:
    def test_daily_weekday_pattern(self):
        # 4 weeks of weekday updates at ~10 AM ET
        updates = []
        for week in range(4):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10, minutes=(day * 10) % 60)
                updates.append(str(ts))

        history = _make_freshness_history(updates, check_interval_minutes=120)
        # Convert timestamps to UTC (history uses naive timestamps treated as UTC)
        zi = zoneinfo.ZoneInfo(TZ)
        utc_updates = []
        for s in updates:
            local_ts = pd.Timestamp(s, tz=zi)
            utc_ts = local_ts.tz_convert("UTC").tz_localize(None)
            utc_updates.append(str(utc_ts))
        history = _make_freshness_history(utc_updates, check_interval_minutes=120)

        schedule = infer_schedule(history, TZ)

        assert schedule is not None
        assert schedule.frequency == "daily"
        assert schedule.num_events == 20

    def test_insufficient_data_returns_none(self):
        # Only 5 updates
        updates = [f"2026-02-{d:02d}T10:00" for d in range(1, 6)]
        history = _make_freshness_history(updates)
        result = infer_schedule(history, TZ)
        assert result is None

    def test_mon_wed_fri_pattern(self):
        """MWF updates at ~10 AM ET for 7 weeks (21 events) → stage should be 'active', not forced to 'irregular'."""
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(7):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)  # Monday
            for day_offset in [0, 2, 4]:  # Mon, Wed, Fri
                ts = base + pd.Timedelta(days=day_offset, hours=10, minutes=(day_offset * 7) % 30)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)
        schedule = infer_schedule(history, TZ)

        assert schedule is not None
        assert schedule.frequency == "irregular"  # median gap ~48h falls in irregular band
        assert schedule.stage == "active"  # confidence-based, NOT forced to "irregular"
        assert schedule.num_events == 21
        assert 0 in schedule.active_days  # Monday
        assert 2 in schedule.active_days  # Wednesday
        assert 4 in schedule.active_days  # Friday

    def test_tue_thu_pattern(self):
        """Tue/Thu updates at ~10 AM ET for 10 weeks (20 events) → stage should be 'active'."""
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(10):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)  # Monday
            for day_offset in [1, 3]:  # Tue, Thu
                ts = base + pd.Timedelta(days=day_offset, hours=10, minutes=(day_offset * 5) % 20)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)
        schedule = infer_schedule(history, TZ)

        assert schedule is not None
        assert schedule.frequency == "irregular"  # median gap ~72-84h
        assert schedule.stage == "active"  # high confidence from consistent day+time pattern
        assert 1 in schedule.active_days  # Tuesday
        assert 3 in schedule.active_days  # Thursday

    def test_sub_daily_pattern(self):
        # 4 weeks of hourly updates during business hours
        updates = []
        for week in range(4):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                for hour in range(9, 17):
                    ts = base + pd.Timedelta(days=day, hours=hour)
                    updates.append(str(ts))

        zi = zoneinfo.ZoneInfo(TZ)
        utc_updates = []
        for s in updates:
            local_ts = pd.Timestamp(s, tz=zi)
            utc_ts = local_ts.tz_convert("UTC").tz_localize(None)
            utc_updates.append(str(utc_ts))
        history = _make_freshness_history(utc_updates, check_interval_minutes=30)

        schedule = infer_schedule(history, TZ)

        assert schedule is not None
        assert schedule.frequency == "sub_daily"
        assert schedule.num_events > 50


# ---------------------------------------------------------------------------
# compute_freshness_threshold with schedule inference Tests
# ---------------------------------------------------------------------------

class Test_ComputeFreshnessThresholdWithSchedule:
    def test_returns_prediction_json_with_tz(self):
        """When tz is provided and enough data exists, prediction JSON should contain schedule info."""
        # 4 weeks of daily weekday updates
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(4):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)
        lower, upper, staleness, prediction_json = compute_freshness_threshold(
            history, PredictSensitivity.medium, schedule_tz=TZ,
        )

        assert upper is not None
        assert prediction_json is not None
        data = json.loads(prediction_json)
        if "schedule_stage" in data:
            assert data["schedule_stage"] in {"training", "tentative", "active", "irregular"}
            assert "frequency" in data
            assert "confidence" in data
            # staleness is non-None only when schedule is active
            if data.get("schedule_stage") == "active":
                assert staleness is not None

    def test_schedule_overrides_threshold_when_active(self):
        """When schedule inference reaches 'active' stage, staleness and upper should be set."""
        zi = zoneinfo.ZoneInfo(TZ)
        # 5 weeks of daily weekday updates at 10 AM ET — 25 events, highly regular
        updates = []
        for week in range(5):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)



        lower, upper, staleness, prediction_json = compute_freshness_threshold(
            history, PredictSensitivity.medium, schedule_tz=TZ,
        )

        assert upper is not None
        assert upper > 0
        assert prediction_json is not None
        assert staleness is not None  # Active schedule → staleness returned

        data = json.loads(prediction_json)
        assert data["schedule_stage"] == "active"
        assert "active_days" in data

    def test_prediction_json_includes_sensitivity_metadata(self):
        """Prediction JSON should include sensitivity-related fields."""
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(5):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)


        _, _, _, prediction_json = compute_freshness_threshold(
            history, PredictSensitivity.high, schedule_tz=TZ,
        )

        assert prediction_json is not None
        data = json.loads(prediction_json)
        assert data["sensitivity"] == "high"
        assert data["deadline_buffer_hours"] == 1.5

    def test_high_sensitivity_tighter_than_low_end_to_end(self):
        """Via compute_freshness_threshold: high sensitivity yields a tighter upper than low."""
        zi = zoneinfo.ZoneInfo(TZ)
        # 5 weeks of daily weekday updates at 10 AM ET — reaches active schedule
        updates = []
        for week in range(5):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)


        _, upper_high, _, json_high = compute_freshness_threshold(
            history, PredictSensitivity.high, schedule_tz=TZ,
        )
        _, upper_low, _, json_low = compute_freshness_threshold(
            history, PredictSensitivity.low, schedule_tz=TZ,
        )

        assert upper_high is not None and upper_low is not None
        assert json_high is not None and json_low is not None

        data_high = json.loads(json_high)
        data_low = json.loads(json_low)
        assert data_high["schedule_stage"] == "active"
        assert data_low["schedule_stage"] == "active"
        assert upper_high < upper_low

    def test_no_schedule_without_tz(self):
        """Without tz, schedule inference is skipped and staleness_upper is absent."""
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)
        _, _, staleness, prediction = compute_freshness_threshold(history, PredictSensitivity.medium)
        assert staleness is None  # No tz → no active schedule → staleness is None
        assert prediction is not None
        data = json.loads(prediction)
        assert "schedule_stage" not in data  # No schedule inference without tz

    def test_staleness_returned_with_active_schedule(self):
        """When schedule inference reaches active stage, staleness is returned as 4th element."""
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(5):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)


        _, _, staleness, prediction_json = compute_freshness_threshold(
            history, PredictSensitivity.medium, schedule_tz=TZ,
        )

        assert staleness is not None
        assert staleness > 0
        assert prediction_json is not None
        data = json.loads(prediction_json)
        assert data["schedule_stage"] == "active"

    def test_excluded_days_in_prediction_json_when_active(self):
        """When schedule reaches active with weekday-only pattern, excluded_days=[5,6] in prediction JSON."""
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(5):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)


        _, _, _, prediction_json = compute_freshness_threshold(
            history, PredictSensitivity.medium, schedule_tz=TZ,
        )

        assert prediction_json is not None
        data = json.loads(prediction_json)
        assert data["schedule_stage"] == "active"
        assert "active_days" in data
        assert sorted(data["active_days"]) == [0, 1, 2, 3, 4]

    def test_staleness_recomputed_with_excluded_days(self):
        """Active schedule with weekday-only pattern: staleness is returned with tz, None without."""
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(5):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)
            for day in range(5):
                ts = base + pd.Timedelta(days=day, hours=10)
                utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                updates.append(str(utc))

        history = _make_freshness_history(updates, check_interval_minutes=120)


        # With tz (triggers schedule inference + excluded_days recomputation)
        _, _, staleness_with_tz, pred_json_with_tz = compute_freshness_threshold(
            history, PredictSensitivity.medium, schedule_tz=TZ,
        )
        # Without tz (no schedule inference, no staleness)
        _, _, staleness_no_tz, pred_json_no_tz = compute_freshness_threshold(
            history, PredictSensitivity.medium,
        )

        assert pred_json_with_tz is not None and pred_json_no_tz is not None
        data_with = json.loads(pred_json_with_tz)

        # With active schedule, staleness is returned
        assert data_with["schedule_stage"] == "active"
        assert staleness_with_tz is not None
        assert staleness_with_tz > 0

        # Without tz, staleness is None (no active schedule)
        assert staleness_no_tz is None

    def test_staleness_catches_daily_miss_that_upper_misses(self):
        """Staleness threshold detects a missed daily update at gap=1440 min where upper doesn't."""
        # Daily weekday pattern: all gaps ~1440 min (24h)
        updates = [f"2026-02-{d:02d}T08:00" for d in range(2, 9) if pd.Timestamp(f"2026-02-{d:02d}").weekday() < 5]
        # Ensure we have enough gaps
        while len(updates) < 8:
            updates.append(f"2026-02-{9 + len(updates) - 7:02d}T08:00")
        history = _make_freshness_history(updates)

        from testgen.commands.test_thresholds_prediction import FRESHNESS_THRESHOLD_MAP, STALENESS_FACTOR_MAP
        upper_pct, floor_mult, lower_pct = FRESHNESS_THRESHOLD_MAP[PredictSensitivity.medium]
        staleness_factor = STALENESS_FACTOR_MAP[PredictSensitivity.medium]

        result = get_freshness_gap_threshold(
            history, upper_percentile=upper_pct, floor_multiplier=floor_mult, lower_percentile=lower_pct,
            staleness_factor=staleness_factor,
        )

        # The typical gap is ~1440 min. After a missed update, the next check shows gap=1440.
        # Upper (P95 with floor) should be >= 1440 — so upper alone wouldn't catch it
        assert result.upper >= 1440
        # Staleness (median x 0.85) should be < 1440 — catches the miss
        assert result.staleness < 1440


# ---------------------------------------------------------------------------
# is_excluded_day with excluded_days Tests
# ---------------------------------------------------------------------------

class Test_IsExcludedDayWithExcludedDays:
    def test_monday_excluded(self):
        """excluded_days={0} should exclude Monday."""
        monday = pd.Timestamp("2026-02-09")  # Monday
        assert is_excluded_day(monday, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({0}))

    def test_weekend_via_excluded_days(self):
        """excluded_days={5,6} without exclude_weekends=True still excludes weekends."""
        saturday = pd.Timestamp("2026-02-07")  # Saturday
        sunday = pd.Timestamp("2026-02-08")  # Sunday
        assert is_excluded_day(saturday, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({5, 6}))
        assert is_excluded_day(sunday, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({5, 6}))

    def test_both_exclude_weekends_and_excluded_days(self):
        """Both flags combined: Mon+Sat+Sun excluded."""
        monday = pd.Timestamp("2026-02-09")
        saturday = pd.Timestamp("2026-02-07")
        tuesday = pd.Timestamp("2026-02-10")
        assert is_excluded_day(monday, exclude_weekends=True, holiday_dates=None, excluded_days=frozenset({0}))
        assert is_excluded_day(saturday, exclude_weekends=True, holiday_dates=None, excluded_days=frozenset({0}))
        assert not is_excluded_day(tuesday, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({0}))

    def test_weekday_not_excluded(self):
        """Wednesday not in excluded_days={5,6} should not be excluded."""
        wednesday = pd.Timestamp("2026-02-11")  # Wednesday
        assert not is_excluded_day(wednesday, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({5, 6}))

    def test_with_timezone(self):
        """excluded_days with timezone conversion."""
        # 2026-02-07 Saturday 23:00 ET = 2026-02-08 Sunday 04:00 UTC
        # In ET this is Saturday (weekday=5), so excluded_days={5} should match
        saturday_utc = pd.Timestamp("2026-02-08T04:00")
        assert is_excluded_day(saturday_utc, exclude_weekends=False, holiday_dates=None, tz=TZ, excluded_days=frozenset({5}))


# ---------------------------------------------------------------------------
# count_excluded_minutes with excluded_days Tests
# ---------------------------------------------------------------------------

class Test_CountExcludedMinutesWithExcludedDays:
    def test_wednesday_excluded(self):
        """excluded_days={2} should subtract Wednesday minutes only."""
        # Tue 2026-02-10 00:00 → Thu 2026-02-12 00:00 (includes a full Wednesday)
        start = pd.Timestamp("2026-02-10T00:00")
        end = pd.Timestamp("2026-02-12T00:00")
        result = count_excluded_minutes(start, end, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({2}))
        # Full Wednesday = 24h = 1440 min
        assert result == 1440.0

    def test_no_excluded_days_returns_zero(self):
        """excluded_days=None should return 0."""
        start = pd.Timestamp("2026-02-10T00:00")
        end = pd.Timestamp("2026-02-12T00:00")
        result = count_excluded_minutes(start, end, exclude_weekends=False, holiday_dates=None, excluded_days=None)
        assert result == 0.0


# ---------------------------------------------------------------------------
# get_schedule_params Tests
# ---------------------------------------------------------------------------

class Test_GetScheduleParams:
    def test_returns_empty_for_none(self):
        result = get_schedule_params(None)
        assert result.excluded_days is None
        assert result.window_start is None
        assert result.window_end is None

    def test_returns_empty_for_empty_string(self):
        result = get_schedule_params("")
        assert result.excluded_days is None

    def test_returns_none_excluded_days_when_no_active_days(self):
        result = get_schedule_params({"schedule_stage": "active"})
        assert result.excluded_days is None

    def test_inverts_active_days_to_excluded_days(self):
        pred = {"active_days": [0, 1, 2, 3, 4], "schedule_stage": "active"}
        result = get_schedule_params(pred)
        assert result.excluded_days == frozenset({5, 6})

    def test_inverts_active_days_from_json_string(self):
        pred = json.dumps({"active_days": [0, 1, 2, 3, 4], "schedule_stage": "active"})
        result = get_schedule_params(pred)
        assert result.excluded_days == frozenset({5, 6})

    def test_all_days_active_returns_empty_excluded(self):
        pred = {"active_days": [0, 1, 2, 3, 4, 5, 6], "schedule_stage": "active"}
        result = get_schedule_params(pred)
        assert not result.excluded_days

    def test_returns_window_for_sub_daily_active(self):
        pred = {"frequency": "sub_daily", "schedule_stage": "active", "window_start": 9.0, "window_end": 17.0}
        result = get_schedule_params(pred)
        assert result.window_start == 9.0
        assert result.window_end == 17.0

    def test_no_window_for_daily(self):
        pred = {"frequency": "daily", "schedule_stage": "active", "window_start": 9.0, "window_end": 17.0}
        result = get_schedule_params(pred)
        assert result.window_start is None
        assert result.window_end is None

    def test_no_exclusions_for_tentative(self):
        pred = {
            "active_days": [0, 2, 4],
            "frequency": "sub_daily",
            "schedule_stage": "tentative",
            "window_start": 9.0,
            "window_end": 17.0,
        }
        result = get_schedule_params(pred)
        assert result.excluded_days is None
        assert result.window_start is None
        assert result.window_end is None

    def test_no_window_when_missing(self):
        pred = {"frequency": "sub_daily", "schedule_stage": "active"}
        result = get_schedule_params(pred)
        assert result.window_start is None

    def test_combined_days_and_window(self):
        pred = {
            "active_days": [0, 1, 2, 3, 4],
            "frequency": "sub_daily",
            "schedule_stage": "active",
            "window_start": 8.0,
            "window_end": 18.0,
        }
        result = get_schedule_params(pred)
        assert result.excluded_days == frozenset({5, 6})
        assert result.window_start == 8.0
        assert result.window_end == 18.0


# ---------------------------------------------------------------------------
# add_business_minutes with excluded_days Tests
# ---------------------------------------------------------------------------

class Test_AddBusinessMinutesWithExcludedDays:
    def test_skips_excluded_day(self):
        """excluded_days={2} (Wednesday) should skip Wednesday entirely."""
        # Tuesday 22:00, add 180 min → skip Wed, land on Thursday 01:00
        start = pd.Timestamp("2026-02-10T22:00")  # Tuesday
        result = add_business_minutes(start, 180, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({2}))
        assert result == pd.Timestamp("2026-02-12T01:00")  # Thursday

    def test_starts_on_excluded_day(self):
        """Starting on an excluded day should fast-forward past it."""
        start = pd.Timestamp("2026-02-11T10:00")  # Wednesday
        result = add_business_minutes(start, 60, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({2}))
        assert result == pd.Timestamp("2026-02-12T01:00")  # Thursday 01:00

    def test_consecutive_excluded_days(self):
        """Multiple consecutive excluded days are all skipped."""
        # Exclude Wed+Thu+Fri (2,3,4), start Tuesday 23:00, add 120 min
        start = pd.Timestamp("2026-02-10T23:00")  # Tuesday
        result = add_business_minutes(start, 120, exclude_weekends=False, holiday_dates=None, excluded_days=frozenset({2, 3, 4}))
        # 1h left on Tuesday (23:00→midnight), skip Wed/Thu/Fri, 1h into Saturday
        assert result == pd.Timestamp("2026-02-14T01:00")  # Saturday

    def test_excluded_days_combined_with_weekends(self):
        """excluded_days + exclude_weekends together: skip excluded + Sat+Sun."""
        # Exclude Friday (4), start Thursday 23:00, add 120 min
        start = pd.Timestamp("2026-02-05T23:00")  # Thursday
        result = add_business_minutes(start, 120, exclude_weekends=True, holiday_dates=None, excluded_days=frozenset({4}))
        # 1h left on Thursday, skip Fri+Sat+Sun, 1h into Monday
        assert result == pd.Timestamp("2026-02-09T01:00")  # Monday

    def test_inverse_property_with_excluded_days(self):
        """add_business_minutes and count_excluded_minutes should be inverses."""
        start = pd.Timestamp("2026-02-06T14:00")  # Friday
        excluded_days = frozenset({5, 6})  # weekend via excluded_days
        business_minutes = 600.0
        end = add_business_minutes(start, business_minutes, exclude_weekends=False, holiday_dates=None, excluded_days=excluded_days)
        wall_minutes = (end - start).total_seconds() / 60
        excluded = count_excluded_minutes(start, end, exclude_weekends=False, holiday_dates=None, excluded_days=excluded_days)
        assert wall_minutes - excluded == business_minutes

    def test_with_timezone(self):
        """excluded_days with timezone: day boundaries use local time."""
        # UTC Friday 23:00 = ET Friday 6PM → Friday is not excluded
        # excluded_days={5} = Saturday only
        start = pd.Timestamp("2026-02-06T23:00")  # UTC Friday 11PM = ET Friday 6PM
        result = add_business_minutes(start, 120, exclude_weekends=False, holiday_dates=None, tz=TZ, excluded_days=frozenset({5}))
        # ET: Fri 6PM + 2h = Fri 8PM ET. Skip Saturday. So 2h consumed on Friday → Fri 8PM ET = Sat 01:00 UTC
        assert result == pd.Timestamp("2026-02-07T01:00")


# ---------------------------------------------------------------------------
# minutes_to_next_deadline Tests
# ---------------------------------------------------------------------------

class Test_MinutesToNextDeadline:
    def test_basic_daily(self):
        """Mon 11AM → Tue deadline (window_end 13 + buffer 3 = 16h) = 29h = 1740 min."""
        schedule = _make_schedule()
        zi = zoneinfo.ZoneInfo(TZ)
        last_update = pd.Timestamp("2026-02-09T11:00", tz=zi).tz_convert("UTC").tz_localize(None)
        result = minutes_to_next_deadline(last_update, schedule, exclude_weekends=False, holiday_dates=None, tz=TZ, buffer_hours=3.0)
        assert result is not None
        assert 1700 <= result <= 1800

    def test_friday_crosses_weekend(self):
        """Friday last update → next active day is Monday, weekend excluded."""
        schedule = _make_schedule()  # active_days = Mon-Fri
        zi = zoneinfo.ZoneInfo(TZ)
        last_update = pd.Timestamp("2026-02-06T11:00", tz=zi).tz_convert("UTC").tz_localize(None)
        result = minutes_to_next_deadline(
            last_update, schedule,
            exclude_weekends=True, holiday_dates=None, tz=TZ, buffer_hours=3.0,
        )
        assert result is not None
        # Fri 11AM → Mon 4PM = 77h wall = 4620 min, minus 2880 weekend = 1740 business min
        assert 1700 <= result <= 1800

    def test_friday_crosses_weekend_plus_holiday(self):
        """Friday → Monday is holiday → deadline still targets Monday (next active day),
        but most of Monday's minutes are subtracted as excluded holiday time."""
        from datetime import date
        schedule = _make_schedule()
        zi = zoneinfo.ZoneInfo(TZ)
        last_update = pd.Timestamp("2026-02-06T11:00", tz=zi).tz_convert("UTC").tz_localize(None)
        holiday_dates = {date(2026, 2, 9)}  # Monday
        result = minutes_to_next_deadline(
            last_update, schedule,
            exclude_weekends=True, holiday_dates=holiday_dates, tz=TZ, buffer_hours=3.0,
        )
        assert result is not None
        # Fri 11AM → Mon 4PM (deadline) = 77h wall = 4620 min
        # Minus Sat+Sun (2880) + Mon midnight-to-4PM holiday (960) = 780 business min
        assert 750 <= result <= 810

    def test_no_window_end_returns_none(self):
        schedule = _make_schedule(window_end=None)
        last_update = pd.Timestamp("2026-02-09T11:00")
        result = minutes_to_next_deadline(last_update, schedule, exclude_weekends=False, holiday_dates=None, tz=TZ, buffer_hours=3.0)
        assert result is None

    def test_buffer_hours_affects_result(self):
        """Larger buffer → later deadline → more minutes."""
        schedule = _make_schedule()
        zi = zoneinfo.ZoneInfo(TZ)
        last_update = pd.Timestamp("2026-02-09T11:00", tz=zi).tz_convert("UTC").tz_localize(None)
        small = minutes_to_next_deadline(last_update, schedule, exclude_weekends=False, holiday_dates=None, tz=TZ, buffer_hours=1.0)
        large = minutes_to_next_deadline(last_update, schedule, exclude_weekends=False, holiday_dates=None, tz=TZ, buffer_hours=5.0)
        assert small is not None and large is not None
        assert small < large

    def test_with_excluded_days(self):
        """excluded_days={5,6} should subtract weekend minutes like exclude_weekends."""
        schedule = _make_schedule()
        zi = zoneinfo.ZoneInfo(TZ)
        last_update = pd.Timestamp("2026-02-06T11:00", tz=zi).tz_convert("UTC").tz_localize(None)
        result = minutes_to_next_deadline(
            last_update, schedule,
            exclude_weekends=False, holiday_dates=None, tz=TZ, buffer_hours=3.0,
            excluded_days=frozenset({5, 6}),
        )
        assert result is not None
        assert 1700 <= result <= 1800



# ---------------------------------------------------------------------------
# is_excluded_day with window_start/window_end Tests
# ---------------------------------------------------------------------------

class Test_IsExcludedDayWithWindow:
    """Test active-hours exclusion for sub-daily schedules."""

    def test_inside_window_not_excluded(self):
        """10:00 ET inside [4, 14] window → not excluded."""
        # 10:00 ET = 15:00 UTC (EST = UTC-5)
        ts = pd.Timestamp("2026-02-09T15:00")  # Monday
        assert not is_excluded_day(
            ts, exclude_weekends=False, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )

    def test_outside_window_excluded(self):
        """20:00 ET outside [4, 14] window → excluded."""
        # 20:00 ET = 01:00+1 UTC
        ts = pd.Timestamp("2026-02-10T01:00")  # Tuesday 01:00 UTC = Monday 20:00 ET
        assert is_excluded_day(
            ts, exclude_weekends=False, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )

    def test_at_window_start_not_excluded(self):
        """Exactly at window_start → inside window → not excluded."""
        # 4:00 ET = 9:00 UTC
        ts = pd.Timestamp("2026-02-09T09:00")  # Monday
        assert not is_excluded_day(
            ts, exclude_weekends=False, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )

    def test_at_window_end_not_excluded(self):
        """Exactly at window_end → inside window → not excluded."""
        # 14:00 ET = 19:00 UTC
        ts = pd.Timestamp("2026-02-09T19:00")  # Monday
        assert not is_excluded_day(
            ts, exclude_weekends=False, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )

    def test_weekend_still_excluded_with_window(self):
        """Weekend exclusion takes priority over window check."""
        # Saturday 10:00 ET (inside window) but weekend
        ts = pd.Timestamp("2026-02-07T15:00")  # Saturday 10:00 ET
        assert is_excluded_day(
            ts, exclude_weekends=True, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )

    def test_excluded_day_takes_priority(self):
        """excluded_days exclusion takes priority over window check."""
        # Monday 10:00 ET (inside window) but Monday excluded
        ts = pd.Timestamp("2026-02-09T15:00")  # Monday 10:00 ET
        assert is_excluded_day(
            ts, exclude_weekends=False, holiday_dates=None,
            tz=TZ, excluded_days=frozenset({0}), window_start=4.0, window_end=14.0,
        )

    def test_no_window_no_effect(self):
        """Without window params, daytime on active day → not excluded."""
        ts = pd.Timestamp("2026-02-10T01:00")  # Monday 20:00 ET
        assert not is_excluded_day(
            ts, exclude_weekends=False, holiday_dates=None, tz=TZ,
        )

    def test_window_without_tz_uses_raw_hour(self):
        """Window params without tz still check the raw timestamp's hour."""
        ts = pd.Timestamp("2026-02-09T20:00")
        # 20:00 is outside [4, 14] → excluded
        assert is_excluded_day(
            ts, exclude_weekends=False, holiday_dates=None,
            window_start=4.0, window_end=14.0,
        )
        # 10:00 is inside [4, 14] → not excluded
        ts2 = pd.Timestamp("2026-02-09T10:00")
        assert not is_excluded_day(
            ts2, exclude_weekends=False, holiday_dates=None,
            window_start=4.0, window_end=14.0,
        )


# ---------------------------------------------------------------------------
# count_excluded_minutes with window_start/window_end Tests
# ---------------------------------------------------------------------------

class Test_CountExcludedMinutesWithWindow:
    """Test active-hours exclusion in gap duration computation."""

    def test_overnight_gap_excludes_outside_window(self):
        """Gap from 14:00 ET to 04:00 ET next day: all 14h overnight are outside [4, 14]."""
        # 14:00 ET = 19:00 UTC, 04:00 ET next day = 09:00 UTC next day
        start = pd.Timestamp("2026-02-09T19:00")  # Monday 14:00 ET
        end = pd.Timestamp("2026-02-10T09:00")     # Tuesday 04:00 ET
        result = count_excluded_minutes(
            start, end, exclude_weekends=False, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )
        # Total gap = 14h = 840 min
        # Monday 14:00-midnight = 10h, outside window = 10h (14:00 is window_end, so 14:00-midnight)
        # Tuesday midnight-04:00 = 4h, outside window = 4h (before window_start)
        # Total excluded = 14h = 840 min (the entire overnight gap is outside the window)
        assert result == 840.0

    def test_within_window_gap_excludes_nothing(self):
        """Gap entirely within [4, 14] window → 0 excluded minutes."""
        # 06:00 ET = 11:00 UTC, 08:00 ET = 13:00 UTC
        start = pd.Timestamp("2026-02-09T11:00")  # Monday 06:00 ET
        end = pd.Timestamp("2026-02-09T13:00")     # Monday 08:00 ET
        result = count_excluded_minutes(
            start, end, exclude_weekends=False, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )
        assert result == 0.0

    def test_gap_spanning_weekend_and_outside_window(self):
        """Gap from Friday 14:00 ET to Monday 04:00 ET: weekend + outside-window hours."""
        # Fri 14:00 ET = 19:00 UTC, Mon 04:00 ET = 09:00 UTC
        start = pd.Timestamp("2026-02-06T19:00")  # Friday 14:00 ET
        end = pd.Timestamp("2026-02-09T09:00")     # Monday 04:00 ET
        result = count_excluded_minutes(
            start, end, exclude_weekends=True, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )
        # Total wall = 62h = 3720 min
        # Friday 14:00 ET → midnight = 10h outside window
        # Saturday (full day excluded as weekend) = 1440 min
        # Sunday (full day excluded as weekend) = 1440 min
        # Monday midnight → 04:00 = 4h outside window (before window_start)
        # Total = 600 + 1440 + 1440 + 240 = 3720 min (everything excluded)
        assert result == 3720.0

    def test_partial_day_with_window(self):
        """Gap starting inside window, ending outside → only outside portion excluded."""
        # 12:00 ET = 17:00 UTC, 16:00 ET = 21:00 UTC (same day)
        start = pd.Timestamp("2026-02-09T17:00")  # Monday 12:00 ET
        end = pd.Timestamp("2026-02-09T21:00")     # Monday 16:00 ET
        result = count_excluded_minutes(
            start, end, exclude_weekends=False, holiday_dates=None,
            tz=TZ, window_start=4.0, window_end=14.0,
        )
        # Total gap = 4h = 240 min
        # 12:00-14:00 ET = inside window = 0 excluded
        # 14:00-16:00 ET = outside window = 120 min excluded
        assert result == 120.0

    def test_no_window_backward_compat(self):
        """Without window params, behaves exactly as before."""
        start = pd.Timestamp("2026-02-09T19:00")  # Monday
        end = pd.Timestamp("2026-02-10T09:00")     # Tuesday
        result = count_excluded_minutes(
            start, end, exclude_weekends=False, holiday_dates=None, tz=TZ,
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# get_freshness_gap_threshold with window_start/window_end Tests
# ---------------------------------------------------------------------------

class Test_GetFreshnessGapThresholdWithWindow:
    """Test that window exclusion in gap computation normalizes overnight gaps to 0."""

    def _make_sub_daily_history(self):
        """Build 4 weeks of 2-hourly updates, 08:00-18:00 UTC weekdays.

        This matches the subdaily_regular scenario: updates every 2h during
        business hours, with overnight and weekend gaps.
        """
        zi = zoneinfo.ZoneInfo(TZ)
        updates = []
        for week in range(4):
            base = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=week)  # Monday
            for day in range(5):  # Mon-Fri
                for hour in range(4, 15, 2):  # 04:00-14:00 ET = 09:00-19:00 UTC
                    ts = base + pd.Timedelta(days=day, hours=hour)
                    utc = pd.Timestamp(ts, tz=zi).tz_convert("UTC").tz_localize(None)
                    updates.append(str(utc))
        return _make_freshness_history(updates, check_interval_minutes=30)

    def test_overnight_gaps_become_zero(self):
        """With window exclusion, overnight gaps are normalized to 0 business minutes."""
        history = self._make_sub_daily_history()
        excluded_days = frozenset({5, 6})

        # Without window exclusion: overnight gaps (~840 min) inflate the distribution
        result_no_window = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10,
            exclude_weekends=True, tz=TZ, excluded_days=excluded_days,
        )

        # With window exclusion: overnight gaps become 0
        result_with_window = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10,
            exclude_weekends=True, tz=TZ, excluded_days=excluded_days,
            window_start=4.0, window_end=14.0,
        )

        # The upper should be much tighter with window exclusion
        assert result_with_window.upper < result_no_window.upper
        # Upper should be around 150 (1.25 * 120) not 1050 (1.25 * 840)
        assert result_with_window.upper <= 200

    def test_within_window_gaps_unchanged(self):
        """Gaps entirely within the activity window are not affected by window exclusion."""
        history = self._make_sub_daily_history()
        excluded_days = frozenset({5, 6})

        result = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10,
            exclude_weekends=True, tz=TZ, excluded_days=excluded_days,
            window_start=4.0, window_end=14.0,
        )

        # Within-window gaps are 120 min (2h), so median should be 120
        # (overnight 0s pull median down, but most gaps are 120)
        assert 100 <= result.staleness / 0.85 <= 130  # median ~120

    def test_lower_disabled_when_overnight_zeros(self):
        """With overnight gaps normalized to 0, P10 is 0 → lower set to None."""
        history = self._make_sub_daily_history()
        excluded_days = frozenset({5, 6})

        result = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.25,
            lower_percentile=10,
            exclude_weekends=True, tz=TZ, excluded_days=excluded_days,
            window_start=4.0, window_end=14.0,
        )

        # P10 should be 0 (or very close) → lower should be None
        assert result.lower is None
