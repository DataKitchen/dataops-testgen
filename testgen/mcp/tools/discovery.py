from uuid import UUID

from testgen.common.models import with_database_session
from testgen.common.models.data_table import DataTable
from testgen.common.models.project import Project
from testgen.common.models.test_suite import TestSuite


@with_database_session
def get_data_inventory() -> str:
    """Get a structural inventory of all projects, connections, table groups, and test suites.

    This is the recommended starting point for understanding the data quality landscape.
    Returns a structured markdown overview of the entire TestGen configuration.
    """
    from testgen.mcp.services.inventory_service import get_inventory

    return get_inventory()


@with_database_session
def list_projects() -> str:
    """List all configured projects.

    Returns project codes and names. Use these to scope queries to specific projects.
    """
    projects = Project.select_where()

    if not projects:
        return "No projects found."

    lines = ["# Projects\n"]
    for project in projects:
        lines.append(f"- **{project.project_name}** (`{project.project_code}`)")

    return "\n".join(lines)


@with_database_session
def list_test_suites(project_code: str) -> str:
    """List all test suites for a project with their latest run statistics.

    Args:
        project_code: The project code to list test suites for.
    """
    if not project_code:
        return "Missing required parameter `project_code`."

    summaries = TestSuite.select_summary(project_code)

    if not summaries:
        return f"No test suites found for project `{project_code}`."

    lines = [f"# Test Suites for `{project_code}`\n"]
    for s in summaries:
        lines.append(f"## {s.test_suite} (id: `{s.id}`)")
        lines.append(f"- Connection: {s.connection_name}")
        lines.append(f"- Table Group: {s.table_groups_name}")
        if s.test_suite_description:
            lines.append(f"- Description: {s.test_suite_description}")
        lines.append(f"- Test definitions: {s.test_ct or 0}")

        if s.latest_run_id:
            lines.append(f"- Latest run: `{s.latest_run_id}` ({s.latest_run_start})")
            lines.append(
                f"  - {s.last_run_test_ct or 0} tests: "
                f"{s.last_run_passed_ct or 0} passed, "
                f"{s.last_run_failed_ct or 0} failed, "
                f"{s.last_run_warning_ct or 0} warnings, "
                f"{s.last_run_error_ct or 0} errors"
            )
            if s.last_run_dismissed_ct:
                lines.append(f"  - {s.last_run_dismissed_ct} dismissed")
        else:
            lines.append("- _No completed runs._")
        lines.append("")

    return "\n".join(lines)


@with_database_session
def list_tables(table_group_id: str, limit: int = 200, page: int = 1) -> str:
    """List tables in a table group.

    Args:
        table_group_id: The table group UUID.
        limit: Maximum number of tables per page (default 200).
        page: Page number, starting from 1 (default 1).
    """
    try:
        group_uuid = UUID(table_group_id)
    except (ValueError, AttributeError) as err:
        raise ValueError(f"Invalid table_group_id: `{table_group_id}` is not a valid UUID.") from err

    offset = (page - 1) * limit
    table_names = DataTable.select_table_names(group_uuid, limit=limit, offset=offset)
    total = DataTable.count_tables(group_uuid)

    if not table_names:
        if page > 1:
            return f"No tables on page {page} (total: {total})."
        return f"No tables found for table group `{table_group_id}`."

    lines = [f"# Tables in Table Group `{table_group_id}`\n"]
    lines.append(f"Total tables: {total}. Showing {len(table_names)} (page {page}).\n")

    for name in table_names:
        lines.append(f"- `{name}`")

    total_pages = (total + limit - 1) // limit
    if page < total_pages:
        lines.append(f"\n_Page {page} of {total_pages}. Use `page={page + 1}` for more._")

    return "\n".join(lines)
