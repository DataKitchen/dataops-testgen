"""Tests for testgen.common.models.monitor parsers and façade."""

import dataclasses
import re
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.models.monitor import (
    Monitor,
    MonitorSeries,
    build_series_sql,
    current_bands,
    parse_freshness_event,
    parse_freshness_message,
    parse_schema_event,
    parse_value_event,
)
from testgen.common.models.table_group import MonitorTableSummary, TableGroup
from testgen.common.models.test_definition import ThresholdMode, derive_threshold_mode

pytestmark = pytest.mark.unit


def test_monitor_table_summary_has_monitor_id_fields():
    fields = {f.name for f in dataclasses.fields(MonitorTableSummary)}
    assert {"freshness_monitor_id", "volume_monitor_id", "schema_monitor_id", "metric_monitors"} <= fields

NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)

MON_MODULE = "testgen.common.models.monitor"


def _monitor(**overrides) -> Monitor:
    base = {
        "monitor_id": uuid4(),
        "test_type": "Volume_Trend",
        "table_group_id": uuid4(),
        "table_name": "orders",
        "column_name": None,
        "history_calculation": "PREDICT",
        "history_calculation_upper": None,
        "project_code": "demo",
        "test_suite_id": uuid4(),
        "monitor_lookback": 14,
        "predict_sensitivity": "medium",
        "prediction": {"mean": {"1": 100.0}, "lower_tolerance|medium": {"1": 80.0}, "upper_tolerance|medium": {"1": 120.0}},
        "lower_tolerance": None,
        "upper_tolerance": None,
        "threshold_value": None,
    }
    base.update(overrides)
    return Monitor(**base)


@patch(f"{MON_MODULE}.get_current_session")
def test_get_returns_none_for_non_monitor(mock_session):
    mock_session.return_value.execute.return_value.mappings.return_value.first.return_value = None
    assert Monitor.get(uuid4()) is None


@patch(f"{MON_MODULE}.get_current_session")
def test_series_volume_builds_points_and_bands(mock_session):
    rows = [
        {"test_time": NOW, "result_id": 1, "result_code": 1, "result_status": "Passed",
         "result_signal": "100", "result_message": "", "input_parameters": "lower_tolerance=80; upper_tolerance=120",
         "column_names": None},
    ]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    series = _monitor(test_type="Volume_Trend").series()
    assert isinstance(series, MonitorSeries)
    assert series.type == "Volume_Trend"
    assert series.threshold_mode == ThresholdMode.PREDICTION
    assert len(series.points) == 1
    assert series.points[0]["value"] == 100.0
    assert series.bands == {"lower_bound": 80.0, "upper_bound": 120.0}


@patch(f"{MON_MODULE}.get_current_session")
def test_series_schema_has_no_bands(mock_session):
    rows = [{"test_time": NOW, "result_id": 1, "result_code": 0, "result_status": "Failed",
             "result_signal": "A|1|0|0|", "result_message": "", "input_parameters": "", "column_names": None}]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    series = _monitor(test_type="Schema_Drift", history_calculation=None).series()
    assert series.bands is None
    assert series.points[0]["table_change"] == "A"


@patch(f"{MON_MODULE}.get_current_session")
def test_series_training_monitor_has_null_bands(mock_session):
    rows = [{"test_time": NOW, "result_id": 1, "result_code": -1, "result_status": "Log",
             "result_signal": None, "result_message": "", "input_parameters": "", "column_names": None}]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    series = _monitor(test_type="Volume_Trend").series()
    assert series.is_training is True
    assert series.bands is None


@patch(f"{MON_MODULE}.get_current_session")
def test_series_is_training_reflects_latest_point_only(mock_session):
    # Oldest→newest: an early training run (-1) followed by a predicting run (1).
    # is_training must key off the latest point, not any() over the window.
    rows = [
        {"test_time": NOW, "result_id": 1, "result_code": -1, "result_status": "Log",
         "result_signal": None, "result_message": "", "input_parameters": "", "column_names": None},
        {"test_time": NOW, "result_id": 2, "result_code": 1, "result_status": "Passed",
         "result_signal": "100", "result_message": "", "input_parameters": "lower_tolerance=80; upper_tolerance=120",
         "column_names": None},
    ]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    series = _monitor(test_type="Volume_Trend").series()
    assert series.is_training is False
    # Bands must not be suppressed once the monitor is predicting.
    assert series.bands == {"lower_bound": 80.0, "upper_bound": 120.0}


