from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible
from testgen.mcp.permissions import ProjectPermissions


@patch("testgen.mcp.services.inventory_service.get_inventory")
def test_get_data_inventory_returns_markdown(mock_get_inventory, db_session_mock):
    mock_get_inventory.return_value = "# Data Inventory\n\n## Project: Demo"

    from testgen.mcp.tools.discovery import get_data_inventory

    result = get_data_inventory()

    assert "Data Inventory" in result
    mock_get_inventory.assert_called_once()


@patch("testgen.mcp.services.inventory_service.get_inventory")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_data_inventory_passes_project_codes_for_scoped_user(
    mock_compute, mock_get_inventory, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_c"},
        permission="catalog",
        username="test_user",
    )
    mock_get_inventory.return_value = "# Data Inventory"

    from testgen.mcp.tools.discovery import get_data_inventory

    get_data_inventory()

    call_kwargs = mock_get_inventory.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


@patch("testgen.mcp.services.inventory_service.get_inventory")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_data_inventory_view_codes_for_scoped_user(
    mock_compute, mock_get_inventory, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_c", "proj_b": "role_a"},
        permission="catalog",
        username="test_user",
    )
    mock_get_inventory.return_value = "# Data Inventory"

    from testgen.mcp.tools.discovery import get_data_inventory

    get_data_inventory()

    call_kwargs = mock_get_inventory.call_args.kwargs
    # "view" includes role_a but not role_c
    assert call_kwargs["view_project_codes"] == ["proj_b"]


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
    # "staging" is not in conftest's default memberships, so filtered out
    assert "Staging" not in result


@patch("testgen.mcp.tools.discovery.Project")
def test_list_projects_empty(mock_project, db_session_mock):
    mock_project.select_where.return_value = []

    from testgen.mcp.tools.discovery import list_projects

    result = list_projects()

    assert "No projects found" in result


@patch("testgen.mcp.tools.discovery.Project")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_projects_filters_for_scoped_user(mock_compute, mock_project, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"demo": "role_a"},
        permission="catalog",
        username="test_user",
    )

    proj1 = MagicMock()
    proj1.project_name = "Demo Project"
    proj1.project_code = "demo"
    proj2 = MagicMock()
    proj2.project_name = "Secret"
    proj2.project_code = "secret"
    mock_project.select_where.return_value = [proj1, proj2]

    from testgen.mcp.tools.discovery import list_projects

    result = list_projects()

    assert "Demo Project" in result
    assert "Secret" not in result


@patch("testgen.mcp.tools.discovery.TestRun")
@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_returns_stats(mock_suite, mock_test_run, db_session_mock):
    run_id = uuid4()
    job_exec_id = uuid4()
    summary = MagicMock()
    summary.id = uuid4()
    summary.test_suite = "Quality Suite"
    summary.connection_name = "main_conn"
    summary.table_groups_name = "core_tables"
    summary.test_suite_description = "Main quality checks"
    summary.test_ct = 50
    summary.latest_run_id = run_id
    summary.latest_run_start = "2024-01-15T10:00:00"
    summary.last_run_test_ct = 50
    summary.last_run_passed_ct = 45
    summary.last_run_failed_ct = 3
    summary.last_run_warning_ct = 2
    summary.last_run_error_ct = 0
    summary.last_run_dismissed_ct = 0
    mock_suite.select_summary.return_value = [summary]
    mock_test_run.get_job_execution_ids.return_value = {run_id: job_exec_id}

    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("demo")

    assert "Quality Suite" in result
    assert "45 passed" in result
    assert "3 failed" in result
    assert str(job_exec_id) in result


@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_empty(mock_suite, db_session_mock):
    mock_suite.select_summary.return_value = []

    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("demo")

    assert "No test suites found" in result


def test_list_test_suites_empty_project_code(db_session_mock):
    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("")

    assert "Missing required parameter" in result
    assert "project_code" in result


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_test_suites_raises_not_found_for_inaccessible_project(
    mock_compute, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"other_project": "role_a"},
        permission="view",
        username="test_user",
    )

    from testgen.mcp.tools.discovery import list_test_suites

    with pytest.raises(MCPResourceNotAccessible, match="Project `secret_project` not found or not accessible"):
        list_test_suites("secret_project")


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_test_suites_raises_denial_for_insufficient_permission(
    mock_compute, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"other_project": "role_a", "secret_project": "role_c"},
        permission="view",
        username="test_user",
    )

    from testgen.mcp.tools.discovery import list_test_suites

    with pytest.raises(MCPPermissionDenied, match="necessary permission"):
        list_test_suites("secret_project")


