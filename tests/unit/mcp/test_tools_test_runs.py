from unittest.mock import MagicMock, patch
from uuid import uuid4


def _make_run_summary(**overrides):
    defaults = {
        "test_run_id": uuid4(), "test_suite": "Quality Suite", "project_name": "Demo",
        "table_groups_name": "core_tables", "status": "Complete",
        "test_starttime": "2024-01-15T10:00:00", "test_endtime": "2024-01-15T10:05:00",
        "test_ct": 50, "passed_ct": 45, "failed_ct": 3, "warning_ct": 2, "error_ct": 0,
        "log_ct": 0, "dismissed_ct": 0, "dq_score_testing": 92.5,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_get_recent_test_runs_default_limit(mock_suite, mock_run, db_session_mock):
    """Default limit=1 returns one run per suite."""
    runs = [_make_run_summary(test_run_id=uuid4()) for _ in range(7)]
    mock_run.select_summary.return_value = runs

    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("demo")

    # All 7 runs have test_suite="Quality Suite", so only 1 should appear
    assert "1 run(s)" in result
    assert "Quality Suite" in result
    assert "92.5" in result
    mock_run.select_summary.assert_called_once_with(project_code="demo", test_suite_id=None)


@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_get_recent_test_runs_custom_limit(mock_suite, mock_run, db_session_mock):
    """Custom limit returns up to N runs per suite."""
    runs = [_make_run_summary() for _ in range(3)]
    mock_run.select_summary.return_value = runs

    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("demo", limit=10)

    assert "3 run(s)" in result


@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_get_recent_test_runs_per_suite_grouping(mock_suite, mock_run, db_session_mock):
    """With multiple suites, returns limit runs per suite."""
    runs = [
        _make_run_summary(test_suite="Suite A", test_run_id=uuid4()),
        _make_run_summary(test_suite="Suite A", test_run_id=uuid4()),
        _make_run_summary(test_suite="Suite B", test_run_id=uuid4()),
        _make_run_summary(test_suite="Suite B", test_run_id=uuid4()),
    ]
    mock_run.select_summary.return_value = runs

    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("demo")

    # limit=1 (default), so 1 per suite = 2 total
    assert "2 run(s)" in result
    assert "Suite A" in result
    assert "Suite B" in result


@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_get_recent_test_runs_with_suite_name(mock_suite, mock_run, db_session_mock):
    suite_id = uuid4()
    suite_minimal = MagicMock()
    suite_minimal.id = suite_id
    mock_suite.select_minimal_where.return_value = [suite_minimal]
    mock_run.select_summary.return_value = [_make_run_summary(test_suite="My Suite")]

    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("demo", test_suite="My Suite")

    mock_run.select_summary.assert_called_once_with(project_code="demo", test_suite_id=str(suite_id))
    assert "My Suite" in result


@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_get_recent_test_runs_suite_not_found(mock_suite, mock_run, db_session_mock):
    mock_suite.select_minimal_where.return_value = []

    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("demo", test_suite="Nonexistent")

    assert "not found" in result
    mock_run.select_summary.assert_not_called()


@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_get_recent_test_runs_no_runs(mock_suite, mock_run, db_session_mock):
    mock_run.select_summary.return_value = []

    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("demo")

    assert "No completed test runs" in result


@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_get_recent_test_runs_shows_failure_counts(mock_suite, mock_run, db_session_mock):
    mock_run.select_summary.return_value = [_make_run_summary(failed_ct=5, warning_ct=2)]

    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("demo")

    assert "5 failed" in result
    assert "2 warnings" in result


def test_get_recent_test_runs_empty_project_code(db_session_mock):
    from testgen.mcp.tools.test_runs import get_recent_test_runs

    result = get_recent_test_runs("")

    assert "Missing required parameter" in result
    assert "project_code" in result
