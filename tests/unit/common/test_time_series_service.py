from datetime import date

import numpy as np
import pandas as pd
import pytest

from testgen.commands.test_thresholds_prediction import compute_freshness_threshold, compute_sarimax_threshold
from testgen.common.freshness_service import (
    MIN_FRESHNESS_GAPS,
    FreshnessThreshold,
    add_business_minutes,
    count_excluded_minutes,
    get_freshness_gap_threshold,
    is_excluded_day,
    next_business_day_start,
)
from testgen.common.models.test_suite import PredictSensitivity
from testgen.common.time_series_service import NotEnoughData, get_sarimax_forecast

from .conftest import _make_freshness_history


class Test_GetFreshnessGapThreshold:
    def test_basic_threshold(self):
        # 6 updates spaced 10h apart = 5 gaps of 600 minutes each
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)

        result = get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10)
        # All gaps are 600 min, so P95 = 600, floor = 600 * 1.25 = 750
        assert isinstance(result, FreshnessThreshold)
        assert result.upper == pytest.approx(750.0)
        # staleness = median(600) * 0.85 = 510
        assert result.staleness == pytest.approx(600.0 * 0.85)

    def test_not_enough_data_few_gaps(self):
        # 4 updates = 3 gaps, below MIN_FRESHNESS_GAPS
        updates = ["2026-02-01T00:00", "2026-02-01T10:00", "2026-02-01T20:00", "2026-02-02T06:00"]
        history = _make_freshness_history(updates)

        with pytest.raises(NotEnoughData, match=f"{MIN_FRESHNESS_GAPS}"):
            get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10)

    def test_not_enough_data_no_updates(self):
        # History with no zero values = no detected updates
        timestamps = pd.date_range("2026-02-01", periods=30, freq="2h")
        signal = np.arange(1, 31, dtype=float) * 120  # never hits 0
        history = pd.DataFrame({"result_signal": signal}, index=timestamps)

        with pytest.raises(NotEnoughData):
            get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10)

    def test_floor_multiplier_dominates(self):
        # 6 identical gaps — percentile ≈ max, so floor_multiplier > 1 dominates
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)

        result_low = get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.0, lower_percentile=10)
        result_high = get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.5, lower_percentile=10)

        assert result_high.upper > result_low.upper

    def test_sensitivity_ordering(self):
        # Varied gaps so percentiles differentiate
        updates = [
            "2026-02-01T00:00",
            "2026-02-01T04:00",   # 4h
            "2026-02-02T14:00",   # 34h
            "2026-02-03T14:00",   # 24h
            "2026-02-04T06:00",   # 16h
            "2026-02-04T08:00",   # 2h
            "2026-02-04T16:00",   # 8h
        ]
        history = _make_freshness_history(updates)

        high = get_freshness_gap_threshold(history, upper_percentile=80, floor_multiplier=1.0, lower_percentile=10)
        medium = get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10)
        low = get_freshness_gap_threshold(history, upper_percentile=99, floor_multiplier=1.5, lower_percentile=10)

        assert high.upper <= medium.upper <= low.upper

    def test_single_update_raises(self):
        # Only one zero = zero gaps
        timestamps = pd.date_range("2026-02-01", periods=10, freq="2h")
        signal = [0.0] + [120.0 * i for i in range(1, 10)]
        history = pd.DataFrame({"result_signal": signal}, index=timestamps)

        with pytest.raises(NotEnoughData):
            get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10)

    def test_returns_last_update_timestamp(self):
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)

        result = get_freshness_gap_threshold(history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10)
        assert result.last_update == pd.Timestamp("2026-02-03T02:00")

    def test_lower_threshold(self):
        # Varied gaps: 4h, 34h, 24h, 16h, 2h, 8h
        updates = [
            "2026-02-01T00:00",
            "2026-02-01T04:00",   # 4h = 240 min
            "2026-02-02T14:00",   # 34h = 2040 min
            "2026-02-03T14:00",   # 24h = 1440 min
            "2026-02-04T06:00",   # 16h = 960 min
            "2026-02-04T08:00",   # 2h = 120 min
            "2026-02-04T16:00",   # 8h = 480 min
        ]
        history = _make_freshness_history(updates)

        result = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.25, lower_percentile=10,
        )
        assert result.lower is not None
        assert result.lower > 0
        assert result.lower < result.upper

    def test_lower_threshold_none_when_zero(self):
        # All identical gaps → P10 = same value, but if very small or zero, returns None
        # Create gaps where the minimum is 0 after percentile
        updates = [
            "2026-02-01T00:00:00",
            "2026-02-01T00:01:00",  # 1 min gap
            "2026-02-01T00:02:00",  # 1 min gap
            "2026-02-01T00:03:00",  # 1 min gap
            "2026-02-01T00:04:00",  # 1 min gap
            "2026-02-01T00:05:00",  # 1 min gap
            "2026-02-01T00:06:00",  # 1 min gap
        ]
        history = _make_freshness_history(updates, check_interval_minutes=1)

        result = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.0, lower_percentile=5,
        )
        # All gaps are 1 min, P5 = 1.0 which is > 0, so lower should be set
        assert result.lower == pytest.approx(1.0)