@patch("testgen.mcp.tools.common.TableGroup")
def test_list_tables_rejects_inaccessible_group(mock_tg_cls, db_session_mock):
    """Inaccessible or non-existent TG raises MCPResourceNotAccessible — same path."""
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.discovery import list_tables

    with pytest.raises(MCPResourceNotAccessible, match="Table group .* not found or not accessible"):
        list_tables(str(uuid4()))


@patch("testgen.mcp.tools.discovery.DataTable")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_tables_scopes_data_lookup_to_resolved_tg_project(mock_tg_cls, mock_dt, db_session_mock):
    """After resolution, data lookup is scoped to just the TG's project, not all allowed projects."""
    tg = MagicMock()
    tg.id = uuid4()
    tg.project_code = "proj_a"
    mock_tg_cls.get.return_value = tg
    mock_dt.select_table_names.return_value = ["customers"]
    mock_dt.count_tables.return_value = 1

    from testgen.mcp.tools.discovery import list_tables

    list_tables(str(uuid4()))

    call_kwargs = mock_dt.select_table_names.call_args
    assert call_kwargs.kwargs["project_codes"] == ["proj_a"]


# ---------------------------------------------------------------------------
# get_project
# ---------------------------------------------------------------------------


def _mock_project(**overrides):
    project = MagicMock()
    project.project_code = overrides.get("project_code", "demo")
    project.project_name = overrides.get("project_name", "Demo Project")
    project.use_dq_score_weights = overrides.get("use_dq_score_weights", True)
    project.data_retention_enabled = overrides.get("data_retention_enabled", True)
    project.data_retention_days = overrides.get("data_retention_days", 180)
    project.observability_api_url = overrides.get("observability_api_url", None)
    return project


def _mock_project_summary(**overrides):
    summary = MagicMock()
    summary.connection_count = overrides.get("connection_count", 3)
    summary.table_group_count = overrides.get("table_group_count", 5)
    summary.test_suite_count = overrides.get("test_suite_count", 7)
    summary.test_definition_count = overrides.get("test_definition_count", 142)
    summary.profiling_run_count = overrides.get("profiling_run_count", 12)
    summary.test_run_count = overrides.get("test_run_count", 38)
    summary.can_export_to_observability = overrides.get("can_export_to_observability", False)
    return summary


@patch("testgen.mcp.tools.discovery.Project")
def test_get_project_returns_counts_and_config(mock_project_cls, db_session_mock):
    mock_project_cls.get.return_value = _mock_project()
    mock_project_cls.get_summary.return_value = _mock_project_summary()

    from testgen.mcp.tools.discovery import get_project

    out = get_project("demo")

    assert "Project `demo`" in out
    assert "Demo Project" in out
    assert "**Connections:** 3" in out
    assert "**Table groups:** 5" in out
    assert "**Test suites:** 7" in out
    assert "**Test definitions:** 142" in out
    assert "**Profiling runs:** 12" in out
    assert "**Test runs:** 38" in out
    assert "**Weighted data quality scoring:** Yes" in out
    assert "## Observability Integration" in out
    assert "**Configured:** No" in out  # default summary has can_export_to_observability=False
    assert "## Data Retention" in out
    assert "**Automatically delete old profiling and test history:** Yes" in out
    assert "**Delete history older than (days):** 180" in out


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_project_raises_not_found_for_inaccessible(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"other": "role_a"}, permission="view", username="test_user",
    )

    from testgen.mcp.tools.discovery import get_project

    with pytest.raises(MCPResourceNotAccessible, match="Project `secret` not found or not accessible"):
        get_project("secret")


@patch("testgen.mcp.tools.discovery.Project")
def test_get_project_raises_not_found_when_missing(mock_project_cls, db_session_mock):
    mock_project_cls.get.return_value = None
    mock_project_cls.get_summary.return_value = None

    from testgen.mcp.tools.discovery import get_project

    with pytest.raises(MCPResourceNotAccessible, match="Project `demo` not found or not accessible"):
        get_project("demo")


# ---------------------------------------------------------------------------
# get_test_suite
# ---------------------------------------------------------------------------


def _mock_test_suite(**overrides):
    suite = MagicMock()
    suite.id = overrides.get("id", uuid4())
    suite.test_suite = overrides.get("test_suite", "qa_checks")
    suite.project_code = overrides.get("project_code", "demo")
    suite.connection_id = overrides.get("connection_id", 42)
    suite.table_groups_id = overrides.get("table_groups_id", uuid4())
    suite.test_suite_description = overrides.get("test_suite_description", "Daily QA")
    suite.severity = overrides.get("severity", "Warning")
    suite.export_to_observability = overrides.get("export_to_observability", True)
    suite.is_monitor = overrides.get("is_monitor", False)
    return suite


_DEFAULT_TYPE_COUNTS = {"Aggregate Balance": 5, "Row Count": 12}


