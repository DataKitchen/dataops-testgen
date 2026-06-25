"""Tests for testgen.api.monitors — monitor reads."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.enums import MonitorSortField, SortOrder
from testgen.common.models.test_definition import ThresholdMode

pytestmark = pytest.mark.unit

DEPS = "testgen.api.deps"
MODULE = "testgen.api.monitors"
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _resolve(monitor, *, allowed=True):
    """Invoke the inner dependency of resolve_monitor with mocks."""
    from testgen.api.deps import resolve_monitor
    dep = resolve_monitor("view").dependency
    with patch(f"{DEPS}.Monitor") as mock_monitor_cls, \
         patch(f"{DEPS}.has_project_permission", return_value=allowed):
        mock_monitor_cls.get.return_value = monitor
        return dep(monitor_id=uuid4(), user=MagicMock())


def test_resolve_monitor_returns_monitor_when_permitted():
    monitor = MagicMock(project_code="demo")
    assert _resolve(monitor) is monitor


def test_resolve_monitor_404_when_missing():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _resolve(None)
    assert exc.value.status_code == 404


def test_resolve_monitor_404_when_not_permitted():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _resolve(MagicMock(project_code="demo"), allowed=False)
    assert exc.value.status_code == 404


# --- endpoint unit tests ---


def _summary_row(**overrides):
    from testgen.common.models.table_group import MonitorTableSummary
    base = {
        "table_name": "orders", "lookback": 14, "lookback_start": NOW, "lookback_end": NOW,
        "freshness_anomalies": 0, "volume_anomalies": 1, "schema_anomalies": 0, "metric_anomalies": 0,
        "freshness_is_training": False, "volume_is_training": False, "metric_is_training": True,
        "freshness_is_pending": False, "volume_is_pending": False, "schema_is_pending": False, "metric_is_pending": False,
        "freshness_error_message": None, "volume_error_message": None, "schema_error_message": None, "metric_error_message": None,
        "latest_update": NOW, "row_count": 100, "previous_row_count": 90, "column_adds": 0, "column_drops": 0, "column_mods": 0,
        "table_state": "modified",
        "freshness_monitor_id": uuid4(), "volume_monitor_id": uuid4(), "schema_monitor_id": uuid4(),
        "metric_monitors": [{"monitor_id": str(uuid4()), "column_name": "amount", "anomalies": 0,
                             "is_training": True, "is_pending": False}],
    }
    base.update(overrides)
    return MonitorTableSummary(**base)


def _group_summary(**overrides):
    from testgen.common.models.table_group import MonitorGroupSummary
    base = {
        "lookback": 14, "lookback_start": NOW, "lookback_end": NOW, "total_monitored_tables": 1,
        "freshness_anomalies": 0, "volume_anomalies": 1, "schema_anomalies": 0, "metric_anomalies": 0,
        "freshness_has_errors": False, "volume_has_errors": False, "schema_has_errors": False, "metric_has_errors": False,
        "freshness_is_training": False, "volume_is_training": False, "metric_is_training": False,
        "freshness_is_pending": False, "volume_is_pending": False, "schema_is_pending": False, "metric_is_pending": False,
    }
    base.update(overrides)
    return MonitorGroupSummary(**base)


@patch(f"{MODULE}.TableGroup")
def test_list_monitors_nests_per_type_and_totals(mock_tg):
    from testgen.api.monitors import list_table_monitors
    mock_tg.list_monitor_table_summaries.return_value = ([_summary_row()], 1)
    mock_tg.get_monitor_group_summary.return_value = _group_summary()
    tg = MagicMock(id=uuid4())

    resp = list_table_monitors(
        table_group=tg, table_name=None, anomalies_only=False,
        sort=MonitorSortField.table_name, order=SortOrder.asc, page=1, limit=20,
    )
    assert resp.total == 1
    row = resp.items[0]
    assert row.volume.anomalies == 1
    assert row.volume.monitor_id is not None
    assert row.schema_.column_adds == 0  # Python attr is schema_; JSON key is "schema"
    assert len(row.metrics) == 1 and row.metrics[0].metric_name == "amount"
    assert resp.totals.volume_anomalies == 1
    # totals must NOT leak group-level booleans
    assert not hasattr(resp.totals, "volume_has_errors")


@patch(f"{MODULE}.TableGroup")
def test_list_monitors_forwards_and_echoes_pagination(mock_tg):
    from testgen.api.monitors import list_table_monitors
    mock_tg.list_monitor_table_summaries.return_value = ([_summary_row()], 7)
    mock_tg.get_monitor_group_summary.return_value = _group_summary()

    resp = list_table_monitors(
        table_group=MagicMock(id=uuid4()), table_name=None, anomalies_only=False,
        sort=MonitorSortField.table_name, order=SortOrder.asc, page=2, limit=3,
    )
    assert resp.total == 7
    assert resp.page == 2
    assert resp.limit == 3
    kwargs = mock_tg.list_monitor_table_summaries.call_args.kwargs
    assert kwargs["page"] == 2 and kwargs["limit"] == 3


@patch(f"{MODULE}.TableGroup")
def test_anomalies_only_maps_to_all_types(mock_tg):
    from testgen.api.monitors import list_table_monitors
    mock_tg.list_monitor_table_summaries.return_value = ([], 0)
    mock_tg.get_monitor_group_summary.return_value = _group_summary(total_monitored_tables=0)
    list_table_monitors(
        table_group=MagicMock(id=uuid4()), table_name=None, anomalies_only=True,
        sort=MonitorSortField.table_name, order=SortOrder.asc, page=1, limit=20,
    )
    kwargs = mock_tg.list_monitor_table_summaries.call_args.kwargs
    assert set(kwargs["anomaly_types"]) == {"Freshness_Trend", "Volume_Trend", "Schema_Drift", "Metric_Trend"}


def test_get_series_maps_header_and_type():
    from testgen.api.monitors import get_monitor_series
    from testgen.common.models.monitor import MonitorSeries
    mid = uuid4()
    monitor = MagicMock()
    monitor.series.return_value = MonitorSeries(
        monitor_id=mid, type="Volume_Trend", threshold_mode=ThresholdMode.PREDICTION, table_name="orders",
        column_name=None, lookback=14, is_training=False, bands={"lower_bound": 1, "upper_bound": 2}, points=[],
    )
    resp = get_monitor_series(monitor=monitor)
    assert resp.monitor_id == mid
    assert resp.type.value == "volume"
    assert resp.threshold_mode.value == "prediction_model"
    assert resp.current_bands == {"lower_bound": 1, "upper_bound": 2}


# --- HTTP-level validation tests ---


def _client() -> TestClient:
    from testgen.api.monitors import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return TestClient(app)


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_http_rejects_unknown_sort(_mock_tg, _mock_perm):
    resp = _client().get(f"/api/v1/table-groups/{uuid4()}/monitors?sort=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "sort"]


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_http_rejects_unknown_order(_mock_tg, _mock_perm):
    resp = _client().get(f"/api/v1/table-groups/{uuid4()}/monitors?order=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "order"]


@pytest.mark.parametrize("query", ["page=0", "limit=0", "limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_http_rejects_out_of_range_pagination(_mock_tg, _mock_perm, query):
    resp = _client().get(f"/api/v1/table-groups/{uuid4()}/monitors?{query}")
    assert resp.status_code == 422
