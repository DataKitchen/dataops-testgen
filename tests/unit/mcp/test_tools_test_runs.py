from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

_CREATED = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
_STARTED = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
_COMPLETED = datetime(2024, 1, 15, 10, 5, 0, tzinfo=UTC)


def _make_run_summary(**overrides):
    defaults = {
        "test_run_id": uuid4(), "job_execution_id": uuid4(),
        "test_suite": "Quality Suite", "project_name": "Demo", "project_code": "demo",
        "table_groups_name": "core_tables", "status": JobStatus.COMPLETED,
        "status_label": "Completed",
        "created_at": _CREATED, "started_at": _STARTED, "completed_at": _COMPLETED,
        "test_ct": 50, "passed_ct": 45, "failed_ct": 3, "warning_ct": 2, "error_ct": 0,
        "log_ct": 0, "dismissed_ct": 0, "dq_score_testing": 92.5,
        "error_message": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_default(mock_suite, mock_run, mock_next, db_session_mock):
    runs = [_make_run_summary() for _ in range(3)]
    mock_run.select_summary.return_value = (runs, len(runs))

    from testgen.mcp.tools.test_runs import list_test_runs

    result = list_test_runs(project_code="demo")

    mock_run.select_summary.assert_called_once_with(
        project_code="demo",
        table_group_id=None,
        test_suite_id=None,
        schedule_id=None,
        statuses=None,
        page=1,
        page_size=10,
    )
    assert "Test runs" in result
    assert "demo" in result
    assert "Quality Suite" in result
    assert "92.5" in result


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_with_status_filter(mock_suite, mock_run, mock_next, db_session_mock):
    mock_run.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.test_runs import list_test_runs

    list_test_runs(project_code="demo", status="Pending")

    call_kwargs = mock_run.select_summary.call_args.kwargs
    assert call_kwargs["statuses"] == [JobStatus.PENDING, JobStatus.CLAIMED]


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_with_schedule_filter(mock_suite, mock_run, mock_next, db_session_mock):
    mock_run.select_summary.return_value = ([], 0)
    schedule_id = str(uuid4())

    from testgen.mcp.tools.test_runs import list_test_runs

    list_test_runs(project_code="demo", schedule_id=schedule_id, status="Completed")

    call_kwargs = mock_run.select_summary.call_args.kwargs
    assert call_kwargs["schedule_id"] == schedule_id
    assert call_kwargs["statuses"] == [JobStatus.COMPLETED]


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_unknown_schedule_returns_empty_envelope(mock_suite, mock_run, mock_next, db_session_mock):
    # Unknown/inaccessible/wrong-kind schedule yields no rows — standard empty envelope, not an error.
    mock_run.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.test_runs import list_test_runs

    result = list_test_runs(project_code="demo", schedule_id=str(uuid4()))

    assert "No test runs" in result


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_malformed_schedule_raises(mock_suite, mock_run, mock_next, db_session_mock):
    from testgen.mcp.tools.test_runs import list_test_runs

    with pytest.raises(MCPUserError):
        list_test_runs(project_code="demo", schedule_id="not-a-uuid")
    mock_run.select_summary.assert_not_called()


@patch("testgen.mcp.tools.test_runs.JobExecution")
@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_schedule_filters_pending(mock_suite, mock_run, mock_next, mock_je, db_session_mock):
    mock_je.select_active_by_kwargs.return_value = []
    suite_id = uuid4()
    mock_suite.select_minimal_where.return_value = [MagicMock(id=suite_id)]
    mock_run.select_summary.return_value = ([], 0)
    schedule_id = str(uuid4())

    from testgen.mcp.tools.test_runs import list_test_runs

    list_test_runs(project_code="demo", test_suite="Quality", schedule_id=schedule_id)

    # A schedule clause is forwarded to the pending-JE query (positional *clauses arg).
    assert mock_je.select_active_by_kwargs.call_args.args


@patch("testgen.mcp.tools.test_runs.JobExecution")
@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_with_suite_name(mock_suite, mock_run, mock_next, mock_je, db_session_mock):
    mock_je.select_active_by_kwargs.return_value = []
    suite_id = uuid4()
    suite_minimal = MagicMock(id=suite_id)
    mock_suite.select_minimal_where.return_value = [suite_minimal]
    mock_run.select_summary.return_value = ([_make_run_summary(test_suite="My Suite")], 1)

    from testgen.mcp.tools.test_runs import list_test_runs

    result = list_test_runs(project_code="demo", test_suite="My Suite")

    call_kwargs = mock_run.select_summary.call_args.kwargs
    assert call_kwargs["test_suite_id"] == str(suite_id)
    assert "My Suite" in result


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_suite_not_found(mock_suite, mock_run, mock_next, db_session_mock):
    mock_suite.select_minimal_where.return_value = []

    from testgen.mcp.tools.test_runs import list_test_runs

    with pytest.raises(MCPResourceNotAccessible):
        list_test_runs(project_code="demo", test_suite="Nonexistent")
    mock_run.select_summary.assert_not_called()


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_empty(mock_suite, mock_run, mock_next, db_session_mock):
    mock_run.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.test_runs import list_test_runs

    result = list_test_runs(project_code="demo")

    assert "No test runs" in result


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_includes_pending_run(mock_suite, mock_run, mock_next, db_session_mock):
    pending = _make_run_summary(
        status=JobStatus.PENDING, status_label="Pending",
        started_at=None, completed_at=None,
        test_ct=None, passed_ct=None, failed_ct=None, warning_ct=None, error_ct=None,
        log_ct=None, dismissed_ct=None, dq_score_testing=None,
    )
    mock_run.select_summary.return_value = ([pending], 1)

    from testgen.mcp.tools.test_runs import list_test_runs

    result = list_test_runs(project_code="demo")

    assert "Pending" in result
    assert "In progress" in result


@patch("testgen.mcp.tools.test_runs.JobExecution")
@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value="2026-06-01T02:00:00")
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_shows_next_scheduled(mock_suite, mock_run, mock_next, mock_je, db_session_mock):
    mock_je.select_active_by_kwargs.return_value = []
    suite_id = uuid4()
    mock_suite.select_minimal_where.return_value = [MagicMock(id=suite_id)]
    mock_run.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.test_runs import list_test_runs

    result = list_test_runs(project_code="demo", test_suite="Quality")

    assert "Next scheduled run" in result