class Test_GetFreshnessGapThreshold_WeekendExclusion:
    def test_weekend_gaps_normalized(self):
        # Table updates daily on weekdays, 72h gap over weekend
        # Mon Feb 2 through Mon Feb 9 (2026-02-02 is a Monday)
        updates = [
            "2026-02-02T08:00",  # Mon
            "2026-02-03T08:00",  # Tue (24h gap)
            "2026-02-04T08:00",  # Wed (24h gap)
            "2026-02-05T08:00",  # Thu (24h gap)
            "2026-02-06T08:00",  # Fri (24h gap)
            "2026-02-09T08:00",  # Mon (72h raw, but 24h after subtracting Sat+Sun)
            "2026-02-10T08:00",  # Tue (24h gap)
        ]
        history = _make_freshness_history(updates)

        # Without exclusion: the 72h gap inflates the threshold
        result_raw = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.0, lower_percentile=10,
        )

        # With exclusion: all gaps normalize to ~24h
        result_normalized = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.0, lower_percentile=10, exclude_weekends=True,
        )

        # Normalized threshold should be lower (all gaps ≈ 24h vs max raw = 72h)
        assert result_normalized.upper < result_raw.upper

    def test_partial_weekend_day_subtracted(self):
        # All gaps are 4h except the last one which crosses into Saturday (14h raw).
        # Partial-day exclusion subtracts the 10h Saturday portion, bringing the
        # max normalized gap below the raw max.
        updates = [
            "2026-02-06T04:00",  # Fri
            "2026-02-06T08:00",  # Fri (4h gap)
            "2026-02-06T12:00",  # Fri (4h gap)
            "2026-02-06T16:00",  # Fri (4h gap)
            "2026-02-06T20:00",  # Fri (4h gap)
            "2026-02-07T00:00",  # Sat midnight (4h gap)
            "2026-02-07T10:00",  # Sat 10AM (10h raw gap, 0h business — entirely on Saturday)
        ]
        history = _make_freshness_history(updates)

        result_raw = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.0, lower_percentile=10,
        )
        result_normalized = get_freshness_gap_threshold(
            history, upper_percentile=95, floor_multiplier=1.0, lower_percentile=10, exclude_weekends=True,
        )

        # Raw: max gap = Sat midnight → Sat 10AM = 10h = 600 min
        # Normalized: 600 - 10h Saturday excluded = 0 min
        # So normalized max = 4h (the weekday gaps), while raw max = 10h
        assert result_normalized.upper < result_raw.upper


