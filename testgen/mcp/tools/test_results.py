from uuid import UUID

from testgen.common.models import with_database_session
from testgen.common.models.test_result import TestResult, TestResultStatus


def _parse_uuid(value: str, label: str = "ID") -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as err:
        raise ValueError(f"Invalid {label}: `{value}` is not a valid UUID.") from err


def _parse_status(value: str) -> TestResultStatus:
    try:
        return TestResultStatus(value)
    except ValueError as err:
        valid = ", ".join(s.value for s in TestResultStatus)
        raise ValueError(f"Invalid status `{value}`. Valid values: {valid}") from err


@with_database_session
def get_test_results(
    test_run_id: str,
    status: str | None = None,
    table_name: str | None = None,
    test_type: str | None = None,
    limit: int = 50,
) -> str:
    """Get individual test results for a test run, with optional filters.

    Args:
        test_run_id: The UUID of the test run.
        status: Filter by result status (Passed, Failed, Warning, Error, Log).
        table_name: Filter by table name.
        test_type: Filter by test type code.
        limit: Maximum number of results to return (default 50).
    """
    run_uuid = _parse_uuid(test_run_id, "test_run_id")
    status_enum = _parse_status(status) if status else None

    results = TestResult.select_results(
        test_run_id=run_uuid,
        status=status_enum,
        table_name=table_name,
        test_type=test_type,
        limit=limit,
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
        return f"No test results found for run `{test_run_id}`{filter_str}."

    lines = [f"# Test Results for run `{test_run_id}`\n"]
    lines.append(f"Showing {len(results)} result(s).\n")

    for r in results:
        status_str = r.status.value if r.status else "Unknown"
        lines.append(f"## [{status_str}] {r.test_type} on `{r.table_name}`")
        lines.append(f"- Test definition: `{r.test_definition_id}`")
        if r.column_names:
            lines.append(f"- Column: `{r.column_names}`")
        if r.result_measure is not None:
            lines.append(f"- Measured value: {r.result_measure}")
        if r.threshold_value is not None:
            lines.append(f"- Threshold: {r.threshold_value}")
        if r.message:
            lines.append(f"- Message: {r.message}")
        lines.append("")

    return "\n".join(lines)


@with_database_session
def get_failure_summary(test_run_id: str, group_by: str = "test_type") -> str:
    """Get a summary of test failures (Failed and Warning) grouped by test type, table name, or column.

    Args:
        test_run_id: The UUID of the test run.
        group_by: Group failures by 'test_type', 'table', or 'column' (default: 'test_type').
    """
    run_uuid = _parse_uuid(test_run_id, "test_run_id")

    # Map public param names to model field names
    model_group_map = {"table": "table_name", "column": "column_names"}
    model_group_by = model_group_map.get(group_by, group_by)
    failures = TestResult.select_failures(test_run_id=run_uuid, group_by=model_group_by)

    if not failures:
        return f"No confirmed failures found for run `{test_run_id}`."

    total = sum(row[-1] for row in failures)
    group_label = {"test_type": "Test Type", "table": "Table Name", "column": "Column"}[group_by]

    lines = [
        f"# Failure Summary for run `{test_run_id}`\n",
        f"**Total confirmed failures (Failed + Warning):** {total}\n",
        f"| {group_label} | Count |",
        "|---|---|",
    ]

    for row in failures:
        count = row[-1]
        if group_by == "column":
            # Row is (table_name, column_names, count)
            table, column = row[0], row[1]
            label = f"{table}.{column}" if column else f"{table} (table-level)"
        else:
            label = row[0]
        lines.append(f"| {label} | {count} |")

    if group_by == "test_type":
        lines.append(
            "\nCheck `testgen://test-types` to understand what each test type checks "
            "and `get_test_type(test_type='...')` to fetch more details."
        )

    return "\n".join(lines)


@with_database_session
def get_test_result_history(
    test_definition_id: str,
    limit: int = 20,
) -> str:
    """Get the historical results of a specific test definition across runs, showing how measure and status changed over time.

    Args:
        test_definition_id: The UUID of the test definition (from get_test_results output).
        limit: Maximum number of historical results to return (default 20).
    """
    def_uuid = _parse_uuid(test_definition_id, "test_definition_id")
    results = TestResult.select_history(test_definition_id=def_uuid, limit=limit)

    if not results:
        return f"No historical results found for test definition `{test_definition_id}`."

    first = results[0]
    lines = [
        "# Test Result History\n",
        f"- **Test Type:** {first.test_type}",
        f"- **Table:** `{first.table_name}`",
    ]
    if first.column_names:
        lines.append(f"- **Column:** `{first.column_names}`")

    lines.extend([
        f"\nShowing {len(results)} result(s), newest first.\n",
        "| Date | Measure | Threshold | Status |",
        "|---|---|---|---|",
    ])

    for r in results:
        date_str = str(r.test_time) if r.test_time else "—"
        measure = r.result_measure if r.result_measure is not None else "—"
        threshold = r.threshold_value if r.threshold_value is not None else "—"
        status_str = r.status.value if r.status else "—"
        lines.append(f"| {date_str} | {measure} | {threshold} | {status_str} |")

    return "\n".join(lines)
