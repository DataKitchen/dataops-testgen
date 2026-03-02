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
