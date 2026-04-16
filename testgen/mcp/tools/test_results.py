from testgen.common.models import with_database_session
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_run import TestRun
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import parse_result_status, parse_uuid, resolve_test_type
from testgen.mcp.tools.markdown import MdDoc


@with_database_session
@mcp_permission("view")
def get_test_results(
    job_execution_id: str,
    status: str | None = None,
    table_name: str | None = None,
    test_type: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> str:
    """Get individual test results for a test run, with optional filters.

    Args:
        job_execution_id: The UUID of the job execution for the test run.
        status: Filter by result status (Passed, Failed, Warning, Error, Log).
        table_name: Filter by table name.
        test_type: Filter by test type (e.g. 'Alpha Truncation', 'Unique Percent').
        limit: Maximum number of results per page (default 50).
        page: Page number, starting from 1 (default 1).
    """
    job_uuid = parse_uuid(job_execution_id, "job_execution_id")
    test_run = TestRun.get_by_id_or_job(job_uuid)
    if not test_run:
        raise MCPUserError(f"No test run found for job execution `{job_execution_id}`.")

    status_enum = parse_result_status(status) if status else None
    offset = (page - 1) * limit

    test_type_code = resolve_test_type(test_type) if test_type else None

    perms = get_project_permissions()

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
        return f"No test results found for run `{job_execution_id}`{filter_str}."

    type_names = {tt.test_type: tt.test_name_short for tt in TestType.select_where(TestType.active == "Y")}

    doc = MdDoc()
    doc.heading(1, f"Test Results for run `{job_execution_id}`")
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
def get_failure_summary(job_execution_id: str, group_by: str = "test_type") -> str:
    """Get a summary of test failures (Failed and Warning) grouped by test type, table name, or column.

    Args:
        job_execution_id: The UUID of the job execution for the test run.
        group_by: Group failures by 'test_type', 'table', or 'column' (default: 'test_type').
    """
    job_uuid = parse_uuid(job_execution_id, "job_execution_id")
    test_run = TestRun.get_by_id_or_job(job_uuid)
    if not test_run:
        raise MCPUserError(f"No test run found for job execution `{job_execution_id}`.")

    perms = get_project_permissions()

    # Map public param names to model field names
    model_group_map = {"table": "table_name", "column": "column_names"}
    model_group_by = model_group_map.get(group_by, group_by)
    failures = TestResult.select_failures(test_run_id=test_run.id, group_by=model_group_by, project_codes=perms.allowed_codes)

    if not failures:
        return f"No confirmed failures found for run `{job_execution_id}`."

    total = sum(row[-1] for row in failures)

    if group_by == "test_type":
        type_names = {tt.test_type: tt.test_name_short for tt in TestType.select_where(TestType.active == "Y")}

    doc = MdDoc()
    doc.heading(1, f"Failure Summary for run `{job_execution_id}`")
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
        test_definition_id: The UUID of the test definition (from get_test_results output).
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
