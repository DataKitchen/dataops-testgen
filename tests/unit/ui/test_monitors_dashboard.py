from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testgen.common.monitor_forecast import gated_forecast_prediction
from testgen.ui.views.monitors_dashboard import _freshness_next_update_window, build_table_trends_data

pytestmark = pytest.mark.unit

# The business-time helpers live in (and are called from) the shared forecast
# module, so patch them there even when exercising the dashboard wrapper.
MODULE = "testgen.common.monitor_forecast"


def _freshness_def(history_calculation="PREDICT", prediction=None, upper="1000", lower="500"):
    d = MagicMock()
    d.history_calculation = history_calculation
    d.prediction = {"schedule_stage": "active"} if prediction is None else prediction
    d.upper_tolerance = upper
    d.lower_tolerance = lower
    return d


def _events(changed=True, is_training=False, is_pending=False, time=datetime(2026, 6, 22, 16, 0)):
    return {"freshness_events": [{"changed": changed, "is_training": is_training, "is_pending": is_pending, "time": time}]}


def _suite():
    s = MagicMock()
    s.predict_exclude_weekends = False
    s.holiday_codes_list = None
    return s


def _schedule():
    s = MagicMock()
    s.cron_tz = "UTC"
    return s


# --- _freshness_next_update_window: guard branches return None ---


def test_window_none_when_no_freshness_definition():
    assert _freshness_next_update_window(None, _events(), _suite(), _schedule()) is None


def test_window_none_when_not_predict():
    d = _freshness_def(history_calculation=None)
    assert _freshness_next_update_window(d, _events(), _suite(), _schedule()) is None


def test_window_none_when_prediction_lacks_schedule_stage():
    # Non-empty prediction without schedule_stage (e.g. still learning) → no window
    d = _freshness_def(prediction={"frequency": "daily"})
    assert _freshness_next_update_window(d, _events(), _suite(), _schedule()) is None


def test_window_none_when_no_upper_tolerance():
    d = _freshness_def(upper=None)
    assert _freshness_next_update_window(d, _events(), _suite(), _schedule()) is None


def test_window_none_when_no_qualifying_update_events():
    # Only training / pending / unchanged events → nothing to anchor the window to
    events = {"freshness_events": [
        {"changed": True, "is_training": True, "is_pending": False, "time": datetime(2026, 6, 22)},
        {"changed": False, "is_training": False, "is_pending": False, "time": datetime(2026, 6, 22)},
    ]}
    assert _freshness_next_update_window(_freshness_def(), events, _suite(), _schedule()) is None


@patch(f"{MODULE}.get_schedule_params", return_value=MagicMock(excluded_days=[]))
@patch(f"{MODULE}.add_business_minutes")
def test_window_returns_start_end_when_valid(mock_abm, _mock_sched):
    # add_business_minutes is called for the end (upper_tolerance) then the start (lower_tolerance)
    mock_abm.side_effect = [pd.Timestamp("2026-06-23 19:00"), pd.Timestamp("2026-06-23 04:00")]
    window = _freshness_next_update_window(_freshness_def(), _events(), _suite(), _schedule())
    assert window == {
        "start": int(pd.Timestamp("2026-06-23 04:00").timestamp() * 1000),
        "end": int(pd.Timestamp("2026-06-23 19:00").timestamp() * 1000),
    }


@patch(f"{MODULE}.get_schedule_params", return_value=MagicMock(excluded_days=[]))
@patch(f"{MODULE}.add_business_minutes")
def test_window_start_is_none_when_no_lower_tolerance(mock_abm, _mock_sched):
    mock_abm.return_value = pd.Timestamp("2026-06-23 19:00")
    window = _freshness_next_update_window(_freshness_def(lower=None), _events(), _suite(), _schedule())
    assert window["start"] is None
    assert window["end"] == int(pd.Timestamp("2026-06-23 19:00").timestamp() * 1000)


# --- gated_forecast_prediction ---

LAST_RUN = datetime(2026, 6, 23, 16, 0)
NOW_MS = int(pd.Timestamp(LAST_RUN).timestamp() * 1000)
HOUR = 3600 * 1000


