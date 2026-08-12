"""MCP tools for triggering and canceling TestGen jobs."""

from typing import Annotated

from pydantic import Field
from sqlalchemy import select

from testgen.common.enums import JOB_STATUS_LABEL, JobKey, JobSource
from testgen.common.generation_set_service import resolve_generation_sets
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import DocGroup, parse_uuid, resolve_table_group, resolve_test_suite

_DOC_GROUP = DocGroup.TRIGGER
from testgen.mcp.tools.markdown import MdDoc


@with_database_session
@mcp_permission("edit")
def run_tests(
    test_suite_id: Annotated[str, Field(description="UUID of the test suite to run, e.g. from ``list_test_suites``.")],
) -> str:
    """Submit a test run for a test suite. Returns immediately with a job_execution_id;
    use ``list_test_runs`` to track status.
    """
    suite = resolve_test_suite(test_suite_id)
    job = JobExecution.submit(
        job_key=JobKey.run_tests,
        kwargs={"test_suite_id": str(suite.id)},
        source=JobSource.mcp,
        project_code=suite.project_code,
    )
    return _render_submission("Test run", suite.test_suite, "Test suite", job, "list_test_runs")


@with_database_session
@mcp_permission("edit")
def run_profiling(
    table_group_id: Annotated[
        str,
        Field(description="UUID of the table group to profile, e.g. from ``get_data_inventory``."),
    ],
) -> str:
    """Submit a profiling run for a table group.
    Returns immediately with a job_execution_id; use ``list_profiling_summaries`` to
    track status.
    """
    table_group = resolve_table_group(table_group_id)
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
def generate_tests(
    test_suite_id: Annotated[
        str,
        Field(description="UUID of the test suite to generate tests for, e.g. from ``list_test_suites``."),
    ],
    generation_sets: Annotated[
        list[str] | None,
        Field(description="Generation set names, e.g. from ``testgen://generation-sets``."),
    ] = None,
) -> str:
    """Submit a test-generation job for a test suite.
    Auto-creates test definitions from the latest profiling results for the table group;
    locked and manually created test definitions are preserved. Returns immediately with
    a job_execution_id.

    Generation sets scope which test types are created. Omit them to use the test suite's stored
    generation sets. Read ``testgen://generation-sets`` for the available sets and the test types
    each one covers. Test types outside the selected sets are deleted unless they are locked.
    """
    suite = resolve_test_suite(test_suite_id)
    try:
        resolved_sets = resolve_generation_sets(suite, generation_sets)
    except ValueError as error:
        raise MCPUserError(str(error)) from error

    job = JobExecution.submit(
        job_key=JobKey.run_test_generation,
        kwargs={"test_suite_id": str(suite.id), "generation_sets": resolved_sets},
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
def cancel_test_run(
    job_execution_id: Annotated[str, Field(description="UUID of a test run, e.g. from ``list_test_runs``.")],
) -> str:
    """Request cancellation of a queued or running test run."""
    job = _resolve_job_execution(job_execution_id, JobKey.run_tests, "Test run")
    return _render_cancel(job, "Test run", "list_test_runs")


@with_database_session
@mcp_permission("edit")
def cancel_profiling_run(
    job_execution_id: Annotated[
        str,
        Field(description="UUID of a profiling run, e.g. from ``list_profiling_summaries``."),
    ],
) -> str:
    """Request cancellation of a queued or running profiling run."""
    job = _resolve_job_execution(job_execution_id, JobKey.run_profile, "Profiling run")
    return _render_cancel(job, "Profiling run", "list_profiling_summaries")


def _resolve_job_execution(job_execution_id: str, expected_job_key: JobKey, kind: str) -> JobExecution:
    """Resolve a user-submitted job by ID + expected job_key, collapsing missing-or-inaccessible
    into one error path. Each MCP tool pins ``expected_job_key`` to a public kind, so the
    job_key match alone restricts the lookup to externally-visible jobs.
    """
    job_uuid = parse_uuid(job_execution_id, "job_execution_id")
    perms = get_project_permissions()
    job = get_current_session().scalars(
        select(JobExecution).where(
            JobExecution.id == job_uuid,
            JobExecution.job_key == expected_job_key,
            JobExecution.project_code.in_(perms.allowed_codes),
        )
    ).first()
    if job is None:
        raise MCPResourceNotAccessible(kind, job_execution_id)
    return job


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
    doc.field(kind.title(), job.id, code=True)
    doc.field(scope_label, scope_name)
    doc.field("Status", "Pending")
    doc.text(f"Use `{poll_tool}` {poll_hint}.")
    return doc.render()


def _render_cancel(job: JobExecution, kind: str, poll_tool: str) -> str:
    if not job.request_cancel():
        status_label = JOB_STATUS_LABEL.get(job.status, job.status)
        raise MCPUserError(
            f"Cannot cancel — current status is {status_label}. Only queued or running jobs can be canceled."
        )
    doc = MdDoc()
    doc.heading(1, f"{kind} cancellation requested")
    doc.field(kind.title(), job.id, code=True)
    doc.field("Status", JOB_STATUS_LABEL.get(job.status, job.status))
    doc.text(f"Use `{poll_tool}` to confirm cancellation.")
    return doc.render()
