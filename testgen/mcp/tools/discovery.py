from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.data_table import DataTable
from testgen.common.models.project import Project
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import resolve_table_group, validate_limit, validate_page
from testgen.mcp.tools.markdown import MdDoc


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
    MixpanelService().send_event("mcp-get-data-inventory", username=perms.username)
    return get_inventory(
        project_codes=perms.allowed_codes,
        view_project_codes=perms.codes_allowed_to("view"),
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
def list_test_suites(project_code: str) -> str:
    """List all test suites for a project with their latest run statistics.

    Args:
        project_code: The project code to list test suites for.
    """
    if not project_code:
        return "Missing required parameter `project_code`."

    perms = get_project_permissions()
    perms.verify_access(project_code, not_found=f"No test suites found for project `{project_code}`.")

    summaries = TestSuite.select_summary(project_code)

    if not summaries:
        return f"No test suites found for project `{project_code}`."

    # Batch-lookup job_execution_ids for latest runs
    run_ids = [s.latest_run_id for s in summaries if s.latest_run_id]
    job_exec_map = TestRun.get_job_execution_ids(run_ids) if run_ids else {}

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
            run_id = job_exec_map.get(s.latest_run_id) or s.latest_run_id
            doc.field("Latest run", f"`{run_id}` ({s.latest_run_start})")
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