def _gated_def(baseline=1000.0, mean=None, lower="950", upper="1400"):
    d = MagicMock()
    d.prediction = {"freshness_gated": True, "baseline_value": baseline}
    if mean is not None:
        d.prediction["mean"] = mean
    d.lower_tolerance = lower
    d.upper_tolerance = upper
    return d


def test_gated_prediction_none_without_window():
    assert gated_forecast_prediction(_gated_def(), None, LAST_RUN) is None


def test_gated_prediction_none_when_window_elapsed():
    window = {"start": NOW_MS - 12 * HOUR, "end": NOW_MS - HOUR}  # window_end already in the past
    assert gated_forecast_prediction(_gated_def(), window, LAST_RUN) is None


def test_gated_prediction_none_without_baseline():
    window = {"start": NOW_MS - HOUR, "end": NOW_MS + 3 * HOUR}
    assert gated_forecast_prediction(_gated_def(baseline=None), window, LAST_RUN) is None


def test_gated_prediction_none_without_last_run():
    window = {"start": NOW_MS - HOUR, "end": NOW_MS + 3 * HOUR}
    assert gated_forecast_prediction(_gated_def(), window, None) is None


def test_gated_prediction_anchors_at_now_when_window_started():
    # window_start is before the latest run → anchor clamps to now (forecast never draws backward)
    window = {"start": NOW_MS - 12 * HOUR, "end": NOW_MS + 3 * HOUR}
    mean = {str(NOW_MS + 3 * HOUR): 1200.0, str(NOW_MS + 27 * HOUR): 1300.0}
    result = gated_forecast_prediction(_gated_def(mean=mean), window, LAST_RUN)
    assert result["method"] == "predict"
    # mean holds flat at baseline then steps to the next-refresh forecast
    assert result["mean"] == {NOW_MS: 1000.0, NOW_MS + 3 * HOUR: 1200.0}
    # band carries the next-refresh tolerance across the whole forecast (continuous width, no
    # zero-width pinch at the flat anchor); coerced from VARCHAR to float
    assert result["lower_tolerance"] == {NOW_MS: 950.0, NOW_MS + 3 * HOUR: 950.0}
    assert result["upper_tolerance"] == {NOW_MS: 1400.0, NOW_MS + 3 * HOUR: 1400.0}


def test_gated_prediction_anchors_at_window_start_when_future():
    # window opens after the latest run → flat segment runs out to window_start
    window = {"start": NOW_MS + HOUR, "end": NOW_MS + 3 * HOUR}
    mean = {str(NOW_MS + 3 * HOUR): 1200.0}
    result = gated_forecast_prediction(_gated_def(mean=mean), window, LAST_RUN)
    assert set(result["mean"].keys()) == {NOW_MS + HOUR, NOW_MS + 3 * HOUR}


def test_gated_prediction_next_mean_falls_back_to_baseline_without_forecast():
    window = {"start": NOW_MS - HOUR, "end": NOW_MS + 3 * HOUR}
    result = gated_forecast_prediction(_gated_def(mean=None), window, LAST_RUN)
    assert result["mean"][NOW_MS + 3 * HOUR] == 1000.0  # baseline used as the step value


# --- build_table_trends_data: forecast anchors are independent of the display window ---

SUITE_ID = "11111111-1111-1111-1111-111111111111"
LATEST_RUN = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
EARLIER_RUN = datetime(2026, 8, 1, 6, 0, tzinfo=UTC)
IN_PAST_WINDOW_RUN = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)


def _series(freshness_times=(), volume_times=()):
    return {
        "freshness_events": [
            {"changed": True, "is_training": False, "is_pending": False, "time": t} for t in freshness_times
        ],
        "volume_events": [{"time": t, "record_count": 10} for t in volume_times],
        "schema_events": [],
        "metric_events": [],
    }


def _range_ending(offset, span=timedelta(days=30)):
    end = datetime.now(UTC) + offset
    return {
        "preset": "custom",
        "start": int((end - span).timestamp() * 1000),
        "end": int(end.timestamp() * 1000),
    }


def _forecast_suite():
    s = _suite()
    s.monitor_lookback = 30
    s.predict_sensitivity = None
    return s


def _table_group():
    tg = MagicMock()
    tg.monitor_test_suite_id = SUITE_ID
    tg.id = "22222222-2222-2222-2222-222222222222"
    return tg


