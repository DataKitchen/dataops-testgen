from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import Disposition, JobStatus
from testgen.common.models.test_result import TestResultStatus
from testgen.common.test_result_disposition_service import DispositionUpdate
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions


def _mock_test_run(test_run_id=None):
    """Create a mock TestRun with an id attribute."""
    run = MagicMock()
    run.id = test_run_id or uuid4()
    return run


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_results_basic(mock_result, mock_tt_cls, mock_test_run_cls, mock_suite_cls, db_session_mock):
    job_id = str(uuid4())
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite()

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

    from testgen.mcp.tools.test_results import list_test_results

    result = list_test_results(job_id)

    assert "Alpha Truncation" in result
    assert "Alpha_Trunc" not in result
    assert "on `customer_name` in `orders`" in result
    assert "15.3" in result
    assert "Truncation detected" in result


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_results_emits_test_result_id(mock_result, mock_tt_cls, mock_test_run_cls, mock_suite_cls, db_session_mock):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite()

    result_id = uuid4()
    r1 = MagicMock()
    r1.id = result_id
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

    from testgen.mcp.tools.test_results import list_test_results

    result = list_test_results(str(uuid4()))

    assert "Test result" in result
    assert str(result_id) in result


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_results_table_level_title(mock_result, mock_tt_cls, mock_test_run_cls, mock_suite_cls, db_session_mock):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite()

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

    from testgen.mcp.tools.test_results import list_test_results

    result = list_test_results(str(uuid4()))

    assert "Row Count on `orders`" in result
    assert "` in `" not in result


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_results_empty(mock_result, mock_test_run_cls, mock_suite_cls, db_session_mock):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite()
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import list_test_results

    result = list_test_results(str(uuid4()))

    assert "No test results found" in result


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.common.TestType")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_results_with_filters(
    mock_result, mock_tt_cls, mock_test_run_cls, mock_tt_common, mock_suite_cls, db_session_mock
):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite()
    tt = MagicMock()
    tt.test_type = "Alpha_Trunc"
    tt.test_name_short = "Alpha Truncation"
    mock_tt_cls.select_where.return_value = [tt]
    mock_tt_common.select_where.return_value = [tt]
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import list_test_results

    result = list_test_results(str(uuid4()), status="Failed", table_name="orders", test_type="Alpha Truncation")

    assert "status=Failed" in result
    assert "table=orders" in result
    assert "type=Alpha Truncation" in result


def test_list_test_results_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        list_test_results("not-a-uuid")


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
def test_list_test_results_invalid_status(mock_test_run_cls, mock_suite_cls, db_session_mock):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="Invalid status"):
        list_test_results(str(uuid4()), status="BadStatus")


@patch("testgen.mcp.tools.test_results.TestRun")
def test_list_test_results_run_not_found(mock_test_run_cls, db_session_mock):
    mock_test_run_cls.get.return_value = None

    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPResourceNotAccessible, match="Test run .* not found or not accessible"):
        list_test_results(str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
def test_list_test_results_run_in_monitor_suite_rejected(mock_test_run_cls, mock_suite_cls, db_session_mock):
    # Run exists, but the resolved suite is monitor → TestSuite.get_regular returns None.
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = None

    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        list_test_results(job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_test_results_run_in_forbidden_project(
    mock_compute, mock_test_run_cls, mock_suite_cls, db_session_mock
):
    mock_compute.return_value = ProjectPermissions(memberships={"proj_a": "role_a"}, permission="view", username="test_user")
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="forbidden_project")

    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        list_test_results(job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_test_results_passes_project_codes(
    mock_compute, mock_result, mock_test_run_cls, mock_suite_cls, db_session_mock
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="proj_a")
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import list_test_results

    list_test_results(str(uuid4()))

    call_kwargs = mock_result.select_results.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.tools.test_results.TestType")
def test_list_test_results_resolves_via_get(
    mock_tt_cls, mock_result, mock_test_run_cls, mock_suite_cls, db_session_mock
):
    """Verify the resolved test_run.id is passed to select_results."""
    resolved_run_id = uuid4()
    mock_test_run_cls.get.return_value = _mock_test_run(resolved_run_id)
    mock_suite_cls.get_regular.return_value = _mock_test_suite()
    mock_result.select_results.return_value = []

    from testgen.mcp.tools.test_results import list_test_results

    job_id = str(uuid4())
    list_test_results(job_id)

    call_kwargs = mock_result.select_results.call_args.kwargs
    assert call_kwargs["test_run_id"] == resolved_run_id


def _mock_test_suite(suite_id=None, project_code="demo", last_complete_test_run_id=None):
    """Create a mock TestSuite for the test_suite_id branch tests."""
    suite = MagicMock()
    suite.id = suite_id or uuid4()
    suite.project_code = project_code
    suite.last_complete_test_run_id = last_complete_test_run_id
    return suite


def test_list_test_results_both_args_rejected(db_session_mock):
    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="Pass either"):
        list_test_results(job_execution_id=str(uuid4()), test_suite_id=str(uuid4()))


def test_list_test_results_neither_arg_rejected(db_session_mock):
    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="Provide either"):
        list_test_results()


