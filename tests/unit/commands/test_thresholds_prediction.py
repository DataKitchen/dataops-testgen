import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from scipy import stats

from testgen.commands.test_thresholds_prediction import (
    T_DISTRIBUTION_THRESHOLD,
    Z_SCORE_MAP,
    TestThresholdsPrediction,
    compute_sarimax_threshold,
    compute_volume_or_metric_threshold,
)
from testgen.common.models.test_suite import PredictSensitivity
from testgen.common.time_series_service import NotEnoughData

pytestmark = pytest.mark.unit


def _make_prediction_instance(suite_id: str = "suite-xyz") -> TestThresholdsPrediction:
    """Build a minimal TestThresholdsPrediction instance for testing instance methods.

    Bypasses __init__ (which queries the database) and sets just the attributes that
    _get_query and methods under test rely on.
    """
    instance = TestThresholdsPrediction.__new__(TestThresholdsPrediction)
    instance.test_suite = MagicMock(id=suite_id)
    instance.test_run = MagicMock(id="run-xyz")
    instance.run_date = datetime(2026, 1, 1)
    instance.tz = None
    return instance


def _make_history(n: int, value: float = 100.0) -> pd.DataFrame:
    """Build a minimal history DataFrame with n data points."""
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({"result_signal": [value] * n}, index=dates)


def _make_forecast(mean_values: list[float], se_values: list[float]) -> pd.DataFrame:
    """Build a minimal forecast DataFrame with 'mean' and 'se' columns."""
    dates = pd.date_range("2025-06-01", periods=len(mean_values), freq="D")
    return pd.DataFrame({"mean": mean_values, "se": se_values}, index=dates)


MOCK_TARGET = "testgen.commands.test_thresholds_prediction.get_sarimax_forecast"


# --- Normal tolerance calculation (large sample, z-scores used directly) ---


@patch(MOCK_TARGET)
def test_medium_sensitivity_large_sample(mock_forecast):
    forecast = _make_forecast([100.0, 105.0], [10.0, 12.0])
    mock_forecast.return_value = forecast
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    lower, upper, forecast_json = compute_sarimax_threshold(history, PredictSensitivity.medium)

    # medium: lower z=-2.5, upper z=2.5, large sample uses z directly
    assert lower == pytest.approx(100.0 + (-2.5 * 10.0))
    assert upper == pytest.approx(100.0 + (2.5 * 10.0))
    assert forecast_json is not None
    parsed = json.loads(forecast_json)
    assert "mean" in parsed


@patch(MOCK_TARGET)
def test_high_sensitivity_large_sample(mock_forecast):
    forecast = _make_forecast([100.0], [10.0])
    mock_forecast.return_value = forecast
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    lower, upper, _ = compute_sarimax_threshold(history, PredictSensitivity.high)

    # high: lower z=-2.0, upper z=2.0
    assert lower == pytest.approx(80.0)
    assert upper == pytest.approx(120.0)


@patch(MOCK_TARGET)
def test_low_sensitivity_large_sample(mock_forecast):
    forecast = _make_forecast([100.0], [10.0])
    mock_forecast.return_value = forecast
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    lower, upper, _ = compute_sarimax_threshold(history, PredictSensitivity.low)

    # low: lower z=-3.0, upper z=3.0
    assert lower == pytest.approx(70.0)
    assert upper == pytest.approx(130.0)


# --- t-distribution adjustment for small samples ---


@patch(MOCK_TARGET)
def test_small_sample_uses_t_distribution(mock_forecast):
    """With fewer than T_DISTRIBUTION_THRESHOLD points, z-scores should be
    widened via t-distribution to account for estimation uncertainty."""
    forecast = _make_forecast([100.0], [10.0])
    mock_forecast.return_value = forecast
    n = 10
    history = _make_history(n)

    lower, upper, _ = compute_sarimax_threshold(history, PredictSensitivity.medium)

    # t-distribution multiplier for medium sensitivity (z=-2.5 / z=2.5)
    lower_percentile = stats.norm.cdf(-2.5)
    upper_percentile = stats.norm.cdf(2.5)
    lower_mult = stats.t.ppf(lower_percentile, df=n - 1)
    upper_mult = stats.t.ppf(upper_percentile, df=n - 1)

    assert lower == pytest.approx(100.0 + (lower_mult * 10.0))
    assert upper == pytest.approx(100.0 + (upper_mult * 10.0))

    # t-distribution should produce wider bounds than raw z-scores
    assert lower < 100.0 + (-2.5 * 10.0)
    assert upper > 100.0 + (2.5 * 10.0)


# --- NaN handling ---


@patch(MOCK_TARGET)
def test_nan_mean_returns_none(mock_forecast):
    forecast = _make_forecast([float("nan")], [10.0])
    mock_forecast.return_value = forecast
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    lower, upper, forecast_json = compute_sarimax_threshold(history, PredictSensitivity.medium)

    assert lower is None
    assert upper is None
    assert forecast_json is None


