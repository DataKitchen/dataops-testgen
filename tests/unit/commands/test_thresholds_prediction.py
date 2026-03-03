import json
from unittest.mock import patch

import pandas as pd
import pytest
from scipy import stats

from testgen.commands.test_thresholds_prediction import (
    T_DISTRIBUTION_THRESHOLD,
    Z_SCORE_MAP,
    compute_sarimax_threshold,
)
from testgen.common.models.test_suite import PredictSensitivity
from testgen.common.time_series_service import NotEnoughData

pytestmark = pytest.mark.unit


def _make_history(n: int, value: float = 100.0) -> pd.DataFrame:
    """Build a minimal history DataFrame with n data points."""
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({"result_signal": [value] * n}, index=dates)


def _make_forecast(mean_values: list[float], se_values: list[float]) -> pd.DataFrame:
    """Build a minimal forecast DataFrame with 'mean' and 'se' columns."""
    dates = pd.date_range("2025-06-01", periods=len(mean_values), freq="D")
    return pd.DataFrame({"mean": mean_values, "se": se_values}, index=dates)


MOCK_TARGET = "testgen.commands.test_thresholds_prediction.get_sarimax_forecast"


# --- min_lookback guard ---


def test_below_min_lookback_returns_none():
    history = _make_history(3)
    lower, upper, prediction = compute_sarimax_threshold(history, PredictSensitivity.medium, min_lookback=5)
    assert lower is None
    assert upper is None
    assert prediction is None


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