@patch("testgen.mcp.tools.test_results.TestSuite")
def test_list_test_results_by_suite_id_monitor_or_missing(mock_suite_cls, db_session_mock):
    # TestSuite.get_regular returns None for monitor suites and unknown ids alike.
    mock_suite_cls.get_regular.return_value = None

    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        list_test_results(test_suite_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_test_results_by_suite_id_inaccessible_project(mock_compute, mock_suite_cls, db_session_mock):
    mock_compute.return_value = ProjectPermissions(memberships={"proj_a": "role_a"}, permission="view", username="test_user")
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="forbidden_project")

    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        list_test_results(test_suite_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
def test_list_test_results_by_suite_id_no_completed_runs(mock_suite_cls, db_session_mock):
    mock_suite_cls.get_regular.return_value = _mock_test_suite(last_complete_test_run_id=None)

    from testgen.mcp.tools.test_results import list_test_results

    with pytest.raises(MCPUserError, match="No completed test runs"):
        list_test_results(test_suite_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_results_by_suite_id_resolves_latest_run(
    mock_result, mock_tt_cls, mock_test_run_cls, mock_suite_cls, db_session_mock
):
    last_run_id = uuid4()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(last_complete_test_run_id=last_run_id)

    resolved_run_id = uuid4()
    resolved_run = _mock_test_run(resolved_run_id)
    mock_test_run_cls.get.return_value = resolved_run

    r1 = MagicMock()
    r1.status = TestResultStatus.Failed
    r1.test_type = "Alpha_Trunc"
    r1.test_definition_id = uuid4()
    r1.table_name = "orders"
    r1.column_names = "name"
    r1.result_measure = "5"
    r1.threshold_value = "1"
    r1.message = None
    mock_result.select_results.return_value = [r1]

    tt = MagicMock()
    tt.test_type = "Alpha_Trunc"
    tt.test_name_short = "Alpha Truncation"
    mock_tt_cls.select_where.return_value = [tt]

    from testgen.mcp.tools.test_results import list_test_results

    suite_id = str(uuid4())
    result = list_test_results(test_suite_id=suite_id)

    # Resolution chain: suite.last_complete_test_run_id → TestRun.get → test_run.id → select_results
    mock_test_run_cls.get.assert_called_once_with(last_run_id)
    assert mock_result.select_results.call_args.kwargs["test_run_id"] == resolved_run_id
    # Output indicates which run the suite was resolved to (run id is the job execution id).
    assert str(resolved_run_id) in result
    assert f"Latest completed run of test suite `{suite_id}`" in result


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_test_type(
    mock_result, mock_tt_cls, mock_test_run_cls, mock_suite_cls, db_session_mock,
):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="demo")
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


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_empty(mock_result, mock_test_run_cls, mock_suite_cls, db_session_mock):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="demo")
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(job_execution_id=str(uuid4()))

    assert "No confirmed failures" in result


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_table(mock_result, mock_test_run_cls, mock_suite_cls, db_session_mock):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="demo")
    mock_result.select_failures.return_value = [("orders", 10)]

    from testgen.mcp.tools.test_results import get_failure_summary

    result = get_failure_summary(job_execution_id=str(uuid4()), group_by="table")

    assert "Table Name" in result
    assert "orders" in result
    assert "get_test_type" not in result


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_get_failure_summary_by_column(mock_result, mock_test_run_cls, mock_suite_cls, db_session_mock):
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="demo")
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
    mock_test_run_cls.get.return_value = None

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPResourceNotAccessible, match="Test run .* not found or not accessible"):
        get_failure_summary(job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_run_in_forbidden_project(
    mock_compute, mock_test_run_cls, mock_suite_cls, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(memberships={"proj_a": "role_a"}, permission="view", username="test_user")
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="forbidden_project")

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPResourceNotAccessible, match="Test run .* not found or not accessible"):
        get_failure_summary(job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
def test_get_failure_summary_run_in_monitor_suite_rejected(mock_test_run_cls, mock_suite_cls, db_session_mock):
    # Run exists, but the resolved suite is monitor → TestSuite.get_regular returns None.
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = None

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPResourceNotAccessible, match="Test run .* not found or not accessible"):
        get_failure_summary(job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_passes_project_codes(
    mock_compute, mock_result, mock_test_run_cls, mock_suite_cls, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    mock_test_run_cls.get.return_value = _mock_test_run()
    mock_suite_cls.get_regular.return_value = _mock_test_suite(project_code="proj_a")
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    get_failure_summary(job_execution_id=str(uuid4()))

    call_kwargs = mock_result.select_failures.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


@patch("testgen.mcp.tools.test_results.TestType")
@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_result_history_basic(mock_result, mock_tt_cls, db_session_mock):
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

    from testgen.mcp.tools.test_results import list_test_result_history

    result = list_test_result_history(def_id)

    assert "Unique Percent" in result
    assert "Unique_Pct" not in result
    assert "orders" in result
    assert "99.5" in result
    assert "88.0" in result
    assert "Passed" in result
    assert "Failed" in result


@patch("testgen.mcp.tools.test_results.TestResult")
def test_list_test_result_history_empty(mock_result, db_session_mock):
    mock_result.select_history.return_value = []

    from testgen.mcp.tools.test_results import list_test_result_history

    result = list_test_result_history(str(uuid4()))

    assert "No historical results" in result


def test_list_test_result_history_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import list_test_result_history

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        list_test_result_history("bad-uuid")


@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_test_result_history_passes_project_codes(
    mock_compute, mock_result, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    mock_result.select_history.return_value = []

    from testgen.mcp.tools.test_results import list_test_result_history

    list_test_result_history(str(uuid4()))

    call_kwargs = mock_result.select_history.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


# ----------------------------------------------------------------------
# get_failure_summary — cross-run additions
# ----------------------------------------------------------------------


def test_get_failure_summary_requires_some_scope(db_session_mock):
    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="single run"):
        get_failure_summary()


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_rejects_project_code_alone(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="'since' is required"):
        get_failure_summary(project_code="proj_a")


@pytest.mark.parametrize("group_by", ["table", "column"])
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_rejects_cross_suite_table_or_column_grouping(mock_compute, db_session_mock, group_by):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="single-suite scope"):
        get_failure_summary(project_code="proj_a", since="7 days", group_by=group_by)


@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_cross_run_by_project(mock_compute, mock_result, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    get_failure_summary(project_code="proj_a", since="7 days")

    call_kwargs = mock_result.select_failures.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]
    assert call_kwargs["test_run_id"] is None
    assert call_kwargs["since"] is not None


@patch("testgen.mcp.tools.common.TestSuite")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_cross_run_by_project_and_suite(
    mock_compute, mock_result, mock_suite_cls, db_session_mock
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    mock_suite_cls.get.return_value = _mock_test_suite(project_code="proj_a")
    mock_result.select_failures.return_value = []

    from testgen.mcp.tools.test_results import get_failure_summary

    get_failure_summary(project_code="proj_a", test_suite_id=str(uuid4()))

    call_kwargs = mock_result.select_failures.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]
    assert call_kwargs["test_suite_id"] is not None
    assert call_kwargs["test_run_id"] is None
    assert call_kwargs["since"] is None


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_rejects_inaccessible_project(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPResourceNotAccessible, match="Project .* not found or not accessible"):
        get_failure_summary(project_code="proj_b", since="7 days")


@patch("testgen.mcp.tools.common.TestSuite")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_rejects_inaccessible_test_suite(mock_compute, mock_suite_cls, db_session_mock):
    """test_suite_id branch validates suite access — inaccessible suites are filtered out by the
    access-scoped query in resolve_test_suite, which returns None."""
    mock_compute.return_value = ProjectPermissions(memberships={"proj_a": "role_a"}, permission="view", username="test_user")
    mock_suite_cls.get.return_value = None

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        get_failure_summary(test_suite_id=str(uuid4()))


@patch("testgen.mcp.tools.common.TestSuite")
def test_get_failure_summary_rejects_unknown_or_monitor_test_suite(mock_suite_cls, db_session_mock):
    # resolve_test_suite's access + is_monitor scoped query returns None for monitor suites and unknown ids alike.
    mock_suite_cls.get.return_value = None

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        get_failure_summary(test_suite_id=str(uuid4()))


def test_get_failure_summary_rejects_invalid_group_by(db_session_mock):
    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="Invalid group_by"):
        get_failure_summary(job_execution_id=str(uuid4()), group_by="bogus")


