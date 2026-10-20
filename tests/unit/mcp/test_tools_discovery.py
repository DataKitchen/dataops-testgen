from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import JOB_STATUS_LABEL, JobStatus, SuiteType
from testgen.common.models.suite_version import ContractState
from testgen.common.models.test_suite import TestSuite as RealTestSuite
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions
from testgen.mcp.tools.common import MCP_SUITE_TYPES


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


@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_returns_stats(mock_suite, db_session_mock):
    run_id = uuid4()
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

    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("demo")

    assert "Quality Suite" in result
    assert "45 passed" in result
    assert "3 failed" in result
    # latest_run_id is already the job execution id — surfaced directly.
    assert str(run_id) in result


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
    suite.deactivate_invalid_tests = overrides.get("deactivate_invalid_tests", False)
    suite.suite_type = overrides.get("suite_type", SuiteType.REGULAR)
    return suite


_DEFAULT_TYPE_COUNTS = {"Aggregate Balance": 5, "Row Count": 12}


def _stats(total=47, locked=3, counts_by_type=None):
    from testgen.common.models.test_suite import TestDefinitionStats

    return TestDefinitionStats(
        total=total,
        locked=locked,
        counts_by_type=_DEFAULT_TYPE_COUNTS if counts_by_type is None else counts_by_type,
    )


