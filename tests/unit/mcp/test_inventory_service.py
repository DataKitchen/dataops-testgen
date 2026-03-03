from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def session_mock():
    with patch("testgen.mcp.services.inventory_service.get_current_session") as mock:
        yield mock.return_value


def _make_row(project_code="demo", project_name="Demo", connection_id=1, connection_name="main",
              table_group_id=None, table_groups_name="core",
              table_group_schema="public", test_suite_id=None, test_suite="Quality"):
    row = MagicMock()
    row.project_code = project_code
    row.project_name = project_name
    row.connection_id = connection_id
    row.connection_name = connection_name
    row.table_group_id = table_group_id or uuid4()
    row.table_groups_name = table_groups_name
    row.table_group_schema = table_group_schema
    row.test_suite_id = test_suite_id or uuid4()
    row.test_suite = test_suite
    return row


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_basic(mock_select, session_mock):
    tg_id = uuid4()
    row = _make_row(table_group_id=tg_id)
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "Data Inventory" in result
    assert "Demo" in result
    assert "main" in result
    assert "core" in result
    assert "Quality" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_empty(mock_select, session_mock):
    session_mock.execute.return_value.all.return_value = []

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "Data Inventory" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_project_no_connections(mock_select, session_mock):
    row = _make_row(connection_id=None)
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "Demo" in result
    assert "No connections" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_includes_list_tables_hint(mock_select, session_mock):
    session_mock.execute.return_value.all.return_value = [_make_row()]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    assert "list_tables" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_compact_groups(mock_select, session_mock):
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

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory()

    # Compact groups: single line with "X test suites", no "#### Table Group:" headers
    assert "test suites)" in result
    assert "#### Table Group:" not in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_hides_suites_without_view_permission(mock_select, session_mock):
    """Suites are hidden for projects where user lacks view permission."""
    tg_id = uuid4()
    suite_id = uuid4()
    row = _make_row(table_group_id=tg_id, test_suite_id=suite_id, test_suite="Secret Suite")
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=[])

    assert "Demo" in result
    assert "Secret Suite" not in result
    assert str(suite_id) not in result
    assert "requires `view` permission" in result
    assert "1 test suite(s)" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_shows_suites_with_view_permission(mock_select, session_mock):
    """Suites are shown for projects where user has view permission."""
    tg_id = uuid4()
    suite_id = uuid4()
    row = _make_row(table_group_id=tg_id, test_suite_id=suite_id, test_suite="Visible Suite")
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "Visible Suite" in result
    assert str(suite_id) in result
    assert "requires `view` permission" not in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_view_none_shows_all_suites(mock_select, session_mock):
    """When view_project_codes is None (global admin), all suites shown."""
    tg_id = uuid4()
    suite_id = uuid4()
    row = _make_row(table_group_id=tg_id, test_suite_id=suite_id, test_suite="Admin Suite")
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=None, view_project_codes=None)

    assert "Admin Suite" in result
    assert "requires `view` permission" not in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_no_suites_without_view_shows_no_suites(mock_select, session_mock):
    """When group has no suites and user lacks view, shows 'No test suites'."""
    tg_id = uuid4()
    row = _make_row(table_group_id=tg_id, test_suite_id=None, test_suite=None)
    # Remove the suite from the row
    row.test_suite_id = None
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=[])

    assert "No test suites" in result
    assert "requires `view` permission" not in result
