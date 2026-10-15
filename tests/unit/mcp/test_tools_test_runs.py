from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus, SuiteType
from testgen.common.models.job_execution import QUEUED_MESSAGE
from testgen.common.models.test_run import TestRunSummary
from testgen.common.models.test_suite import TestSuite as RealTestSuite
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions
from testgen.mcp.tools.common import MCP_SUITE_TYPES
from testgen.mcp.tools.markdown import MdDoc

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
        "version_number": None, "version_frozen_at": None, "active_version_number": None,
        "test_starttime": None, "is_preview": False,
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
        suite_types=MCP_SUITE_TYPES,
        version_id=None,
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


@patch("testgen.mcp.tools.test_runs.TestRun")
def test_get_test_run_explains_a_queued_run(mock_run, db_session_mock):
    summary = _make_run_summary(
        project_code="demo",
        status=JobStatus.QUEUED, status_label="Queued",
        started_at=None, completed_at=None,
        test_ct=None, passed_ct=None, failed_ct=None, warning_ct=None, error_ct=None,
        log_ct=None, dismissed_ct=None, dq_score_testing=None,
    )
    mock_run.select_summary.return_value = ([summary], 1)

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"}, permission="view", username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]
            from testgen.mcp.tools.test_runs import get_test_run

            result = get_test_run(str(summary.job_execution_id))

    assert "**Status:** Queued" in result
    assert QUEUED_MESSAGE in result


@patch("testgen.mcp.tools.test_runs.JobExecution")
@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_resolves_a_contract_by_name(mock_suite, mock_run, mock_next, mock_je, db_session_mock):
    mock_je.select_active_by_kwargs.return_value = []
    mock_suite.suite_type = RealTestSuite.suite_type
    mock_suite.project_code = RealTestSuite.project_code
    mock_suite.test_suite = RealTestSuite.test_suite
    mock_suite.select_minimal_where.return_value = [MagicMock(id=uuid4())]
    mock_run.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.test_runs import list_test_runs

    list_test_runs(project_code="demo", test_suite="Orders")

    clauses = [
        " ".join(str(c.compile(compile_kwargs={"literal_binds": True})).split())
        for c in mock_suite.select_minimal_where.call_args.args
    ]
    assert "test_suites.suite_type IN ('regular', 'contract')" in clauses
    assert mock_run.select_summary.call_args.kwargs["suite_types"] == MCP_SUITE_TYPES


# --- versions ---------------------------------------------------------------


def test_list_test_runs_with_a_version_requires_a_suite(db_session_mock):
    from testgen.mcp.tools.test_runs import list_test_runs

    with pytest.raises(MCPUserError, match="`version` needs `test_suite`"):
        list_test_runs(project_code="demo", version=3)


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.JobExecution")
@patch("testgen.mcp.tools.test_runs.resolve_contract_version")
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_with_a_version_narrows_to_that_version(
    mock_suite, mock_run, mock_resolve, mock_je, mock_next, db_session_mock,
):
    mock_je.select_active_by_kwargs.return_value = []
    suite_id = uuid4()
    mock_suite.select_minimal_where.return_value = [MagicMock(id=suite_id)]
    contract = MagicMock(id=suite_id)
    mock_suite.get.return_value = contract
    v3 = MagicMock(id=uuid4())
    mock_resolve.return_value = v3
    mock_run.select_summary.return_value = ([_make_run_summary(test_suite="Orders")], 1)

    from testgen.mcp.tools.test_runs import list_test_runs

    list_test_runs(project_code="demo", test_suite="Orders", version=3)

    mock_resolve.assert_called_once_with(contract, 3)
    assert mock_run.select_summary.call_args.kwargs["version_id"] == str(v3.id)
    assert mock_run.select_summary.call_args.kwargs["test_suite_id"] == str(suite_id)


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.JobExecution")
@patch("testgen.mcp.tools.test_runs.resolve_contract_version")
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_pending_runs_match_the_version_only_when_one_is_given(
    mock_suite, mock_run, mock_resolve, mock_je, mock_next, db_session_mock,
):
    mock_je.select_active_by_kwargs.return_value = []
    suite_id = uuid4()
    mock_suite.select_minimal_where.return_value = [MagicMock(id=suite_id)]
    v3 = MagicMock(id=uuid4())
    mock_resolve.return_value = v3
    mock_run.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.test_runs import list_test_runs

    list_test_runs(project_code="demo", test_suite="Orders", version=3)
    assert mock_je.select_active_by_kwargs.call_args.kwargs["kwargs_match"] == {
        "test_suite_id": str(suite_id), "version_id": str(v3.id),
    }

    list_test_runs(project_code="demo", test_suite="Orders")
    assert mock_je.select_active_by_kwargs.call_args.kwargs["kwargs_match"] == {"test_suite_id": str(suite_id)}