@patch(MOCK_TARGET)
def test_nan_se_returns_none(mock_forecast):
    forecast = _make_forecast([100.0], [float("nan")])
    mock_forecast.return_value = forecast
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    lower, upper, forecast_json = compute_sarimax_threshold(history, PredictSensitivity.medium)

    assert lower is None
    assert upper is None
    assert forecast_json is None


# --- NotEnoughData from SARIMAX ---


@patch(MOCK_TARGET, side_effect=NotEnoughData("not enough"))
def test_not_enough_data_returns_none(mock_forecast):
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    lower, upper, forecast_json = compute_sarimax_threshold(history, PredictSensitivity.medium)

    assert lower is None
    assert upper is None
    assert forecast_json is None


# --- Uses first forecast date ---


@patch(MOCK_TARGET)
def test_uses_first_forecast_date(mock_forecast):
    """Tolerances should be computed from the first row of the forecast."""
    forecast = _make_forecast([100.0, 200.0], [10.0, 50.0])
    mock_forecast.return_value = forecast
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    lower, upper, _ = compute_sarimax_threshold(history, PredictSensitivity.medium)

    # Should use first row (mean=100, se=10), not second (mean=200, se=50)
    assert lower == pytest.approx(100.0 + (-2.5 * 10.0))
    assert upper == pytest.approx(100.0 + (2.5 * 10.0))


# --- Z_SCORE_MAP completeness ---


def test_z_score_map_covers_all_sensitivities():
    """Every sensitivity level should have both lower and upper entries."""
    for sensitivity in PredictSensitivity:
        assert ("lower_tolerance", sensitivity) in Z_SCORE_MAP
        assert ("upper_tolerance", sensitivity) in Z_SCORE_MAP


@patch(MOCK_TARGET)
def test_all_z_score_columns_added_to_forecast(mock_forecast):
    forecast = _make_forecast([100.0], [10.0])
    mock_forecast.return_value = forecast
    history = _make_history(T_DISTRIBUTION_THRESHOLD)

    compute_sarimax_threshold(history, PredictSensitivity.medium)

    for key in Z_SCORE_MAP:
        col = f"{key[0]}|{key[1].value}"
        assert col in forecast.columns


# --- TestThresholdsPrediction._fetch_freshness_updates_by_table ---
#
# Method fetches via _get_query → get_freshness_fingerprint_events.sql, which returns
# rows pre-filtered to fingerprint-change events and ordered by (schema, table, time).
# Tests mock the fetch and verify the indexing.

FETCH_TARGET = "testgen.commands.test_thresholds_prediction.fetch_dict_from_db"


@patch(FETCH_TARGET)
def test_fetch_freshness_events_groups_by_table(mock_fetch):
    mock_fetch.return_value = [
        {"schema_name": "s", "table_name": "t1", "test_run_id": "run_1"},
        {"schema_name": "s", "table_name": "t1", "test_run_id": "run_2"},
        {"schema_name": "s", "table_name": "t2", "test_run_id": "run_3"},
    ]
    instance = _make_prediction_instance()
    events = instance._fetch_freshness_updates_by_table()
    assert set(events.keys()) == {("s", "t1"), ("s", "t2")}
    assert events[("s", "t1")] == ["run_1", "run_2"]
    assert events[("s", "t2")] == ["run_3"]


@patch(FETCH_TARGET)
def test_fetch_freshness_events_preserves_input_order(mock_fetch):
    """SQL returns rows ordered by (schema, table, test_time); the method trusts that
    order rather than re-sorting."""
    mock_fetch.return_value = [
        {"schema_name": "s", "table_name": "t", "test_run_id": "run_a"},
        {"schema_name": "s", "table_name": "t", "test_run_id": "run_b"},
        {"schema_name": "s", "table_name": "t", "test_run_id": "run_c"},
    ]
    instance = _make_prediction_instance()
    events = instance._fetch_freshness_updates_by_table()
    assert events[("s", "t")] == ["run_a", "run_b", "run_c"]


@patch(FETCH_TARGET)
def test_fetch_freshness_events_coerces_run_id_to_str(mock_fetch):
    """test_run_id can come back as a UUID object — must be cast to str for downstream
    .isin() matching against the str-cast Volume/Metric test_run_id column."""
    from uuid import UUID as _UUID
    rid = _UUID("12345678-1234-5678-1234-567812345678")
    mock_fetch.return_value = [
        {"schema_name": "s", "table_name": "t", "test_run_id": rid},
    ]
    instance = _make_prediction_instance()
    events = instance._fetch_freshness_updates_by_table()
    assert events[("s", "t")] == [str(rid)]