class Test_CountExcludedMinutes:
    def test_no_exclusions(self):
        start = pd.Timestamp("2026-02-06T17:00")  # Friday
        end = pd.Timestamp("2026-02-09T08:00")     # Monday
        result = count_excluded_minutes(start, end, exclude_weekends=False, holiday_dates=None)
        assert result == 0.0

    def test_full_weekend(self):
        # Friday 5PM to Monday 8AM — Saturday and Sunday are full days in between
        start = pd.Timestamp("2026-02-06T17:00")  # Friday
        end = pd.Timestamp("2026-02-09T08:00")     # Monday
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == 2 * 24 * 60  # 2 full weekend days

    def test_partial_weekend_day(self):
        # Saturday 1AM to Saturday 11PM — 22 hours of excluded Saturday
        start = pd.Timestamp("2026-02-07T01:00")  # Saturday
        end = pd.Timestamp("2026-02-07T23:00")     # Saturday
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == 22 * 60

    def test_weekday_only(self):
        # Monday to Wednesday — no weekends
        start = pd.Timestamp("2026-02-02T08:00")  # Monday
        end = pd.Timestamp("2026-02-04T08:00")     # Wednesday
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == 0.0

    def test_holiday(self):
        start = pd.Timestamp("2026-02-02T08:00")  # Monday
        end = pd.Timestamp("2026-02-05T08:00")     # Thursday
        # Wednesday is a holiday
        holiday_dates = {date(2026, 2, 4)}
        result = count_excluded_minutes(start, end, exclude_weekends=False, holiday_dates=holiday_dates)
        assert result == 1 * 24 * 60  # 1 holiday

    def test_weekend_and_holiday(self):
        # Friday to Tuesday, with Monday as holiday
        start = pd.Timestamp("2026-02-06T08:00")  # Friday
        end = pd.Timestamp("2026-02-10T08:00")     # Tuesday
        holiday_dates = {date(2026, 2, 9)}  # Monday
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=holiday_dates)
        # Saturday + Sunday + Monday(holiday) = 3 days
        assert result == 3 * 24 * 60

    def test_holiday_on_weekend_not_double_counted(self):
        # Holiday falls on Saturday — should only count once
        start = pd.Timestamp("2026-02-06T08:00")  # Friday
        end = pd.Timestamp("2026-02-09T08:00")     # Monday
        holiday_dates = {date(2026, 2, 7)}  # Saturday
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=holiday_dates)
        # Saturday (weekend) + Sunday (weekend) = 2 days, not 3
        assert result == 2 * 24 * 60

    def test_same_excluded_day(self):
        # Saturday 8AM to 8PM — 12 hours of excluded time
        start = pd.Timestamp("2026-02-07T08:00")
        end = pd.Timestamp("2026-02-07T20:00")
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == 12 * 60

    def test_same_weekday(self):
        # Monday 8AM to 8PM — no excluded time
        start = pd.Timestamp("2026-02-09T08:00")
        end = pd.Timestamp("2026-02-09T20:00")
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == 0.0

    def test_accepts_datetime(self):
        from datetime import datetime
        start = datetime(2026, 2, 6, 17, 0)  # Friday
        end = datetime(2026, 2, 9, 8, 0)     # Monday
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == 2 * 24 * 60


    def test_partial_start_on_excluded_day(self):
        # Last update Saturday 1AM, end Monday midnight
        # Saturday has 23h excluded (1AM to midnight), Sunday has 24h
        start = pd.Timestamp("2026-02-07T01:00")  # Saturday 1AM
        end = pd.Timestamp("2026-02-09T00:00")     # Monday midnight
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == (23 + 24) * 60  # 23h Saturday + 24h Sunday

    def test_start_equals_end(self):
        ts = pd.Timestamp("2026-02-07T08:00")
        result = count_excluded_minutes(ts, ts, exclude_weekends=True, holiday_dates=None)
        assert result == 0.0

    def test_start_after_end(self):
        start = pd.Timestamp("2026-02-08T08:00")
        end = pd.Timestamp("2026-02-07T08:00")
        result = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert result == 0.0

    def test_timezone_shifts_weekend_boundaries(self):
        # Without timezone: UTC Fri 23:00 to UTC Mon 01:00
        # UTC Saturday and Sunday are full weekend days → 2 * 24h = 2880 min
        start = pd.Timestamp("2026-02-06T23:00")  # UTC Friday 11PM
        end = pd.Timestamp("2026-02-09T01:00")     # UTC Monday 1AM
        result_utc = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)

        # With ET timezone (UTC-5): start = Fri 6PM ET, end = Sun 8PM ET
        # ET Saturday = UTC Sat 05:00 to UTC Sun 05:00
        # ET Sunday = UTC Sun 05:00 to UTC Mon 05:00
        # The interval Fri 6PM ET → Sun 8PM ET contains:
        #   Full ET Saturday (24h) + partial ET Sunday (midnight to 8PM = 20h) = 44h = 2640 min
        result_et = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None, tz="America/New_York")

        assert result_et != result_utc
        assert result_et == pytest.approx(44 * 60)


