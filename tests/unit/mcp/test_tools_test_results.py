from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import ProjectPermissions


@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_basic(mock_result, mock_tt_cls, db_session_mock):
    run_id = str(uuid4())
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

    result = get_test_results(run_id)

    assert "Alpha Truncation" in result
    assert "Alpha_Trunc" not in result
    assert "on `customer_name` in `orders`" in result
    assert "15.3" in result
    assert "Truncation detected" in result


@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_table_level_title(mock_result, mock_tt_cls, db_session_mock):
    run_id = str(uuid4())
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

    result = get_test_results(run_id)

    assert "Row Count on `orders`" in result
    assert "` in `" not in result


@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_empty(mock_result, db_session_mock):
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import get_test_results

    result = get_test_results(str(uuid4()))

    assert "No test results found" in result


@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_test_results_with_filters(mock_result, mock_tt_cls, db_session_mock):
    tt = MagicMock()
    tt.test_type = "Alpha_Trunc"
    tt.test_name_short = "Alpha Truncation"
    mock_tt_cls.select_where.return_value = [tt]
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


def test_get_test_results_invalid_status(db_session_mock):
    from testgen.mcp.tools.test_results import get_test_results

    with pytest.raises(MCPUserError, match="Invalid status"):
        get_test_results(str(uuid4()), status="BadStatus")


@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_test_results_passes_project_codes(mock_compute, mock_result, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import get_test_results

    get_test_results(str(uuid4()))

    call_kwargs = mock_result.select_results.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_test_type(mock_result, mock_tt_cls, db_session_mock):
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

    result = get_failure_summary(str(uuid4()))

    assert "Failed + Warning" in result
    assert "8" in result
    assert "Alpha Truncation" in result
    assert "Alpha_Trunc" not in result
    assert "Severity" in result
    assert "Failed" in result
    assert "Warning" in result
    assert "get_test_type" in result


@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_empty(mock_result, db_session_mock):
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(str(uuid4()))

    assert "No confirmed failures" in result


@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_table(mock_result, db_session_mock):
    mock_result.select_failures.return_value = [("orders", 10)]

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(str(uuid4()), group_by="table")

    assert "Table Name" in result
    assert "orders" in result
    assert "get_test_type" not in result


@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_column(mock_result, db_session_mock):
    mock_result.select_failures.return_value = [("orders", "total_value", 34), ("orders", None, 2)]

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(str(uuid4()), group_by="column")

    assert "Column" in result
    assert "`total_value` in `orders`" in result
    assert "`orders` (table-level)" in result
    assert "get_test_type" not in result


def test_get_failure_summary_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_failure_summary("bad-uuid")


@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_passes_project_codes(
    mock_compute, mock_result, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    get_failure_summary(str(uuid4()))

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
