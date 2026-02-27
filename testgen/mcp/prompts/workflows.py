def health_check() -> str:
    """Run a data quality health check across all projects and test suites.

    Provides a comprehensive overview of the current data quality status.
    """
    return """\
Please perform a data quality health check:

1. Call `get_data_inventory()` to get a complete overview of all projects, connections, table groups, and test suites.
2. For each project, call `get_recent_test_runs(project_code='...')` to get the most recent test run.
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
2. Call `get_recent_test_runs(project_code='...')` to find the most recent run{f" for suite `{test_suite}`" if test_suite else ""}.
3. Call `get_failure_summary(test_run_id='...')` to see failures grouped by test type.
4. For each failure category, call `get_test_type(test_type='...')` to understand what the test checks.
5. Call `get_test_results(test_run_id='...', status='Failed')` to see individual failure details.
6. Analyze the patterns:
   - Are failures concentrated in specific tables or columns?
   - Do certain test types fail consistently?
   - What do the measured values vs thresholds tell us about the root cause?
7. Provide a root cause analysis and recommended remediation steps.
"""


def table_health(table_name: str) -> str:
    """Assess the data quality health of a specific table across all test suites.

    Args:
        table_name: The name of the table to investigate.
    """
    return f"""\
Please assess the data quality health of table `{table_name}`:

1. Call `get_data_inventory()` to find which table groups and test suites include this table.
2. For each relevant test suite, call `get_recent_test_runs(project_code='...')` to find the latest run.
3. Call `get_test_results(test_run_id='...', table_name='{table_name}')` to get all results for this table.
4. Summarize the table's health:
   - Which tests pass and which fail?
   - What data quality dimensions are affected?
   - Are there patterns in the failures (e.g., specific columns)?
5. Provide recommendations for improving data quality for this table.
"""


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
3. For the most recent completed run, call `get_test_results(test_run_id='...')` to get all results.
4. For the previous run, call `get_test_results(test_run_id='...')` to get all results.
5. Compare the two runs:
   - **Regressions:** Tests that passed before but now fail.
   - **Improvements:** Tests that failed before but now pass.
   - **Persistent failures:** Tests that failed in both runs.
   - **Stable passes:** Tests that passed in both runs.
6. Summarize the trend and highlight any concerning regressions.
"""