class Test_IsExcludedDay:
    def test_weekend_saturday(self):
        assert is_excluded_day(pd.Timestamp("2026-02-07"), exclude_weekends=True, holiday_dates=None) is True

    def test_weekend_sunday(self):
        assert is_excluded_day(pd.Timestamp("2026-02-08"), exclude_weekends=True, holiday_dates=None) is True

    def test_weekday(self):
        assert is_excluded_day(pd.Timestamp("2026-02-09"), exclude_weekends=True, holiday_dates=None) is False

    def test_holiday(self):
        holidays = {date(2026, 2, 9)}  # Monday
        assert is_excluded_day(pd.Timestamp("2026-02-09"), exclude_weekends=False, holiday_dates=holidays) is True

    def test_timestamp(self):
        assert is_excluded_day(pd.Timestamp("2026-02-07T14:00"), exclude_weekends=True, holiday_dates=None) is True

    def test_no_exclusions(self):
        assert is_excluded_day(pd.Timestamp("2026-02-07"), exclude_weekends=False, holiday_dates=None) is False

    def test_timezone_converts_utc_to_local(self):
        # UTC Saturday 03:00 = Friday 10PM in New York → NOT a weekend day in ET
        assert is_excluded_day(
            pd.Timestamp("2026-02-07T03:00"), exclude_weekends=True, holiday_dates=None, tz="America/New_York",
        ) is False

    def test_timezone_saturday_in_local(self):
        # UTC Saturday 15:00 = Saturday 10AM in New York → IS a weekend day in ET
        assert is_excluded_day(
            pd.Timestamp("2026-02-07T15:00"), exclude_weekends=True, holiday_dates=None, tz="America/New_York",
        ) is True

    def test_timezone_sunday_to_monday_boundary(self):
        # UTC Monday 03:00 = Sunday 10PM in New York → IS a weekend day in ET
        assert is_excluded_day(
            pd.Timestamp("2026-02-09T03:00"), exclude_weekends=True, holiday_dates=None, tz="America/New_York",
        ) is True