@patch("testgen.mcp.tools.common.TestSuite")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_summary_rejects_cross_project_suite(mock_compute, mock_suite_cls, db_session_mock):
    """A suite the caller can access but in a different project than project_code is rejected,
    not silently scoped away to an empty result."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a", "proj_b": "role_a"}, permission="view", username="test_user",
    )
    mock_suite_cls.get.return_value = _mock_test_suite(project_code="proj_b")

    from testgen.mcp.tools.test_results import get_failure_summary

    with pytest.raises(MCPUserError, match="belongs to project `proj_b`, not `proj_a`"):
        get_failure_summary(project_code="proj_a", test_suite_id=str(uuid4()))


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
        username="test_user",
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
        username="test_user",
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
        username="test_user",
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
        username="test_user",
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
        username="test_user",
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
        username="test_user",
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
        username="test_user",
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


@patch("testgen.mcp.tools.common.TestSuite")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_trend_rejects_cross_project_suite(mock_compute, mock_suite_cls, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a", "proj_b": "role_a"}, permission="view", username="test_user",
    )
    mock_suite_cls.get.return_value = _mock_test_suite(project_code="proj_b")

    from testgen.mcp.tools.test_results import get_failure_trend

    with pytest.raises(MCPUserError, match="belongs to project `proj_b`, not `proj_a`"):
        get_failure_trend(project_code="proj_a", test_suite_id=str(uuid4()))


@patch("testgen.mcp.tools.common.TestSuite")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_trend_rejects_inaccessible_suite(mock_compute, mock_suite_cls, db_session_mock):
    """An inaccessible (or unknown/monitor) suite errors instead of silently returning an empty trend."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"}, permission="view", username="test_user",
    )
    mock_suite_cls.get.return_value = None

    from testgen.mcp.tools.test_results import get_failure_trend

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        get_failure_trend(test_suite_id=str(uuid4()))


