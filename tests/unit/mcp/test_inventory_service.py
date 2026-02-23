from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def session_mock():
    with patch("testgen.mcp.services.inventory_service.get_current_session") as mock:
        yield mock.return_value


def _make_row(project_code="demo", project_name="Demo", connection_id=1, connection_name="main",
              sql_flavor_code="postgresql", table_group_id=None, table_groups_name="core",
              table_group_schema="public", test_suite_id=None, test_suite="Quality",
              last_run_id=None, test_starttime=None, last_run_status=None,
              test_ct=None, passed_ct=None, failed_ct=None, warning_ct=None):
    row = MagicMock()
    row.project_code = project_code
    row.project_name = project_name
    row.connection_id = connection_id
    row.connection_name = connection_name
    row.sql_flavor_code = sql_flavor_code
    row.table_group_id = table_group_id or uuid4()
    row.table_groups_name = table_groups_name
    row.table_group_schema = table_group_schema
    row.test_suite_id = test_suite_id or uuid4()
    row.test_suite = test_suite
    row.last_run_id = last_run_id or uuid4()
    row.test_starttime = test_starttime or "2024-01-15T10:00:00"
    row.last_run_status = last_run_status or "Complete"
    row.test_ct = test_ct if test_ct is not None else 50
    row.passed_ct = passed_ct if passed_ct is not None else 47
    row.failed_ct = failed_ct if failed_ct is not None else 2
    row.warning_ct = warning_ct if warning_ct is not None else 1
    return row


@patch("testgen.mcp.services.inventory_service.DataTable")
@patch("testgen.mcp.services.inventory_service.TableGroup")
@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_basic(mock_select, mock_tg, mock_dt, session_mock):
    tg_id = uuid4()
    row = _make_row(table_group_id=tg_id)
    session_mock.execute.return_value.all.return_value = [row]

    stat = MagicMock()
    stat.id = tg_id
    stat.table_ct = 10
    stat.column_ct = 50
    mock_tg.select_stats.return_value = [stat]
    mock_dt.select_table_names.return_value = ["customers", "orders", "products"]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "Data Inventory" in result
    assert "Demo" in result
    assert "main" in result
    assert "core" in result
    assert "Quality" in result
    assert "10 tables" in result
    assert "`customers`" in result
    assert "`orders`" in result


@patch("testgen.mcp.services.inventory_service.DataTable")
@patch("testgen.mcp.services.inventory_service.TableGroup")
@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_empty(mock_select, mock_tg, mock_dt, session_mock):
    session_mock.execute.return_value.all.return_value = []

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "Data Inventory" in result


@patch("testgen.mcp.services.inventory_service.DataTable")
@patch("testgen.mcp.services.inventory_service.TableGroup")
@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_project_no_connections(mock_select, mock_tg, mock_dt, session_mock):
    row = _make_row(connection_id=None)
    session_mock.execute.return_value.all.return_value = [row]
    mock_tg.select_stats.return_value = []

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "Demo" in result
    assert "No connections" in result


@patch("testgen.mcp.services.inventory_service.DataTable")
@patch("testgen.mcp.services.inventory_service.TableGroup")
@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_includes_test_type_hint(mock_select, mock_tg, mock_dt, session_mock):
    session_mock.execute.return_value.all.return_value = [_make_row()]
    stat = MagicMock()
    stat.id = uuid4()
    stat.table_ct = 5
    stat.column_ct = 20
    mock_tg.select_stats.return_value = [stat]
    mock_dt.select_table_names.return_value = []

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "test-types" in result


@patch("testgen.mcp.services.inventory_service.DataTable")
@patch("testgen.mcp.services.inventory_service.TableGroup")
@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_compact_suites(mock_select, mock_tg, mock_dt, session_mock):
    """When >20 suites, suite output uses compact format (name + status icon only)."""
    tg_id = uuid4()
    rows = [
        _make_row(
            table_group_id=tg_id,
            test_suite=f"Suite_{i}",
            test_suite_id=uuid4(),
            failed_ct=1 if i == 0 else 0,
            warning_ct=0,
        )
        for i in range(25)
    ]
    session_mock.execute.return_value.all.return_value = rows

    stat = MagicMock()
    stat.id = tg_id
    stat.table_ct = 10
    stat.column_ct = 50
    mock_tg.select_stats.return_value = [stat]
    mock_dt.select_table_names.return_value = ["t1"]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    # Compact suites: show "[FAILURES]" / "[OK]" badges, no full run details
    assert "[FAILURES]" in result
    assert "[OK]" in result
    # Full format markers should NOT appear
    assert "Last run:" not in result


@patch("testgen.mcp.services.inventory_service.DataTable")
@patch("testgen.mcp.services.inventory_service.TableGroup")
@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_compact_groups(mock_select, mock_tg, mock_dt, session_mock):
    """When >50 groups, group output uses single-line compact format."""
    rows = [
        _make_row(
            table_group_id=uuid4(),
            table_groups_name=f"Group_{i}",
            test_suite=f"Suite_{i}",
            test_suite_id=uuid4(),
        )
        for i in range(55)
    ]
    session_mock.execute.return_value.all.return_value = rows

    mock_tg.select_stats.return_value = []
    mock_dt.select_table_names.return_value = []

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    # Compact groups: single line with "X test suites", no "#### Table Group:" headers
    assert "test suites)" in result
    assert "#### Table Group:" not in result