@patch(FETCH_TARGET)
def test_fetch_freshness_events_empty_result(mock_fetch):
    mock_fetch.return_value = []
    instance = _make_prediction_instance()
    assert instance._fetch_freshness_updates_by_table() == {}


@patch(FETCH_TARGET)
def test_fetch_freshness_events_passes_suite_id_through_get_query(mock_fetch):
    """Reuses self._get_query, which substitutes TEST_SUITE_ID from self.test_suite.id."""
    mock_fetch.return_value = []
    instance = _make_prediction_instance(suite_id="suite-xyz")
    instance._fetch_freshness_updates_by_table()
    _query, params = mock_fetch.call_args.args
    assert params["TEST_SUITE_ID"] == "suite-xyz"


# --- compute_volume_or_metric_threshold ---


def _history_with_run_ids(timestamps: list[str], run_ids: list[str], value: float = 100.0) -> pd.DataFrame:
    """Build a Volume/Metric-shaped history: indexed by test_time, with a test_run_id
    column matching how `run()` slices the historical-results dataframe per definition."""
    assert len(timestamps) == len(run_ids)
    return pd.DataFrame(
        {"result_signal": [value] * len(timestamps), "test_run_id": run_ids},
        index=pd.to_datetime(timestamps),
    )


@patch(MOCK_TARGET)
def test_freshness_gating_engages_when_filtered_fit_succeeds(mock_forecast):
    mock_forecast.return_value = _make_forecast([220.0], [1.0])
    timestamps = [f"2026-01-{day:02d}" for day in range(1, 21)]
    run_ids = [f"run_{i:02d}" for i in range(len(timestamps))]
    history = _history_with_run_ids(timestamps, run_ids, value=220.0)
    freshness_updates = run_ids[:8]

    lower, upper, baseline, prediction = compute_volume_or_metric_threshold(
        history, freshness_updates, PredictSensitivity.medium,
    )

    assert lower is not None and upper is not None
    assert baseline == 220.0
    assert prediction is not None
    parsed = json.loads(prediction)
    assert parsed["freshness_gated"] is True
    assert parsed["baseline_value"] == 220.0


@patch(MOCK_TARGET)
def test_freshness_gating_falls_back_when_filtered_fit_raises(mock_forecast):
    """If SARIMAX fails on the freshness-filtered series (NotEnoughData after resample,
    convergence), fall back to fitting on the raw value series and emit a prediction
    without the freshness-gating markers."""
    raw_forecast = _make_forecast([220.0], [1.0])
    mock_forecast.side_effect = [NotEnoughData("not enough"), raw_forecast]
    timestamps = [f"2026-01-{day:02d}" for day in range(1, 21)]
    run_ids = [f"run_{i:02d}" for i in range(len(timestamps))]
    history = _history_with_run_ids(timestamps, run_ids, value=220.0)
    freshness_updates = run_ids[:5]  # any selection — first call is forced to raise

    _, _, baseline, prediction = compute_volume_or_metric_threshold(
        history, freshness_updates, PredictSensitivity.medium,
    )

    assert mock_forecast.call_count == 2  # filtered failed, raw retried
    assert baseline is None
    assert prediction is not None
    parsed = json.loads(prediction)
    assert "freshness_gated" not in parsed
    assert "baseline_value" not in parsed


@patch(MOCK_TARGET)
def test_freshness_gating_falls_back_when_no_freshness_events(mock_forecast):
    """Empty freshness_updates → filtered history is empty → filtered fit fails →
    fall back to fitting on the raw series."""
    # First call (filtered, 0 rows) returns enough that compute_sarimax_threshold trips
    # the NaN tolerance path; second call (raw) succeeds.
    raw_forecast = _make_forecast([220.0], [1.0])
    mock_forecast.side_effect = [NotEnoughData("not enough"), raw_forecast]
    timestamps = [f"2026-01-{day:02d}" for day in range(1, 21)]
    run_ids = [f"run_{i:02d}" for i in range(len(timestamps))]
    history = _history_with_run_ids(timestamps, run_ids)

    _, _, baseline, prediction = compute_volume_or_metric_threshold(
        history, freshness_updates=[], sensitivity=PredictSensitivity.medium,
    )

    assert baseline is None
    assert prediction is not None
    parsed = json.loads(prediction)
    assert "freshness_gated" not in parsed


@patch(MOCK_TARGET)
def test_freshness_gating_fits_on_filtered_series(mock_forecast):
    """SARIMAX should be fit on the filtered series (one row per freshness change),
    not on the raw plateau-laden series. Verified via the length of the dataframe
    passed to get_sarimax_forecast on the engaging call."""
    mock_forecast.return_value = _make_forecast([220.0], [1.0])
    timestamps = [f"2026-01-{day:02d}" for day in range(1, 21)]
    run_ids = [f"run_{i:02d}" for i in range(len(timestamps))]
    history = _history_with_run_ids(timestamps, run_ids, value=220.0)
    freshness_updates = run_ids[:8]

    compute_volume_or_metric_threshold(
        history, freshness_updates, PredictSensitivity.medium,
    )

    fitted_history = mock_forecast.call_args.args[0]
    assert len(fitted_history) == len(freshness_updates)