def _monitor_def(test_type, history_calculation="PREDICT", prediction=None, lower=None, upper=None):
    d = MagicMock()
    d.test_type = test_type
    d.history_calculation = history_calculation
    d.prediction = prediction
    d.lower_tolerance = lower
    d.upper_tolerance = upper
    return d


@contextmanager
def _trends_harness(trend_range, definitions, windowed, unwindowed):
    """Patch build_table_trends_data's collaborators, yielding the events mock."""
    table_group = _table_group()
    session_state = {f"table_monitoring_trends:range:{SUITE_ID}:orders": trend_range}

    def events_for(_suite_id, _table_name, start=None, _end=None):
        return windowed if start is not None else unwindowed

    with (
        patch("testgen.common.models.database_session"),
        patch("testgen.ui.views.monitors_dashboard.temp_value", return_value=(lambda: None, lambda _v: None)),
        patch("testgen.ui.views.monitors_dashboard.st") as mock_st,
        patch("testgen.ui.views.monitors_dashboard.select_test_definitions_where", return_value=definitions),
        patch("testgen.ui.views.monitors_dashboard.get_test_suite", return_value=_forecast_suite()),
        patch("testgen.ui.views.monitors_dashboard.get_monitor_schedule", return_value=_schedule()),
        patch("testgen.ui.views.monitors_dashboard.count_monitor_runs", return_value=1),
        patch("testgen.ui.views.monitors_dashboard.get_monitor_events_for_table", side_effect=events_for) as mock_events,
    ):
        mock_st.session_state = session_state
        yield table_group, mock_events


def test_freshness_anchor_ignores_a_narrow_display_window():
    # A weekly-refreshed table viewed over 7 days: the window holds no detected update, but the
    # forecast must still anchor on the one outside it.
    windowed = _series(freshness_times=(), volume_times=(LATEST_RUN,))
    unwindowed = _series(freshness_times=(EARLIER_RUN,), volume_times=(EARLIER_RUN, LATEST_RUN))
    trend_range = _range_ending(timedelta(hours=1), span=timedelta(days=7))
    definitions = [_monitor_def("Freshness_Trend")]

    with _trends_harness(trend_range, definitions, windowed, unwindowed) as (table_group, mock_events):
        with patch(
            "testgen.ui.views.monitors_dashboard._freshness_next_update_window", return_value=None,
        ) as mock_window:
            data, _handlers = build_table_trends_data(table_group, {"table_name": "orders"})

    # Two fetches: the windowed one for display, the full lookback for the anchors.
    assert mock_events.call_count == 2
    assert mock_window.call_args.args[1] is unwindowed
    # Display still shows only the selected window.
    assert data["freshness_events"] == []


def test_forecast_anchors_reuse_the_display_events_when_unbounded():
    unwindowed = _series(freshness_times=(EARLIER_RUN,), volume_times=(EARLIER_RUN, LATEST_RUN))
    trend_range = {"preset": "default", "start": None, "end": None}
    definitions = [_monitor_def("Freshness_Trend")]

    with _trends_harness(trend_range, definitions, None, unwindowed) as (table_group, mock_events):
        with patch(
            "testgen.ui.views.monitors_dashboard._freshness_next_update_window", return_value=None,
        ) as mock_window:
            build_table_trends_data(table_group, {"table_name": "orders"})

    assert mock_events.call_count == 1
    assert mock_window.call_args.args[1] is unwindowed


def test_cron_reference_time_anchors_on_the_full_lookback():
    # The static fallback samples upcoming runs from the last actual run, which must not move
    # when the user narrows the view to a slice that excludes it.
    windowed = _series(volume_times=(IN_PAST_WINDOW_RUN,))
    unwindowed = _series(volume_times=(IN_PAST_WINDOW_RUN, EARLIER_RUN, LATEST_RUN))
    trend_range = _range_ending(timedelta(hours=1), span=timedelta(days=7))
    definitions = [_monitor_def("Volume_Trend", history_calculation=None, lower="900", upper="1100")]

    with _trends_harness(trend_range, definitions, windowed, unwindowed) as (table_group, _mock_events):
        with (
            patch("testgen.ui.views.monitors_dashboard._freshness_next_update_window", return_value=None),
            patch(
                "testgen.ui.views.monitors_dashboard.get_cron_sample", return_value={"samples": []},
            ) as mock_cron,
        ):
            build_table_trends_data(table_group, {"table_name": "orders"})

    assert mock_cron.call_args.kwargs["reference_time"] == LATEST_RUN