@patch("testgen.mcp.tools.discovery.list_generation_sets", return_value=["Standard"])
@patch("testgen.mcp.tools.discovery.TestSuite")
@patch("testgen.mcp.tools.discovery.resolve_table_group")
@patch("testgen.mcp.tools.discovery.resolve_connection")
@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_returns_full_config(
    mock_common_suite, mock_resolve_conn, mock_resolve_tg, mock_suite_cls, _mock_sets, db_session_mock,
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
    assert "**Automatically deactivate tests that fail validation:** No" in out
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
    """A monitor suite is rejected because resolve_test_suite passes a
    ``suite_type IN (regular, contract)`` clause.

    Simulates the real DB filter behaviour: ``TestSuite.get`` returns the monitor
    suite when called without the filter clause, ``None`` when the clause is present.
    """
    monitor_suite = _mock_test_suite(suite_type=SuiteType.MONITOR)
    # The patched class must carry the real column descriptors. Comparing a bare MagicMock
    # attribute against an enum member yields a plain False rather than a clause, and every
    # MagicMock answers `compare()` truthily, which would make the check below always match.
    mock_common_suite.suite_type = RealTestSuite.suite_type
    mock_common_suite.project_code = RealTestSuite.project_code
    exclusion = RealTestSuite.suite_type.in_(MCP_SUITE_TYPES)

    def filtered_get(_uuid, *clauses):
        # The resolver's contract: pass the regular-suite clause to TestSuite.get.
        # If the clause is present, a DB query against it would not match this monitor row.
        # Compared structurally, not as text: the value sits in a bound parameter, so
        # `str(clause)` cannot tell `= 'regular'` from `= 'monitor'`.
        if any(clause.compare(exclusion) for clause in clauses):
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


@patch("testgen.mcp.tools.discovery.list_generation_sets", return_value=["Standard"])
@patch("testgen.mcp.tools.discovery.TestSuite")
@patch("testgen.mcp.tools.discovery.resolve_table_group")
@patch("testgen.mcp.tools.discovery.resolve_connection")
@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_no_severity_renders_inherit(
    mock_common_suite, mock_resolve_conn, mock_resolve_tg, mock_suite_cls, _mock_sets, db_session_mock,
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


@patch("testgen.mcp.services.inventory_service.get_inventory")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_data_inventory_forwards_identity_and_roles(
    mock_compute, mock_get_inventory, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_c"},
        permission="catalog",
        username="alice",
        is_global_admin=False,
    )
    mock_get_inventory.return_value = "# Data Inventory"

    from testgen.mcp.tools.discovery import get_data_inventory

    get_data_inventory()

    kwargs = mock_get_inventory.call_args.kwargs
    assert kwargs["username"] == "alice"
    assert kwargs["is_global_admin"] is False
    assert kwargs["roles_by_code"] == {"proj_a": "role_c"}


# --- generation sets on the read surfaces ---


@patch("testgen.mcp.tools.discovery.list_generation_sets", return_value=["Plugin_Set", "Standard"])
@patch("testgen.mcp.tools.discovery.TestSuite")
@patch("testgen.mcp.tools.discovery.resolve_table_group")
@patch("testgen.mcp.tools.discovery.resolve_connection")
@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_shows_stored_and_available_sets(
    mock_common_suite, mock_resolve_conn, mock_resolve_tg, mock_suite_cls, _mock_sets, db_session_mock,
):
    suite = _mock_test_suite()
    suite.generation_sets = ["Standard", "Plugin_Set"]
    mock_common_suite.get.return_value = suite
    mock_resolve_conn.return_value = MagicMock(
        connection_id=42, connection_name="warehouse_prod", sql_flavor_code="snowflake"
    )
    tg = MagicMock(table_groups_name="curated_payments")
    tg.id = suite.table_groups_id
    mock_resolve_tg.return_value = tg
    mock_suite_cls.test_definition_stats.return_value = _stats()

    from testgen.mcp.tools.discovery import get_test_suite

    out = get_test_suite(str(suite.id))

    assert "**Generation sets:** Standard, Plugin_Set" in out
    assert "**Available generation sets:** Plugin_Set, Standard" in out


@patch("testgen.mcp.tools.discovery.list_generation_sets", return_value=["Plugin_Set", "Standard"])
@patch("testgen.mcp.tools.discovery.TestSuite")
@patch("testgen.mcp.tools.discovery.resolve_table_group")
@patch("testgen.mcp.tools.discovery.resolve_connection")
@patch("testgen.mcp.tools.common.TestSuite")
def test_get_test_suite_reports_unset_generation_sets(
    mock_common_suite, mock_resolve_conn, mock_resolve_tg, mock_suite_cls, _mock_sets, db_session_mock,
):
    suite = _mock_test_suite()
    suite.generation_sets = None
    mock_common_suite.get.return_value = suite
    mock_resolve_conn.return_value = MagicMock(
        connection_id=42, connection_name="warehouse_prod", sql_flavor_code="snowflake"
    )
    tg = MagicMock(table_groups_name="curated_payments")
    tg.id = suite.table_groups_id
    mock_resolve_tg.return_value = tg
    mock_suite_cls.test_definition_stats.return_value = _stats()

    from testgen.mcp.tools.discovery import get_test_suite

    out = get_test_suite(str(suite.id))

    assert "**Generation sets:** Not set, defaults to Standard" in out


@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_shows_stored_sets(mock_suite, db_session_mock):
    summary = MagicMock()
    summary.id = uuid4()
    summary.test_suite = "qa_checks"
    summary.connection_name = "warehouse_prod"
    summary.table_groups_name = "curated_payments"
    summary.test_suite_description = None
    summary.test_ct = 12
    summary.latest_run_id = None
    summary.generation_sets = ["Standard", "Plugin_Set"]
    mock_suite.select_summary.return_value = [summary]

    from testgen.mcp.tools.discovery import list_test_suites

    out = list_test_suites("demo")

    assert "**Generation sets:** Standard, Plugin_Set" in out


@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_omits_generation_sets_when_unset(mock_suite, db_session_mock):
    summary = MagicMock()
    summary.id = uuid4()
    summary.test_suite = "qa_checks"
    summary.connection_name = "warehouse_prod"
    summary.table_groups_name = "curated_payments"
    summary.test_suite_description = None
    summary.test_ct = 12
    summary.latest_run_id = None
    summary.generation_sets = None
    mock_suite.select_summary.return_value = [summary]

    from testgen.mcp.tools.discovery import list_test_suites

    out = list_test_suites("demo")

    assert "Generation sets" not in out


@patch("testgen.mcp.services.inventory_service.get_inventory")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_data_inventory_forwards_global_admin_flag(
    mock_compute, mock_get_inventory, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="catalog",
        username="root",
        is_global_admin=True,
    )
    mock_get_inventory.return_value = "# Data Inventory"

    from testgen.mcp.tools.discovery import get_data_inventory

    get_data_inventory()

    kwargs = mock_get_inventory.call_args.kwargs
    assert kwargs["is_global_admin"] is True


def _summary(name, suite_type="regular"):
    s = MagicMock()
    s.id = uuid4()
    s.test_suite = name
    s.suite_type = suite_type
    s.connection_name = "main_conn"
    s.table_groups_name = "core"
    s.test_suite_description = None
    s.test_ct = 3
    s.generation_sets = None
    s.latest_run_id = None
    return s


@patch("testgen.mcp.tools.discovery.SuiteVersion")
@patch("testgen.mcp.tools.discovery.TestSuite")
def test_list_test_suites_includes_contracts_by_default(mock_suite, mock_versions, db_session_mock):
    regular, contract = _summary("Quality"), _summary("Orders", SuiteType.CONTRACT)
    mock_suite.select_summary.return_value = [regular, contract]
    active = MagicMock(version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC))
    draft = MagicMock(version=4, frozen_at=None)
    mock_versions.states_for.return_value = {contract.id: ContractState(active=active, draft=draft)}

    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("demo")

    assert mock_suite.select_summary.call_args.kwargs["suite_types"] == MCP_SUITE_TYPES
    assert "Contract · v3 active · v4 draft" in result
    assert mock_versions.states_for.call_args.args[0] == [contract.id]


@patch("testgen.mcp.tools.discovery.SuiteVersion")
@patch("testgen.mcp.tools.discovery.TestSuite")
def test_a_regular_row_is_unchanged(mock_suite, mock_versions, db_session_mock):
    mock_suite.select_summary.return_value = [_summary("Quality")]
    mock_versions.states_for.return_value = {}

    from testgen.mcp.tools.discovery import list_test_suites

    result = list_test_suites("demo")

    assert "Type" not in result
    assert " v" not in result.split("Quality", 1)[1].split("\n## ", 1)[0].replace("(id:", "")


@patch("testgen.mcp.tools.discovery.SuiteVersion")
@patch("testgen.mcp.tools.discovery.TestSuite")
def test_suite_type_narrows_to_contracts(mock_suite, mock_versions, db_session_mock):
    mock_suite.select_summary.return_value = []
    mock_versions.states_for.return_value = {}

    from testgen.mcp.tools.discovery import list_test_suites

    list_test_suites("demo", suite_type="Contract")

    assert mock_suite.select_summary.call_args.kwargs["suite_types"] == (SuiteType.CONTRACT,)


@patch("testgen.mcp.tools.discovery.SuiteVersion")
@patch("testgen.mcp.tools.discovery.TestSuite")
def test_a_contract_with_only_a_draft(mock_suite, mock_versions, db_session_mock):
    contract = _summary("Orders", SuiteType.CONTRACT)
    mock_suite.select_summary.return_value = [contract]
    mock_versions.states_for.return_value = {
        contract.id: ContractState(active=None, draft=MagicMock(version=1, frozen_at=None))
    }

    from testgen.mcp.tools.discovery import list_test_suites

    assert "Contract · v1 draft" in list_test_suites("demo")


def test_an_unknown_suite_type_is_a_user_error(db_session_mock):
    from testgen.mcp.tools.discovery import list_test_suites

    with pytest.raises(MCPUserError, match="suite_type"):
        list_test_suites("demo", suite_type="Monitor")


def _contract_suite():
    suite = MagicMock()
    suite.id = uuid4()
    suite.test_suite = "Orders"
    suite.suite_type = SuiteType.CONTRACT
    suite.connection_id = None
    suite.table_groups_id = None
    suite.generation_sets = None
    return suite


def _get(suite, state, verification=None, run_summary=None, latest_verification=None, summaries=None):
    from testgen.mcp.tools.discovery import get_test_suite

    # A run's summary carries the run's own id: a test run shares it with the job that started it.
    if summaries is not None:
        def select_summary(*, test_run_ids, **_):
            found = [summaries[run_id] for run_id in test_run_ids if run_id in summaries]
            for run_id, summary in zip(test_run_ids, found, strict=True):
                summary.job_execution_id = run_id
            return found, len(found)
    else:
        def select_summary(*, test_run_ids, **_):
            if run_summary is None:
                return [], 0
            run_summary.job_execution_id = test_run_ids[0]
            return [run_summary], 1

    with (
        patch("testgen.mcp.tools.discovery.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.discovery.TestSuite.test_definition_stats",
              return_value=MagicMock(total=3, locked=0, counts_by_type={})),
        patch("testgen.common.contract_service.SuiteVersion.states_for", return_value={suite.id: state}),
        patch(
            "testgen.common.contract_service.TestRun.latest_verification",
            new=latest_verification or MagicMock(return_value=verification),
        ),
        patch("testgen.common.contract_service.TestRun.select_summary", side_effect=select_summary),
        patch("testgen.mcp.tools.discovery.list_generation_sets", return_value=[]),
    ):
        return get_test_suite(str(suite.id))


FROZEN = datetime(2026, 9, 12, 14, 3, tzinfo=UTC)


def test_the_block_names_active_draft_and_counted_version(db_session_mock):
    active = MagicMock(version=3, frozen_at=FROZEN, label="Q3 agreement", created_by="alice")
    draft = MagicMock(version=4, frozen_at=None)
    out = _get(_contract_suite(), ContractState(active=active, draft=draft))
    assert "## Contract" in out
    assert '- **Active version:** v3 active — "Q3 agreement" (frozen 2026-09-12 14:03 UTC)' in out
    assert "**Draft:** v4 draft" in out
    assert "**Tests counted from:** v4 draft" in out


def test_the_verification_is_the_latest_run_of_the_active_version(db_session_mock):
    active = MagicMock(version=3, frozen_at=FROZEN, label=None, created_by="alice")
    run = MagicMock(id=uuid4())
    summary = MagicMock(
        status=JobStatus.COMPLETED, status_label=JOB_STATUS_LABEL[JobStatus.COMPLETED],
        test_ct=12, passed_ct=10, failed_ct=1, warning_ct=1, error_ct=0, started_at=FROZEN,
    )
    out = _get(_contract_suite(), ContractState(active=active, draft=None), run, summary)
    assert (
        f"- **Latest verification:** Failed — run `{run.id}` (started 2026-09-12 14:03 UTC); "
        "12 tests: 10 passed, 1 failed, 1 warnings, 0 errors"
    ) in out


@pytest.mark.parametrize(
    ("failed", "errors", "warnings", "verdict"),
    [
        (1, 1, 1, "Failed"),
        (0, 1, 1, "Error"),
        (0, 0, 1, "Warning"),
        (0, 0, 0, "Passed"),
    ],
)
def test_the_verdict_ranks_failed_then_error_then_warning(db_session_mock, failed, errors, warnings, verdict):
    active = MagicMock(version=3, frozen_at=FROZEN, label=None, created_by="alice")
    summary = MagicMock(
        status=JobStatus.COMPLETED, status_label=JOB_STATUS_LABEL[JobStatus.COMPLETED],
        test_ct=5, passed_ct=2, failed_ct=failed, warning_ct=warnings, error_ct=errors, started_at=FROZEN,
    )
    out = _get(_contract_suite(), ContractState(active=active, draft=None), MagicMock(id=uuid4()), summary)
    assert f"**Latest verification:** {verdict} — run" in out


def test_no_frozen_version_means_verification_unavailable(db_session_mock):
    out = _get(_contract_suite(), ContractState(active=None, draft=MagicMock(version=1, frozen_at=None)))
    assert "Verification unavailable: no version has been frozen yet, so runs of the draft are previews." in out


def test_a_frozen_version_never_run_since(db_session_mock):
    active = MagicMock(version=3, frozen_at=FROZEN, label=None, created_by="alice")
    out = _get(_contract_suite(), ContractState(active=active, draft=None))
    assert "Verification unavailable: v3 active has not run since it was frozen." in out


def test_a_latest_verification_with_no_summary_reads_as_not_run_since(db_session_mock):
    active = MagicMock(version=3, frozen_at=FROZEN, label=None, created_by="alice")
    out = _get(_contract_suite(), ContractState(active=active, draft=None), MagicMock(id=uuid4()))
    assert "Verification unavailable: v3 active has not run since it was frozen." in out


def test_an_unfinished_latest_verification_is_named_not_counted(db_session_mock):
    active = MagicMock(version=3, frozen_at=FROZEN, label=None, created_by="alice")
    run = MagicMock(id=uuid4())
    summary = MagicMock(status=JobStatus.RUNNING, status_label=JOB_STATUS_LABEL[JobStatus.RUNNING])
    out = _get(
        _contract_suite(), ContractState(active=active, draft=None),
        latest_verification=MagicMock(side_effect=[run, None]), summaries={run.id: summary},
    )
    assert f"Verification unavailable: the latest run of v3 active (`{run.id}`) is Running." in out


def test_the_active_version_line_names_no_author(db_session_mock):
    active = MagicMock(version=3, frozen_at=FROZEN, label=None, created_by=None)
    out = _get(_contract_suite(), ContractState(active=active, draft=None))
    assert "- **Active version:** v3 active (frozen 2026-09-12 14:03 UTC)" in out
    assert "None)" not in out


@pytest.mark.parametrize("status", [JobStatus.ERROR, JobStatus.CANCELED, JobStatus.RUNNING])
def test_an_unfinished_latest_run_falls_back_to_the_latest_completed_one(db_session_mock, status):
    active = MagicMock(version=3, frozen_at=FROZEN, label=None, created_by=None)
    newest, completed = MagicMock(id=uuid4()), MagicMock(id=uuid4())
    summaries = {
        newest.id: MagicMock(status=status, status_label=JOB_STATUS_LABEL[status]),
        completed.id: MagicMock(
            status=JobStatus.COMPLETED, status_label=JOB_STATUS_LABEL[JobStatus.COMPLETED],
            test_ct=4, passed_ct=4, failed_ct=0, warning_ct=0, error_ct=0, started_at=FROZEN,
        ),
    }
    latest_verification = MagicMock(side_effect=[newest, completed])

    out = _get(
        _contract_suite(), ContractState(active=active, draft=None),
        latest_verification=latest_verification, summaries=summaries,
    )

    assert f"- **Latest verification:** Passed — run `{completed.id}`" in out
    assert f"A newer run of v3 active (`{newest.id}`) is {JOB_STATUS_LABEL[status]}." in out
    fallback_clause = latest_verification.call_args_list[1].args[1]
    assert str(fallback_clause.compile(compile_kwargs={"literal_binds": True})) == (
        "job_executions.status = 'completed'"
    )


def test_a_regular_suite_has_no_contract_block(db_session_mock):
    suite = _contract_suite()
    suite.suite_type = SuiteType.REGULAR
    latest_verification = MagicMock()
    out = _get(suite, None, latest_verification=latest_verification)
    assert "## Contract" not in out
    latest_verification.assert_not_called()