@patch(MOCK_TARGET)
def test_freshness_gating_filtered_fit_uses_event_space(mock_forecast):
    """The freshness-filtered fit must run in event-space (event_space=True): the filtered
    series has one point per refresh and is irregularly spaced, so calendar resampling would
    interpolate the refresh jumps into uniform increments and bias the forecast low."""
    mock_forecast.return_value = _make_forecast([220.0], [1.0])
    timestamps = [f"2026-01-{day:02d}" for day in range(1, 21)]
    run_ids = [f"run_{i:02d}" for i in range(len(timestamps))]
    history = _history_with_run_ids(timestamps, run_ids, value=220.0)

    compute_volume_or_metric_threshold(history, run_ids[:8], PredictSensitivity.medium)

    assert mock_forecast.call_args.kwargs["event_space"] is True


@patch(MOCK_TARGET)
def test_freshness_gating_raw_fallback_uses_calendar(mock_forecast):
    """The raw-history fallback (when the filtered fit fails) keeps calendar regularization."""
    mock_forecast.side_effect = [NotEnoughData("not enough"), _make_forecast([220.0], [1.0])]
    timestamps = [f"2026-01-{day:02d}" for day in range(1, 21)]
    run_ids = [f"run_{i:02d}" for i in range(len(timestamps))]
    history = _history_with_run_ids(timestamps, run_ids, value=220.0)

    compute_volume_or_metric_threshold(history, run_ids[:5], PredictSensitivity.medium)

    assert mock_forecast.call_count == 2  # filtered (event-space) failed, raw retried
    assert mock_forecast.call_args_list[0].kwargs["event_space"] is True
    assert mock_forecast.call_args_list[1].kwargs["event_space"] is False


@patch(MOCK_TARGET)
def test_freshness_gating_baseline_from_filtered_when_events_extend_past_history(mock_forecast):
    """When freshness_updates includes runs beyond the (retention-trimmed) history window,
    baseline_value must come from the most recent filtered row — not from a run that's no
    longer in history."""
    mock_forecast.return_value = _make_forecast([220.0], [1.0])
    # History only covers the first 8 days (run_00..run_07)
    history_timestamps = [f"2026-01-{day:02d}" for day in range(1, 9)]
    history_run_ids = [f"run_{i:02d}" for i in range(8)]
    values = [float(i) for i in range(1, 9)]  # distinct values so baseline is identifiable
    history = pd.DataFrame(
        {"result_signal": values, "test_run_id": history_run_ids},
        index=pd.to_datetime(history_timestamps),
    )
    # Freshness events for those 8 runs PLUS 3 more that aren't in history (trimmed)
    freshness_updates = history_run_ids + [f"run_{i}" for i in range(20, 23)]

    _, _, baseline, prediction = compute_volume_or_metric_threshold(
        history, freshness_updates, PredictSensitivity.medium,
    )

    assert baseline == 8.0
    assert prediction is not None
    parsed = json.loads(prediction)
    assert parsed["freshness_gated"] is True
    # baseline_value must be the value at the LAST timestamp present in BOTH history and
    # freshness_updates (not freshness_updates[-1] which points past the history window)
    assert parsed["baseline_value"] == 8.0


@patch(MOCK_TARGET)
def test_freshness_gating_baseline_survives_two_runs_in_one_second(mock_forecast):
    """test_time labels every result row a run writes and carries whole seconds, so two runs
    of one suite starting in the same second tie on it. A label lookup against the tied index
    returns both rows, and converting that Series to a float raises — which escapes the
    per-definition loop and discards the whole suite's predictions for the run."""
    mock_forecast.return_value = _make_forecast([220.0], [1.0])
    timestamps = [f"2026-01-{day:02d}" for day in range(1, 10)]
    # The two most recent events land in the same second.
    timestamps.append(timestamps[-1])
    run_ids = [f"run_{i:02d}" for i in range(len(timestamps))]
    values = [float(i) for i in range(1, len(timestamps) + 1)]
    history = pd.DataFrame(
        {"result_signal": values, "test_run_id": run_ids},
        index=pd.to_datetime(timestamps),
    )

    _, _, baseline, prediction = compute_volume_or_metric_threshold(
        history, run_ids, PredictSensitivity.medium,
    )

    assert prediction is not None
    parsed = json.loads(prediction)
    assert parsed["freshness_gated"] is True
    # The last row in run order wins, and the value stays a scalar.
    assert baseline == 10.0
    assert parsed["baseline_value"] == 10.0