@patch(f"{MON_MODULE}.get_current_session")
def test_series_is_training_false_for_empty_series(mock_session):
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = []
    assert _monitor(test_type="Volume_Trend").series().is_training is False


@patch(f"{MON_MODULE}.get_current_session")
def test_series_freshness_unknown_signal_does_not_crash(mock_session):
    rows = [
        {"test_time": NOW, "result_id": 1, "result_code": 1, "result_status": "Passed",
         "result_signal": "Unknown", "result_message": "Table update detected: No",
         "input_parameters": "", "column_names": None},
    ]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    series = _monitor(test_type="Freshness_Trend", history_calculation=None).series()
    assert series.points[0]["minutes_since_update"] is None


def test_build_series_sql_table_scope_orders_by_starttime():
    query, _ = build_series_sql(test_suite_id=uuid4(), table_name="orders")
    assert "ORDER BY active_runs.test_starttime" in query
    assert "ORDER BY active_runs.id" not in query


def _row(**overrides) -> dict:
    base = {
        "test_time": NOW,
        "result_id": 1,
        "result_code": 1,
        "result_status": "Passed",
        "result_signal": "100",
        "result_message": "On time.",
        "input_parameters": "lower_tolerance=80; upper_tolerance=120; threshold_value=130",
        "column_names": "amount",
    }
    base.update(overrides)
    return base


def test_parse_value_event_normal():
    p = parse_value_event(_row(result_signal="100", result_code=1))
    assert p["value"] == 100.0
    assert p["lower_bound"] == 80.0
    assert p["upper_bound"] == 120.0
    assert p["threshold_value"] == 130.0
    assert p["is_anomaly"] is False
    assert p["is_training"] is False
    assert p["is_pending"] is False


def test_parse_value_event_anomaly_and_training_flags():
    assert parse_value_event(_row(result_code=0))["is_anomaly"] is True
    assert parse_value_event(_row(result_code=-1))["is_training"] is True


def test_parse_value_event_pending_when_no_result_id():
    p = parse_value_event(_row(result_id=None, result_code=None, result_signal=None))
    assert p["is_pending"] is True
    assert p["value"] is None
    assert p["is_anomaly"] is None
    assert p["is_training"] is None


def test_parse_events_surface_is_error():
    assert parse_value_event(_row(result_status="Error"))["is_error"] is True
    assert parse_value_event(_row(result_status="Passed"))["is_error"] is False
    assert parse_freshness_event(_row(result_status="Error"))["is_error"] is True
    assert parse_freshness_event(_row(result_status="Passed"))["is_error"] is False
    assert parse_schema_event(_row(result_signal="A|1|0|0|", result_status="Error"))["is_error"] is True
    assert parse_schema_event(_row(result_signal="A|1|0|0|", result_status="Failed"))["is_error"] is False


def test_parse_freshness_event_minutes_and_staleness():
    p = parse_freshness_event(_row(result_signal="240", result_code=1))
    assert p["minutes_since_update"] == 240
    assert p["staleness_threshold"] == 130.0
    assert p["lower_bound"] == 80.0
    assert p["upper_bound"] == 120.0
    assert p["update_detected"] is False


def test_parse_freshness_event_update_detected_at_zero_signal():
    p = parse_freshness_event(_row(result_signal="0"))
    assert p["minutes_since_update"] == 0
    assert p["update_detected"] is True


def test_parse_freshness_event_pending():
    p = parse_freshness_event(_row(result_id=None, result_code=None, result_signal=None))
    assert p["is_pending"] is True
    assert p["minutes_since_update"] is None
    assert p["update_detected"] is False


def test_parse_freshness_event_unknown_signal_is_none():
    # The Freshness_Trend template emits result_signal='Unknown' on the no-change branch
    # when interval_minutes is NULL. int('Unknown') must not raise.
    p = parse_freshness_event(_row(result_signal="Unknown", result_code=1))
    assert p["minutes_since_update"] is None
    assert p["update_detected"] is False


def test_parse_freshness_event_non_numeric_signal_is_none():
    # Error rows can carry an arbitrary non-numeric signal.
    p = parse_freshness_event(_row(result_signal="n/a", result_code=None, result_status="Error"))
    assert p["minutes_since_update"] is None


def test_parse_schema_event_pipe_signal():
    p = parse_schema_event(_row(result_signal="A|2|1|3|2026-06-20T00:00:00", result_code=0))
    assert p["table_change"] == "A"
    assert p["additions"] == 2
    assert p["deletions"] == 1
    assert p["modifications"] == 3
    assert p["window_start"] == datetime.fromisoformat("2026-06-20T00:00:00")