def _stats(total=47, locked=3, counts_by_type=None):
    from testgen.common.models.test_suite import TestDefinitionStats

    return TestDefinitionStats(
        total=total,
        locked=locked,
        counts_by_type=_DEFAULT_TYPE_COUNTS if counts_by_type is None else counts_by_type,
    )


@patch("testgen.mcp.tools.discovery.TestSuite")
@patch("testgen.mcp.tools.discovery.resolve_table_group")
@patch("testgen.mcp.tools.discovery.resolve_connection")
@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_returns_full_config(
    mock_common_suite, mock_resolve_conn, mock_resolve_tg, mock_suite_cls, db_session_mock,
):
    suite = _mock_test_suite()
    mock_common_suite.get.return_value = suite
    conn = MagicMock(connection_id=42, connection_name="warehouse_prod", sql_flavor_code="snowflake")
    mock_resolve_conn.return_value = conn
    tg = MagicMock(table_groups_name="curated_payments")
    tg.id = suite.table_groups_id
    mock_resolve_tg.return_value = tg
    mock_suite_cls.test_definition_stats.return_value = _stats()

    from testgen.mcp.tools.discovery import get_test_suite

    out = get_test_suite(str(suite.id))

    assert "Test Suite `qa_checks`" in out
    assert f"**ID:** `{suite.id}`" in out
    assert "**Project:** `demo`" in out
    assert "warehouse_prod" in out
    assert "Snowflake" in out
    assert "curated_payments" in out
    assert "**Default severity:** Warning" in out
    assert "**Export to observability:** Yes" in out
    assert "**Total tests:** 47" in out
    assert "**Locked tests:** 3" in out
    assert "Tests by type" in out
    # Renders short_name labels (e.g. "Aggregate Balance"), NOT raw test_type codes (e.g. "Aggregate_Balance")
    assert "Aggregate Balance" in out
    assert "Row Count" in out
    assert "Aggregate_Balance" not in out  # the raw test_type code must NOT appear


@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_rejects_inaccessible_id(mock_common_suite, db_session_mock):
    """A genuinely missing / inaccessible id (TestSuite.get returns None) raises the unified error."""
    mock_common_suite.get.return_value = None

    from testgen.mcp.tools.discovery import get_test_suite

    bogus_id = str(uuid4())
    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        get_test_suite(bogus_id)


@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_rejects_actual_monitor_suite(mock_common_suite, db_session_mock):
    """An existing ``is_monitor=True`` suite is rejected because resolve_test_suite
    passes ``TestSuite.is_monitor.isnot(True)`` as a filter clause.

    Simulates the real DB filter behaviour: ``TestSuite.get`` returns the monitor
    suite when called without the filter clause, ``None`` when the clause is present.
    """
    monitor_suite = _mock_test_suite(is_monitor=True)

    def filtered_get(_uuid, *clauses):
        # The resolver's contract: pass an `is_monitor.isnot(True)` clause to TestSuite.get.
        # If the clause is present, a DB query against it would not match this monitor row.
        for clause in clauses:
            clause_str = str(clause).lower()
            if "is_monitor" in clause_str and "not" in clause_str:
                return None
        return monitor_suite

    mock_common_suite.get.side_effect = filtered_get

    from testgen.mcp.tools.discovery import get_test_suite

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        get_test_suite(str(monitor_suite.id))


@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_rejects_invalid_uuid(mock_common_suite, db_session_mock):
    from testgen.mcp.exceptions import MCPUserError as _MCPUserError
    from testgen.mcp.tools.discovery import get_test_suite

    with pytest.raises(_MCPUserError, match="not a valid UUID"):
        get_test_suite("not-a-uuid")


@patch("testgen.mcp.tools.discovery.TestSuite")
@patch("testgen.mcp.tools.discovery.resolve_table_group")
@patch("testgen.mcp.tools.discovery.resolve_connection")
@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_no_severity_renders_inherit(
    mock_common_suite, mock_resolve_conn, mock_resolve_tg, mock_suite_cls, db_session_mock,
):
    suite = _mock_test_suite(severity=None, connection_id=None, table_groups_id=None)
    mock_common_suite.get.return_value = suite
    # connection_id / table_groups_id are None, so resolvers should not be called
    mock_suite_cls.test_definition_stats.return_value = _stats(total=0, locked=0, counts_by_type={})

    from testgen.mcp.tools.discovery import get_test_suite

    out = get_test_suite(str(suite.id))

    assert "Inherit from test type" in out
    # No "Tests by type" table when there are no test definitions
    assert "Tests by type" not in out
    mock_resolve_conn.assert_not_called()
    mock_resolve_tg.assert_not_called()