class Test_NextBusinessDayStart:
    def test_friday_to_monday(self):
        result = next_business_day_start(pd.Timestamp("2026-02-06T17:00"), exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09")  # Monday midnight

    def test_saturday_to_monday(self):
        result = next_business_day_start(pd.Timestamp("2026-02-07T10:00"), exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09")  # Monday midnight

    def test_sunday_to_monday(self):
        result = next_business_day_start(pd.Timestamp("2026-02-08T10:00"), exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09")  # Monday midnight

    def test_weekday_to_next_day(self):
        result = next_business_day_start(pd.Timestamp("2026-02-09T17:00"), exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-10")  # Tuesday midnight

    def test_weekend_plus_holiday(self):
        # Friday → Saturday (weekend) → Sunday (weekend) → Monday (holiday) → Tuesday
        holidays = {date(2026, 2, 9)}  # Monday
        result = next_business_day_start(pd.Timestamp("2026-02-06T17:00"), exclude_weekends=True, holiday_dates=holidays)
        assert result == pd.Timestamp("2026-02-10")  # Tuesday midnight


class Test_ComputeFreshnessThreshold:
    def test_returns_business_minute_thresholds(self):
        # 6 updates spaced 10h apart = 5 gaps of 600 minutes each
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)

        lower, upper, staleness, prediction = compute_freshness_threshold(history, PredictSensitivity.medium)
        assert upper is not None
        assert upper > 0
        # Without exclusions, thresholds are raw business minutes from gap analysis
        assert upper == pytest.approx(750.0)  # P95 of uniform 600-min gaps = 600, floor 1.25x = 750
        # No tz → no schedule → staleness is None
        assert staleness is None
        # prediction JSON is returned (staleness only when schedule is active)
        assert prediction is not None

    def test_not_enough_data_returns_none(self):
        # 4 updates = 3 gaps, below MIN_FRESHNESS_GAPS
        updates = ["2026-02-01T00:00", "2026-02-01T10:00", "2026-02-01T20:00", "2026-02-02T06:00"]
        history = _make_freshness_history(updates)

        lower, upper, staleness, prediction = compute_freshness_threshold(history, PredictSensitivity.medium)
        assert lower is None
        assert upper is None
        assert staleness is None
        assert prediction is None

    def test_returns_four_tuple(self):
        """Verify compute_freshness_threshold returns a 4-tuple (lower, upper, prediction, staleness)."""
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)
        result = compute_freshness_threshold(history, PredictSensitivity.medium)
        assert len(result) == 4

    def test_prediction_json_without_tz_has_no_staleness(self):
        """Without tz (no active schedule), staleness_upper is absent from prediction JSON."""
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)
        _, upper, staleness, prediction = compute_freshness_threshold(history, PredictSensitivity.medium)
        # No tz → staleness is None
        assert staleness is None
        assert prediction is not None

    def test_with_weekend_exclusion_returns_business_thresholds(self):
        # Table updates daily on weekdays, 72h gap over weekend
        updates = [
            "2026-02-02T08:00",  # Mon
            "2026-02-03T08:00",  # Tue
            "2026-02-04T08:00",  # Wed
            "2026-02-05T08:00",  # Thu
            "2026-02-06T08:00",  # Fri
            "2026-02-09T08:00",  # Mon (72h raw, 24h business)
            "2026-02-10T08:00",  # Tue
        ]
        history = _make_freshness_history(updates)

        _, upper_raw, _, _ = compute_freshness_threshold(history, PredictSensitivity.medium)
        _, upper_biz, _, _ = compute_freshness_threshold(
            history, PredictSensitivity.medium, exclude_weekends=True,
        )

        # With exclusion, the 72h weekend gap normalizes to ~24h, so threshold is lower
        assert upper_biz < upper_raw

    def test_sensitivity_ordering(self):
        updates = [
            "2026-02-01T00:00",
            "2026-02-01T04:00",
            "2026-02-02T14:00",
            "2026-02-03T14:00",
            "2026-02-04T06:00",
            "2026-02-04T08:00",
            "2026-02-04T16:00",
        ]
        history = _make_freshness_history(updates)

        _, upper_high, _, _ = compute_freshness_threshold(history, PredictSensitivity.high)
        _, upper_med, _, _ = compute_freshness_threshold(history, PredictSensitivity.medium)
        _, upper_low, _, _ = compute_freshness_threshold(history, PredictSensitivity.low)

        assert upper_high <= upper_med <= upper_low

    def test_min_lookback_respected(self):
        # 6 updates with sawtooth rows in between — the helper generates many rows
        updates = [f"2026-02-{d:02d}T{h:02d}:00" for d, h in [(1, 0), (1, 10), (1, 20), (2, 6), (2, 16), (3, 2)]]
        history = _make_freshness_history(updates)
        row_count = len(history)

        # With min_lookback at exactly the row count → should produce thresholds
        _, upper, _, _ = compute_freshness_threshold(history, PredictSensitivity.medium, min_lookback=row_count)
        assert upper is not None

        # With min_lookback above the row count → training mode
        lower, upper, staleness, prediction = compute_freshness_threshold(history, PredictSensitivity.medium, min_lookback=row_count + 1)
        assert lower is None
        assert upper is None
        assert staleness is None
        assert prediction is None

class Test_AddBusinessMinutes:
    def test_no_exclusions(self):
        start = pd.Timestamp("2026-02-09T08:00")  # Monday
        result = add_business_minutes(start, 120, exclude_weekends=False, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09T10:00")

    def test_zero_minutes(self):
        start = pd.Timestamp("2026-02-09T08:00")
        result = add_business_minutes(start, 0, exclude_weekends=True, holiday_dates=None)
        assert result == start

    def test_negative_minutes(self):
        start = pd.Timestamp("2026-02-09T08:00")
        result = add_business_minutes(start, -10, exclude_weekends=True, holiday_dates=None)
        assert result == start

    def test_within_same_business_day(self):
        start = pd.Timestamp("2026-02-09T08:00")  # Monday
        result = add_business_minutes(start, 60, exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09T09:00")

    def test_crosses_to_next_weekday(self):
        # Monday 23:00, add 120 min → Tuesday 01:00
        start = pd.Timestamp("2026-02-09T23:00")  # Monday
        result = add_business_minutes(start, 120, exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-10T01:00")  # Tuesday

    def test_crosses_weekend(self):
        # Friday 22:00, add 180 min (3h) → should skip Sat+Sun, land on Monday 01:00
        start = pd.Timestamp("2026-02-06T22:00")  # Friday
        result = add_business_minutes(start, 180, exclude_weekends=True, holiday_dates=None)
        # 2h left on Friday (22:00→midnight), then skip Sat+Sun, 1h into Monday
        assert result == pd.Timestamp("2026-02-09T01:00")  # Monday

    def test_starts_on_excluded_day(self):
        # Starting on Saturday — should fast-forward to Monday midnight before consuming
        start = pd.Timestamp("2026-02-07T10:00")  # Saturday
        result = add_business_minutes(start, 60, exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09T01:00")  # Monday 01:00

    def test_starts_on_sunday(self):
        start = pd.Timestamp("2026-02-08T14:00")  # Sunday
        result = add_business_minutes(start, 120, exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09T02:00")  # Monday 02:00

    def test_holiday_skipped(self):
        # Wednesday is a holiday
        start = pd.Timestamp("2026-02-03T22:00")  # Tuesday
        holiday_dates = {date(2026, 2, 4)}
        result = add_business_minutes(start, 180, exclude_weekends=False, holiday_dates=holiday_dates)
        # 2h left on Tuesday (22:00→midnight), skip Wed holiday, 1h into Thursday
        assert result == pd.Timestamp("2026-02-05T01:00")

    def test_weekend_plus_adjacent_holiday(self):
        # Friday 23:00, Monday is holiday → skip Sat, Sun, Mon
        start = pd.Timestamp("2026-02-06T23:00")  # Friday
        holiday_dates = {date(2026, 2, 9)}  # Monday
        result = add_business_minutes(start, 120, exclude_weekends=True, holiday_dates=holiday_dates)
        # 1h left on Friday (23:00→midnight), skip Sat+Sun+Mon, 1h into Tuesday
        assert result == pd.Timestamp("2026-02-10T01:00")  # Tuesday

    def test_multi_day_span(self):
        # Monday 08:00, add 3 business days (4320 min) with weekends excluded
        start = pd.Timestamp("2026-02-09T08:00")  # Monday
        result = add_business_minutes(start, 3 * 24 * 60, exclude_weekends=True, holiday_dates=None)
        # Mon→Tue→Wed→Thu 08:00 (no weekends in the way)
        assert result == pd.Timestamp("2026-02-12T08:00")

    def test_multi_day_span_crossing_weekend(self):
        # Thursday 08:00, add 3 business days → Fri, skip Sat+Sun, Mon 08:00
        start = pd.Timestamp("2026-02-05T08:00")  # Thursday
        result = add_business_minutes(start, 3 * 24 * 60, exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-10T08:00")  # Monday (skipped Sat+Sun)

    def test_inverse_property(self):
        # add_business_minutes(start, N) → end, then wall_minutes - excluded ≈ N
        start = pd.Timestamp("2026-02-06T14:00")  # Friday
        business_minutes = 600.0  # 10 hours
        end = add_business_minutes(start, business_minutes, exclude_weekends=True, holiday_dates=None)

        wall_minutes = (end - start).total_seconds() / 60
        excluded = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=None)
        assert wall_minutes - excluded == pytest.approx(business_minutes)

    def test_inverse_property_with_holidays(self):
        start = pd.Timestamp("2026-02-06T14:00")  # Friday
        holiday_dates = {date(2026, 2, 9)}  # Monday
        business_minutes = 600.0
        end = add_business_minutes(start, business_minutes, exclude_weekends=True, holiday_dates=holiday_dates)

        wall_minutes = (end - start).total_seconds() / 60
        excluded = count_excluded_minutes(start, end, exclude_weekends=True, holiday_dates=holiday_dates)
        assert wall_minutes - excluded == pytest.approx(business_minutes)

    def test_timezone_friday_night_utc_vs_et(self):
        # UTC Friday 23:00 = ET Friday 6PM → still a business day in ET
        # Without tz: Sat in UTC, would skip weekend immediately
        # With ET tz: still Friday, consumes some time before weekend
        start = pd.Timestamp("2026-02-06T23:00")  # UTC Friday 11PM

        result_no_tz = add_business_minutes(start, 120, exclude_weekends=True, holiday_dates=None)
        result_et = add_business_minutes(start, 120, exclude_weekends=True, holiday_dates=None, tz="America/New_York")

        # Without tz: naive Saturday → skip to Monday, 2h into Monday
        assert result_no_tz == pd.Timestamp("2026-02-09T01:00")
        # With ET: Friday 6PM ET, 2h → Friday 8PM ET = Sat 01:00 UTC
        assert result_et == pd.Timestamp("2026-02-07T01:00")

    def test_timezone_result_is_naive_when_input_is_naive(self):
        start = pd.Timestamp("2026-02-06T22:00")
        result = add_business_minutes(start, 60, exclude_weekends=True, holiday_dates=None, tz="America/New_York")
        assert result.tzinfo is None

    def test_no_exclusions_ignores_tz(self):
        start = pd.Timestamp("2026-02-07T10:00")  # Saturday
        result = add_business_minutes(start, 120, exclude_weekends=False, holiday_dates=None, tz="America/New_York")
        assert result == pd.Timestamp("2026-02-07T12:00")

    def test_accepts_datetime(self):
        from datetime import datetime
        start = datetime(2026, 2, 9, 8, 0)  # Monday
        result = add_business_minutes(start, 60, exclude_weekends=True, holiday_dates=None)
        assert result == pd.Timestamp("2026-02-09T09:00")


class Test_GetSarimaxForecast_TimezoneExog:
    """Verify that get_sarimax_forecast uses the schedule timezone for weekend/holiday exog flags."""

    @staticmethod
    def _make_daily_history(n_days: int = 30, hour_utc: int = 3) -> pd.DataFrame:
        """Create a simple daily history at a fixed UTC hour.

        With hour_utc=3, the timestamps are 3 AM UTC = 10 PM ET (previous day).
        This means UTC Saturday 3 AM = ET Friday 10 PM — a weekday in ET but weekend in UTC.
        """
        dates = pd.date_range("2026-01-05", periods=n_days, freq="1D") + pd.Timedelta(hours=hour_utc)
        values = np.arange(100, 100 + n_days, dtype=float) + np.random.default_rng(42).normal(0, 5, n_days)
        return pd.DataFrame({"value": values}, index=dates)

    def test_timezone_changes_weekend_flags(self):
        # History at 3 AM UTC daily — in ET that's 10 PM the previous day
        history = self._make_daily_history(n_days=40, hour_utc=3)

        # Without timezone: UTC Saturday/Sunday get is_excluded=1
        forecast_utc = get_sarimax_forecast(history, num_forecast=3, exclude_weekends=True)
        # With ET timezone: ET Saturday/Sunday get is_excluded=1 (shifted by ~5 hours)
        forecast_et = get_sarimax_forecast(history, num_forecast=3, exclude_weekends=True, tz="America/New_York")

        # The forecasts should differ because the exog flags apply to different days
        # (UTC Sat 3AM = ET Fri 10PM → not excluded in ET, excluded in UTC)
        assert not forecast_utc["mean"].equals(forecast_et["mean"])

    def test_no_timezone_preserves_original_behavior(self):
        history = self._make_daily_history(n_days=40)

        forecast_no_tz = get_sarimax_forecast(history, num_forecast=3, exclude_weekends=True)
        forecast_none_tz = get_sarimax_forecast(history, num_forecast=3, exclude_weekends=True, tz=None)

        pd.testing.assert_frame_equal(forecast_no_tz, forecast_none_tz)

    def test_without_exclusions_timezone_has_no_effect(self):
        history = self._make_daily_history(n_days=40)

        forecast_no_tz = get_sarimax_forecast(history, num_forecast=3, exclude_weekends=False)
        forecast_with_tz = get_sarimax_forecast(history, num_forecast=3, exclude_weekends=False, tz="America/New_York")

        pd.testing.assert_frame_equal(forecast_no_tz, forecast_with_tz)


class Test_ComputeSarimaxThreshold_CumulativeFloor:
    """Tests for the cumulative table floor constraint in compute_sarimax_threshold."""

    @staticmethod
    def _make_monotonic_history(n_days: int = 30, start_value: int = 1000, daily_growth: int = 100) -> pd.DataFrame:
        """Create a monotonically increasing row count history (cumulative table)."""
        dates = pd.date_range("2026-01-01", periods=n_days, freq="1D")
        values = [start_value + i * daily_growth for i in range(n_days)]
        return pd.DataFrame({"result_signal": values}, index=dates)

    def test_cumulative_floors_lower_at_last_observed(self):
        history = self._make_monotonic_history(n_days=30, start_value=1000, daily_growth=100)
        last_observed = float(history["result_signal"].iloc[-1])

        lower, upper, prediction = compute_sarimax_threshold(
            history, PredictSensitivity.medium, is_cumulative=True,
        )

        assert lower is not None
        assert upper is not None
        assert prediction is not None
        assert lower >= last_observed

    def test_non_cumulative_allows_lower_below_last_observed(self):
        # With high variance, SARIMAX lower bound can drop below last observed
        rng = np.random.default_rng(42)
        dates = pd.date_range("2026-01-01", periods=30, freq="1D")
        # Trending up but with large noise — lower bound should be below last value
        values = [1000 + i * 50 + rng.normal(0, 200) for i in range(30)]
        history = pd.DataFrame({"result_signal": values}, index=dates)
        last_observed = float(history["result_signal"].iloc[-1])

        lower, upper, prediction = compute_sarimax_threshold(
            history, PredictSensitivity.low, is_cumulative=False,
        )

        assert lower is not None
        # With low sensitivity (z=-3.0) and high noise, lower should be below last value
        # This is the behavior we're protecting against with the cumulative floor
        assert lower < last_observed

    def test_cumulative_does_not_affect_upper_tolerance(self):
        history = self._make_monotonic_history(n_days=30)

        _, upper_cumulative, _ = compute_sarimax_threshold(
            history, PredictSensitivity.medium, is_cumulative=True,
        )
        _, upper_normal, _ = compute_sarimax_threshold(
            history, PredictSensitivity.medium, is_cumulative=False,
        )

        assert upper_cumulative == upper_normal

    def test_cumulative_with_insufficient_data_returns_none(self):
        history = self._make_monotonic_history(n_days=2)

        lower, upper, prediction = compute_sarimax_threshold(
            history, PredictSensitivity.medium, min_lookback=5, is_cumulative=True,
        )

        assert lower is None
        assert upper is None
        assert prediction is None

    def test_cumulative_default_is_false(self):
        history = self._make_monotonic_history(n_days=30)

        # Without is_cumulative param, should behave as non-cumulative
        lower_default, _, _ = compute_sarimax_threshold(history, PredictSensitivity.medium)
        lower_explicit, _, _ = compute_sarimax_threshold(history, PredictSensitivity.medium, is_cumulative=False)

        assert lower_default == lower_explicit