@patch("testgen.mcp.tools.test_runs.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.test_runs.TestRun")
@patch("testgen.mcp.tools.test_runs.TestSuite")
def test_list_test_runs_with_a_version_of_a_regular_suite_is_refused(
    mock_suite, mock_run, mock_next, db_session_mock,
):
    mock_suite.select_minimal_where.return_value = [MagicMock(id=uuid4())]
    mock_suite.get.return_value = MagicMock(id=uuid4(), suite_type=SuiteType.REGULAR)

    from testgen.mcp.tools.test_runs import list_test_runs

    with pytest.raises(MCPUserError, match="is not a contract, so it keeps no versions"):
        list_test_runs(project_code="demo", test_suite="Quality Suite", version=2)
    mock_run.select_summary.assert_not_called()


def _real_run_summary(**overrides):
    fields = {
        "job_execution_id": uuid4(), "test_run_id": uuid4(), "job_schedule_id": None,
        "status": JobStatus.COMPLETED, "created_at": _CREATED, "started_at": _STARTED,
        "completed_at": _COMPLETED, "active_seconds": 300.0, "error_message": None, "progress": [],
        "table_groups_name": "core_tables", "test_suite": "Orders", "project_code": "demo",
        "project_name": "Demo", "test_ct": 5, "passed_ct": 5, "warning_ct": 0, "failed_ct": 0,
        "error_ct": 0, "log_ct": 0, "dismissed_ct": 0, "dq_score_testing": None, "total_count": 1,
    }
    fields.update(overrides)
    return TestRunSummary(**fields)


def _render(run):
    from testgen.mcp.tools.test_runs import _render_test_run_section

    doc = MdDoc()
    _render_test_run_section(doc, run)
    return doc.render()


def test_a_preview_run_stays_a_preview_after_its_version_was_frozen(db_session_mock):
    run = _real_run_summary(
        version_number=4, version_frozen_at=datetime(2026, 9, 12, tzinfo=UTC),
        active_version_number=4, test_starttime=datetime(2026, 9, 10, 9, 0),
    )
    out = _render(run)
    assert "**Version:** v4 active" in out
    assert "**Preview:** Yes" in out


def test_a_run_started_after_its_version_was_frozen_is_not_a_preview(db_session_mock):
    run = _real_run_summary(
        version_number=4, version_frozen_at=datetime(2026, 9, 12, tzinfo=UTC),
        active_version_number=5, test_starttime=datetime(2026, 9, 13, 9, 0),
    )
    out = _render(run)
    assert "**Version:** v4 superseded" in out
    assert "Preview" not in out


def test_a_run_of_a_draft_is_a_preview(db_session_mock):
    run = _real_run_summary(version_number=5, active_version_number=4, test_starttime=datetime(2026, 9, 13, 9, 0))
    out = _render(run)
    assert "**Version:** v5 draft" in out
    assert "**Preview:** Yes" in out


def test_a_versioned_run_without_a_start_time_is_not_a_preview(db_session_mock):
    run = _real_run_summary(
        version_number=4, version_frozen_at=datetime(2026, 9, 12, tzinfo=UTC), active_version_number=4,
    )
    assert run.is_preview is False


def test_a_regular_run_row_names_no_version(db_session_mock):
    out = _render(_real_run_summary())
    assert "Version" not in out and "Preview" not in out
