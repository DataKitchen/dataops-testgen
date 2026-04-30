from datetime import UTC, datetime, timedelta

from testgen.common.models import with_database_session
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_result import BucketInterval, TestResult, TestResultStatus
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    format_page_footer,
    format_page_info,
    parse_result_status,
    parse_since_arg,
    parse_uuid,
    resolve_test_type,
)
from testgen.mcp.tools.markdown import MdDoc

_DEFAULT_SEARCH_STATUSES = [TestResultStatus.Failed, TestResultStatus.Warning]


@with_database_session
@mcp_permission("view")
def list_test_results(
    job_execution_id: str | None = None,
    test_suite_id: str | None = None,
    status: str | None = None,
    table_name: str | None = None,
    test_type: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> str:
    """List individual test results for a test run, with optional filters.

    Provide either ``job_execution_id`` for a specific run, or ``test_suite_id`` to use
    the latest completed run of that suite.

    Args:
        job_execution_id: UUID of a test run, e.g. from ``get_recent_test_runs`` or
            ``list_test_suites``.
        test_suite_id: UUID of a test suite. Resolves to the latest completed test run
            for the suite. Mutually exclusive with ``job_execution_id``.
        status: Filter by result status (Passed, Failed, Warning, Error, Log).
        table_name: Filter by table name.
        test_type: Filter by test type (e.g. 'Alpha Truncation', 'Unique Percent').
        limit: Maximum number of results per page (default 50).
        page: Page number, starting from 1 (default 1).
    """
    if job_execution_id and test_suite_id:
        raise MCPUserError("Pass either `job_execution_id` or `test_suite_id`, not both.")
    if not job_execution_id and not test_suite_id:
        raise MCPUserError("Provide either `job_execution_id` or `test_suite_id`.")

    perms = get_project_permissions()

    resolved_via_suite = False
    if test_suite_id:
        suite_uuid = parse_uuid(test_suite_id, "test_suite_id")
        suite = TestSuite.get_regular(suite_uuid)
        if suite is None or not perms.has_access(suite.project_code):
            raise MCPResourceNotAccessible("Test suite", test_suite_id)
        if suite.last_complete_test_run_id is None:
            raise MCPUserError(f"No completed test runs found for test suite `{test_suite_id}`.")
        test_run = TestRun.get_by_id_or_job(suite.last_complete_test_run_id)
        if test_run is None:
            raise MCPUserError(f"No completed test runs found for test suite `{test_suite_id}`.")
        resolved_via_suite = True
        run_id_label = str(test_run.job_execution_id)
    else:
        job_uuid = parse_uuid(job_execution_id, "job_execution_id")
        test_run = TestRun.get_by_id_or_job(job_uuid)
        suite = TestSuite.get_regular(test_run.test_suite_id) if test_run else None
        if test_run is None or suite is None or not perms.has_access(suite.project_code):
            raise MCPResourceNotAccessible("Test run", job_execution_id)
        run_id_label = job_execution_id

    status_enum = parse_result_status(status) if status else None
    offset = (page - 1) * limit
    test_type_code = resolve_test_type(test_type) if test_type else None

    results = TestResult.select_results(
        test_run_id=test_run.id,
        status=status_enum,
        table_name=table_name,
        test_type=test_type_code,
        limit=limit,
        offset=offset,
        project_codes=perms.allowed_codes,
    )

    if not results:
        filters = []
        if status:
            filters.append(f"status={status}")
        if table_name:
            filters.append(f"table={table_name}")
        if test_type:
            filters.append(f"type={test_type}")
        filter_str = f" (filters: {', '.join(filters)})" if filters else ""
        return f"No test results found for run `{run_id_label}`{filter_str}."

    type_names = {tt.test_type: tt.test_name_short for tt in TestType.select_where(TestType.active == "Y")}

    doc = MdDoc()
    doc.heading(1, f"Test Results for run `{run_id_label}`")
    if resolved_via_suite:
        doc.text(f"_Latest completed run of test suite `{test_suite_id}`._")
    doc.text(f"Showing {len(results)} result(s) (page {page}).")

    for r in results:
        status_str = r.status.value if r.status else "Unknown"
        test_name = type_names.get(r.test_type, r.test_type)
        if r.column_names:
            doc.heading(2, f"[{status_str}] {test_name} on `{r.column_names}` in `{r.table_name}`")
        else:
            doc.heading(2, f"[{status_str}] {test_name} on `{r.table_name}`")
        doc.field("Test definition", r.test_definition_id, code=True)
        if r.column_names:
            doc.field("Column", r.column_names, code=True)
        if r.result_measure is not None:
            doc.field("Measured value", r.result_measure)
        if r.threshold_value is not None:
            doc.field("Threshold", r.threshold_value)
        if r.message:
            doc.field("Message", r.message)

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_failure_summary(
    *,
    project_code: str | None = None,
    test_suite_id: str | None = None,
    job_execution_id: str | None = None,
    since: str | None = None,
    group_by: str = "test_type",
) -> str:
    """Summarize test failures (Failed and Warning) grouped by test type, table, or column.

    Supply a ``job_execution_id`` for a single-run summary. Alternatively, provide
    ``test_suite_id`` or ``project_code`` to aggregate across multiple runs. Use
    ``since`` to narrow the results by recency (required when ``test_suite_id`` is
    not provided).

    Table- and column-grouped summaries require a single-suite scope
    (``job_execution_id`` or ``test_suite_id``).

    Args:
        project_code: Scope to a project the caller can view. Ignored if ``job_execution_id`` is set.
        test_suite_id: UUID of a test suite to scope the aggregation to.
        job_execution_id: UUID of a test run, e.g. from ``get_recent_test_runs``,
            to scope the summary to a single run.
        since: Include runs since this point in time — e.g. '7 days', '2 weeks', '2026-04-01'.
        group_by: Group failures by 'test_type', 'table', or 'column' (default: 'test_type').
    """
    perms = get_project_permissions()

    if not any((job_execution_id, test_suite_id, since)):
        raise MCPUserError(
            "Provide 'job_execution_id' for a single run, or 'test_suite_id' or 'project_code' "
            "to aggregate across runs. 'since' is required when 'test_suite_id' is not provided."
        )
    if group_by in ("table", "column") and not (job_execution_id or test_suite_id):
        raise MCPUserError(
            f"'{group_by}' grouping requires a single-suite scope. "
            "Provide 'job_execution_id' or 'test_suite_id'."
        )

    model_group_map = {"table": "table_name", "column": "column_names"}
    model_group_by = model_group_map.get(group_by, group_by)

    scope_label: str
    test_run_id = None
    test_suite_uuid = parse_uuid(test_suite_id, "test_suite_id") if test_suite_id else None
    since_date = parse_since_arg(since) if since else None

    if job_execution_id:
        job_uuid = parse_uuid(job_execution_id, "job_execution_id")
        test_run = TestRun.get_by_id_or_job(job_uuid)
        suite = TestSuite.get_regular(test_run.test_suite_id) if test_run else None
        if test_run is None or suite is None or not perms.has_access(suite.project_code):
            raise MCPResourceNotAccessible("Test run", job_execution_id)
        test_run_id = test_run.id
        scope_label = f"run `{job_execution_id}`"
        project_codes = perms.allowed_codes
    else:
        if project_code:
            perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))
            project_codes = [project_code]
        else:
            project_codes = perms.allowed_codes
        if test_suite_uuid is not None:
            suite = TestSuite.get_regular(test_suite_uuid)
            if suite is None or not perms.has_access(suite.project_code):
                raise MCPResourceNotAccessible("Test suite", test_suite_id)
        scope_parts = []
        if project_code:
            scope_parts.append(f"project `{project_code}`")
        if test_suite_id:
            scope_parts.append(f"suite `{test_suite_id}`")
        if since:
            scope_parts.append(f"since {since}")
        scope_label = ", ".join(scope_parts) or "accessible projects"

    failures = TestResult.select_failures(
        test_run_id=test_run_id,
        group_by=model_group_by,
        project_codes=project_codes,
        test_suite_id=test_suite_uuid,
        since=since_date,
    )

    if not failures:
        return f"No confirmed failures found for {scope_label}."

    total = sum(row[-1] for row in failures)
    if group_by == "test_type":
        type_names = {tt.test_type: tt.test_name_short for tt in TestType.select_where(TestType.active == "Y")}

    doc = MdDoc()
    doc.heading(1, f"Failure Summary — {scope_label}")
    doc.text(f"**Total confirmed failures (Failed + Warning):** {total}")

    if group_by == "test_type":
        headers = ["Test Type", "Severity", "Count"]
        rows = []
        for row in failures:
            code, status, count = row[0], row[1], row[-1]
            name = type_names.get(code, code)
            severity = status.value if status else "Unknown"
            rows.append([name, severity, count])
    elif group_by == "column":
        headers = ["Column", "Count"]
        rows = []
        for row in failures:
            table, column, count = row[0], row[1], row[-1]
            label = f"{MdDoc.code(column)} in {MdDoc.code(table)}" if column else f"{MdDoc.code(table)} (table-level)"
            rows.append([label, count])
    else:
        headers = ["Table Name", "Count"]
        rows = [[row[0], row[-1]] for row in failures]

    doc.table(headers, rows, code=[0] if group_by == "table" else None)

    if group_by == "test_type":
        doc.text(
            "Check `testgen://test-types` to understand what each test type checks "
            "and `get_test_type(test_type='...')` to fetch more details."
        )

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_test_result_history(
    test_definition_id: str,
    limit: int = 20,
    page: int = 1,
) -> str:
    """Get the historical results of a specific test definition across runs, showing how measure and status changed over time.

    Args:
        test_definition_id: UUID of a test definition, e.g. from ``list_test_results``.
        limit: Maximum number of historical results per page (default 20).
        page: Page number, starting from 1 (default 1).
    """
    def_uuid = parse_uuid(test_definition_id, "test_definition_id")
    offset = (page - 1) * limit

    perms = get_project_permissions()

    results = TestResult.select_history(
        test_definition_id=def_uuid, limit=limit, offset=offset, project_codes=perms.allowed_codes
    )

    if not results:
        return f"No historical results found for test definition `{test_definition_id}`."

    type_names = {tt.test_type: tt.test_name_short for tt in TestType.select_where(TestType.active == "Y")}

    first = results[0]
    test_name = type_names.get(first.test_type, first.test_type)

    doc = MdDoc()
    doc.heading(1, "Test Result History")
    doc.field("Test Type", test_name)
    doc.field("Table", first.table_name, code=True)
    if first.column_names:
        doc.field("Column", first.column_names, code=True)
    doc.text(f"Showing {len(results)} result(s), newest first (page {page}).")
    doc.table(
        headers=["Date", "Measure", "Threshold", "Status"],
        rows=[
            [r.test_time, r.result_measure, r.threshold_value, r.status.value if r.status else None]
            for r in results
        ],
    )

    return doc.render()


