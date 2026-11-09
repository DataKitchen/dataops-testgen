from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from testgen.common.enums import JobKey, JobStatus
from testgen.common.models import with_database_session
from testgen.common.models.job_execution import QUEUED_MESSAGE, JobExecution
from testgen.common.models.scheduler import RUN_TESTS_JOB_KEY
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun, TestRunSummary
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    MCP_SUITE_TYPES,
    DocGroup,
    format_page_footer,
    format_page_info,
    format_run_duration,
    next_scheduled_run,
    parse_run_status_filter,
    parse_uuid,
    resolve_contract_version,
    resolve_table_group,
    resolve_test_suite,
    run_status_filter_options,
    target_db_error_text,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.utils import friendly_score

_DOC_GROUP = DocGroup.INVESTIGATE


@with_database_session
@mcp_permission("view")
def list_test_runs(
    project_code: Annotated[
        str | None,
        Field(
            description="Project code to query, e.g. from `list_projects`. Required unless `table_group_id` is "
            "provided (which scopes to a single project).",
        ),
    ] = None,
    test_suite: Annotated[
        str | None,
        Field(description="Optional test suite name to filter by (case-sensitive)."),
    ] = None,
    test_suite_id: Annotated[
        str | None,
        Field(description="Optional UUID of a test suite to filter by, e.g. from `list_test_suites`. Supply this "
              "or `test_suite`, not both."),
    ] = None,
    table_group_id: Annotated[
        str | None,
        Field(
            description="Optional UUID of a table group, e.g. from `get_data_inventory`. Returns runs for any suite in "
            "the group.",
        ),
    ] = None,
    schedule_id: Annotated[
        str | None,
        Field(
            description="Optional UUID of a schedule, e.g. from `list_schedules`. Returns only runs triggered by that "
            "schedule.",
        ),
    ] = None,
    status: Annotated[
        str | None,
        Field(description=f"Optional run status filter. One of: {run_status_filter_options(JobKey.run_tests)}."),
    ] = None,
    version: Annotated[
        int | None,
        Field(
            description="Contract version number, e.g. from `list_contract_versions`. Requires `test_suite` or "
            "`test_suite_id`. "
            "Returns only that version's runs.",
        ),
    ] = None,
    limit: Annotated[int, Field(description="Page size (default 10, max 100).")] = 10,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """List test runs across a project, including queued and in-progress runs.
    Ordered by submission time descending. Excludes monitor suites.
    """
    validate_limit(limit, 100)
    validate_page(page)

    statuses = parse_run_status_filter(status, JobKey.run_tests) if status else None
    if schedule_id:
        parse_uuid(schedule_id, "schedule_id")

    if test_suite and test_suite_id:
        raise MCPUserError("Supply `test_suite` or `test_suite_id`, not both.")
    suite_table_group_id = None
    if test_suite_id:
        suite = resolve_test_suite(test_suite_id)
        test_suite_id = str(suite.id)
        test_suite = suite.test_suite
        suite_table_group_id = suite.table_groups_id
        if project_code and project_code != suite.project_code:
            raise MCPUserError(f"`project_code` `{project_code}` does not match the test suite's project.")
        project_code = suite.project_code
    if not project_code and not table_group_id:
        raise MCPUserError("Provide either `project_code` or `table_group_id`.")
    if version is not None and not test_suite:
        raise MCPUserError(
            "`version` needs `test_suite` or `test_suite_id`: a version number belongs to one contract."
        )

    perms = get_project_permissions()
    table_group = None

    if table_group_id:
        table_group = resolve_table_group(table_group_id)
        if project_code and project_code != table_group.project_code:
            raise MCPUserError(
                f"`project_code` `{project_code}` does not match the table group's project."
            )
        project_code = table_group.project_code
    else:
        perms.verify_access(
            project_code,
            not_found=MCPResourceNotAccessible("Project", project_code),
        )

    if test_suite and not test_suite_id:
        suites = TestSuite.select_minimal_where(
            TestSuite.project_code == project_code,
            TestSuite.test_suite == test_suite,
            TestSuite.suite_type.in_(MCP_SUITE_TYPES),
        )
        if not suites:
            raise MCPResourceNotAccessible("Test suite", test_suite)
        test_suite_id = str(suites[0].id)
        suite_table_group_id = suites[0].table_groups_id
    if table_group and suite_table_group_id and suite_table_group_id != table_group.id:
        raise MCPUserError(f"Test suite `{test_suite}` is not in table group `{table_group.table_groups_name}`.")

    target = None
    if version is not None:
        target = resolve_contract_version(TestSuite.get(test_suite_id), version)

    summaries, total = TestRun.select_summary(
        project_code=project_code,
        table_group_id=str(table_group.id) if table_group else None,
        test_suite_id=test_suite_id,
        schedule_id=schedule_id,
        statuses=statuses,
        page=page,
        page_size=limit,
        suite_types=MCP_SUITE_TYPES,
        version_id=str(target.id) if target else None,
    )

    # Queued/claimed JEs that don't yet have a test_runs row are invisible to suite/TG-scoped
    # joined-run queries. Surface them as a separate "Pending" section on page 1.
    pending_jes: list[JobExecution] = []
    if page == 1 and (test_suite_id or table_group):
        pending_jes = _select_pending_test_jes(
            project_code=project_code,
            test_suite_id=test_suite_id,
            table_group_id=str(table_group.id) if table_group else None,
            schedule_id=schedule_id,
            statuses=statuses,
            version_id=str(target.id) if target else None,
        )

    scope_descriptor = _scope_descriptor(project_code, test_suite, table_group_id, schedule_id, status)
    doc = MdDoc()
    doc.heading(1, f"Test runs{scope_descriptor}")

    next_run = _next_test_run(
        project_code=project_code,
        test_suite_id=test_suite_id,
        table_group_id=str(table_group.id) if table_group else None,
    )
    if next_run:
        doc.field("Next scheduled run", next_run)

    if pending_jes:
        doc.heading(2, f"Pending ({len(pending_jes)})")
        for je in pending_jes:
            _render_pending_je(doc, je, label=test_suite or "Test run")

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    if not summaries:
        if page > 1:
            doc.text(f"_No test runs on page {page} (total: {total})._")
        elif not pending_jes:
            doc.text("_No test runs found._")
        return doc.render()

    for run in summaries:
        _render_test_run_section(doc, run)

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_test_run(
    job_execution_id: Annotated[str, Field(description="UUID of a test run, e.g. from `list_test_runs`.")],
) -> str:
    """Get a single test run with status, timing, result counts, and testing score.
    Returns the run regardless of state — including queued and in-progress runs without
    complete results yet.
    """
    parse_uuid(job_execution_id, "job_execution_id")
    perms = get_project_permissions()

    summaries, _ = TestRun.select_summary(
        job_execution_id=job_execution_id, page_size=1, suite_types=MCP_SUITE_TYPES
    )
    summary = summaries[0] if summaries else None
    if summary is None or summary.project_code not in perms.allowed_codes:
        raise MCPResourceNotAccessible("Test run", job_execution_id)

    suite_name, table_group_name = summary.test_suite, summary.table_groups_name
    if summary.test_run_id is None:
        suite_name, table_group_name = _pending_run_scope(summary.job_execution_id)

    doc = MdDoc()
    suite_label = suite_name or "—"
    doc.heading(1, f"Test run: {suite_label}")
    doc.field("Test Run", summary.job_execution_id, code=True)
    doc.field("Test suite", suite_label)
    if table_group_name:
        doc.field("Table group", table_group_name)
    doc.field("Project", summary.project_code)
    doc.field("Status", summary.status_label)
    if summary.status == JobStatus.QUEUED:
        doc.text(QUEUED_MESSAGE)
    doc.field("Submitted", summary.created_at)
    doc.field("Started", summary.started_at or "—")
    doc.field("Ended", summary.completed_at or "In progress")
    _render_run_version(doc, summary)
    duration = format_run_duration(summary.active_seconds, summary.status)
    if duration:
        doc.field("Duration", duration)

    has_results = summary.test_ct or summary.passed_ct or summary.failed_ct or summary.warning_ct or summary.error_ct
    if has_results:
        passed = summary.passed_ct or 0
        failed = summary.failed_ct or 0
        warning = summary.warning_ct or 0
        errors = summary.error_ct or 0
        doc.field(
            "Results",
            f"{summary.test_ct or 0} tests — {passed} passed, {failed} failed, {warning} warnings, {errors} errors",
        )
        if summary.dismissed_ct:
            doc.field("Dismissed", summary.dismissed_ct)
        if summary.dq_score_testing is not None:
            doc.field("Testing Score", friendly_score(summary.dq_score_testing))

    if summary.error_message:
        doc.heading(2, "Error")
        doc.text(target_db_error_text(summary.error_message))

    return doc.render()


def _pending_run_scope(job_execution_id: UUID) -> tuple[str | None, str | None]:
    """Return the suite and table group names of a test run that has no run record yet, from its job's arguments.

    Raises MCPResourceNotAccessible when the job targets a suite kind MCP does not serve.
    """
    job = JobExecution.get(job_execution_id)
    suite = TestSuite.get(job.kwargs.get("test_suite_id", "")) if job else None
    if suite is None:
        return None, None
    if suite.suite_type not in MCP_SUITE_TYPES:
        raise MCPResourceNotAccessible("Test run", str(job_execution_id))
    table_group = TableGroup.get(suite.table_groups_id)
    return suite.test_suite, table_group.table_groups_name if table_group else None


def _scope_descriptor(
    project_code: str | None,
    test_suite: str | None,
    table_group_id: str | None,
    schedule_id: str | None,
    status: str | None,
) -> str:
    parts: list[str] = []
    if project_code:
        parts.append(f"project `{project_code}`")
    if test_suite:
        parts.append(f"suite `{test_suite}`")
    if table_group_id:
        parts.append(f"table group `{table_group_id}`")
    if schedule_id:
        parts.append(f"schedule `{schedule_id}`")
    if status:
        parts.append(f"status `{status}`")
    return f" — {', '.join(parts)}" if parts else ""


def _next_test_run(
    project_code: str | None,
    test_suite_id: str | None,
    table_group_id: str | None,
) -> datetime | None:
    """Compute the next scheduled test run when scoped to a single suite or table group."""
    if not project_code:
        return None
    if test_suite_id:
        return next_scheduled_run(RUN_TESTS_JOB_KEY, {"test_suite_id": test_suite_id}, project_code)
    if table_group_id:
        suite_ids = [
            str(s.id)
            for s in TestSuite.select_minimal_where(
                TestSuite.project_code == project_code,
                TestSuite.table_groups_id == table_group_id,
                TestSuite.suite_type.in_(MCP_SUITE_TYPES),
            )
        ]
        candidates = [
            next_scheduled_run(RUN_TESTS_JOB_KEY, {"test_suite_id": sid}, project_code)
            for sid in suite_ids
        ]
        candidates = [c for c in candidates if c is not None]
        return min(candidates) if candidates else None
    return None


def _select_pending_test_jes(
    *,
    project_code: str,
    test_suite_id: str | None,
    table_group_id: str | None,
    schedule_id: str | None,
    statuses,
    version_id: str | None = None,
) -> list[JobExecution]:
    """Find queued/in-flight test-run JEs for a given suite or table group scope. For a
    table-group scope, expands to the non-monitor suites in the group so monitor runs stay
    excluded.
    """
    if test_suite_id:
        suite_ids: str | list[str] = test_suite_id
    elif table_group_id:
        suite_ids = [
            str(s.id)
            for s in TestSuite.select_minimal_where(
                TestSuite.project_code == project_code,
                TestSuite.table_groups_id == table_group_id,
                TestSuite.suite_type.in_(MCP_SUITE_TYPES),
            )
        ]
        if not suite_ids:
            return []
    else:
        return []
    clauses = [JobExecution.job_schedule_id == schedule_id] if schedule_id else []
    kwargs_match: dict[str, str | list[str]] = {"test_suite_id": suite_ids}
    if version_id:
        kwargs_match["version_id"] = version_id
    return JobExecution.select_active_by_kwargs(
        *clauses,
        project_code=project_code,
        job_key=RUN_TESTS_JOB_KEY,
        kwargs_match=kwargs_match,
        statuses=statuses,
    )


def _render_pending_je(doc: MdDoc, je: JobExecution, label: str) -> None:
    status_label = TestRunSummary.STATUS_LABEL.get(je.status, je.status)
    doc.heading(3, f"{label} — {status_label}")
    if je.status == JobStatus.QUEUED:
        doc.text(QUEUED_MESSAGE)
    doc.field("Test Run", je.id, code=True)
    if je.job_schedule_id is not None:
        doc.field("Schedule", je.job_schedule_id, code=True)
    doc.field("Submitted", je.created_at)
    doc.field("Started", je.started_at or "—")
    doc.field("Ended", je.completed_at or "In progress")


def _render_test_run_section(doc: MdDoc, run: TestRunSummary) -> None:
    title = run.test_suite or run.project_code
    doc.heading(2, f"{title} — {run.status_label}")
    doc.field("Test Run", run.job_execution_id, code=True)
    if run.job_schedule_id is not None:
        doc.field("Schedule", run.job_schedule_id, code=True)
    if run.test_suite:
        doc.field("Test suite", run.test_suite)
    if run.table_groups_name:
        doc.field("Table group", run.table_groups_name)
    doc.field("Submitted", run.created_at)
    doc.field("Started", run.started_at or "—")
    doc.field("Ended", run.completed_at or "In progress")
    _render_run_version(doc, run)
    duration = format_run_duration(run.active_seconds, run.status)
    if duration:
        doc.field("Duration", duration)

    passed = run.passed_ct or 0
    failed = run.failed_ct or 0
    warning = run.warning_ct or 0
    errors = run.error_ct or 0
    if run.test_ct or passed or failed or warning or errors:
        doc.field(
            "Results",
            f"{run.test_ct or 0} tests — {passed} passed, {failed} failed, {warning} warnings, {errors} errors",
        )

    if run.dismissed_ct:
        doc.field("Dismissed", run.dismissed_ct)
    if run.dq_score_testing is not None:
        doc.field("Testing Score", friendly_score(run.dq_score_testing))


def _render_run_version(doc: MdDoc, run: TestRunSummary) -> None:
    """Add the contract version a run checked and, when the run does not count as the contract's status, why."""
    if run.version_label is None:
        return
    doc.field("Version", run.version_label)
    if run.is_preview:
        doc.field("Preview", "Yes")
        return
    if run.is_out_of_force:
        doc.field("Out of force", "Yes")
    run_version = run.run_version
    if not run_version.checked_version_in_force:
        doc.field("Counts as contract status", "No, a later version was already frozen when it ran")
    elif run_version.status not in JobStatus.terminal():
        doc.field("Counts as contract status", "Not yet, the run has not completed")
    elif not run_version.counts_as_status:
        doc.field("Counts as contract status", "No, the run did not complete")
