from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import ProjectPermissions


def _mock_test_run(test_run_id=None):
    """Create a mock TestRun with an id attribute."""
    run = MagicMock()
    run.id = test_run_id or uuid4()
    return run


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_basic(mock_result, mock_tt_cls, mock_test_run_cls, db_session_mock):
    job_id = str(uuid4())
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()

    r1 = MagicMock()
    r1.status = TestResultStatus.Failed
    r1.test_type = "Alpha_Trunc"
    r1.test_definition_id = uuid4()
    r1.table_name = "orders"
    r1.column_names = "customer_name"
    r1.result_measure = "15.3"
    r1.threshold_value = "10.0"
    r1.message = "Truncation detected"
    mock_result.select_results.return_value = [r1]

    tt = MagicMock()
    tt.test_type = "Alpha_Trunc"
    tt.test_name_short = "Alpha Truncation"
    mock_tt_cls.select_where.return_value = [tt]

    from testgen.mcp.tools.test_results import get_test_results

    result = get_test_results(job_id)

    assert "Alpha Truncation" in result
    assert "Alpha_Trunc" not in result
    assert "on `customer_name` in `orders`" in result
    assert "15.3" in result
    assert "Truncation detected" in result


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_table_level_title(mock_result, mock_tt_cls, mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()

    r1 = MagicMock()
    r1.status = TestResultStatus.Passed
    r1.test_type = "Row_Ct"
    r1.test_definition_id = uuid4()
    r1.table_name = "orders"
    r1.column_names = None
    r1.result_measure = "1000"
    r1.threshold_value = "500"
    r1.message = None
    mock_result.select_results.return_value = [r1]

    tt = MagicMock()
    tt.test_type = "Row_Ct"
    tt.test_name_short = "Row Count"
    mock_tt_cls.select_where.return_value = [tt]

    from testgen.mcp.tools.test_results import get_test_results

    result = get_test_results(str(uuid4()))

    assert "Row Count on `orders`" in result
    assert "` in `" not in result


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_empty(mock_result, mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import get_test_results

    result = get_test_results(str(uuid4()))

    assert "No test results found" in result


@patch("testgen.mcp.tools.common.TestType")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_with_filters(mock_result, mock_tt_cls, mock_test_run_cls, mock_tt_common, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    tt = MagicMock()
    tt.test_type = "Alpha_Trunc"
    tt.test_name_short = "Alpha Truncation"
    mock_tt_cls.select_where.return_value = [tt]
    mock_tt_common.select_where.return_value = [tt]
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import get_test_results

    result = get_test_results(str(uuid4()), status="Failed", table_name="orders", test_type="Alpha Truncation")

    assert "status=Failed" in result
    assert "table=orders" in result
    assert "type=Alpha Truncation" in result


def test_get_test_results_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import get_test_results

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_test_results("not-a-uuid")


@patch("testgen.mcp.tools.test_results.TestRun")
def test_get_test_results_invalid_status(mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()

    from testgen.mcp.tools.test_results import get_test_results

    with pytest.raises(MCPUserError, match="Invalid status"):
        get_test_results(str(uuid4()), status="BadStatus")


@patch("testgen.mcp.tools.test_results.TestRun")
def test_get_test_results_run_not_found(mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = None

    from testgen.mcp.tools.test_results import get_test_results

    with pytest.raises(MCPUserError, match="No test run found"):
        get_test_results(str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_results_passes_project_codes(mock_compute, mock_result, mock_test_run_cls, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import get_test_results

    get_test_results(str(uuid4()))

    call_kwargs = mock_result.select_results.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.tools.test_results.TestType")
def test_get_test_results_resolves_via_get_by_id_or_job(mock_tt_cls, mock_result, mock_test_run_cls, db_session_mock):
    """Verify the resolved test_run.id is passed to select_results."""
    resolved_run_id = uuid4()
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run(resolved_run_id)
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import get_test_results

    job_id = str(uuid4())
    get_test_results(job_id)

    call_kwargs = mock_result.select_results.call_args.kwargs
    assert call_kwargs["test_run_id"] == resolved_run_id


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_test_type(mock_result, mock_tt_cls, mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result.select_failures.return_value = [
        ("Alpha_Trunc", TestResultStatus.Failed, 5),
        ("Unique_Pct", TestResultStatus.Warning, 3),
    ]
    tt1 = MagicMock()
    tt1.test_type = "Alpha_Trunc"
    tt1.test_name_short = "Alpha Truncation"
    tt2 = MagicMock()
    tt2.test_type = "Unique_Pct"
    tt2.test_name_short = "Unique Percent"
    mock_tt_cls.select_where.return_value = [tt1, tt2]

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(job_execution_id=str(uuid4()))

    assert "Failed + Warning" in result
    assert "8" in result
    assert "Alpha Truncation" in result
    assert "Alpha_Trunc" not in result
    assert "Severity" in result
    assert "Failed" in result
    assert "Warning" in result
    assert "get_test_type" in result


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_empty(mock_result, mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(job_execution_id=str(uuid4()))

    assert "No confirmed failures" in result


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_table(mock_result, mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result.select_failures.return_value = [("orders", 10)]

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(job_execution_id=str(uuid4()), group_by="table")

    assert "Table Name" in result
    assert "orders" in result
    assert "get_test_type" not in result


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_column(mock_result, mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result.select_failures.return_value = [("orders", "total_value", 34), ("orders", None, 2)]

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(job_execution_id=str(uuid4()), group_by="column")

    assert "Column" in result
    assert "`total_value` in `orders`" in result
    assert "`orders` (table-level)" in result
    assert "get_test_type" not in result


def test_get_failure_summary_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_failure_summary(job_execution_id="bad-uuid")


@patch("testgen.mcp.tools.test_results.TestRun")
def test_get_failure_summary_run_not_found(mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get_by_id_or_job.return_value = None

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="No test run found"):
        get_failure_summary(job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_passes_project_codes(
    mock_compute, mock_result, mock_test_run_cls, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_test_run_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    get_failure_summary(job_execution_id=str(uuid4()))

    call_kwargs = mock_result.select_failures.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_result_history_basic(mock_result, mock_tt_cls, db_session_mock):
    def_id = str(uuid4())
    r1 = MagicMock()
    r1.test_type = "Unique_Pct"
    r1.table_name = "orders"
    r1.column_names = "order_id"
    r1.test_time = "2024-01-15T10:00:00"
    r1.result_measure = "99.5"
    r1.threshold_value = "95.0"
    r1.status = TestResultStatus.Passed
    r2 = MagicMock()
    r2.test_type = "Unique_Pct"
    r2.table_name = "orders"
    r2.column_names = "order_id"
    r2.test_time = "2024-01-10T10:00:00"
    r2.result_measure = "88.0"
    r2.threshold_value = "95.0"
    r2.status = TestResultStatus.Failed
    mock_result.select_history.return_value = [r1, r2]

    tt = MagicMock()
    tt.test_type = "Unique_Pct"
    tt.test_name_short = "Unique Percent"
    mock_tt_cls.select_where.return_value = [tt]

    from testgen.mcp.tools.test_results import get_test_result_history

    result = get_test_result_history(def_id)

    assert "Unique Percent" in result
    assert "Unique_Pct" not in result
    assert "orders" in result
    assert "99.5" in result
    assert "88.0" in result
    assert "Passed" in result
    assert "Failed" in result


@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_result_history_empty(mock_result, db_session_mock):
    mock_result.select_history.return_value = []

    from testgen.mcp.tools.test_results import get_test_result_history

    result = get_test_result_history(str(uuid4()))

    assert "No historical results" in result


def test_get_test_result_history_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import get_test_result_history

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_test_result_history("bad-uuid")


@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_result_history_passes_project_codes(
    mock_compute, mock_result, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_result.select_history.return_value = []

    from testgen.mcp.tools.test_results import get_test_result_history

    get_test_result_history(str(uuid4()))

    call_kwargs = mock_result.select_history.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


# ----------------------------------------------------------------------
# get_failure_summary — cross-run additions
# ----------------------------------------------------------------------


def test_get_failure_summary_requires_some_scope(db_session_mock):
    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="at least one of"):
        get_failure_summary()


@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_cross_run_by_project(mock_compute, mock_result, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    get_failure_summary(project_code="proj_a", since="7 days")

    call_kwargs = mock_result.select_failures.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]
    assert call_kwargs["test_run_id"] is None
    assert call_kwargs["since"] is not None


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_rejects_inaccessible_project(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        get_failure_summary(project_code="proj_b")


# ----------------------------------------------------------------------
# search_test_results
# ----------------------------------------------------------------------


def _mock_search_row(**overrides):
    row = MagicMock()
    row.test_definition_id = uuid4()
    row.test_run_id = uuid4()
    row.job_execution_id = uuid4()
    row.test_time = "2026-04-15T10:00:00"
    row.test_suite_id = uuid4()
    row.test_suite_name = "Sales Suite"
    row.test_type = "Pattern_Match"
    row.test_name_short = "Pattern Match"
    row.table_name = "orders"
    row.column_names = "customer_id"
    row.status = TestResultStatus.Failed
    row.result_measure = "12"
    row.threshold_value = "0"
    row.result_message = "Bad pattern"
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


@patch("testgen.mcp.tools.test_results.TestResult.search_results")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_search_test_results_happy_path(mock_compute, mock_search_results, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_search_results.return_value = ([_mock_search_row()], 1)

    from testgen.mcp.tools.test_results import search_test_results

    out = search_test_results(project_code="proj_a", since="7 days")

    assert "Pattern Match" in out
    assert "Sales Suite" in out
    assert "on `customer_id` in `orders`" in out
    # Defaults to Failed + Warning — result_status clause present in *args.
    args_repr = " ".join(str(c) for c in mock_search_results.call_args.args).lower()
    assert "result_status in" in args_repr
    # project_codes scoping present
    assert "project_code in" in args_repr


@patch("testgen.mcp.tools.test_results.TestResult.search_results")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_search_test_results_empty(mock_compute, mock_search_results, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_search_results.return_value = ([], 0)

    from testgen.mcp.tools.test_results import search_test_results

    out = search_test_results()

    assert "No test results match" in out


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_search_test_results_rejects_unknown_project(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )

    from testgen.mcp.tools.test_results import search_test_results

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        search_test_results(project_code="proj_b")


@patch("testgen.mcp.tools.test_results.TestResult.search_results")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_search_test_results_paginates(mock_compute, mock_search_results, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    # total > limit → footer expected
    rows = [_mock_search_row() for _ in range(2)]
    mock_search_results.return_value = (rows, 100)

    from testgen.mcp.tools.test_results import search_test_results

    out = search_test_results(limit=2, page=1)
    assert "Showing 1" in out and "2 of 100" in out
    assert "Use `page=2` for more" in out


# ----------------------------------------------------------------------
# get_failure_trend
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.test_results.TestResult.failure_trend")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_trend_happy_path(mock_compute, mock_failure_trend, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    b1 = MagicMock(failed_ct=3, warning_ct=1, total_ct=10)
    b1.bucket = date(2026, 4, 1)
    b1.failure_rate = 0.4
    mock_failure_trend.return_value = [b1]

    from testgen.mcp.tools.test_results import get_failure_trend

    out = get_failure_trend(since="30 days")

    assert "Failure Trend" in out
    assert "40.0%" in out
    assert mock_failure_trend.call_args.kwargs["bucket"] == "day"
    # project_codes is now a caller-built clause, not a kwarg.
    clauses = mock_failure_trend.call_args.args
    assert any("project_code" in str(c) for c in clauses)


@patch("testgen.mcp.tools.test_results.TestResult.failure_trend")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_trend_empty(mock_compute, mock_failure_trend, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_failure_trend.return_value = []

    from testgen.mcp.tools.test_results import get_failure_trend

    out = get_failure_trend(since="30 days")
    assert "No test results found" in out


def test_get_failure_trend_invalid_bucket(db_session_mock):
    from testgen.mcp.tools.test_results import get_failure_trend

    with pytest.raises(MCPUserError, match="Invalid"):
        get_failure_trend(bucket="month")


@patch("testgen.mcp.tools.test_results.TestResult.failure_trend")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_trend_exclude_today_shifts_end_date(mock_compute, mock_failure_trend, db_session_mock):
    """exclude_today=True (default) passes yesterday as end_date; False passes today."""
    from datetime import UTC, datetime, timedelta

    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"}, permission="view",
    )
    mock_failure_trend.return_value = []

    from testgen.mcp.tools.test_results import get_failure_trend

    real_today = datetime.now(UTC).date()

    # Default: exclude_today=True → end_date is yesterday.
    get_failure_trend(since="14 days")
    assert mock_failure_trend.call_args.kwargs["end_date"] == real_today - timedelta(days=1)

    # Explicit exclude_today=False → end_date is today.
    get_failure_trend(since="14 days", exclude_today=False)
    assert mock_failure_trend.call_args.kwargs["end_date"] == real_today


# ----------------------------------------------------------------------
# get_test_run_diff
# ----------------------------------------------------------------------


def _mock_diff_row(status_a, status_b, **overrides):
    row = MagicMock()
    row.test_definition_id = uuid4()
    row.test_type = "Pattern_Match"
    row.test_name_short = "Pattern Match"
    row.table_name = "orders"
    row.column_names = "customer_id"
    row.status_a = status_a
    row.status_b = status_b
    row.measure_a = "5"
    row.measure_b = "12"
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_run_diff_happy_path(
    mock_compute, mock_test_run_cls, mock_result, mock_test_suite_cls, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    suite_id = uuid4()
    run_a = MagicMock(id=uuid4(), test_suite_id=suite_id)
    run_b = MagicMock(id=uuid4(), test_suite_id=suite_id)
    mock_test_run_cls.get_by_id_or_job.side_effect = [run_a, run_b]
    mock_test_suite_cls.id = MagicMock()  # support .in_(...) on attribute mock
    mock_test_suite_cls.select_where.return_value = [MagicMock(id=suite_id, project_code="proj_a", is_monitor=False)]

    diff = MagicMock()
    diff.total_a = 100
    diff.total_b = 100
    diff.regressions = [_mock_diff_row(TestResultStatus.Passed, TestResultStatus.Failed)]
    diff.improvements = []
    diff.persistent_failures = []
    diff.new_tests = []
    diff.removed_tests = []
    mock_result.diff_with_details.return_value = diff

    from testgen.mcp.tools.test_results import get_test_run_diff

    out = get_test_run_diff(str(uuid4()), str(uuid4()))

    assert "Test Run Diff" in out
    assert "Regressions" in out
    assert "Pattern Match" in out
    assert "Passed → Failed" in out


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_run_diff_run_not_found(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """One run missing, other accessible — unified error without leaking which side failed."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    suite_id = uuid4()
    mock_test_run_cls.get_by_id_or_job.side_effect = [None, MagicMock(id=uuid4(), test_suite_id=suite_id)]
    mock_test_suite_cls.id = MagicMock()
    mock_test_suite_cls.select_where.return_value = [MagicMock(id=suite_id, project_code="proj_a", is_monitor=False)]

    from testgen.mcp.tools.test_results import get_test_run_diff

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        get_test_run_diff(str(uuid4()), str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_run_diff_rejects_inaccessible_project(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Runs in an inaccessible project produce the same unified message, not a separate one."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    suite_id = uuid4()
    run = MagicMock(id=uuid4(), test_suite_id=suite_id)
    mock_test_run_cls.get_by_id_or_job.side_effect = [run, run]
    mock_test_suite_cls.id = MagicMock()
    mock_test_suite_cls.select_where.return_value = [MagicMock(id=suite_id, project_code="proj_forbidden", is_monitor=False)]

    from testgen.mcp.tools.test_results import get_test_run_diff

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        get_test_run_diff(str(uuid4()), str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_run_diff_rejects_different_suites(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Both runs accessible but in different suites → suite-mismatch error."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    suite_id_a = uuid4()
    suite_id_b = uuid4()
    run_a = MagicMock(id=uuid4(), test_suite_id=suite_id_a)
    run_b = MagicMock(id=uuid4(), test_suite_id=suite_id_b)
    mock_test_run_cls.get_by_id_or_job.side_effect = [run_a, run_b]
    mock_test_suite_cls.id = MagicMock()
    mock_test_suite_cls.select_where.return_value = [
        MagicMock(id=suite_id_a, project_code="proj_a", is_monitor=False),
        MagicMock(id=suite_id_b, project_code="proj_a", is_monitor=False),
    ]

    from testgen.mcp.tools.test_results import get_test_run_diff

    with pytest.raises(MCPUserError, match="must belong to the same test suite"):
        get_test_run_diff(str(uuid4()), str(uuid4()))


def test_get_test_run_diff_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import get_test_run_diff

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_test_run_diff("bad-uuid", str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_run_diff_rejects_monitor_suite(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Monitor suites are hidden from this tool, same as inaccessible projects — unified message."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    suite_id = uuid4()
    run = MagicMock(id=uuid4(), test_suite_id=suite_id)
    mock_test_run_cls.get_by_id_or_job.side_effect = [run, run]
    mock_test_suite_cls.id = MagicMock()
    mock_test_suite_cls.select_where.return_value = [
        MagicMock(id=suite_id, project_code="proj_a", is_monitor=True)
    ]

    from testgen.mcp.tools.test_results import get_test_run_diff

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        get_test_run_diff(str(uuid4()), str(uuid4()))