@with_database_session
@mcp_permission("view")
def search_test_results(
    *,
    project_code: str | None = None,
    test_suite_id: str | None = None,
    table_group_id: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    test_type: str | None = None,
    status: list[str] | None = None,
    since: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> str:
    """Search test results across multiple runs with flexible filters.

    To drill into a single run, use ``list_test_results``. For a single test's history, use
    ``get_test_result_history``.

    Args:
        project_code: Scope to a project the caller can view.
        test_suite_id: UUID of a test suite to scope to.
        table_group_id: UUID of a table group to scope to.
        table_name: Filter by table name.
        column_name: Filter by column name.
        test_type: Filter by test type (e.g. 'Pattern Match').
        status: Filter by result statuses (defaults to ['Failed', 'Warning']).
        since: Include results since this point — e.g. '7 days', '2 weeks', '2026-04-01'.
        limit: Maximum results per page (default 50).
        page: Page number, starting from 1 (default 1).
    """
    perms = get_project_permissions()
    if project_code:
        perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))
        project_codes = [project_code]
    else:
        project_codes = perms.allowed_codes

    suite_uuid = parse_uuid(test_suite_id, "test_suite_id") if test_suite_id else None
    table_group_uuid = parse_uuid(table_group_id, "table_group_id") if table_group_id else None
    since_date = parse_since_arg(since) if since else None
    type_code = resolve_test_type(test_type) if test_type else None

    # Treat empty list the same as None — an empty IN (…) would silently match nothing.
    if not status:
        status_enums = list(_DEFAULT_SEARCH_STATUSES)
    else:
        status_enums = [parse_result_status(s) for s in status]

    clauses = [
        TestSuite.project_code.in_(project_codes),
        TestResult.status.in_(status_enums),
    ]
    if suite_uuid is not None:
        clauses.append(TestResult.test_suite_id == suite_uuid)
    if table_group_uuid is not None:
        clauses.append(TestResult.table_groups_id == table_group_uuid)
    if table_name:
        clauses.append(TestResult.table_name == table_name)
    if column_name:
        clauses.append(TestResult.column_names == column_name)
    if type_code:
        clauses.append(TestResult.test_type == type_code)
    if since_date is not None:
        clauses.append(TestResult.test_time >= since_date)

    rows, total = TestResult.search_results(*clauses, page=page, limit=limit)

    if not rows:
        return "No test results match the supplied filters."

    doc = MdDoc()
    doc.heading(1, "Test Result Search")
    doc.text(format_page_info(total, page, limit))

    for r in rows:
        display_name = r.test_name_short or r.test_type
        status_str = r.status.value if r.status else "Unknown"
        if r.column_names:
            doc.heading(2, f"[{status_str}] {display_name} on `{r.column_names}` in `{r.table_name}`")
        else:
            doc.heading(2, f"[{status_str}] {display_name} on `{r.table_name}`")
        doc.field("Test Run", r.job_execution_id or r.test_run_id, code=True)
        doc.field("Run time", r.test_time)
        doc.field("Test suite", r.test_suite_name)
        doc.field("Test definition", r.test_definition_id, code=True)
        if r.result_measure is not None:
            doc.field("Measured value", r.result_measure)
        if r.threshold_value is not None:
            doc.field("Threshold", r.threshold_value)
        if r.result_message:
            doc.field("Message", r.result_message)

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_failure_trend(
    *,
    project_code: str | None = None,
    test_suite_id: str | None = None,
    table_group_id: str | None = None,
    table_name: str | None = None,
    test_type: str | None = None,
    since: str = "30 days",
    bucket: BucketInterval = BucketInterval.DAY,
    exclude_today: bool = True,
) -> str:
    """Time-series of test result counts by time bucket — use this to see whether failures are trending up or down.

    Args:
        project_code: Scope to a project the caller can view.
        test_suite_id: UUID of a test suite to scope to.
        table_group_id: UUID of a table group to scope to.
        table_name: Filter by table name.
        test_type: Filter by test type.
        since: Include runs since this point — e.g. '30 days', '2 weeks', '2026-04-01' (default '30 days').
        bucket: Time bucket size — 'day' or 'week' (default 'day').
        exclude_today: If True (default), buckets end yesterday; set False to also compute today's incomplete data.
    """
    try:
        bucket = BucketInterval(bucket)
    except ValueError as err:
        valid = ", ".join(v.value for v in BucketInterval)
        raise MCPUserError(f"Invalid `bucket`: `{bucket}`. Valid values: {valid}") from err

    perms = get_project_permissions()
    if project_code:
        perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))
        project_codes = [project_code]
    else:
        project_codes = perms.allowed_codes

    anchor_today = datetime.now(UTC).date()
    if exclude_today:
        anchor_today -= timedelta(days=1)

    suite_uuid = parse_uuid(test_suite_id, "test_suite_id") if test_suite_id else None
    table_group_uuid = parse_uuid(table_group_id, "table_group_id") if table_group_id else None
    since_date = parse_since_arg(since, today=anchor_today)
    type_code = resolve_test_type(test_type) if test_type else None

    # Build WHERE clauses at the tool layer. Model stays agnostic to specific filter concepts.
    clauses = [TestSuite.project_code.in_(project_codes)]
    if suite_uuid is not None:
        clauses.append(TestResult.test_suite_id == suite_uuid)
    if table_group_uuid is not None:
        clauses.append(TestResult.table_groups_id == table_group_uuid)
    if table_name:
        clauses.append(TestResult.table_name == table_name)
    if type_code:
        clauses.append(TestResult.test_type == type_code)

    buckets = TestResult.failure_trend(
        *clauses,
        start_date=since_date,
        end_date=anchor_today,
        bucket=bucket,
    )

    if not buckets:
        return f"No test results found in the selected window (since {since})."

    doc = MdDoc()
    doc.heading(1, f"Failure Trend — by {bucket}")
    doc.text(f"Window: since {since}. Failure rate = (Failed + Warning) / Total.")
    doc.table(
        headers=["Bucket", "Failed", "Warning", "Total", "Failure rate"],
        rows=[
            [b.bucket, b.failed_ct, b.warning_ct, b.total_ct, f"{b.failure_rate:.1%}"]
            for b in buckets
        ],
    )

    # For weekly buckets, surface the partial-window gap if we dropped data at the oldest end.
    if bucket == "week":
        first_bucket_date = buckets[0].bucket
        if first_bucket_date > since_date:
            dropped_end = first_bucket_date - timedelta(days=1)
            doc.text(
                f"_Note: the partial week from {since_date} to {dropped_end} was excluded "
                f"because it does not form a complete 7-day bucket._"
            )

    # Flag the most recent bucket as "in progress" if it contains today — its counts may grow.
    today = datetime.now(UTC).date()
    last_bucket_start = buckets[-1].bucket
    last_bucket_end = last_bucket_start + timedelta(days=(0 if bucket == "day" else 6))
    if last_bucket_start <= today <= last_bucket_end:
        doc.text(
            f"_Note: the most recent bucket includes today ({today}) and is still in progress; "
            f"its counts may grow before the bucket closes._"
        )

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_test_run_diff(job_execution_id_a: str, job_execution_id_b: str) -> str:
    """Compare two test runs and report regressions, improvements, persistent failures, and added/removed tests.

    Args:
        job_execution_id_a: UUID of the older (baseline) test run, e.g. from ``get_recent_test_runs``.
        job_execution_id_b: UUID of the newer test run.
    """
    uuid_a = parse_uuid(job_execution_id_a, "job_execution_id_a")
    uuid_b = parse_uuid(job_execution_id_b, "job_execution_id_b")

    run_a = TestRun.get_by_id_or_job(uuid_a)
    run_b = TestRun.get_by_id_or_job(uuid_b)

    # Permission check first — unify "not found" and "inaccessible" (also covers monitor suites,
    # which are hidden from this tool the same way they're hidden from the inventory tools).
    perms = get_project_permissions()
    suite_ids = [r.test_suite_id for r in (run_a, run_b) if r is not None]
    suites_by_id: dict = {}
    if suite_ids:
        suites_by_id = {
            s.id: s for s in TestSuite.select_where(TestSuite.id.in_(suite_ids))
        }

    def _accessible(run) -> bool:
        if run is None:
            return False
        suite = suites_by_id.get(run.test_suite_id)
        if suite is None or suite.is_monitor:
            return False
        return perms.has_access(suite.project_code)

    if not _accessible(run_a):
        raise MCPResourceNotAccessible("Test run", job_execution_id_a)
    if not _accessible(run_b):
        raise MCPResourceNotAccessible("Test run", job_execution_id_b)

    # Both runs confirmed accessible — safe to reveal suite IDs in the compatibility message.
    if run_a.test_suite_id != run_b.test_suite_id:
        raise MCPUserError(
            "Both runs must belong to the same test suite to be comparable. "
            f"Run A is in suite `{run_a.test_suite_id}`, run B is in suite `{run_b.test_suite_id}`. "
            "Use `get_recent_test_runs(test_suite=...)` to pick two runs of the same suite."
        )

    diff = TestResult.diff_with_details(run_a.id, run_b.id)

    doc = MdDoc()
    doc.heading(1, "Test Run Diff")
    doc.field("Test Run A", job_execution_id_a, code=True)
    doc.field("Test Run B", job_execution_id_b, code=True)
    doc.table(
        headers=["Category", "Count"],
        rows=[
            ["Regressions (A passed → B failed/warning)", len(diff.regressions)],
            ["Improvements (A failed/warning → B passed)", len(diff.improvements)],
            ["Persistent failures", len(diff.persistent_failures)],
            ["New tests (only in B)", len(diff.new_tests)],
            ["Removed tests (only in A)", len(diff.removed_tests)],
            ["Total in A", diff.total_a],
            ["Total in B", diff.total_b],
        ],
    )

    def _section(title: str, rows: list) -> None:
        if not rows:
            return
        doc.heading(2, title)
        doc.table(
            headers=["Test Type", "Table", "Column", "A → B", "Measure A", "Measure B", "Threshold A", "Threshold B"],
            rows=[
                [
                    row.test_name_short or row.test_type,
                    row.table_name,
                    row.column_names,
                    f"{row.status_a.value if row.status_a else '—'} → {row.status_b.value if row.status_b else '—'}",
                    row.measure_a,
                    row.measure_b,
                    row.threshold_a,
                    row.threshold_b,
                ]
                for row in rows
            ],
        )

    _section("Regressions", diff.regressions)
    _section("Improvements", diff.improvements)
    _section("Persistent Failures", diff.persistent_failures)
    _section("New Tests", diff.new_tests)
    _section("Removed Tests", diff.removed_tests)

    return doc.render()
