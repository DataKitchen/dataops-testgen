"""Monitor forecast computation shared by the monitors dashboard and the MCP
monitor tools.

The forecast a monitor displays depends on its threshold mode and type:

* Volume / Metric in Prediction Model mode: a value band extending forward. For
  monitors coupled to a Freshness monitor the band holds at the baseline until
  the next expected refresh, then steps to the forecast value (``gated_forecast_prediction``);
  otherwise it is the raw per-step prediction band.
* Freshness in Prediction Model mode: a predicted next-update *time window*
  rather than a value band (``next_update_window``).

These functions are intentionally free of any UI dependency so both surfaces
render the same forecast from the same source of truth.
"""

from datetime import UTC, date, datetime

import pandas as pd

from testgen.common.freshness_service import add_business_minutes, get_schedule_params, resolve_holiday_dates
from testgen.common.models.test_definition import MonitorForecastPoint, TestDefinition, TestDefinitionSummary
from testgen.common.models.test_suite import TestSuite

# A monitor definition carrying the forecast-relevant fields — satisfied by both
# the ORM row and the read-only summary dataclass.
MonitorDefinition = TestDefinition | TestDefinitionSummary


def resolve_suite_holiday_dates(test_suite: TestSuite) -> set[date] | None:
    """Holiday dates excluded from the suite's schedule, over a window spanning
    recent history through the forecast horizon. ``None`` when no calendars are set."""
    if not test_suite.holiday_codes_list:
        return None
    now = pd.Timestamp.now("UTC")
    idx = pd.DatetimeIndex([now - pd.Timedelta(days=7), now + pd.Timedelta(days=30)])
    return resolve_holiday_dates(test_suite.holiday_codes_list, idx)


def next_update_window(
    freshness_definition: MonitorDefinition | None,
    last_detection_time: datetime | None,
    *,
    test_suite: TestSuite,
    cron_tz: str | None,
) -> dict | None:
    """Predicted next-update window as ``{"start", "end"}`` epoch-ms, or ``None``.

    The schedule-derived business-time interval from the last detected update out
    to the lower/upper staleness tolerance. ``start`` is ``None`` when only an
    upper tolerance is configured (the update is expected by ``end``). Returns
    ``None`` unless the Freshness monitor is in Prediction Model mode with a
    trained schedule and at least one observed update.
    """
    if (
        freshness_definition is None
        or freshness_definition.history_calculation != "PREDICT"
        or (freshness_definition.prediction and not freshness_definition.prediction.get("schedule_stage"))
        or freshness_definition.upper_tolerance is None
        or last_detection_time is None
    ):
        return None

    tz = cron_tz or "UTC"
    exclude_weekends = test_suite.predict_exclude_weekends
    holiday_dates = resolve_suite_holiday_dates(test_suite)
    sched = get_schedule_params(freshness_definition.prediction)

    window_end = add_business_minutes(
        pd.Timestamp(last_detection_time),
        float(freshness_definition.upper_tolerance),
        exclude_weekends,
        holiday_dates, tz,
        excluded_days=sched.excluded_days,
    )
    window_start = None
    if lower_minutes := (float(freshness_definition.lower_tolerance) if freshness_definition.lower_tolerance else None):
        window_start = add_business_minutes(
            pd.Timestamp(last_detection_time),
            lower_minutes,
            exclude_weekends,
            holiday_dates, tz,
            excluded_days=sched.excluded_days,
        )

    return {
        "start": int(window_start.timestamp() * 1000) if window_start else None,
        "end": int(window_end.timestamp() * 1000),
    }


def gated_forecast_prediction(
    definition: MonitorDefinition,
    freshness_window: dict | None,
    last_run_time: datetime | None,
) -> dict | None:
    """Coupled forecast band for a Volume/Metric monitor whose value holds at its
    baseline between refreshes.

    A flat baseline line from the latest run up to the predicted next-update
    window, then a step to the forecast's next-refresh value with the band
    opening to its tolerance. The anchor is never earlier than the latest run, so
    the forecast extends forward rather than back over history. Returns ``None``
    when there is no usable forward window — no predicted window, the window has
    already elapsed, or no stored baseline — keyed as ``lower_tolerance`` /
    ``upper_tolerance`` (no sensitivity suffix); read with ``forecast_band_points``.
    """
    baseline = definition.prediction.get("baseline_value") if definition.prediction else None
    now_ms = int(pd.Timestamp(last_run_time).timestamp() * 1000) if last_run_time is not None else None
    if freshness_window is None or now_ms is None or baseline is None:
        return None
    window_end = freshness_window.get("end")
    if window_end is None or window_end <= now_ms:
        return None

    forecast_means = (definition.prediction.get("mean") if definition.prediction else None) or {}
    next_refresh_mean = forecast_means[min(forecast_means, key=lambda k: int(k))] if forecast_means else baseline
    flat_anchor = max(freshness_window.get("start") or now_ms, now_ms)
    # lower/upper_tolerance are VARCHAR columns — coerce to float so the band dicts are numerically
    # typed throughout (baseline is already a float).
    lower_tol = float(definition.lower_tolerance) if definition.lower_tolerance is not None else None
    upper_tol = float(definition.upper_tolerance) if definition.upper_tolerance is not None else None
    return {
        "method": "predict",
        "mean": {flat_anchor: baseline, window_end: next_refresh_mean},
        "lower_tolerance": {flat_anchor: baseline, window_end: lower_tol},
        "upper_tolerance": {flat_anchor: baseline, window_end: upper_tol},
    }


def forecast_band_points(prediction: dict | None) -> list[MonitorForecastPoint]:
    """Convert a forecast band dict with plain ``lower_tolerance`` / ``upper_tolerance``
    epoch-ms series (as built by ``gated_forecast_prediction``) into time-ordered
    forecast points. For the raw per-sensitivity prediction JSONB use
    ``forecast_points_from_prediction`` instead."""
    if not prediction:
        return []
    lower_series = prediction.get("lower_tolerance") or {}
    upper_series = prediction.get("upper_tolerance") or {}
    keys = sorted(set(lower_series) | set(upper_series), key=lambda k: int(k))
    points: list[MonitorForecastPoint] = []
    for k in keys:
        ts = datetime.fromtimestamp(int(k) / 1000.0, UTC)
        lower = lower_series.get(k)
        upper = upper_series.get(k)
        points.append(MonitorForecastPoint(
            test_time=ts,
            lower_bound=float(lower) if lower is not None else None,
            upper_bound=float(upper) if upper is not None else None,
        ))
    return points