# --- build_table_trends_data: a window wider than the chart can show is not fetched ---


def test_oversized_window_is_not_fetched_and_says_why():
    with _trends_harness(_range_ending(timedelta(hours=1), span=timedelta(days=365)), [_monitor_def("Freshness_Trend")], None, None) as (tg, mock_events):
        with patch("testgen.ui.views.monitors_dashboard.count_monitor_runs", return_value=8760):
            data, _handlers = build_table_trends_data(tg, {"table_name": "orders"})

    mock_events.assert_not_called()
    assert data["freshness_events"] == []
    assert data["volume_events"] == []
    assert data["predictions"] == {}
    assert "8,760 monitor runs" in data["trend_notice"]
    assert "shorter range" in data["trend_notice"]


def test_window_within_budget_is_fetched_normally():
    series = _series(freshness_times=(LATEST_RUN,), volume_times=(LATEST_RUN,))
    with _trends_harness(_range_ending(timedelta(hours=1)), [_monitor_def("Freshness_Trend")], series, series) as (tg, mock_events):
        with (
            patch("testgen.ui.views.monitors_dashboard.count_monitor_runs", return_value=720),
            patch("testgen.ui.views.monitors_dashboard._freshness_next_update_window", return_value=None),
        ):
            data, _handlers = build_table_trends_data(tg, {"table_name": "orders"})

    assert mock_events.call_count == 2
    assert data["trend_notice"] is None
    assert len(data["freshness_events"]) == 1


def test_unbounded_window_is_never_counted():
    # Default is capped by the suite's configured run count, so there is nothing to guard.
    series = _series(volume_times=(LATEST_RUN,))
    trend_range = {"preset": "default", "start": None, "end": None}
    with _trends_harness(trend_range, [_monitor_def("Freshness_Trend")], None, series) as (tg, _mock_events):
        with (
            patch("testgen.ui.views.monitors_dashboard.count_monitor_runs") as mock_count,
            patch("testgen.ui.views.monitors_dashboard._freshness_next_update_window", return_value=None),
        ):
            data, _handlers = build_table_trends_data(tg, {"table_name": "orders"})

    mock_count.assert_not_called()
    assert data["trend_notice"] is None


# --- build_table_trends_data: a window that has already closed gets no forecast ---


def _static_volume_monitor():
    return _monitor_def("Volume_Trend", history_calculation=None, lower="900", upper="1100")


@contextmanager
def _forecast_collaborators():
    with (
        patch("testgen.ui.views.monitors_dashboard._freshness_next_update_window", return_value=None),
        patch("testgen.ui.views.monitors_dashboard.get_cron_sample", return_value={"samples": [1]}),
    ):
        yield


def test_forecast_is_dropped_for_a_window_that_ends_in_the_past():
    series = _series(volume_times=(LATEST_RUN,))
    trend_range = _range_ending(-timedelta(days=7))
    with _trends_harness(trend_range, [_static_volume_monitor()], series, series) as (tg, _mock_events):
        with _forecast_collaborators():
            data, _handlers = build_table_trends_data(tg, {"table_name": "orders"})

    assert data["predictions"] == {}


def test_forecast_is_kept_for_a_window_that_is_still_open():
    series = _series(volume_times=(LATEST_RUN,))
    trend_range = _range_ending(timedelta(hours=1))
    with _trends_harness(trend_range, [_static_volume_monitor()], series, series) as (tg, _mock_events):
        with _forecast_collaborators():
            data, _handlers = build_table_trends_data(tg, {"table_name": "orders"})

    assert "volume_trend" in data["predictions"]


def test_past_window_does_not_fetch_the_forecast_anchors():
    # The full-lookback fetch exists only to anchor the forecast, so a closed window skips it.
    series = _series(volume_times=(LATEST_RUN,))
    trend_range = _range_ending(-timedelta(days=7))
    with _trends_harness(trend_range, [_static_volume_monitor()], series, series) as (tg, mock_events):
        with _forecast_collaborators():
            build_table_trends_data(tg, {"table_name": "orders"})

    assert mock_events.call_count == 1
