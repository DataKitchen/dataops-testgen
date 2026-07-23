from testgen.common.models import with_database_session
from testgen.common.models.data_table import DataTable
from testgen.common.models.project import Project
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_flavor_label,
    resolve_connection,
    resolve_table_group,
    resolve_test_suite,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.DISCOVER


@with_database_session
@mcp_permission("catalog")
def get_data_inventory() -> str:
    """Get a structural inventory of all projects, connections, table groups, and test suites
    accessible to the authenticated user.

    This is the recommended starting point for understanding the data quality landscape.
    Returns a structured markdown overview of the TestGen configuration.
    """
    from testgen.mcp.services.inventory_service import get_inventory

    perms = get_project_permissions()
    return get_inventory(
        project_codes=perms.allowed_codes,
        view_project_codes=perms.codes_allowed_to("view"),
        username=perms.username,
        is_global_admin=perms.is_global_admin,
        roles_by_code=perms.memberships,
    )


@with_database_session
@mcp_permission("catalog")
def list_projects() -> str:
    """List all projects the authenticated user has access to.

    Returns project codes and names. Use these to scope queries to specific projects.
    """
    perms = get_project_permissions()
    projects = [p for p in Project.select_where() if perms.has_access(p.project_code)]

    if not projects:
        return "No projects found."

    doc = MdDoc()
    doc.heading(1, "Projects")
    for project in projects:
        doc.field(project.project_name, project.project_code, code=True)

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_project(project_code: str) -> str:
    """Get a project's configuration and configuration counts.

    Returns the project name, observability and data-retention settings, and counts
    of connections, table groups, test suites, test definitions, profiling runs, and
    test runs scoped to the project. Use this before configuration changes to confirm
    a project's current shape.

    Args:
        project_code: The project code, e.g. from `list_projects`.
    """
    perms = get_project_permissions()
    perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))

    project = Project.get(project_code)
    summary = Project.get_summary(project_code)
    if project is None or summary is None:
        raise MCPResourceNotAccessible("Project", project_code)

    doc = MdDoc()
    doc.heading(1, f"Project `{project_code}`")
    doc.field("Name", project.project_name)
    doc.field("Connections", summary.connection_count)
    doc.field("Table groups", summary.table_group_count)
    doc.field("Test suites", summary.test_suite_count)
    doc.field("Test definitions", summary.test_definition_count)
    doc.field("Profiling runs", summary.profiling_run_count)
    doc.field("Test runs", summary.test_run_count)

    doc.heading(2, "Configuration")
    doc.field("Weighted data quality scoring", project.use_dq_score_weights)

    doc.heading(2, "Observability Integration")
    doc.field("Configured", summary.can_export_to_observability)
    if project.observability_api_url:
        doc.field("API URL", project.observability_api_url, code=True)

    doc.heading(2, "Data Retention")
    doc.field("Automatically delete old profiling and test history", project.data_retention_enabled)
    if project.data_retention_enabled and project.data_retention_days is not None:
        doc.field("Delete history older than (days)", project.data_retention_days)

    return doc.render()


