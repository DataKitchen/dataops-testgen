def health_check() -> str:
    """Run a data quality health check across all projects and test suites.

    Provides a comprehensive overview of the current data quality status.
    """
    return """\
Please perform a data quality health check:

1. Call `get_data_inventory()` to get a complete overview of all projects, connections, table groups, and test suites.
2. For each project, call `get_recent_test_runs(...)` to get the latest test runs across all suites.
3. Summarize the overall health:
   - Which projects/suites are healthy (all tests passing)?
   - Which have failures or warnings?
   - Which have not been run recently?
4. Highlight any critical issues that need immediate attention.
5. Provide actionable recommendations for improving data quality.
"""


def investigate_failures(test_suite: str | None = None) -> str:
    """Investigate test failures to identify root causes and patterns.

    Args:
        test_suite: Optional test suite name to focus the investigation on.
    """
    suite_filter = f" Focus on the test suite named `{test_suite}`." if test_suite else ""

    return f"""\
Please investigate test failures and identify root causes:{suite_filter}

1. Call `get_data_inventory()` to understand the project structure.
2. Call `get_recent_test_runs(...)` to find the latest run per suite{f" for suite `{test_suite}`" if test_suite else ""}.
3. Call `get_failure_summary(job_execution_id='...')` to see failures grouped by test type.
4. For each failure category, call `get_test_type(test_type='...')` to understand what the test checks.
5. Call `list_test_results(test_suite_id='...', status='Failed')` to drill into the specific failing tests in the latest run.
6. For key failures, call `get_source_data(test_definition_id='...')` to see the actual rows violating the test criteria.
   This shows current data from the connected database — rows may have been fixed since the test ran.
7. Analyze the patterns:
   - Are failures concentrated in specific tables or columns?
   - Do certain test types fail consistently?
   - What do the measured values vs thresholds tell us about the root cause?
8. Provide a root cause analysis and recommended remediation steps.
"""


def table_health(table_name: str) -> str:
    """Assess the data quality health of a specific table across all test suites.

    Args:
        table_name: The name of the table to investigate.
    """
    return f"""\
Please assess the data quality health of table `{table_name}`:

1. Call `get_data_inventory()` to discover all table groups.
2. For each table group, call `list_tables(table_group_id='...')` to check if it contains `{table_name}`.
3. For each relevant test suite, call `list_test_results(test_suite_id='...', table_name='{table_name}')` to see results from the latest run for this table.
4. Summarize the table's health:
   - Which tests pass and which fail?
   - What data quality dimensions are affected?
   - Are there patterns in the failures (e.g., specific columns)?
5. Provide recommendations for improving data quality for this table.
"""


def profiling_overview() -> str:
    """Explore the profiling results for a table group — understand data shapes, types, null rates, and hygiene issues."""
    return """\
Please perform a profiling exploration:

1. Call `get_data_inventory()` to see projects and table groups, with profiling status per group.
2. Pick a table group that has been profiled.
3. Call `list_profiling_summaries(table_group_id='...')` for the quality health overview (scores, hygiene issue counts, last profiled).
4. Call `get_table(table_group_id='...', table_name='...')` for structural metadata, the column list, and table-level highlights.
5. Call `list_column_profiles(table_group_id='...', table_name='...')` to scan all columns — datatype, null rates, distinct counts, quality scores, and hygiene issue counts per column.
6. Summarize findings: which tables/columns have quality concerns, and which trends are worth investigating further.
"""


def hygiene_triage(table_group_id: str | None = None) -> str:
    """Guided hygiene issue triage workflow — review hygiene issues and decide what to do.

    Args:
        table_group_id: Optional UUID of a table group to focus on.
    """
    intro = (
        f"Focus on table group `{table_group_id}`."
        if table_group_id
        else "Pick a table group with confirmed hygiene issues."
    )
    tg = f"'{table_group_id}'" if table_group_id else "'...'"

    steps: list[str] = []
    if not table_group_id:
        steps.append(
            "Call `get_data_inventory()` to see projects and table groups, with profiling status per group."
        )
    steps.append(f"Call `list_profiling_summaries(table_group_id={tg})` to see hygiene issue counts per run.")
    steps.append(f"Call `list_hygiene_issues(table_group_id={tg}, disposition='Confirmed')` for the issues to review.")
    steps.append(
        "For each top issue (ordered by priority), call `get_hygiene_issue(issue_id='...')` for full context — "
        "issue type description, suggested action, column profile."
    )
    steps.append("For unfamiliar issue types, read `testgen://hygiene-issue-types` once for the reference table.")
    steps.append(
        "For each issue: explain what was found, then ask the user whether to dismiss the issue "
        "(call `update_hygiene_issue(issue_id='...', disposition='Dismissed')`) or investigate further."
    )
    steps.append("Summarize the triage results and any patterns noted across the issues.")

    numbered = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
    return f"Please triage hygiene issues. {intro}\n\n{numbered}\n"


def compare_runs(test_suite: str | None = None) -> str:
    """Compare the two most recent test runs to identify regressions and improvements.

    Args:
        test_suite: Optional test suite name to focus the comparison on.
    """
    suite_filter = f" for suite `{test_suite}`" if test_suite else ""

    return f"""\
Please compare the two most recent test runs{suite_filter} to identify regressions and improvements:

1. Call `get_data_inventory()` to understand the project structure.
2. Call `list_test_suites(project_code='...')` to find suites{suite_filter} and their latest runs.
3. For the most recent completed run, call `list_test_results(test_suite_id='...')` to get all results.
4. For the previous run, call `list_test_results(job_execution_id='...')` to get all results.
5. Compare the two runs:
   - **Regressions:** Tests that passed before but now fail.
   - **Improvements:** Tests that failed before but now pass.
   - **Persistent failures:** Tests that failed in both runs.
   - **Stable passes:** Tests that passed in both runs.
6. Summarize the trend and highlight any concerning regressions.
"""
