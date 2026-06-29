"""Tests for the MCP monitor tools — read (``get_monitor_summary`` / ``list_monitored_tables`` /
``list_monitor_events`` / ``list_monitors`` / ``list_monitor_schema_changes``) and
lifecycle/settings (``enable_monitors`` / ``get_monitor_settings`` / ``update_monitor_settings``
/ ``disable_monitors``)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.data_structure_log import DataStructureLog
from testgen.common.models.table_group import MonitorGroupSummary, MonitorTableSummary
from testgen.common.models.test_suite import PredictSensitivity
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.monitors"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _patch_perms(allowed=("demo",), memberships=None, permission="view"):
    memberships = memberships or dict.fromkeys(allowed, "role_a")
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships=memberships, permission=permission, username="test_user",
        ),
    )


def _mock_table_group(**overrides) -> MagicMock:
    tg = MagicMock()
    tg.id = overrides.get("id", uuid4())
    tg.project_code = overrides.get("project_code", "demo")
    tg.table_groups_name = overrides.get("table_groups_name", "Sales")
    tg.monitor_test_suite_id = overrides.get("monitor_test_suite_id", uuid4())
    return tg


def _mock_monitor_suite(**overrides) -> MagicMock:
    from testgen.common.models.test_suite import PredictSensitivity

    suite = MagicMock()
    suite.id = overrides.get("id", uuid4())
    suite.is_monitor = True
    suite.monitor_lookback = overrides.get("monitor_lookback", 7)
    suite.predict_sensitivity = overrides.get("predict_sensitivity", PredictSensitivity.medium)
    return suite


def _group_summary(**overrides) -> MonitorGroupSummary:
    defaults: dict = {
        "lookback": 7,
        "lookback_start": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "lookback_end": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        "total_monitored_tables": 12,
        "freshness_anomalies": 2,
        "volume_anomalies": 0,
        "schema_anomalies": 1,
        "metric_anomalies": 0,
        "freshness_has_errors": False,
        "volume_has_errors": False,
        "schema_has_errors": False,
        "metric_has_errors": False,
        "freshness_is_training": False,
        "volume_is_training": False,
        "metric_is_training": True,
        "freshness_is_pending": False,
        "volume_is_pending": False,
        "schema_is_pending": False,
        "metric_is_pending": False,
    }
    defaults.update(overrides)
    return MonitorGroupSummary(**defaults)


def _table_summary(**overrides) -> MonitorTableSummary:
    defaults: dict = {
        "table_name": "orders",
        "lookback": 7,
        "lookback_start": datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        "lookback_end": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        "freshness_anomalies": 2,
        "volume_anomalies": 0,
        "schema_anomalies": 0,
        "metric_anomalies": 0,
        "freshness_is_training": False,
        "volume_is_training": False,
        "metric_is_training": None,
        "freshness_is_pending": False,
        "volume_is_pending": False,
        "schema_is_pending": False,
        "metric_is_pending": True,
        "freshness_error_message": None,
        "volume_error_message": None,
        "schema_error_message": None,
        "metric_error_message": None,
        "latest_update": datetime(2026, 6, 1, 8, 30, tzinfo=UTC),
        "row_count": 1_234_567,
        "previous_row_count": 1_200_000,
        "column_adds": 0,
        "column_drops": 0,
        "column_mods": 0,
        "table_state": None,
    }
    defaults.update(overrides)
    return MonitorTableSummary(**defaults)


# ---------------------------------------------------------------------------
# get_monitor_summary
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.next_scheduled_run", return_value=None)
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_summary_happy_path(mock_resolve, mock_tg_cls, mock_next, db_session_mock):
    tg = _mock_table_group()
    suite = _mock_monitor_suite()
    mock_resolve.return_value = (tg, suite)
    mock_tg_cls.get_monitor_group_summary.return_value = _group_summary()

    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms():
        out = get_monitor_summary(str(tg.id))

    assert "# Monitor summary for `Sales`" in out
    assert "**Project:** `demo`" in out
    assert "**Monitored tables:** 12" in out
    assert "**Lookback:** 7 runs" in out
    assert "(override)" not in out
    assert "**Next scheduled run:** not scheduled" in out
    # Per-type rows
    assert "| Freshness | 2 | Ok |" in out
    assert "| Volume | 0 | Ok |" in out
    assert "| Schema | 1 | Ok |" in out
    assert "| Metric | 0 | Training |" in out


@patch(f"{MODULE}.next_scheduled_run", return_value=datetime(2026, 6, 2, 18, 0, tzinfo=UTC))
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_summary_renders_next_scheduled(mock_resolve, mock_tg_cls, mock_next, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.get_monitor_group_summary.return_value = _group_summary()

    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms():
        out = get_monitor_summary(str(tg.id))

    assert "Next scheduled run" in out
    assert "2026-06-02" in out


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_summary_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms():
        out = get_monitor_summary(str(tg.id))

    assert out == "This table group is not monitored."


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_summary_inaccessible(mock_resolve, db_session_mock):
    bad_id = str(uuid4())
    mock_resolve.side_effect = MCPResourceNotAccessible("Table group", bad_id)

    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible):
        get_monitor_summary(bad_id)


@patch(f"{MODULE}.next_scheduled_run", return_value=None)
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_summary_lookback_override_applied(mock_resolve, mock_tg_cls, mock_next, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.get_monitor_group_summary.return_value = _group_summary(lookback=14)

    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms():
        out = get_monitor_summary(str(tg.id), lookback=14)

    mock_tg_cls.get_monitor_group_summary.assert_called_once_with(tg.id, lookback_override=14)
    assert "**Lookback:** 14 runs (override)" in out


@pytest.mark.parametrize("bad_lookback", [0, 366, 500, -1])
def test_get_monitor_summary_lookback_out_of_range(bad_lookback, db_session_mock):
    """Both bounds (and beyond) are pinned — the model accepts 1..365 inclusive."""
    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        get_monitor_summary(str(uuid4()), lookback=bad_lookback)
    assert "between 1 and 365" in str(exc.value)
    assert f"`{bad_lookback}`" in str(exc.value)


@patch(f"{MODULE}.next_scheduled_run", return_value=None)
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_summary_empty_state_lookback_zero(
    mock_resolve, mock_tg_cls, mock_next, db_session_mock,
):
    """When a monitor suite is configured but no runs have happened yet, the model
    method returns ``lookback=0`` (preserves the pre-refactor signal the dashboard
    uses to render "No monitor runs yet"). The MCP output reflects the empty state
    rather than fabricating a one-run window."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.get_monitor_group_summary.return_value = _group_summary(
        lookback=0,
        lookback_start=None,
        lookback_end=None,
        total_monitored_tables=0,
        freshness_anomalies=0, volume_anomalies=0,
        schema_anomalies=0, metric_anomalies=0,
        freshness_is_pending=True, volume_is_pending=True,
        schema_is_pending=True, metric_is_pending=True,
        freshness_is_training=False, volume_is_training=False,
        metric_is_training=False,
    )

    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms():
        out = get_monitor_summary(str(tg.id))

    assert "**Lookback:** 0 runs" in out, "must show 0, not a fabricated default like 1"
    # Window start / end fields are absent in the empty case (None values render as em-dash
    # at most, but the tool omits them when the value is falsy)
    assert "**Window start:**" not in out
    assert "**Window end:**" not in out
    # All per-type status cells reflect "no results"
    assert out.count("No results yet or not configured") == 4


