from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.common.models.test_suite import TestSuite


@with_database_session
def get_data_inventory() -> str:
    """Get a complete inventory of all projects, connections, table groups, and test suites with their latest run status.

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
