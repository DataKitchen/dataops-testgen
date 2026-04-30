"""MCP tools for triggering and canceling TestGen jobs."""

from sqlalchemy import select

from testgen.api.schemas import JobKey, JobSource
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import parse_uuid
from testgen.mcp.tools.markdown import MdDoc


@with_database_session
@mcp_permission("edit")
def run_tests(test_suite_id: str) -> str:
    """Submit a test run for a test suite. Returns immediately with a job_execution_id;
    use ``get_recent_test_runs`` to track status.

    Args:
        test_suite_id: UUID of the test suite to run, e.g. from ``list_test_suites``.
    """
    suite_uuid = parse_uuid(test_suite_id, "test_suite_id")

    suite = TestSuite.get_regular(suite_uuid)
    perms = get_project_permissions()
    if suite is None or not perms.has_access(suite.project_code):
        raise MCPResourceNotAccessible("Test suite", test_suite_id)

    job = JobExecution.submit(
        job_key=JobKey.run_tests,
        kwargs={"test_suite_id": str(suite.id)},
        source=JobSource.mcp,
        project_code=suite.project_code,
    )
    return _render_submission("Test run", suite.test_suite, "Test suite", job, "get_recent_test_runs")


@with_database_session
@mcp_permission("edit")
def run_profiling(table_group_id: str) -> str:
    """Submit a profiling run for a table group. Returns immediately with a job_execution_id;
    use ``list_profiling_summaries`` to track status.

    Args:
        table_group_id: UUID of the table group to profile, e.g. from ``get_data_inventory``.
    """
    group_uuid = parse_uuid(table_group_id, "table_group_id")

    table_group = TableGroup.get(group_uuid)
    perms = get_project_permissions()
    if table_group is None or not perms.has_access(table_group.project_code):
        raise MCPResourceNotAccessible("Table group", table_group_id)

    job = JobExecution.submit(
        job_key=JobKey.run_profile,
        kwargs={"table_group_id": str(table_group.id)},
        source=JobSource.mcp,
        project_code=table_group.project_code,
    )
    return _render_submission(
        "Profiling run", table_group.table_groups_name, "Table group", job, "list_profiling_summaries"
    )


@with_database_session
@mcp_permission("edit")
def generate_tests(test_suite_id: str) -> str:
    """Submit a test-generation job for a test suite. Auto-creates test definitions from the latest
    profiling results for the table group; locked and manually created test definitions are preserved.
    Returns immediately with a job_execution_id.

    Args:
        test_suite_id: UUID of the test suite to generate tests for, e.g. from ``list_test_suites``.
    """
    suite_uuid = parse_uuid(test_suite_id, "test_suite_id")

    suite = TestSuite.get_regular(suite_uuid)
    perms = get_project_permissions()
    if suite is None or not perms.has_access(suite.project_code):
        raise MCPResourceNotAccessible("Test suite", test_suite_id)

    job = JobExecution.submit(
        job_key=JobKey.run_test_generation,
        kwargs={"test_suite_id": str(suite.id), "generation_set": "Standard"},
        source=JobSource.mcp,
        project_code=suite.project_code,
    )
    return _render_submission(
        "Test generation",
        suite.test_suite,
        "Test suite",
        job,
        "list_tests",
        poll_hint="to verify the new definitions appear",
    )


@with_database_session
@mcp_permission("edit")
def cancel_test_run(job_execution_id: str) -> str:
    """Request cancellation of a queued or running test run.

    Args:
        job_execution_id: UUID of a test run, e.g. from ``get_recent_test_runs``.
    """
    return _cancel_job(job_execution_id, JobKey.run_tests, "Test run", "get_recent_test_runs")


@with_database_session
@mcp_permission("edit")
def cancel_profiling_run(job_execution_id: str) -> str:
    """Request cancellation of a queued or running profiling run.

    Args:
        job_execution_id: UUID of a profiling run, e.g. from ``list_profiling_summaries``.
    """
    return _cancel_job(job_execution_id, JobKey.run_profile, "Profiling run", "list_profiling_summaries")


def _render_submission(
    kind: str,
    scope_name: str,
    scope_label: str,
    job: JobExecution,
    poll_tool: str,
    poll_hint: str = "to track status",
) -> str:
    doc = MdDoc()
    doc.heading(1, f"{kind} submitted for `{scope_name}`")
    doc.field("Job ID", job.id, code=True)
    doc.field(scope_label, scope_name)
    doc.field("Status", "Pending")
    doc.text(f"Use `{poll_tool}` {poll_hint}.")
    return doc.render()


def _cancel_job(job_execution_id: str, expected_job_key: JobKey, kind: str, poll_tool: str) -> str:
    job_uuid = parse_uuid(job_execution_id, "job_execution_id")

    job = get_current_session().scalars(
        select(JobExecution).where(
            JobExecution.id == job_uuid,
            JobExecution.job_key == expected_job_key,
            JobExecution.source != "system",
        )
    ).first()

    perms = get_project_permissions()
    if job is None or not perms.has_access(job.project_code):
        raise MCPResourceNotAccessible(kind, job_execution_id)

    if not job.request_cancel():
        raise MCPUserError(
            f"Cannot cancel — current status is `{job.status}`. Only queued or running jobs can be canceled."
        )

    doc = MdDoc()
    doc.heading(1, f"{kind} cancellation requested")
    doc.field("Job ID", job.id, code=True)
    doc.field("Status", job.status)
    doc.text(f"Use `{poll_tool}` to confirm cancellation.")
    return doc.render()