@with_database_session
@mcp_permission("view")
def list_test_suites(project_code: str) -> str:
    """List all test suites for a project with their latest run statistics.

    Args:
        project_code: The project code to list test suites for.
    """
    if not project_code:
        return "Missing required parameter `project_code`."

    perms = get_project_permissions()
    perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))

    summaries = TestSuite.select_summary(project_code)

    if not summaries:
        return f"No test suites found for project `{project_code}`."

    doc = MdDoc()
    doc.heading(1, f"Test Suites for `{project_code}`")
    for s in summaries:
        doc.heading(2, f"{s.test_suite} (id: `{s.id}`)")
        doc.field("Connection", s.connection_name)
        doc.field("Table Group", s.table_groups_name)
        if s.test_suite_description:
            doc.field("Description", s.test_suite_description)
        doc.field("Test definitions", s.test_ct or 0)

        if s.latest_run_id:
            doc.field("Latest run", f"`{s.latest_run_id}` ({s.latest_run_start})")
            results_summary = (
                f"{s.last_run_test_ct or 0} tests: "
                f"{s.last_run_passed_ct or 0} passed, "
                f"{s.last_run_failed_ct or 0} failed, "
                f"{s.last_run_warning_ct or 0} warnings, "
                f"{s.last_run_error_ct or 0} errors"
            )
            doc.field("Results", results_summary)
            if s.last_run_dismissed_ct:
                doc.field("Dismissed", s.last_run_dismissed_ct)
        else:
            doc.text("_No completed runs._")

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_test_suite(test_suite_id: str) -> str:
    """Get a test suite's configuration: connection, table group, default severity, and per-test-type counts.

    Returns the test suite's identity and configuration along with a breakdown of how many test
    definitions it contains by type and how many are locked (excluded from regeneration).
    Use this before changing a suite's tests to understand what will be affected.

    Args:
        test_suite_id: The test suite UUID, e.g. from `list_test_suites`.
    """
    suite = resolve_test_suite(test_suite_id)
    # Defense in depth: resolve via perm-filtered helpers rather than `Model.get(...)`.
    # FK constraints guarantee same-project today; the resolvers are the established wrapper
    # for project-scoped lookups and keep us aligned if those guarantees ever change.
    connection = resolve_connection(suite.connection_id) if suite.connection_id else None
    table_group = resolve_table_group(str(suite.table_groups_id)) if suite.table_groups_id else None
    stats = TestSuite.test_definition_stats(suite.id)

    doc = MdDoc()
    doc.heading(1, f"Test Suite `{suite.test_suite}`")
    doc.field("ID", str(suite.id), code=True)
    doc.field("Project", suite.project_code, code=True)

    if connection is not None:
        doc.field(
            "Connection",
            f"{connection.connection_name} (`{connection.connection_id}`, {format_flavor_label(connection.sql_flavor_code)})",
        )
    if table_group is not None:
        doc.field(
            "Table group",
            f"{table_group.table_groups_name} (`{table_group.id}`)",
        )

    if suite.test_suite_description:
        doc.field("Description", suite.test_suite_description)
    doc.field("Default severity", suite.severity or "Inherit from test type")
    doc.field("Export to observability", suite.export_to_observability)

    doc.field("Total tests", stats.total)
    doc.field("Locked tests", stats.locked)

    if stats.counts_by_type:
        doc.heading(2, "Tests by type")
        rows = [[type_label, count] for type_label, count in stats.counts_by_type.items()]
        doc.table(["Test", "Count"], rows)

    return doc.render()


@with_database_session
@mcp_permission("catalog")
def list_tables(table_group_id: str, limit: int = 200, page: int = 1) -> str:
    """List tables in a table group.

    Args:
        table_group_id: The table group UUID.
        limit: Maximum number of tables per page (default 200, max 500).
        page: Page number, starting from 1 (default 1).
    """
    validate_page(page)
    validate_limit(limit, 500)

    tg = resolve_table_group(table_group_id)
    project_codes = [tg.project_code]

    offset = (page - 1) * limit
    table_names = DataTable.select_table_names(tg.id, limit=limit, offset=offset, project_codes=project_codes)
    total = DataTable.count_tables(tg.id, project_codes=project_codes)

    if not table_names:
        if page > 1:
            return f"No tables on page {page} (total: {total})."
        return f"No tables found for table group `{table_group_id}`."

    doc = MdDoc()
    doc.heading(1, f"Tables in Table Group `{table_group_id}`")
    doc.text(f"Total tables: {total}. Showing {len(table_names)} (page {page}).")
    doc.bullets([f"`{name}`" for name in table_names])

    total_pages = (total + limit - 1) // limit
    if page < total_pages:
        doc.text(f"_Page {page} of {total_pages}. Use `page={page + 1}` for more._")

    return doc.render()