@patch("testgen.mcp.tools.common.TableGroup")
@patch("testgen.mcp.tools.common.TestSuite")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_failure_trend_rejects_suite_and_table_group_in_different_projects(
    mock_compute, mock_suite_cls, mock_tg_cls, db_session_mock
):
    """No project_code, but the suite and table group resolve to different accessible projects:
    the two filters would AND to an empty result, so reject instead of silently returning empty."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a", "proj_b": "role_a"}, permission="view", username="test_user",
    )
    mock_suite_cls.get.return_value = _mock_test_suite(project_code="proj_a")
    mock_tg_cls.get.return_value = MagicMock(project_code="proj_b")

    from testgen.mcp.tools.test_results import get_failure_trend

    with pytest.raises(MCPUserError, match="different projects"):
        get_failure_trend(test_suite_id=str(uuid4()), table_group_id=str(uuid4()))


# ----------------------------------------------------------------------
# compare_test_runs
# ----------------------------------------------------------------------


def _mock_diff_row(status_baseline, status_target, **overrides):
    row = MagicMock()
    row.test_definition_id = uuid4()
    row.test_type = "Pattern_Match"
    row.test_name_short = "Pattern Match"
    row.table_name = "orders"
    row.column_names = "customer_id"
    row.status_baseline = status_baseline
    row.status_target = status_target
    row.measure_baseline = "5"
    row.measure_target = "12"
    row.threshold_baseline = "0"
    row.threshold_target = "0"
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


def _mock_run(suite_id, je_id=None):
    run = MagicMock(id=uuid4(), test_suite_id=suite_id)
    run.job_execution_id = je_id or uuid4()
    return run


def _je(status=JobStatus.COMPLETED):
    """Build a JobExecution mock for ``session.get(JobExecution, ...)`` returns."""
    je = MagicMock()
    je.status = status
    return je


def _patch_test_results_session(jes):
    """Patch ``get_current_session`` in test_results so ``session.get(JobExecution, ...)``
    returns the given JEs in order (one per ``_require_completed`` call)."""
    session = MagicMock()
    session.get.side_effect = jes
    return patch("testgen.mcp.tools.test_results.get_current_session", return_value=session)


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_happy_path(
    mock_compute, mock_test_run_cls, mock_result, mock_test_suite_cls, db_session_mock,
):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    baseline_run = _mock_run(suite_id)
    target_run = _mock_run(suite_id)
    # Tool resolves target first, then baseline.
    mock_test_run_cls.get.side_effect = [target_run, baseline_run]
    mock_test_suite_cls.get_regular.return_value = _mock_test_suite(suite_id=suite_id, project_code="proj_a")

    diff = MagicMock()
    diff.total_baseline = 100
    diff.total_target = 100
    diff.stable_passes = 98
    diff.regressions = [
        _mock_diff_row(
            TestResultStatus.Passed,
            TestResultStatus.Failed,
            threshold_baseline="1",
            threshold_target="3",
        )
    ]
    diff.improvements = []
    diff.persistent_failures = []
    diff.new_tests = []
    diff.removed_tests = []
    mock_result.diff_with_details.return_value = diff

    from testgen.mcp.tools.test_results import compare_test_runs

    with _patch_test_results_session([_je(), _je()]):
        out = compare_test_runs(str(uuid4()), str(uuid4()))

    assert "Test Run Comparison" in out
    assert "Stable passes (Baseline passed → Target passed)" in out
    assert "| Stable passes (Baseline passed → Target passed) | 98 |" in out
    assert "Regressions" in out
    assert "Pattern Match" in out
    assert "Passed → Failed" in out
    assert "Threshold Baseline" in out and "Threshold Target" in out
    assert "| 1 | 3 |" in out  # threshold columns populated when thresholds changed
    # diff_with_details called with (baseline_run.id, target_run.id) in that order.
    mock_result.diff_with_details.assert_called_once_with(baseline_run.id, target_run.id)


def _fetch_row(test_definition_id, status):
    row = MagicMock()
    row.test_definition_id = test_definition_id
    row.test_type = "Pattern_Match"
    row.test_name_short = "Pattern Match"
    row.table_name = "orders"
    row.column_names = "customer_id"
    row.status = status
    row.result_measure = "0"
    row.threshold_value = "0"
    return row


def test_diff_with_details_counts_stable_passes():
    from testgen.common.models.test_result import TestResult

    stable_1, stable_2, regressed, improved = uuid4(), uuid4(), uuid4(), uuid4()
    baseline_rows = [
        _fetch_row(stable_1, TestResultStatus.Passed),
        _fetch_row(stable_2, TestResultStatus.Passed),
        _fetch_row(regressed, TestResultStatus.Passed),
        _fetch_row(improved, TestResultStatus.Failed),
    ]
    target_rows = [
        _fetch_row(stable_1, TestResultStatus.Passed),
        _fetch_row(stable_2, TestResultStatus.Passed),
        _fetch_row(regressed, TestResultStatus.Failed),
        _fetch_row(improved, TestResultStatus.Passed),
    ]
    session = MagicMock()
    session.execute.side_effect = [baseline_rows, target_rows]

    with patch("testgen.common.models.test_result.get_current_session", return_value=session):
        diff = TestResult.diff_with_details(uuid4(), uuid4())

    assert diff.stable_passes == 2
    assert len(diff.regressions) == 1
    assert len(diff.improvements) == 1
    assert len(diff.persistent_failures) == 0
    # Internal consistency: with no out-of-bucket statuses (Error/Log) in the fixture, the four
    # named buckets account for every shared test definition.
    shared = diff.total_target - len(diff.new_tests)
    assert diff.stable_passes + len(diff.regressions) + len(diff.improvements) + len(diff.persistent_failures) == shared


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestResult")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_single_arg_resolves_previous(
    mock_compute, mock_test_run_cls, mock_result, mock_test_suite_cls, db_session_mock,
):
    """Only target supplied — baseline is resolved via target_run.get_previous()."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    target_run = _mock_run(suite_id)
    baseline_run = _mock_run(suite_id)
    target_run.get_previous.return_value = baseline_run
    mock_test_run_cls.get.return_value = target_run
    mock_test_suite_cls.get_regular.return_value = _mock_test_suite(suite_id=suite_id, project_code="proj_a")

    diff = MagicMock(
        total_baseline=10, total_target=10,
        regressions=[], improvements=[], persistent_failures=[], new_tests=[], removed_tests=[],
    )
    mock_result.diff_with_details.return_value = diff

    from testgen.mcp.tools.test_results import compare_test_runs

    with _patch_test_results_session([_je()]):
        out = compare_test_runs(str(uuid4()))

    target_run.get_previous.assert_called_once_with()
    mock_result.diff_with_details.assert_called_once_with(baseline_run.id, target_run.id)
    # Rendered Baseline cell shows the resolved run id (the job execution id), not an input string.
    assert str(baseline_run.id) in out


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_single_arg_no_previous_raises(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Target is the oldest run — get_previous() returns None — clear user-facing error."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    target_run = _mock_run(suite_id)
    target_run.get_previous.return_value = None
    mock_test_run_cls.get.return_value = target_run
    mock_test_suite_cls.get_regular.return_value = _mock_test_suite(suite_id=suite_id, project_code="proj_a")

    from testgen.mcp.tools.test_results import compare_test_runs

    with _patch_test_results_session([_je()]), pytest.raises(MCPUserError, match="no earlier completed test run"):
        compare_test_runs(str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_single_arg_inaccessible_target(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Inaccessible target — error raised before get_previous() is consulted."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    target_run = _mock_run(suite_id)
    mock_test_run_cls.get.return_value = target_run
    # Monitor suite or inaccessible project — get_regular returns None either way.
    mock_test_suite_cls.get_regular.return_value = None

    from testgen.mcp.tools.test_results import compare_test_runs

    with pytest.raises(MCPResourceNotAccessible, match="Test run .* not found or not accessible"):
        compare_test_runs(str(uuid4()))
    target_run.get_previous.assert_not_called()


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_run_not_found(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Target not found — unified not-found-or-inaccessible error."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    mock_test_run_cls.get.return_value = None

    from testgen.mcp.tools.test_results import compare_test_runs

    with pytest.raises(MCPResourceNotAccessible, match="Test run .* not found or not accessible"):
        compare_test_runs(str(uuid4()), str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_rejects_inaccessible_project(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Runs in an inaccessible project produce the unified message."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    run = _mock_run(suite_id)
    mock_test_run_cls.get.return_value = run
    mock_test_suite_cls.get_regular.return_value = _mock_test_suite(suite_id=suite_id, project_code="proj_forbidden")

    from testgen.mcp.tools.test_results import compare_test_runs

    with pytest.raises(MCPResourceNotAccessible, match="not found or not accessible"):
        compare_test_runs(str(uuid4()), str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_rejects_different_suites(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Both runs accessible but in different suites → suite-mismatch error."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id_target = uuid4()
    suite_id_baseline = uuid4()
    target_run = _mock_run(suite_id_target)
    baseline_run = _mock_run(suite_id_baseline)
    mock_test_run_cls.get.side_effect = [target_run, baseline_run]
    mock_test_suite_cls.get_regular.side_effect = [
        _mock_test_suite(suite_id=suite_id_target, project_code="proj_a"),
        _mock_test_suite(suite_id=suite_id_baseline, project_code="proj_a"),
    ]

    from testgen.mcp.tools.test_results import compare_test_runs

    with _patch_test_results_session([_je()]), pytest.raises(MCPUserError, match="must belong to the same test suite"):
        compare_test_runs(str(uuid4()), str(uuid4()))


def test_compare_test_runs_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_results import compare_test_runs

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        compare_test_runs("bad-uuid", str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_rejects_monitor_suite(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Monitor suites are hidden — TestSuite.get_regular returns None — unified message."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    run = _mock_run(suite_id)
    mock_test_run_cls.get.return_value = run
    mock_test_suite_cls.get_regular.return_value = None

    from testgen.mcp.tools.test_results import compare_test_runs

    with pytest.raises(MCPResourceNotAccessible, match="not found or not accessible"):
        compare_test_runs(str(uuid4()), str(uuid4()))


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_rejects_target_not_completed(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Target run still Running — comparison rejected before any diff work."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    target_run = _mock_run(suite_id)
    mock_test_run_cls.get.return_value = target_run
    mock_test_suite_cls.get_regular.return_value = _mock_test_suite(suite_id=suite_id, project_code="proj_a")

    from testgen.mcp.tools.test_results import compare_test_runs

    with _patch_test_results_session([_je(status=JobStatus.RUNNING)]), \
            pytest.raises(MCPUserError, match=r"Target run is in `Running` state"):
        compare_test_runs(str(uuid4()))
    target_run.get_previous.assert_not_called()


@patch("testgen.mcp.tools.test_results.TestSuite")
@patch("testgen.mcp.tools.test_results.TestRun")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_compare_test_runs_rejects_baseline_not_completed(
    mock_compute, mock_test_run_cls, mock_test_suite_cls, db_session_mock,
):
    """Two-arg path: target completes the check but baseline is in Error state."""
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
        username="test_user",
    )
    suite_id = uuid4()
    target_run = _mock_run(suite_id)
    baseline_run = _mock_run(suite_id)
    mock_test_run_cls.get.side_effect = [target_run, baseline_run]
    mock_test_suite_cls.get_regular.return_value = _mock_test_suite(suite_id=suite_id, project_code="proj_a")

    from testgen.mcp.tools.test_results import compare_test_runs

    with _patch_test_results_session([_je(), _je(status=JobStatus.ERROR)]), \
            pytest.raises(MCPUserError, match=r"Baseline run is in `Error` state"):
        compare_test_runs(str(uuid4()), str(uuid4()))


# ---------------------------------------------------------------------------
# update_test_result
# ---------------------------------------------------------------------------


@pytest.fixture
def disposition_perms():
    """Grant 'disposition' permission on demo (the conftest matrix omits it)."""
    perms = MagicMock(spec=ProjectPermissions)
    perms.memberships = {"demo": "role_a"}
    perms.permission = "disposition"
    perms.username = "test_user"
    perms.allowed_codes = ["demo"]
    perms.codes_allowed_to.return_value = ["demo"]
    perms.has_access.side_effect = lambda code: code in ["demo"]
    with patch("testgen.mcp.permissions._compute_project_permissions", return_value=perms):
        yield perms


def test_update_test_result_invalid_uuid(db_session_mock, disposition_perms):
    from testgen.mcp.tools.test_results import update_test_result

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        update_test_result(test_result_id="bogus", disposition="Confirmed")


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.resolve_test_result")
def test_update_test_result_muted_maps_to_inactive(mock_resolve, mock_set, db_session_mock, disposition_perms):
    from testgen.mcp.tools.test_results import update_test_result

    mock_resolve.return_value = MagicMock(id=uuid4())
    mock_set.return_value = DispositionUpdate(matched=1, passed_skipped=0)
    update_test_result(test_result_id=str(uuid4()), disposition="Muted")

    assert mock_set.call_args.args[1] == Disposition.INACTIVE


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.resolve_test_result")
def test_update_test_result_no_decision_clears(mock_resolve, mock_set, db_session_mock, disposition_perms):
    from testgen.mcp.tools.test_results import update_test_result

    mock_resolve.return_value = MagicMock(id=uuid4())
    mock_set.return_value = DispositionUpdate(matched=1, passed_skipped=0)
    update_test_result(test_result_id=str(uuid4()), disposition="No Decision")

    assert mock_set.call_args.args[1] is None


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.resolve_test_result")
def test_update_test_result_success_message(mock_resolve, mock_set, db_session_mock, disposition_perms):
    from testgen.mcp.tools.test_results import update_test_result

    rid = str(uuid4())
    mock_resolve.return_value = MagicMock(id=uuid4())
    mock_set.return_value = DispositionUpdate(matched=1, passed_skipped=0)
    out = update_test_result(test_result_id=rid, disposition="Dismissed")

    assert rid in out and "Dismissed" in out


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.resolve_test_result")
def test_update_test_result_passed_row_is_noop(mock_resolve, mock_set, db_session_mock, disposition_perms):
    from testgen.mcp.tools.test_results import update_test_result

    mock_resolve.return_value = MagicMock(id=uuid4())
    mock_set.return_value = DispositionUpdate(matched=0, passed_skipped=1)
    out = update_test_result(test_result_id=str(uuid4()), disposition="Confirmed")

    assert "passed" in out and "No change" in out


def test_update_test_result_uses_disposition_permission():
    import testgen.mcp.tools.test_results as mod

    closure = {c.cell_contents for c in mod.update_test_result.__wrapped__.__closure__}
    assert "disposition" in closure


# ---------------------------------------------------------------------------
# bulk_update_test_results
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.get_current_session")
@patch("testgen.mcp.tools.test_results.resolve_test_suite")
def test_bulk_update_uses_latest_run_when_run_omitted(
    mock_resolve_suite, mock_session, mock_set, db_session_mock, disposition_perms
):
    from testgen.mcp.tools.test_results import bulk_update_test_results

    run_id = uuid4()
    suite = MagicMock(id=uuid4(), test_suite="suite_a", last_complete_test_run_id=run_id)
    mock_resolve_suite.return_value = suite
    matched_ids = [uuid4(), uuid4()]
    mock_session.return_value.scalars.return_value.all.return_value = matched_ids
    mock_set.return_value = DispositionUpdate(matched=2, passed_skipped=0)

    with patch("testgen.mcp.tools.test_results.TestRun.get",
               return_value=MagicMock(id=run_id, job_execution_id=run_id, test_suite_id=suite.id)):
        out = bulk_update_test_results(test_suite_id=str(uuid4()), disposition="Dismissed")

    assert mock_set.call_args.args[0] == matched_ids
    assert mock_set.call_args.args[1] == Disposition.DISMISSED
    assert "2" in out


@patch("testgen.mcp.tools.test_results.resolve_test_suite")
def test_bulk_update_no_completed_run_errors(mock_resolve_suite, db_session_mock, disposition_perms):
    from testgen.mcp.tools.test_results import bulk_update_test_results

    mock_resolve_suite.return_value = MagicMock(last_complete_test_run_id=None, test_suite="suite_a")
    with pytest.raises(MCPUserError, match="No completed test runs"):
        bulk_update_test_results(test_suite_id=str(uuid4()), disposition="Confirmed")


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.get_current_session")
@patch("testgen.mcp.tools.test_results.resolve_test_suite")
def test_bulk_update_reports_passed_exclusions(
    mock_resolve_suite, mock_session, mock_set, db_session_mock, disposition_perms
):
    from testgen.mcp.tools.test_results import bulk_update_test_results

    run_id = uuid4()
    suite = MagicMock(id=uuid4(), test_suite="suite_a", last_complete_test_run_id=run_id)
    mock_resolve_suite.return_value = suite
    mock_session.return_value.scalars.return_value.all.return_value = [uuid4(), uuid4(), uuid4()]
    mock_set.return_value = DispositionUpdate(matched=2, passed_skipped=1)

    with patch("testgen.mcp.tools.test_results.TestRun.get",
               return_value=MagicMock(id=run_id, job_execution_id=run_id, test_suite_id=suite.id)):
        out = bulk_update_test_results(test_suite_id=str(uuid4()), disposition="Muted")

    assert "2" in out  # matched
    assert "1" in out and "passed" in out  # exclusions surfaced


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.get_current_session")
@patch("testgen.mcp.tools.test_results.resolve_test_suite")
def test_bulk_update_no_matches(mock_resolve_suite, mock_session, mock_set, db_session_mock, disposition_perms):
    from testgen.mcp.tools.test_results import bulk_update_test_results

    run_id = uuid4()
    suite = MagicMock(id=uuid4(), test_suite="suite_a", last_complete_test_run_id=run_id)
    mock_resolve_suite.return_value = suite
    mock_session.return_value.scalars.return_value.all.return_value = []
    mock_set.return_value = DispositionUpdate(matched=0, passed_skipped=0)

    with patch("testgen.mcp.tools.test_results.TestRun.get",
               return_value=MagicMock(id=run_id, job_execution_id=run_id, test_suite_id=suite.id)):
        out = bulk_update_test_results(test_suite_id=str(uuid4()), disposition="Confirmed")

    assert "No test results matched" in out


def test_bulk_update_uses_disposition_permission():
    import testgen.mcp.tools.test_results as mod

    closure = {c.cell_contents for c in mod.bulk_update_test_results.__wrapped__.__closure__}
    assert "disposition" in closure


@patch("testgen.mcp.tools.test_results.set_test_results_disposition")
@patch("testgen.mcp.tools.test_results.get_current_session")
@patch("testgen.mcp.tools.test_results.resolve_test_suite")
def test_bulk_update_explicit_run_in_suite(
    mock_resolve_suite, mock_session, mock_set, db_session_mock, disposition_perms
):
    from testgen.mcp.tools.test_results import bulk_update_test_results

    suite = MagicMock(id=uuid4(), test_suite="suite_a")
    mock_resolve_suite.return_value = suite
    run_id = uuid4()
    matched_ids = [uuid4()]
    mock_session.return_value.scalars.return_value.all.return_value = matched_ids
    mock_set.return_value = DispositionUpdate(matched=1, passed_skipped=0)

    with patch(
        "testgen.mcp.tools.test_results.TestRun.get",
        return_value=MagicMock(id=uuid4(), job_execution_id=run_id, test_suite_id=suite.id),
    ):
        out = bulk_update_test_results(
            test_suite_id=str(uuid4()), disposition="Confirmed", job_execution_id=str(run_id)
        )

    assert mock_set.call_args.args[0] == matched_ids
    assert "1" in out


@patch("testgen.mcp.tools.test_results.resolve_test_suite")
def test_bulk_update_explicit_run_from_other_suite_rejected(
    mock_resolve_suite, db_session_mock, disposition_perms
):
    from testgen.mcp.tools.test_results import bulk_update_test_results

    suite = MagicMock(id=uuid4(), test_suite="suite_a")
    mock_resolve_suite.return_value = suite

    with patch(
        "testgen.mcp.tools.test_results.TestRun.get",
        return_value=MagicMock(test_suite_id=uuid4()),  # different suite
    ):
        with pytest.raises(MCPResourceNotAccessible, match=r"Test run .* not found or not accessible"):
            bulk_update_test_results(
                test_suite_id=str(uuid4()), disposition="Confirmed", job_execution_id=str(uuid4())
            )