@patch(f"{MODULE}.next_scheduled_run", return_value=None)
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_summary_renders_error_and_pending_states(
    mock_resolve, mock_tg_cls, mock_next, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.get_monitor_group_summary.return_value = _group_summary(
        freshness_has_errors=True,
        volume_is_pending=True,
        schema_is_pending=True,
        metric_is_pending=True,
    )

    from testgen.mcp.tools.monitors import get_monitor_summary

    with _patch_perms():
        out = get_monitor_summary(str(tg.id))

    assert "| Freshness | 2 | Error |" in out
    assert "| Volume | 0 | No results yet or not configured |" in out
    assert "| Schema | 1 | No results yet or not configured |" in out
    assert "| Metric | 0 | No results yet or not configured |" in out


# ---------------------------------------------------------------------------
# list_monitored_tables
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_happy_path(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = (
        [
            _table_summary(table_name="orders", freshness_anomalies=2),
            _table_summary(table_name="customers", freshness_anomalies=0, row_count=42_000),
        ],
        2,
    )

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        out = list_monitored_tables(str(tg.id))

    assert "# Monitored tables in `Sales`" in out
    assert "Showing 1–2 of 2" in out  # noqa: RUF001 — page-info formatter uses EN DASH
    assert "`orders`" in out
    assert "`customers`" in out
    # "Row count change" column renders the signed delta (row_count - previous_row_count),
    # not the raw current count. Defaults are row_count=1_234_567, previous=1_200_000.
    assert "+34,567" in out
    # customers overrides row_count to 42_000 — delta vs default previous of 1_200_000 is -1,158,000.
    assert "-1,158,000" in out
    # Absolute current count should not appear in the column.
    assert "1,234,567" not in out
    # Default sort_by is None → table_name asc
    mock_tg_cls.list_monitor_table_summaries.assert_called_once_with(
        tg.id, anomaly_types=None, sort_by=None, page=1, limit=20,
    )


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_anomaly_type_filter_translated(
    mock_resolve, mock_tg_cls, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = ([], 0)

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        list_monitored_tables(str(tg.id), anomaly_type="freshness")

    mock_tg_cls.list_monitor_table_summaries.assert_called_once_with(
        tg.id, anomaly_types=["Freshness_Trend"], sort_by=None, page=1, limit=20,
    )


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_sort_by_translated(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = ([], 0)

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        list_monitored_tables(str(tg.id), sort_by="anomaly_count_desc")

    mock_tg_cls.list_monitor_table_summaries.assert_called_once_with(
        tg.id, anomaly_types=None, sort_by="total_anomalies_desc", page=1, limit=20,
    )


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        out = list_monitored_tables(str(tg.id))

    assert out == "This table group is not monitored."


def test_list_monitored_tables_invalid_anomaly_type(db_session_mock):
    """Error message must reference the caller's public arg name (``anomaly_type``)
    rather than the helper's internal arg name (``monitor_type``)."""
    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        list_monitored_tables(str(uuid4()), anomaly_type="bogus")
    msg = str(exc.value)
    assert "Invalid anomaly_type" in msg
    assert "Invalid monitor_type" not in msg


def test_list_monitored_tables_invalid_sort_by(db_session_mock):
    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        list_monitored_tables(str(uuid4()), sort_by="wat")
    assert "Invalid sort_by" in str(exc.value)


def test_list_monitored_tables_invalid_page(db_session_mock):
    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms(), pytest.raises(MCPUserError):
        list_monitored_tables(str(uuid4()), page=0)


def test_list_monitored_tables_limit_out_of_range(db_session_mock):
    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms(), pytest.raises(MCPUserError):
        list_monitored_tables(str(uuid4()), limit=500)


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_schema_change_column(
    mock_resolve, mock_tg_cls, db_session_mock,
):
    """The Schema column shows just the anomaly count; the new Schema change column
    renders the verbose description (added with N columns / modified breakdown /
    dropped with N columns)."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = (
        [
            _table_summary(
                table_name="t_mod", schema_anomalies=2, table_state="modified",
                column_adds=1, column_drops=2, column_mods=0,
            ),
            _table_summary(
                table_name="t_add", schema_anomalies=1, table_state="added",
                column_adds=5, column_drops=0, column_mods=0,
            ),
            _table_summary(
                table_name="t_drop", schema_anomalies=1, table_state="dropped",
                column_adds=0, column_drops=10, column_mods=0,
            ),
            _table_summary(table_name="t_quiet", schema_anomalies=0, table_state=None),
        ],
        4,
    )

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        out = list_monitored_tables(str(tg.id))

    # New column appears in the header
    assert "Schema change" in out
    # Verbose strings appear in their respective rows
    assert "Table added with 5 columns." in out
    assert "Table dropped with 10 columns." in out
    assert "1 column added. 2 columns dropped." in out
    # No more parenthetical states on the Schema column
    assert "(columns)" not in out
    assert "(added)" not in out
    assert "(dropped)" not in out
    # Quiet row's Schema column is the raw count, Schema change is em-dash
    quiet_row = next(line for line in out.splitlines() if "`t_quiet`" in line)
    assert quiet_row.count(" 0 ") >= 1  # Schema = 0 for quiet


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_training_and_pending_cells(
    mock_resolve, mock_tg_cls, db_session_mock,
):
    """Status words render when the per-type count is zero."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = (
        [
            _table_summary(
                table_name="t1",
                freshness_anomalies=0, freshness_is_training=True,
                volume_anomalies=0, volume_is_pending=True,
                metric_anomalies=0, metric_error_message="boom",
            ),
        ],
        1,
    )

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        out = list_monitored_tables(str(tg.id))

    row = next(line for line in out.splitlines() if "`t1`" in line)
    assert "Training" in row
    assert "Pending" in row
    assert "Error" in row


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_count_wins_over_training_and_pending(
    mock_resolve, mock_tg_cls, db_session_mock,
):
    """A positive anomaly count must surface even when the monitor is in training
    or pending state — otherwise the cell hides the value that made the row match
    an ``anomaly_type`` filter, and the table doesn't agree with itself.

    Precedence is error > positive count > pending > training > zero. Errors still
    win (the latest measurement is suspect, so the historic count is misleading).
    """
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = (
        [
            _table_summary(
                table_name="t_busy_during_learn",
                freshness_anomalies=5, freshness_is_training=True,
                volume_anomalies=3, volume_is_pending=True,
                metric_anomalies=2, metric_is_training=True,
            ),
            _table_summary(
                table_name="t_error_with_count",
                freshness_anomalies=4, freshness_error_message="db down",
            ),
        ],
        2,
    )

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        out = list_monitored_tables(str(tg.id))

    # Row 1: counts visible despite training/pending
    row_count = next(line for line in out.splitlines() if "`t_busy_during_learn`" in line)
    assert " 5 " in row_count, "freshness count should render despite is_training"
    assert " 3 " in row_count, "volume count should render despite is_pending"
    assert " 2 " in row_count, "metric count should render despite is_training"
    assert "Training" not in row_count
    assert "Pending" not in row_count
    # Row 2: error still wins over count
    row_error = next(line for line in out.splitlines() if "`t_error_with_count`" in line)
    assert "Error" in row_error
    assert " 4 " not in row_error, "error must win over count (measurement is suspect)"


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_empty(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = ([], 0)

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        out = list_monitored_tables(str(tg.id))

    assert "_No monitored tables match this filter._" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitored_tables_empty_beyond_last_page(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tg_cls.list_monitor_table_summaries.return_value = ([], 7)

    from testgen.mcp.tools.monitors import list_monitored_tables

    with _patch_perms():
        out = list_monitored_tables(str(tg.id), page=99)

    assert "No tables on page 99 (total: 7)." in out


# ---------------------------------------------------------------------------
# Lifecycle & settings helpers
# ---------------------------------------------------------------------------


def _mock_schedule(**overrides) -> MagicMock:
    sched = MagicMock()
    sched.id = overrides.get("id", uuid4())
    sched.cron_expr = overrides.get("cron_expr", "0 6 * * *")
    sched.cron_tz = overrides.get("cron_tz", "UTC")
    sched.active = overrides.get("active", True)
    sched.get_sample_triggering_timestamps.return_value = [
        overrides.get("next_run", datetime(2026, 6, 10, 6, 0, tzinfo=UTC))
    ]
    return sched


def _settings_suite(**overrides) -> MagicMock:
    suite = _mock_monitor_suite(**overrides)
    suite.predict_sensitivity = overrides.get("predict_sensitivity", PredictSensitivity.medium)
    suite.monitor_lookback = overrides.get("monitor_lookback", 14)
    suite.predict_min_lookback = overrides.get("predict_min_lookback", 30)
    suite.predict_exclude_weekends = overrides.get("predict_exclude_weekends", False)
    suite.monitor_regenerate_freshness = overrides.get("monitor_regenerate_freshness", True)
    suite.holiday_codes_list = overrides.get("holiday_codes_list", None)
    return suite


# ---------------------------------------------------------------------------
# enable_monitors
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.enable_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_enable_monitors_happy_path(mock_resolve, mock_enable, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)
    mock_enable.return_value = (MagicMock(), 4)

    from testgen.mcp.tools.monitors import enable_monitors

    with _patch_perms(permission="edit"):
        out = enable_monitors(str(tg.id), "0 6 * * *", "America/New_York")

    assert "# Monitoring enabled for `Sales`" in out
    assert "**Initial monitors created:** 4" in out
    assert "**Cron expression:** `0 6 * * *`" in out
    assert "America/New_York" in out
    mock_enable.assert_called_once_with(tg, "0 6 * * *", "America/New_York")


@patch(f"{MODULE}.enable_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_enable_monitors_already_enabled(mock_resolve, mock_enable, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())

    from testgen.mcp.tools.monitors import enable_monitors

    with _patch_perms(permission="edit"), pytest.raises(MCPUserError, match="already enabled"):
        enable_monitors(str(tg.id), "0 6 * * *")

    mock_enable.assert_not_called()


@patch(f"{MODULE}.enable_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_enable_monitors_invalid_cron_rejected_before_side_effects(mock_resolve, mock_enable, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import enable_monitors

    with _patch_perms(permission="edit"), pytest.raises(MCPUserError):
        enable_monitors(str(tg.id), "not a cron")

    mock_enable.assert_not_called()


# ---------------------------------------------------------------------------
# get_monitor_settings
# ---------------------------------------------------------------------------


@patch(f"{MODULE}._last_monitor_run", return_value=None)
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_settings_happy_path(mock_resolve, mock_js, mock_last, db_session_mock):
    tg = _mock_table_group()
    suite = _settings_suite(
        predict_sensitivity=PredictSensitivity.high, monitor_lookback=50, holiday_codes_list=["US", "NYSE"]
    )
    mock_resolve.return_value = (tg, suite)
    mock_js.get_for_monitor_suite.return_value = _mock_schedule(cron_expr="0 */12 * * *", cron_tz="UTC", active=True)

    from testgen.mcp.tools.monitors import get_monitor_settings

    with _patch_perms():
        out = get_monitor_settings(str(tg.id))

    assert "# Monitor settings for `Sales`" in out
    assert "**Sensitivity:** high" in out
    assert "**Lookback runs:** 50" in out
    assert "**Holiday codes:** US, NYSE" in out
    assert "**Regenerate freshness:** Yes" in out
    assert "## Schedule" in out
    assert "**Cron expression:** `0 */12 * * *`" in out
    assert "**Status:** Active" in out
    assert "Next run" in out


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_get_monitor_settings_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import get_monitor_settings

    with _patch_perms():
        out = get_monitor_settings(str(tg.id))
# list_monitor_events (TG-1092)
# ---------------------------------------------------------------------------


def _monitor_event(test_type="Volume_Trend", **overrides):
    from testgen.common.models.test_result import MonitorEvent

    defaults: dict = {
        "monitor_id": uuid4(),
        "test_type": test_type,
        "test_time": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        "is_anomaly": False,
        "is_training": False,
        "is_pending": False,
        "is_error": False,
        "message": None,
        "signal": "1000",
        "lower_bound": "900",
        "upper_bound": "1100",
        "schema_change_kind": None,
        "column_adds": None,
        "column_drops": None,
        "column_mods": None,
        "metric_name": None,
    }
    defaults.update(overrides)
    return MonitorEvent(**defaults)


@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_happy_volume(mock_resolve, mock_tr_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = (
        [
            _monitor_event(signal="1000", is_anomaly=True),
            _monitor_event(signal="800", is_training=True),
        ],
        2,
    )

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "volume")

    assert "Monitor events: `orders` — `volume` in `Sales`" in out
    assert "| Time | Status | Row count | Lower bound | Upper bound |" in out
    assert "Anomaly" in out
    assert "Training" in out
    # Volume rendering must not pull in Metric's name header
    assert "Metric name" not in out
    mock_tr_cls.list_monitor_events_for_table.assert_called_once_with(
        mock_resolve.return_value[1].id,
        "orders",
        monitor_type="Volume_Trend",
        page=1,
        limit=20,
    )


@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_freshness_parses_message_into_columns(
    mock_resolve, mock_tr_cls, db_session_mock,
):
    """Freshness events carry a structured message from the SQL template:
    ``"Table update detected: {Yes|No}[. {Detail}]"``. Render it as two
    distinct columns so the LLM consumer doesn't have to re-parse the text."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = (
        [
            _monitor_event(test_type="Freshness_Trend", message="Table update detected: Yes. On time."),
            _monitor_event(test_type="Freshness_Trend", message="Table update detected: No. Late.", is_anomaly=True),
            _monitor_event(test_type="Freshness_Trend", message="Table update detected: Yes. Later than expected.", is_anomaly=True),
            _monitor_event(test_type="Freshness_Trend", message="Table update detected: No"),
        ],
        4,
    )

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "freshness")

    assert "| Time | Status | Update detected | Detail |" in out
    # Freshness rendering should not surface raw bound columns (they map to
    # the static-mode upper_tolerance, which is configuration, not per-event data).
    assert "Lower bound" not in out
    assert "Row count" not in out
    # Each row's structured fields land in their own columns.
    assert "| Yes | On time |" in out
    assert "| No | Late |" in out
    assert "| Yes | Later than expected |" in out
    # Missing detail renders as em-dash.
    assert "| No | — |" in out


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_metric_renders_name_in_heading(
    mock_resolve, mock_tr_cls, mock_td_cls, db_session_mock,
):
    """For Metric monitors the metric name belongs in the heading (one metric
    per call — see the ``monitor_id`` requirement). The data table itself
    only carries Time / Status / Value / bounds."""
    monitor_id = str(uuid4())
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_metric_monitor_events.return_value = (
        [_monitor_event(test_type="Metric_Trend", metric_name="total_amount")],
        1,
    )
    # Scoped lookup returns the metric's summary (select_where, not the bare get).
    mock_td_cls.select_where.return_value = [
        SimpleNamespace(test_type="Metric_Trend", column_name="total_amount"),
    ]

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "metric", monitor_id=monitor_id)

    assert "Monitor events: Metric `total_amount` on `orders` in `Sales`" in out
    assert "| Time | Status | Value | Lower bound | Upper bound |" in out
    # metric_name lives in the heading, not as a column
    assert "Metric name" not in out


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_metric_requires_monitor_id(mock_resolve, db_session_mock):
    """Metric is the only multi-instance monitor type — without ``monitor_id``
    the query would interleave every metric on the table."""
    from testgen.mcp.exceptions import MCPUserError
    from testgen.mcp.tools.monitors import list_monitor_events

    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())

    with _patch_perms(), pytest.raises(MCPUserError, match="monitor_id.*required.*metric"):
        list_monitor_events(str(tg.id), "orders", "metric")


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_monitor_id_rejected_for_non_metric(mock_resolve, db_session_mock):
    """Singleton monitor types (freshness/volume/schema) are uniquely
    identified by table + type; ``monitor_id`` is meaningless for them and
    must be rejected so the caller gets a clear discovery path."""
    from testgen.mcp.exceptions import MCPUserError
    from testgen.mcp.tools.monitors import list_monitor_events

    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())

    with _patch_perms(), pytest.raises(MCPUserError, match="monitor_id.*only applies.*metric"):
        list_monitor_events(str(tg.id), "orders", "volume", monitor_id=str(uuid4()))


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_metric_invalid_monitor_id(mock_resolve, db_session_mock):
    """A malformed ``monitor_id`` is rejected with a clean MCPUserError before
    it reaches the query — not surfaced as a raw Postgres UUID-cast error."""
    from testgen.mcp.tools.monitors import list_monitor_events

    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid monitor_id"):
        list_monitor_events(str(tg.id), "orders", "metric", monitor_id="not-a-uuid")


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_metric_monitor_id_scoped_and_not_found(
    mock_resolve, mock_tr_cls, mock_td_cls, db_session_mock,
):
    """The metric lookup is scoped to this suite + table + Metric_Trend, so a
    ``monitor_id`` that doesn't resolve within scope (wrong table, wrong suite,
    or not a metric) yields a discovery-hint error rather than another table's
    events under this table's heading."""
    from testgen.mcp.tools.monitors import list_monitor_events

    tg = _mock_table_group()
    suite = _mock_monitor_suite()
    mock_resolve.return_value = (tg, suite)
    mock_td_cls.select_where.return_value = []  # no metric matches the scoped clauses

    with _patch_perms(), pytest.raises(MCPUserError, match=r"No metric monitor.*list_monitors"):
        list_monitor_events(str(tg.id), "orders", "metric", monitor_id=str(uuid4()))

    # The events query never runs when the scoped definition lookup fails.
    mock_tr_cls.list_metric_monitor_events.assert_not_called()
    # Lookup was scoped (id + suite + table + type clauses), not a bare PK fetch.
    assert len(mock_td_cls.select_where.call_args[0]) == 4


@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_schema_uses_dedicated_columns(mock_resolve, mock_tr_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = (
        [
            _monitor_event(
                test_type="Schema_Drift",
                signal="A|3|1|0|2026-05-01T00:00:00",
                schema_change_kind="A",
                column_adds=3, column_drops=1, column_mods=0,
                is_anomaly=True,
            ),
        ],
        1,
    )

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "schema")

    assert "| Time | Status | Table change | Columns added | Columns dropped | Columns modified |" in out
    assert "added" in out
    # Internal codes never leak
    assert "Schema_Drift" not in out
    assert "| A |" not in out


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_forecast_renders_separate_section(
    mock_resolve, mock_tr_cls, mock_td_cls, db_session_mock,
):
    """``include_predictions=True`` against a Prediction-Model monitor appends
    a ``## Forecast`` section listing forecast points (future timestamps with
    predicted bounds). Predictions never bleed into the historical events
    table — the LLM consumer can distinguish observed from predicted at a
    glance."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = (
        [_monitor_event()],
        1,
    )
    # Build a prediction JSONB the helper will read at render time. Keys are
    # epoch-ms strings — same format the dashboard uses.
    def _epoch_ms(ts):
        return str(int(ts.timestamp() * 1000))

    forecast_t1 = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
    forecast_t2 = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    monitor_def = MagicMock()
    monitor_def.history_calculation = "PREDICT"
    monitor_def.prediction = {
        "lower_tolerance|medium": {_epoch_ms(forecast_t1): 500.4, _epoch_ms(forecast_t2): 500.3},
        "upper_tolerance|medium": {_epoch_ms(forecast_t1): 503.6, _epoch_ms(forecast_t2): 503.7},
    }
    mock_td_cls.get_singleton_monitor.return_value = monitor_def

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "volume", include_predictions=True)

    # Forecast section is separate from the historical table
    assert "## Forecast" in out
    assert "**Sensitivity:** medium" in out
    assert "| Time | Predicted lower | Predicted upper |" in out
    assert "500.4" in out and "503.6" in out
    # Singleton lookup ran for the non-metric forecast path
    mock_td_cls.get_singleton_monitor.assert_called_once()


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_predictions_unavailable_note(
    mock_resolve, mock_tr_cls, mock_td_cls, db_session_mock,
):
    """include_predictions=True against a non-Prediction-Model monitor surfaces
    a note under the forecast heading explaining why no forecast follows. The
    historical events table itself stays clean."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = ([_monitor_event()], 1)
    monitor_def = MagicMock()
    monitor_def.history_calculation = None  # Static or Historical, not Prediction
    mock_td_cls.get_singleton_monitor.return_value = monitor_def

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "volume", include_predictions=True)

    assert "## Forecast" in out
    assert "Predictions not available" in out
    assert "Static or Historical Calculation" in out


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_predictions_not_applicable_for_schema(
    mock_resolve, mock_tr_cls, mock_td_cls, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = (
        [_monitor_event(test_type="Schema_Drift", schema_change_kind="M", column_mods=1)],
        1,
    )

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "schema", include_predictions=True)

    assert "## Forecast" in out
    assert "Predictions not applicable to Schema monitors" in out
    # Schema short-circuits before any TestDefinition lookup — predictions
    # never apply, so don't waste a DB round-trip.
    mock_td_cls.get_singleton_monitor.assert_not_called()


@patch(f"{MODULE}.next_update_window")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_freshness_prediction_shows_window(
    mock_resolve, mock_tr_cls, mock_td_cls, mock_sched, mock_window, db_session_mock,
):
    """A Freshness monitor in Prediction Model mode forecasts a next-update time
    window (the same one the dashboard computes), not a value band — so the
    forecast section presents that window rather than a band table or a note."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = (
        [_monitor_event(test_type="Freshness_Trend", message="Table update detected: Yes. On time.")],
        1,
    )
    monitor_def = MagicMock()
    monitor_def.history_calculation = "PREDICT"
    mock_td_cls.get_singleton_monitor.return_value = monitor_def
    mock_sched.get_for_monitor_suite.return_value = SimpleNamespace(cron_tz="UTC")
    start_ms = int(datetime(2026, 7, 1, 9, 0, tzinfo=UTC).timestamp() * 1000)
    end_ms = int(datetime(2026, 7, 1, 17, 0, tzinfo=UTC).timestamp() * 1000)
    mock_window.return_value = {"start": start_ms, "end": end_ms}

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "freshness", include_predictions=True)

    assert "## Forecast" in out
    assert "Next update expected" in out
    assert "2026-07-01 09:00 to 2026-07-01 17:00 UTC" in out
    # A window, not a value-band table.
    assert "| Time | Predicted lower | Predicted upper |" not in out


@patch(f"{MODULE}.next_update_window")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_freshness_coupled_volume_shows_gated_band(
    mock_resolve, mock_tr_cls, mock_td_cls, mock_sched, mock_window, db_session_mock,
):
    """A Volume/Metric monitor coupled to a Freshness monitor holds at its
    baseline until the next expected refresh — the forecast renders that coupled
    band (the UI's), and the internal coupling is never named in the output."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    # First call: the volume monitor's own events; second: the freshness events
    # the window is derived from.
    mock_tr_cls.list_monitor_events_for_table.side_effect = [
        ([_monitor_event()], 1),
        ([_monitor_event(test_type="Freshness_Trend", message="Table update detected: Yes.")], 1),
    ]
    volume_def = MagicMock()
    volume_def.history_calculation = "PREDICT"
    end_ms = int(datetime(2026, 6, 2, 12, 0, tzinfo=UTC).timestamp() * 1000)
    volume_def.prediction = {"freshness_gated": True, "baseline_value": 500.0, "mean": {str(end_ms): 480.0}}
    volume_def.lower_tolerance = "450"
    volume_def.upper_tolerance = "550"
    freshness_def = MagicMock()
    # list_monitor_events looks up the volume singleton; _compute_forecast then
    # looks up the table's freshness definition for the window.
    mock_td_cls.get_singleton_monitor.side_effect = [volume_def, freshness_def]
    mock_sched.get_for_monitor_suite.return_value = SimpleNamespace(cron_tz="UTC")
    start_ms = int(datetime(2026, 6, 1, 18, 0, tzinfo=UTC).timestamp() * 1000)
    mock_window.return_value = {"start": start_ms, "end": end_ms}

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "volume", include_predictions=True)

    assert "## Forecast" in out
    # The coupled band IS rendered (the step to the next-refresh tolerances).
    assert "| Time | Predicted lower | Predicted upper |" in out
    assert "450" in out and "550" in out
    # Internal coupling terminology must never reach the client.
    assert "gated" not in out.lower()


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_freshness_coupled_volume_without_tolerances_shows_note(
    mock_resolve, mock_tr_cls, mock_td_cls, db_session_mock,
):
    """A coupled Volume/Metric monitor with no configured tolerance has no band on
    the dashboard either, so the MCP shows a note (and skips the window queries),
    rather than diverging by computing a band the UI never plots."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_tr_cls.list_monitor_events_for_table.return_value = ([_monitor_event()], 1)
    volume_def = MagicMock()
    volume_def.history_calculation = "PREDICT"
    volume_def.prediction = {"freshness_gated": True, "baseline_value": 500.0}
    volume_def.lower_tolerance = None
    volume_def.upper_tolerance = None
    mock_td_cls.get_singleton_monitor.return_value = volume_def

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "volume", include_predictions=True)

    assert "## Forecast" in out
    assert "No forecast available for this monitor right now" in out
    # No band, and no terminology leak.
    assert "| Time | Predicted lower | Predicted upper |" not in out
    assert "gated" not in out.lower()
    # The freshness window queries are skipped when there's no tolerance to band.
    assert mock_td_cls.get_singleton_monitor.call_count == 1  # only the volume singleton lookup


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_events_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms():
        out = list_monitor_events(str(tg.id), "orders", "volume")

    assert out == "This table group is not monitored."


# ---------------------------------------------------------------------------
# update_monitor_settings
# ---------------------------------------------------------------------------


@patch(f"{MODULE}._last_monitor_run", return_value=None)
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.update_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_partial_maps_args(mock_resolve, mock_update, mock_js, mock_last, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _settings_suite(predict_sensitivity=PredictSensitivity.high))
    mock_js.get_for_monitor_suite.return_value = _mock_schedule()

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"):
        out = update_monitor_settings(str(tg.id), sensitivity="high", lookback_runs=50, exclude_weekends=True)

    assert "# Monitor settings updated for `Sales`" in out
    mock_update.assert_called_once()
    suite_attrs = mock_update.call_args.kwargs["suite_attrs"]
    assert suite_attrs["predict_sensitivity"] == PredictSensitivity.high
    assert suite_attrs["monitor_lookback"] == 50
    assert suite_attrs["predict_exclude_weekends"] is True


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"):
        out = update_monitor_settings(str(tg.id), sensitivity="high")

    assert out == "This table group is not monitored."


@patch(f"{MODULE}.update_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_no_fields(mock_resolve, mock_update, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"), pytest.raises(MCPUserError, match="No fields supplied"):
        update_monitor_settings(str(tg.id))

    mock_update.assert_not_called()


@patch(f"{MODULE}.update_monitoring")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_invalid_sensitivity(mock_resolve, mock_js, mock_update, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_js.get_for_monitor_suite.return_value = _mock_schedule()

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"), pytest.raises(MCPUserError, match="Invalid sensitivity"):
        update_monitor_settings(str(tg.id), sensitivity="extreme")

    mock_update.assert_not_called()


@patch(f"{MODULE}.update_monitoring")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_lookback_out_of_range(mock_resolve, mock_js, mock_update, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_js.get_for_monitor_suite.return_value = _mock_schedule()

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"), pytest.raises(MCPUserError, match="between 1 and 200"):
        update_monitor_settings(str(tg.id), lookback_runs=5000)

    mock_update.assert_not_called()


@patch(f"{MODULE}.update_monitoring")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_unknown_holiday_code(mock_resolve, mock_js, mock_update, db_session_mock):
    # ``is_supported_holiday_code`` runs for real here — ``US_FEDERAL`` is not a valid calendar.
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_js.get_for_monitor_suite.return_value = _mock_schedule()

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"), pytest.raises(MCPUserError, match="Unknown holiday codes"):
        update_monitor_settings(str(tg.id), holiday_codes=["US_FEDERAL"])

    mock_update.assert_not_called()


@patch(f"{MODULE}._last_monitor_run", return_value=None)
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.update_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_holiday_codes_serialized(mock_resolve, mock_update, mock_js, mock_last, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _settings_suite())
    mock_js.get_for_monitor_suite.return_value = _mock_schedule()

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"):
        update_monitor_settings(str(tg.id), holiday_codes=["US", "NYSE"])

    assert mock_update.call_args.kwargs["suite_attrs"]["predict_holiday_codes"] == "US,NYSE"


@patch(f"{MODULE}._last_monitor_run", return_value=None)
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.update_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_update_monitor_settings_empty_holiday_codes_clears(mock_resolve, mock_update, mock_js, mock_last, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _settings_suite())
    mock_js.get_for_monitor_suite.return_value = _mock_schedule()

    from testgen.mcp.tools.monitors import update_monitor_settings

    with _patch_perms(permission="edit"):
        update_monitor_settings(str(tg.id), holiday_codes=[])

    assert mock_update.call_args.kwargs["suite_attrs"]["predict_holiday_codes"] is None


# ---------------------------------------------------------------------------
# disable_monitors
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.disable_monitoring", return_value={"monitors": 4, "events": 2, "runs": 1})
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_disable_monitors_happy_path(mock_resolve, mock_disable, db_session_mock):
    tg = _mock_table_group()
    suite = _mock_monitor_suite()
    mock_resolve.return_value = (tg, suite)

    from testgen.mcp.tools.monitors import disable_monitors

    with _patch_perms(permission="edit"):
        out = disable_monitors(str(tg.id))

    assert "# Monitoring disabled for `Sales`" in out
    assert "**Monitors removed:** 4" in out
    assert "**Events removed:** 2" in out
    assert "**Runs removed:** 1" in out
    mock_disable.assert_called_once_with(suite)


@patch(f"{MODULE}.disable_monitoring")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_disable_monitors_not_enabled(mock_resolve, mock_disable, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import disable_monitors

    with _patch_perms(permission="edit"), pytest.raises(MCPUserError, match="not enabled"):
        disable_monitors(str(tg.id))

    mock_disable.assert_not_called()
def test_list_monitor_events_invalid_monitor_type(db_session_mock):
    from testgen.mcp.tools.monitors import list_monitor_events

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        list_monitor_events(str(uuid4()), "orders", "metrics")
    assert "Invalid monitor_type" in str(exc.value)


# ---------------------------------------------------------------------------
# list_monitors (TG-1092)
# ---------------------------------------------------------------------------


def _monitor_config(**overrides):
    from testgen.common.models.test_definition import (
        MonitorConfig,
        ThresholdMode,
    )

    defaults: dict = {
        "monitor_id": uuid4(),
        "test_type": "Volume_Trend",
        "table_name": "orders",
        "metric_name": None,
        "threshold_mode": ThresholdMode.STATIC,
        "threshold_lower": "900",
        "threshold_upper": "1100",
        "custom_query": None,
    }
    defaults.update(overrides)
    return MonitorConfig(**defaults)


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitors_happy_path(mock_resolve, mock_td_cls, db_session_mock):
    tg = _mock_table_group()
    suite = _mock_monitor_suite()
    mock_resolve.return_value = (tg, suite)
    mock_td_cls.list_monitor_configs_for_table.return_value = [
        _monitor_config(test_type="Freshness_Trend", threshold_lower=None, threshold_upper="60"),
        _monitor_config(
            test_type="Volume_Trend",
            threshold_mode="Prediction Model",
            threshold_lower=None, threshold_upper=None,
        ),
        _monitor_config(
            test_type="Metric_Trend",
            metric_name="total_amount",
            custom_query="SUM(total_amount)",
        ),
    ]

    from testgen.mcp.tools.monitors import list_monitors

    with _patch_perms():
        out = list_monitors(str(tg.id), "orders")

    assert "Monitors on `orders` in `Sales`" in out
    assert "**Prediction model sensitivity:** medium" in out
    # Type column uses Title Case (reuses _MONITOR_LABEL — no duplicate
    # lowercase dict needed; parse_monitor_type accepts either casing).
    assert "Freshness" in out
    assert "Volume" in out
    assert "Metric" in out
    # Metric expression column only populated for Metric
    assert "SUM(total_amount)" in out
    # Configuration tool must not surface runtime prediction bands
    assert "Prediction bands" not in out
    # Internal codes never leak
    assert "Volume_Trend" not in out
    assert "Freshness_Trend" not in out


@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitors_empty(mock_resolve, mock_td_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_td_cls.list_monitor_configs_for_table.return_value = []

    from testgen.mcp.tools.monitors import list_monitors

    with _patch_perms():
        out = list_monitors(str(tg.id), "orders")

    assert "_No monitors configured for this table._" in out


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitors_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import list_monitors

    with _patch_perms():
        out = list_monitors(str(tg.id), "orders")

    assert out == "This table group is not monitored."


# ---------------------------------------------------------------------------
# list_monitor_schema_changes (TG-1092)
# ---------------------------------------------------------------------------


def _schema_log_entry(**overrides):
    from testgen.common.models.data_structure_log import DataStructureLogEntry

    defaults: dict = {
        "log_id": uuid4(),
        "table_groups_id": uuid4(),
        "table_name": "orders",
        "column_name": "customer_id",
        "change_date": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        "change": "A",
        "old_data_type": None,
        "new_data_type": "INTEGER",
    }
    defaults.update(overrides)
    return DataStructureLogEntry(**defaults)


@patch.object(DataStructureLog, "list_for_table_group")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_schema_changes_happy_path(mock_resolve, mock_list, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_list.return_value = (
        [
            _schema_log_entry(change="A", column_name="new_col", old_data_type=None, new_data_type="TEXT"),
            _schema_log_entry(change="D", column_name="old_col", old_data_type="INTEGER", new_data_type=None),
            _schema_log_entry(change="M", column_name="total", old_data_type="NUMERIC", new_data_type="DECIMAL(10,2)"),
        ],
        3,
    )

    from testgen.mcp.tools.monitors import list_monitor_schema_changes

    with _patch_perms():
        out = list_monitor_schema_changes(str(tg.id))

    assert "Schema changes in `Sales`" in out
    assert "| Time | Change | Table | Column | Old type | New type |" in out
    # Codes are mapped to user-facing words; raw codes don't leak
    assert "added" in out
    assert "dropped" in out
    assert "modified" in out
    out_row_section = out.split("| --- |", 1)[1]
    assert "| A |" not in out_row_section
    assert "| D |" not in out_row_section
    assert "| M |" not in out_row_section


@patch.object(DataStructureLog, "list_for_table_group")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_schema_changes_table_filter_in_heading(
    mock_resolve, mock_list, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_list.return_value = ([], 0)

    from testgen.mcp.tools.monitors import list_monitor_schema_changes

    with _patch_perms():
        out = list_monitor_schema_changes(str(tg.id), table_name="orders", since="7 days")

    assert "table `orders`" in out
    assert "since `7 days`" in out
    # table_name + since reach the model as WHERE clauses, not named kwargs.
    sql = _compile_clauses(mock_list)
    assert "data_structure_log.table_name = 'orders'" in sql
    assert "data_structure_log.change_date >=" in sql


@patch.object(DataStructureLog, "list_for_table_group")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_schema_changes_since_passed_to_model(
    mock_resolve, mock_list, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_list.return_value = ([], 0)

    from testgen.mcp.tools.monitors import list_monitor_schema_changes

    with _patch_perms():
        list_monitor_schema_changes(str(tg.id), since="2026-05-01")

    # ``since`` is passed as a ``change_date >= <date>`` WHERE clause, not a kwarg.
    sql = _compile_clauses(mock_list)
    assert "data_structure_log.change_date >=" in sql
    assert "2026-05-01" in sql


def _compile_clauses(mock_method) -> str:
    """Compile the ``*clauses`` positional args of a captured
    ``list_for_table_group`` call into one SQL string."""
    clauses = mock_method.call_args[0][1:]  # drop table_group_id (first positional)
    return " ".join(str(c.compile(compile_kwargs={"literal_binds": True})) for c in clauses)


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_list_monitor_schema_changes_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitors import list_monitor_schema_changes

    with _patch_perms():
        out = list_monitor_schema_changes(str(tg.id))

    assert out == "This table group is not monitored."


def test_list_monitor_schema_changes_invalid_since(db_session_mock):
    from testgen.mcp.tools.monitors import list_monitor_schema_changes

    with _patch_perms(), pytest.raises(MCPUserError):
        list_monitor_schema_changes(str(uuid4()), since="bogus")


def test_list_monitor_schema_changes_limit_out_of_range(db_session_mock):
    from testgen.mcp.tools.monitors import list_monitor_schema_changes

    with _patch_perms(), pytest.raises(MCPUserError):
        list_monitor_schema_changes(str(uuid4()), limit=500)
