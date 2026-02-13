import json

import pandas as pd
import pytest

from testgen.commands.test_thresholds_prediction import Z_SCORE_MAP, calculate_prediction_tolerances
from testgen.common.models.test_suite import PredictSensitivity

pytestmark = pytest.mark.unit


def _make_forecast(mean_values: list[float], se_values: list[float]) -> pd.DataFrame:
    """Build a minimal forecast DataFrame with 'mean' and 'se' columns."""
    dates = pd.date_range("2025-01-01", periods=len(mean_values), freq="D")
    return pd.DataFrame({"mean": mean_values, "se": se_values}, index=dates)


def test_normal_calculation_medium_sensitivity():
    forecast = _make_forecast([100.0, 105.0], [10.0, 12.0])
    lower, upper, forecast_json = calculate_prediction_tolerances(
        forecast, PredictSensitivity.medium,
    )
    # medium: lower z=-1.5, upper z=1.5
    # lower = 100 + (-1.5 * 10) = 85.0
    # upper = 100 + (1.5 * 10) = 115.0
    assert lower == pytest.approx(85.0)
    assert upper == pytest.approx(115.0)
    assert forecast_json is not None
    # Verify it's valid JSON
    parsed = json.loads(forecast_json)
    assert "mean" in parsed


def test_high_sensitivity_tighter_bounds():
    forecast = _make_forecast([100.0], [10.0])
    lower, upper, _ = calculate_prediction_tolerances(
        forecast, PredictSensitivity.high,
    )
    # high: lower z=-1.0, upper z=1.0
    assert lower == pytest.approx(90.0)
    assert upper == pytest.approx(110.0)


def test_low_sensitivity_wider_bounds():
    forecast = _make_forecast([100.0], [10.0])
    lower, upper, _ = calculate_prediction_tolerances(
        forecast, PredictSensitivity.low,
    )
    # low: lower z=-2.0, upper z=2.0
    assert lower == pytest.approx(80.0)
    assert upper == pytest.approx(120.0)


def test_nan_in_forecast_returns_none():
    forecast = _make_forecast([float("nan")], [10.0])
    lower, upper, forecast_json = calculate_prediction_tolerances(
        forecast, PredictSensitivity.medium,
    )
    assert lower is None
    assert upper is None
    assert forecast_json is None


def test_nan_se_returns_none():
    forecast = _make_forecast([100.0], [float("nan")])
    lower, upper, forecast_json = calculate_prediction_tolerances(
        forecast, PredictSensitivity.medium,
    )
    assert lower is None
    assert upper is None
    assert forecast_json is None


def test_z_score_columns_added_to_forecast():
    """Verify that the z-score tolerance columns are added to the forecast DataFrame."""
    forecast = _make_forecast([100.0, 105.0], [10.0, 12.0])
    calculate_prediction_tolerances(forecast, PredictSensitivity.medium)
    # All z-score columns should be present
    for key in Z_SCORE_MAP:
        col = f"{key[0]}|{key[1].value}"
        assert col in forecast.columns


def test_uses_first_forecast_date():
    """Tolerances should be computed from the first row of the forecast."""
    forecast = _make_forecast([100.0, 200.0], [10.0, 50.0])
    lower, upper, _ = calculate_prediction_tolerances(
        forecast, PredictSensitivity.medium,
    )
    # Should use first row (mean=100, se=10), not second (mean=200, se=50)
    assert lower == pytest.approx(85.0)
    assert upper == pytest.approx(115.0)
