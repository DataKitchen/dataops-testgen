"""Tests for testgen.api.enums presentation enums and DB maps."""

import pytest

from testgen.api.enums import (
    MONITOR_TYPE_FROM_DB,
    MONITOR_TYPE_TO_DB,
    MonitorSortField,
    MonitorThresholdMode,
    MonitorType,
    SortOrder,
    TableState,
    monitor_sort_to_model,
    threshold_mode_from_db,
)
from testgen.common.models.test_definition import ThresholdMode

pytestmark = pytest.mark.unit


def test_monitor_type_tokens_are_lowercase_snake():
    assert {m.value for m in MonitorType} == {"freshness", "volume", "schema", "metric"}


def test_monitor_type_roundtrip_covers_all_four_test_types():
    assert MONITOR_TYPE_TO_DB == {
        MonitorType.freshness: "Freshness_Trend",
        MonitorType.volume: "Volume_Trend",
        MonitorType.schema: "Schema_Drift",
        MonitorType.metric: "Metric_Trend",
    }
    assert MONITOR_TYPE_FROM_DB == {v: k for k, v in MONITOR_TYPE_TO_DB.items()}


def test_table_state_tokens():
    assert {s.value for s in TableState} == {"added", "dropped", "modified"}


def test_monitor_threshold_mode_tokens():
    assert {m.value for m in MonitorThresholdMode} == {
        "prediction_model", "historical_calculation", "static", "not_applicable",
    }


@pytest.mark.parametrize(
    "canonical_mode,expected",
    [
        (ThresholdMode.PREDICTION, MonitorThresholdMode.prediction_model),
        (ThresholdMode.HISTORICAL, MonitorThresholdMode.historical_calculation),
        (ThresholdMode.STATIC, MonitorThresholdMode.static),
        (ThresholdMode.NONE, MonitorThresholdMode.not_applicable),
    ],
)
def test_threshold_mode_from_db(canonical_mode, expected):
    assert threshold_mode_from_db(canonical_mode) == expected


def test_sort_order_tokens():
    assert {o.value for o in SortOrder} == {"asc", "desc"}


@pytest.mark.parametrize(
    "sort,order,expected",
    [
        (MonitorSortField.table_name, SortOrder.asc, "table_name"),
        (MonitorSortField.row_count, SortOrder.desc, "row_count_desc"),
        (MonitorSortField.metric_anomalies, SortOrder.desc, "metric_anomalies_desc"),
    ],
)
def test_monitor_sort_to_model(sort, order, expected):
    assert monitor_sort_to_model(sort, order) == expected


def test_monitor_sort_fields_match_dashboard_allowed_set():
    assert {f.value for f in MonitorSortField} == {
        "table_name", "freshness_anomalies", "volume_anomalies", "schema_anomalies",
        "metric_anomalies", "latest_update", "row_count",
    }
