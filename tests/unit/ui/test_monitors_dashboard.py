from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testgen.ui.views.monitors_dashboard import (
    _build_gated_forecast_prediction,
    _freshness_next_update_window,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.monitors_dashboard"


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


# --- _build_gated_forecast_prediction ---

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
    assert _build_gated_forecast_prediction(_gated_def(), None, LAST_RUN) is None


def test_gated_prediction_none_when_window_elapsed():
    window = {"start": NOW_MS - 12 * HOUR, "end": NOW_MS - HOUR}  # window_end already in the past
    assert _build_gated_forecast_prediction(_gated_def(), window, LAST_RUN) is None


def test_gated_prediction_none_without_baseline():
    window = {"start": NOW_MS - HOUR, "end": NOW_MS + 3 * HOUR}
    assert _build_gated_forecast_prediction(_gated_def(baseline=None), window, LAST_RUN) is None


def test_gated_prediction_none_without_last_run():
    window = {"start": NOW_MS - HOUR, "end": NOW_MS + 3 * HOUR}
    assert _build_gated_forecast_prediction(_gated_def(), window, None) is None


def test_gated_prediction_anchors_at_now_when_window_started():
    # window_start is before the latest run → anchor clamps to now (forecast never draws backward)
    window = {"start": NOW_MS - 12 * HOUR, "end": NOW_MS + 3 * HOUR}
    mean = {str(NOW_MS + 3 * HOUR): 1200.0, str(NOW_MS + 27 * HOUR): 1300.0}
    result = _build_gated_forecast_prediction(_gated_def(mean=mean), window, LAST_RUN)
    assert result["method"] == "predict"
    assert result["mean"] == {NOW_MS: 1000.0, NOW_MS + 3 * HOUR: 1200.0}
    # tolerances coerced from VARCHAR to float
    assert result["lower_tolerance"] == {NOW_MS: 1000.0, NOW_MS + 3 * HOUR: 950.0}
    assert result["upper_tolerance"] == {NOW_MS: 1000.0, NOW_MS + 3 * HOUR: 1400.0}


def test_gated_prediction_anchors_at_window_start_when_future():
    # window opens after the latest run → flat segment runs out to window_start
    window = {"start": NOW_MS + HOUR, "end": NOW_MS + 3 * HOUR}
    mean = {str(NOW_MS + 3 * HOUR): 1200.0}
    result = _build_gated_forecast_prediction(_gated_def(mean=mean), window, LAST_RUN)
    assert set(result["mean"].keys()) == {NOW_MS + HOUR, NOW_MS + 3 * HOUR}


def test_gated_prediction_next_mean_falls_back_to_baseline_without_forecast():
    window = {"start": NOW_MS - HOUR, "end": NOW_MS + 3 * HOUR}
    result = _build_gated_forecast_prediction(_gated_def(mean=None), window, LAST_RUN)
    assert result["mean"][NOW_MS + 3 * HOUR] == 1000.0  # baseline used as the step value