def test_parse_schema_event_empty_signal_defaults():
    p = parse_schema_event(_row(result_signal=None))
    assert p["table_change"] is None
    assert p["additions"] == 0
    assert p["deletions"] == 0
    assert p["modifications"] == 0
    assert p["window_start"] is None


def test_current_bands_predicted_uses_sensitivity_keys():
    prediction = {
        "mean": {"1750000000000": 100.0},
        "lower_tolerance|medium": {"1750000000000": 80.0},
        "upper_tolerance|medium": {"1750000000000": 120.0},
    }
    bands = current_bands("Volume_Trend", "PREDICT", prediction, "medium", None, None, None, is_training=False)
    assert bands == {"lower_bound": 80.0, "upper_bound": 120.0}


def test_current_bands_static_uses_tolerances():
    bands = current_bands("Volume_Trend", None, None, "medium", "10", "20", None, is_training=False)
    assert bands == {"lower_bound": 10.0, "upper_bound": 20.0}


def test_current_bands_none_while_training():
    assert current_bands("Volume_Trend", "PREDICT", {}, "medium", None, None, None, is_training=True) is None


def test_current_bands_freshness_shape():
    # threshold_value takes precedence over upper_tolerance for staleness_threshold
    bands = current_bands("Freshness_Trend", None, None, "medium", "60", "1440", "900", is_training=False)
    assert bands == {"staleness_threshold": 900.0, "expected_gap": {"lower_bound": 60.0, "upper_bound": 1440.0}}


def test_current_bands_freshness_falls_back_to_upper_tolerance():
    # When threshold_value is None, staleness_threshold falls back to upper_tolerance
    bands = current_bands("Freshness_Trend", None, None, "medium", "60", "1440", None, is_training=False)
    assert bands == {"staleness_threshold": 1440.0, "expected_gap": {"lower_bound": 60.0, "upper_bound": 1440.0}}


def test_current_bands_schema_is_none():
    assert current_bands("Schema_Drift", None, None, "medium", None, None, None, is_training=False) is None


@pytest.mark.parametrize(
    "test_type,history,history_upper,lower,upper,expected",
    [
        # Schema is presence-only — always N/A, no bounds.
        ("Schema_Drift", "PREDICT", None, None, None, (ThresholdMode.NONE, None, None)),
        # PREDICT flags Prediction Model; runtime bands live on each event, not config.
        ("Volume_Trend", "PREDICT", None, "10", "20", (ThresholdMode.PREDICTION, None, None)),
        # Any other non-empty history_calculation flags Historical (carries the expressions).
        ("Volume_Trend", "Minimum", "Maximum", None, None, (ThresholdMode.HISTORICAL, "Minimum", "Maximum")),
        # Historical is not available for Freshness — falls through to Static (upper only).
        ("Freshness_Trend", "Minimum", "Maximum", "60", "1440", (ThresholdMode.STATIC, None, "1440")),
        # Freshness Static uses only the upper bound.
        ("Freshness_Trend", None, None, "60", "1440", (ThresholdMode.STATIC, None, "1440")),
        # Volume / Metric Static uses both tolerances.
        ("Volume_Trend", "", None, "10", "20", (ThresholdMode.STATIC, "10", "20")),
        ("Metric_Trend", None, None, "10", "20", (ThresholdMode.STATIC, "10", "20")),
    ],
)
def test_derive_threshold_mode(test_type, history, history_upper, lower, upper, expected):
    assert derive_threshold_mode(test_type, history, history_upper, lower, upper) == expected


@patch(f"{MON_MODULE}.get_current_session")
def test_series_threshold_mode_historical(mock_session):
    rows = [{"test_time": NOW, "result_id": 1, "result_code": 1, "result_status": "Passed",
             "result_signal": "100", "result_message": "", "input_parameters": "", "column_names": None}]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    series = _monitor(
        test_type="Volume_Trend", history_calculation="Minimum", history_calculation_upper="Maximum",
    ).series()
    assert series.threshold_mode == ThresholdMode.HISTORICAL


