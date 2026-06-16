"""Tests for the MCP monitor read tools — ``get_monitor_summary`` and ``list_monitored_tables``."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.table_group import MonitorGroupSummary, MonitorTableSummary
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
    suite = MagicMock()
    suite.id = overrides.get("id", uuid4())
    suite.is_monitor = True
    suite.monitor_lookback = overrides.get("monitor_lookback", 7)
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
    assert "| Freshness | 2 | ok |" in out
    assert "| Volume | 0 | ok |" in out
    assert "| Schema | 1 | ok |" in out
    assert "| Metric | 0 | training |" in out


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
    assert out.count("no results yet or not configured") == 4


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

    assert "| Freshness | 2 | error |" in out
    assert "| Volume | 0 | no results yet or not configured |" in out
    assert "| Schema | 1 | no results yet or not configured |" in out
    assert "| Metric | 0 | no results yet or not configured |" in out


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
    assert "training" in row
    assert "pending" in row
    assert "error" in row


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
    assert "training" not in row_count
    assert "pending" not in row_count
    # Row 2: error still wins over count
    row_error = next(line for line in out.splitlines() if "`t_error_with_count`" in line)
    assert "error" in row_error
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
