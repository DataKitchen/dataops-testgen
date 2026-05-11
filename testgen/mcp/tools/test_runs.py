from datetime import datetime

from testgen.common.models import with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scheduler import RUN_TESTS_JOB_KEY
from testgen.common.models.test_run import TestRun, TestRunSummary
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_page_footer,
    format_page_info,
    format_run_duration,
    next_scheduled_run,
    parse_run_status_filter,
    parse_uuid,
    resolve_table_group,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.INVESTIGATE


@with_database_session
@mcp_permission("view")
def list_test_runs(
    project_code: str | None = None,
    test_suite: str | None = None,
    table_group_id: str | None = None,
    status: str | None = None,
    limit: int = 10,
    page: int = 1,
) -> str:
    """List test runs across a project, including queued and in-progress runs. Ordered by submission
    time descending. Excludes monitor suites.

    Args:
        project_code: Project code to query, e.g. from `list_projects`. Required unless
            `table_group_id` is provided (which scopes to a single project).
        test_suite: Optional test suite name to filter by (case-sensitive).
        table_group_id: Optional UUID of a table group, e.g. from `get_data_inventory`. Returns
            runs for any suite in the group.
        status: Optional run status filter. One of: Pending, Running, Completed, Canceled, Error.
        limit: Page size (default 10, max 100).
        page: Page number starting at 1 (default 1).
    """
    validate_limit(limit, 100)
    validate_page(page)

    statuses = parse_run_status_filter(status) if status else None

    if not project_code and not table_group_id:
        raise MCPUserError("Provide either `project_code` or `table_group_id`.")

    perms = get_project_permissions()
    test_suite_id = None
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

    if test_suite:
        suites = TestSuite.select_minimal_where(
            TestSuite.project_code == project_code,
            TestSuite.test_suite == test_suite,
            TestSuite.is_monitor.isnot(True),
        )
        if not suites:
            raise MCPResourceNotAccessible("Test suite", test_suite)
        test_suite_id = str(suites[0].id)

    summaries, total = TestRun.select_summary(
        project_code=project_code,
        table_group_id=str(table_group.id) if table_group else None,
        test_suite_id=test_suite_id,
        statuses=statuses,
        page=page,
        page_size=limit,
    )

    # Queued/claimed JEs that don't yet have a test_runs row are invisible to suite/TG-scoped
    # joined-run queries. Surface them as a separate "Pending" section on page 1.
    pending_jes: list[JobExecution] = []
    if page == 1 and (test_suite_id or table_group):
        pending_jes = _select_pending_test_jes(
            project_code=project_code,
            test_suite_id=test_suite_id,
            table_group_id=str(table_group.id) if table_group else None,
            statuses=statuses,
        )

    scope_descriptor = _scope_descriptor(project_code, test_suite, table_group_id, status)
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
def get_test_run(job_execution_id: str) -> str:
    """Get a single test run with status, timing, result counts, and testing score. Returns the
    run regardless of state — including queued and in-progress runs without complete results yet.

    Args:
        job_execution_id: UUID of a test run, e.g. from `list_test_runs`.
    """
    parse_uuid(job_execution_id, "job_execution_id")
    perms = get_project_permissions()

    summaries, _ = TestRun.select_summary(job_execution_id=job_execution_id, page_size=1)
    summary = summaries[0] if summaries else None
    if summary is None or summary.project_code not in perms.allowed_codes:
        raise MCPResourceNotAccessible("Test run", job_execution_id)

    doc = MdDoc()
    suite_label = summary.test_suite or "—"
    doc.heading(1, f"Test run: {suite_label}")
    doc.field("Job ID", summary.job_execution_id, code=True)
    doc.field("Test suite", suite_label)
    if summary.table_groups_name:
        doc.field("Table group", summary.table_groups_name)
    doc.field("Project", summary.project_code)
    doc.field("Status", summary.status_label)
    doc.field("Submitted", summary.created_at)
    doc.field("Started", summary.started_at or "—")
    doc.field("Ended", summary.completed_at or "In progress")
    duration = format_run_duration(summary.started_at, summary.completed_at)
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
            doc.field("Testing Score", f"{summary.dq_score_testing:.1f}")

    if summary.error_message:
        doc.heading(2, "Error")
        doc.text(summary.error_message)

    return doc.render()


def _scope_descriptor(
    project_code: str | None,
    test_suite: str | None,
    table_group_id: str | None,
    status: str | None,
) -> str:
    parts: list[str] = []
    if project_code:
        parts.append(f"project `{project_code}`")
    if test_suite:
        parts.append(f"suite `{test_suite}`")
    if table_group_id:
        parts.append(f"table group `{table_group_id}`")
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
                TestSuite.is_monitor.isnot(True),
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
    statuses,
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
                TestSuite.is_monitor.isnot(True),
            )
        ]
        if not suite_ids:
            return []
    else:
        return []
    return JobExecution.select_active_by_kwargs(
        project_code=project_code,
        job_key=RUN_TESTS_JOB_KEY,
        kwargs_match={"test_suite_id": suite_ids},
        statuses=statuses,
    )


def _render_pending_je(doc: MdDoc, je: JobExecution, label: str) -> None:
    status_label = TestRunSummary.STATUS_LABEL.get(je.status, je.status)
    doc.heading(3, f"{label} — {status_label}")
    doc.field("Job ID", je.id, code=True)
    doc.field("Submitted", je.created_at)
    doc.field("Started", je.started_at or "—")
    doc.field("Ended", je.completed_at or "In progress")


def _render_test_run_section(doc: MdDoc, run: TestRunSummary) -> None:
    title = run.test_suite or run.project_code
    doc.heading(2, f"{title} — {run.status_label}")
    doc.field("Job ID", run.job_execution_id, code=True)
    if run.test_suite:
        doc.field("Test suite", run.test_suite)
    if run.table_groups_name:
        doc.field("Table group", run.table_groups_name)
    doc.field("Submitted", run.created_at)
    doc.field("Started", run.started_at or "—")
    doc.field("Ended", run.completed_at or "In progress")
    duration = format_run_duration(run.started_at, run.completed_at)
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
        doc.field("Testing Score", f"{run.dq_score_testing:.1f}")