@patch("testgen.mcp.tools.test_runs.JobExecution")
@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_renders_pending_section(
    mock_suite, mock_run, mock_next, mock_je, db_session_mock,
):
    """When scoped by suite, pending JEs are surfaced in a separate section."""
    suite_id = uuid4()
    mock_suite.select_minimal_where.return_value = [MagicMock(id=suite_id)]
    mock_run.select_summary.return_value = ([], 0)
    pending_je = MagicMock(
        id=uuid4(), status=JobStatus.PENDING,
        created_at=_CREATED, started_at=None, completed_at=None,
    )
    mock_je.select_active_by_kwargs.return_value = [pending_je]

    from testgen.mcp.tools.test_runs import list_test_runs

    result = list_test_runs(project_code="demo", test_suite="Quality")

    assert "Pending (1)" in result
    assert "In progress" in result
    mock_je.select_active_by_kwargs.assert_called_once()


def test_list_test_runs_invalid_status(db_session_mock):
    from testgen.mcp.tools.test_runs import list_test_runs

    with pytest.raises(MCPUserError, match="Invalid status"):
        list_test_runs(project_code="demo", status="Bogus")


def test_list_test_runs_requires_project_or_table_group(db_session_mock):
    from testgen.mcp.tools.test_runs import list_test_runs

    with pytest.raises(MCPUserError, match="Provide either"):
        list_test_runs()


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_test_runs_raises_not_found_for_inaccessible_project(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"other_project": "role_a"},
        permission="view",
        username="test_user",
    )

    from testgen.mcp.tools.test_runs import list_test_runs

    with pytest.raises(MCPPermissionDenied):
        list_test_runs(project_code="secret_project")


# ----------------------------------------------------------------------
# get_test_run
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.test_runs.TestRun")
def test_get_test_run_returns_detail(mock_run, db_session_mock):
    summary = _make_run_summary(project_code="demo")
    mock_run.select_summary.return_value = ([summary], 1)

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"},
            permission="view",
            username="test_user",
        )
        with patch(
            "testgen.mcp.permissions.PluginHook"
        ) as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]
            from testgen.mcp.tools.test_runs import get_test_run

            result = get_test_run(str(summary.job_execution_id))

    assert "Quality Suite" in result
    assert "Completed" in result
    assert "92.5" in result


@patch("testgen.mcp.tools.test_runs.TestRun")
def test_get_test_run_pending_no_results(mock_run, db_session_mock):
    summary = _make_run_summary(
        project_code="demo",
        status=JobStatus.PENDING, status_label="Pending",
        started_at=None, completed_at=None,
        test_ct=None, passed_ct=None, failed_ct=None, warning_ct=None, error_ct=None,
        log_ct=None, dismissed_ct=None, dq_score_testing=None,
    )
    mock_run.select_summary.return_value = ([summary], 1)

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"},
            permission="view",
            username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]
            from testgen.mcp.tools.test_runs import get_test_run

            result = get_test_run(str(summary.job_execution_id))

    assert "Pending" in result
    assert "In progress" in result
    assert "Results" not in result


@patch("testgen.mcp.tools.test_runs.TestRun")
def test_get_test_run_not_found(mock_run, db_session_mock):
    mock_run.select_summary.return_value = ([], 0)

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"},
            permission="view",
            username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]
            from testgen.mcp.tools.test_runs import get_test_run

            with pytest.raises(MCPResourceNotAccessible):
                get_test_run(str(uuid4()))


@patch("testgen.mcp.tools.test_runs.TestRun")
def test_get_test_run_inaccessible_project(mock_run, db_session_mock):
    summary = _make_run_summary(project_code="secret")
    mock_run.select_summary.return_value = ([summary], 1)

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"},
            permission="view",
            username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]
            from testgen.mcp.tools.test_runs import get_test_run

            with pytest.raises(MCPResourceNotAccessible):
                get_test_run(str(summary.job_execution_id))


def test_get_test_run_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_runs import get_test_run

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_test_run("not-a-uuid")
