from unittest.mock import MagicMock, patch
from uuid import uuid4


@patch("testgen.mcp.services.inventory_service.get_inventory")
def test_get_data_inventory_returns_markdown(mock_get_inventory, db_session_mock):
    mock_get_inventory.return_value = "# Data Inventory\n\n## Project: Demo"

    from testgen.mcp.tools.discovery import get_data_inventory

    result = get_data_inventory()

    assert "Data Inventory" in result
    mock_get_inventory.assert_called_once()


@patch("testgen.mcp.tools.discovery.Project")
def test_list_projects_returns_formatted(mock_project, db_session_mock):
    proj1 = MagicMock()
    proj1.project_name = "Demo Project"
    proj1.project_code = "demo"
    proj2 = MagicMock()
    proj2.project_name = "Staging"
    proj2.project_code = "staging"
    mock_project.select_where.return_value = [proj1, proj2]

    from testgen.mcp.tools.discovery import list_projects

    result = list_projects()

    assert "Demo Project" in result
    assert "`demo`" in result
    assert "Staging" in result


@patch("testgen.mcp.tools.discovery.Project")
def test_list_projects_empty(mock_project, db_session_mock):
    mock_project.select_where.return_value = []

    from testgen.mcp.tools.discovery import list_projects

    result = list_projects()

    assert "No projects found" in result


@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_returns_stats(mock_suite, db_session_mock):
    summary = MagicMock()
    summary.id = uuid4()
    summary.test_suite = "Quality Suite"
    summary.connection_name = "main_conn"
    summary.table_groups_name = "core_tables"
    summary.test_suite_description = "Main quality checks"
    summary.test_ct = 50
    summary.latest_run_id = uuid4()
    summary.latest_run_start = "2024-01-15T10:00:00"
    summary.last_run_test_ct = 50
    summary.last_run_passed_ct = 45
    summary.last_run_failed_ct = 3
    summary.last_run_warning_ct = 2
    summary.last_run_error_ct = 0
    summary.last_run_dismissed_ct = 0
    mock_suite.select_summary.return_value = [summary]

    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("demo")

    assert "Quality Suite" in result
    assert "45 passed" in result
    assert "3 failed" in result


@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_empty(mock_suite, db_session_mock):
    mock_suite.select_summary.return_value = []

    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("nonexistent")

    assert "No test suites found" in result


def test_list_test_suites_empty_project_code(db_session_mock):
    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("")

    assert "Missing required parameter" in result
    assert "project_code" in result