@patch("testgen.common.models.table_group.get_current_session")
def test_table_series_groups_all_types(mock_session):
    from testgen.common.models.table_group import TableGroup

    rows = [
        {
            "test_time": NOW, "result_id": 1, "result_code": 1, "result_status": "Passed",
            "result_signal": "100", "result_message": "", "input_parameters": "", "column_names": None,
            "test_definition_id": None, "test_type": "Volume_Trend",
        },
        {
            "test_time": NOW, "result_id": 2, "result_code": 0, "result_status": "Failed",
            "result_signal": "A|1|0|0|", "result_message": "", "input_parameters": "", "column_names": None,
            "test_definition_id": None, "test_type": "Schema_Drift",
        },
    ]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    out = TableGroup.get_table_monitor_series(uuid4(), "orders")
    assert {"freshness_events", "volume_events", "schema_events", "metric_events"} == set(out)
    assert len(out["volume_events"]) == 1
    assert len(out["schema_events"]) == 1


@patch("testgen.common.models.table_group.get_current_session")
def test_table_series_metric_events_keep_frontend_tolerance_keys(mock_session):
    from testgen.common.models.table_group import TableGroup

    rows = [
        {
            "test_time": NOW, "result_id": 3, "result_code": 1, "result_status": "Passed",
            "result_signal": "50", "result_message": "",
            "input_parameters": "lower_tolerance=10; upper_tolerance=90; threshold_value=99",
            "column_names": "amount", "test_definition_id": "def-1", "test_type": "Metric_Trend",
        },
    ]
    mock_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows
    out = TableGroup.get_table_monitor_series(uuid4(), "orders")
    event = out["metric_events"][0]["events"][0]
    # The frontend chart still consumes lower_tolerance/upper_tolerance keys.
    assert event["lower_tolerance"] == 10.0
    assert event["upper_tolerance"] == 90.0


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Table update detected: Yes. On time.", (True, "On time")),
        ("Table update detected: Yes. Earlier than expected.", (True, "Earlier than expected")),
        ("Table update detected: Yes. Later than expected.", (True, "Later than expected")),
        ("Table update detected: No. Late.", (False, "Late")),
        # No timing verdict is emitted while tolerances are still NULL (training) or
        # when a missing update is not yet past its staleness threshold.
        ("Table update detected: Yes", (True, None)),
        ("Table update detected: No", (False, None)),
    ],
)
def test_parse_freshness_message_all_verdicts(message, expected):
    assert parse_freshness_message(message) == expected


@pytest.mark.parametrize("message", [None, "", "   "])
def test_parse_freshness_message_blank(message):
    assert parse_freshness_message(message) == (None, None)


def test_parse_freshness_message_unrecognized_returns_text_as_detail():
    # Error rows carry free-form text; callers still get something to surface.
    assert parse_freshness_message("Connection reset by peer") == (None, "Connection reset by peer")


def test_monitor_table_summary_has_single_run_scoped_fields():
    fields = {f.name for f in dataclasses.fields(MonitorTableSummary)}
    assert {
        "previous_run_start",
        "previous_run_row_count",
        "latest_run_schema_anomalies",
        "latest_run_column_adds",
        "latest_run_column_drops",
        "latest_run_column_mods",
        "latest_run_table_state",
        "latest_run_freshness_message",
    } <= fields


def test_monitor_changes_query_projects_every_summary_field():
    """Every ``MonitorTableSummary`` field must be projected by the query that fills it.

    The rows are splatted in as ``MonitorTableSummary(**row)``, so a field added to the
    dataclass without a matching alias silently keeps its default instead of the value
    the caller expects.
    """
    query, _params = TableGroup._monitor_changes_by_tables_query(uuid4())
    missing = [
        f.name for f in dataclasses.fields(MonitorTableSummary)
        if not re.search(rf"\b{f.name}\b", query)
    ]
    assert not missing


@pytest.mark.parametrize(
    ("sort_by", "baseline_column", "state_column"),
    [
        ("row_count_change_desc", "previous_row_count", "table_state"),
        ("latest_run_row_count_change_desc", "previous_run_row_count", "latest_run_table_state"),
    ],
)
def test_row_count_change_sorts_on_the_same_states_it_renders(sort_by, baseline_column, state_column):
    """Ordering resolves a missing count exactly as the rendered cell does: an added table
    counts from zero, a dropped one counts to zero, and any other missing endpoint leaves
    the expression NULL so the row sorts last instead of by a fabricated delta.
    """
    query, _params = TableGroup._monitor_changes_by_tables_query(uuid4(), sort_by=sort_by)
    order_by = query[query.rindex("ORDER BY"):]

    assert f"COALESCE(baseline_tables.{baseline_column}, 0)" not in order_by, (
        "a missing baseline must not collapse to zero unconditionally"
    )
    assert f"monitor_tables.{state_column} = 'added'" in order_by
    assert f"monitor_tables.{state_column} = 'dropped'" in order_by
    assert f"baseline_tables.{baseline_column}" in order_by
