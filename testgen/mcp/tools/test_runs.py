from testgen.common.models import with_database_session
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.permissions import get_project_access, mcp_permission


@with_database_session
@mcp_permission("view")
def get_recent_test_runs(project_code: str, test_suite: str | None = None, limit: int = 1) -> str:
    """Get the latest test runs for each test suite in a project, optionally filtered by test suite name.

    Args:
        project_code: The project code to query.
        test_suite: Optional test suite name to filter by.
        limit: Maximum runs per test suite (default 1).
    """
    if not project_code:
        return "Missing required parameter `project_code`."

    access = get_project_access()
    access.verify_access(project_code, not_found=f"No completed test runs found in project `{project_code}`.")

    test_suite_id = None
    if test_suite:
        suites = TestSuite.select_minimal_where(
            TestSuite.project_code == project_code,
            TestSuite.test_suite == test_suite,
        )
        if not suites:
            return f"Test suite `{test_suite}` not found in project `{project_code}`."
        test_suite_id = str(suites[0].id)

    summaries = TestRun.select_summary(project_code=project_code, test_suite_id=test_suite_id)

    if not summaries:
        scope = f" for suite `{test_suite}`" if test_suite else ""
        return f"No completed test runs found in project `{project_code}`{scope}."

    # Take the first `limit` runs per suite (summaries are ordered by test_starttime DESC)
    seen: dict[str, int] = {}
    runs = []
    for s in summaries:
        count = seen.get(s.test_suite, 0)
        if count < limit:
            runs.append(s)
            seen[s.test_suite] = count + 1

    lines = [f"# Recent Test Runs for `{project_code}`\n"]
    if test_suite:
        lines[0] = f"# Recent Test Runs for `{project_code}` / `{test_suite}`\n"
    lines.append(f"Showing {len(runs)} run(s) ({limit} per suite).\n")

    current_suite = None
    for run in runs:
        if run.test_suite != current_suite:
            current_suite = run.test_suite
            lines.append(f"## {current_suite}\n")

        passed = run.passed_ct or 0
        failed = run.failed_ct or 0
        warning = run.warning_ct or 0
        errors = run.error_ct or 0

        lines.append(f"### {run.test_starttime} — {run.status_label}")
        lines.append(f"- **Run ID:** `{run.test_run_id}`")
        lines.append(f"- **Started:** {run.test_starttime}  |  **Ended:** {run.test_endtime}")
        lines.append(f"- **Results:** {run.test_ct or 0} tests — {passed} passed, {failed} failed, {warning} warnings, {errors} errors")

        if run.dismissed_ct:
            lines.append(f"- **Dismissed:** {run.dismissed_ct}")

        if run.dq_score_testing is not None:
            lines.append(f"- **Testing Score:** {run.dq_score_testing:.1f}")

        lines.append("")

    lines.append("Use `get_test_results(test_run_id='...')` for detailed results of a specific run.")

    return "\n".join(lines)
