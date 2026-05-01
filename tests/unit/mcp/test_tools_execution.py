from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions


def _mock_test_suite(suite_id=None, project_code="demo", name="Quality Suite"):
    suite = MagicMock()
    suite.id = suite_id or uuid4()
    suite.project_code = project_code
    suite.test_suite = name
    return suite


def _mock_table_group(group_id=None, project_code="demo", name="core_tables"):
    tg = MagicMock()
    tg.id = group_id or uuid4()
    tg.project_code = project_code
    tg.table_groups_name = name
    return tg


def _mock_job(job_id=None, project_code="demo", status="pending", request_cancel_returns=True):
    job = MagicMock()
    job.id = job_id or uuid4()
    job.project_code = project_code
    job.status = status
    job.request_cancel.return_value = request_cancel_returns
    return job


def _patch_job_lookup(job):
    """Patch the SQLAlchemy lookup chain inside _resolve_job_execution to return ``job``."""
    session = MagicMock()
    session.scalars.return_value.first.return_value = job
    return patch("testgen.mcp.tools.execution.get_current_session", return_value=session)


# --- run_tests --------------------------------------------------------------


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_run_tests_submits_job(mock_suite_cls, mock_job_exec, db_session_mock):
    suite_id = uuid4()
    suite = _mock_test_suite(suite_id=suite_id)
    mock_suite_cls.get.return_value = suite
    submitted = MagicMock(id=uuid4())
    mock_job_exec.submit.return_value = submitted

    from testgen.mcp.tools.execution import run_tests

    result = run_tests(str(suite_id))

    mock_job_exec.submit.assert_called_once()
    call_kwargs = mock_job_exec.submit.call_args.kwargs
    assert call_kwargs["job_key"] == "run-tests"
    assert call_kwargs["kwargs"] == {"test_suite_id": str(suite_id)}
    assert call_kwargs["source"] == "mcp"
    assert call_kwargs["project_code"] == "demo"

    assert "Test run submitted for `Quality Suite`" in result
    assert str(submitted.id) in result
    assert "Pending" in result
    assert "get_recent_test_runs" in result


def test_run_tests_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.execution import run_tests

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        run_tests("not-a-uuid")


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_run_tests_suite_not_found_or_inaccessible(mock_suite_cls, mock_job_exec, db_session_mock):
    """Unknown UUID, monitor suite, and forbidden project all collapse to the same SQL-side
    miss inside resolve_test_suite."""
    mock_suite_cls.get.return_value = None

    from testgen.mcp.tools.execution import run_tests

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        run_tests(str(uuid4()))
    mock_job_exec.submit.assert_not_called()


# --- run_profiling ----------------------------------------------------------


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TableGroup")
def test_run_profiling_submits_job(mock_tg_cls, mock_job_exec, db_session_mock):
    group_id = uuid4()
    tg = _mock_table_group(group_id=group_id)
    mock_tg_cls.get.return_value = tg
    submitted = MagicMock(id=uuid4())
    mock_job_exec.submit.return_value = submitted

    from testgen.mcp.tools.execution import run_profiling

    result = run_profiling(str(group_id))

    call_kwargs = mock_job_exec.submit.call_args.kwargs
    assert call_kwargs["job_key"] == "run-profile"
    assert call_kwargs["kwargs"] == {"table_group_id": str(group_id)}
    assert call_kwargs["source"] == "mcp"
    assert call_kwargs["project_code"] == "demo"

    assert "Profiling run submitted for `core_tables`" in result
    assert str(submitted.id) in result
    assert "Pending" in result
    assert "list_profiling_summaries" in result


def test_run_profiling_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.execution import run_profiling

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        run_profiling("not-a-uuid")


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TableGroup")
def test_run_profiling_table_group_not_found_or_inaccessible(mock_tg_cls, mock_job_exec, db_session_mock):
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.execution import run_profiling

    with pytest.raises(MCPResourceNotAccessible, match="Table group .* not found or not accessible"):
        run_profiling(str(uuid4()))
    mock_job_exec.submit.assert_not_called()


# --- generate_tests ---------------------------------------------------------


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_submits_job(mock_suite_cls, mock_job_exec, db_session_mock):
    suite_id = uuid4()
    suite = _mock_test_suite(suite_id=suite_id)
    mock_suite_cls.get.return_value = suite
    submitted = MagicMock(id=uuid4())
    mock_job_exec.submit.return_value = submitted

    from testgen.mcp.tools.execution import generate_tests

    result = generate_tests(str(suite_id))

    call_kwargs = mock_job_exec.submit.call_args.kwargs
    assert call_kwargs["job_key"] == "run-test-generation"
    assert call_kwargs["kwargs"] == {"test_suite_id": str(suite_id), "generation_set": "Standard"}
    assert call_kwargs["source"] == "mcp"

    assert "Test generation submitted for `Quality Suite`" in result
    assert str(submitted.id) in result
    assert "Pending" in result
    assert "list_tests" in result
    assert "verify the new definitions appear" in result


def test_generate_tests_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.execution import generate_tests

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        generate_tests("not-a-uuid")


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_suite_not_found_or_inaccessible(mock_suite_cls, mock_job_exec, db_session_mock):
    mock_suite_cls.get.return_value = None

    from testgen.mcp.tools.execution import generate_tests

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        generate_tests(str(uuid4()))
    mock_job_exec.submit.assert_not_called()


# --- decorator-level denial (no edit on any project) -----------------------


@pytest.mark.parametrize(
    "tool_name, args",
    [
        ("run_tests", (str(uuid4()),)),
        ("run_profiling", (str(uuid4()),)),
        ("generate_tests", (str(uuid4()),)),
        ("cancel_test_run", (str(uuid4()),)),
        ("cancel_profiling_run", (str(uuid4()),)),
    ],
)
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_decorator_denies_when_user_has_no_edit_on_any_project(
    mock_compute, tool_name, args, db_session_mock
):
    """@mcp_permission('edit') raises MCPPermissionDenied — distinct from the
    resolver-level MCPResourceNotAccessible — when the user has no edit on any project."""
    mock_compute.return_value = ProjectPermissions(memberships={"some_project": "role_c"}, permission="edit")

    from testgen.mcp.tools import execution

    tool = getattr(execution, tool_name)
    with pytest.raises(MCPPermissionDenied, match="does not include the necessary permission"):
        tool(*args)


# --- cancel_test_run --------------------------------------------------------


def test_cancel_test_run_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.execution import cancel_test_run

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        cancel_test_run("not-a-uuid")


def test_cancel_test_run_not_found_or_inaccessible(db_session_mock):
    """Unknown UUID, wrong job_key (e.g. profiling run UUID), forbidden project, and
    source='system' all collapse to the same SQL-side miss inside _resolve_job_execution."""
    from testgen.mcp.tools.execution import cancel_test_run

    with _patch_job_lookup(None):
        with pytest.raises(MCPResourceNotAccessible, match="Test run .* not found or not accessible"):
            cancel_test_run(str(uuid4()))


def test_cancel_test_run_terminal_status(db_session_mock):
    job = _mock_job(status="completed", request_cancel_returns=False)

    from testgen.mcp.tools.execution import cancel_test_run

    with _patch_job_lookup(job):
        with pytest.raises(MCPUserError, match=r"Cannot cancel.*current status is `completed`"):
            cancel_test_run(str(uuid4()))


def test_cancel_test_run_success(db_session_mock):
    job_id = uuid4()
    job = _mock_job(job_id=job_id, status="pending")

    def fake_request_cancel():
        job.status = "cancel_requested"
        return True

    job.request_cancel.side_effect = fake_request_cancel

    from testgen.mcp.tools.execution import cancel_test_run

    with _patch_job_lookup(job):
        result = cancel_test_run(str(job_id))

    assert "Test run cancellation requested" in result
    assert str(job_id) in result
    assert "cancel_requested" in result
    assert "get_recent_test_runs" in result


def test_cancel_test_run_filters_by_job_key(db_session_mock):
    """Verify the WHERE clause filters by job_key='run-tests'. A profiling-run UUID
    handed to cancel_test_run resolves to None and surfaces as 'not found or not accessible'."""
    from sqlalchemy.sql.elements import BinaryExpression

    captured: dict = {}

    class FakeSession:
        def scalars(self, query):
            captured["clauses"] = list(query.whereclause.clauses) if query.whereclause is not None else []
            return MagicMock(first=MagicMock(return_value=None))

    fake = FakeSession()

    from testgen.mcp.tools.execution import cancel_test_run

    with patch("testgen.mcp.tools.execution.get_current_session", return_value=fake):
        with pytest.raises(MCPResourceNotAccessible):
            cancel_test_run(str(uuid4()))

    rendered = [str(c) for c in captured["clauses"] if isinstance(c, BinaryExpression)]
    assert any("job_executions.job_key" in s for s in rendered), rendered


# --- cancel_profiling_run ---------------------------------------------------


def test_cancel_profiling_run_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.execution import cancel_profiling_run

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        cancel_profiling_run("not-a-uuid")


def test_cancel_profiling_run_not_found_or_inaccessible(db_session_mock):
    from testgen.mcp.tools.execution import cancel_profiling_run

    with _patch_job_lookup(None):
        with pytest.raises(MCPResourceNotAccessible, match="Profiling run .* not found or not accessible"):
            cancel_profiling_run(str(uuid4()))


def test_cancel_profiling_run_terminal_status(db_session_mock):
    job = _mock_job(status="error", request_cancel_returns=False)

    from testgen.mcp.tools.execution import cancel_profiling_run

    with _patch_job_lookup(job):
        with pytest.raises(MCPUserError, match=r"Cannot cancel.*current status is `error`"):
            cancel_profiling_run(str(uuid4()))


def test_cancel_profiling_run_success(db_session_mock):
    job_id = uuid4()
    job = _mock_job(job_id=job_id, status="running")

    def fake_request_cancel():
        job.status = "cancel_requested"
        return True

    job.request_cancel.side_effect = fake_request_cancel

    from testgen.mcp.tools.execution import cancel_profiling_run

    with _patch_job_lookup(job):
        result = cancel_profiling_run(str(job_id))

    assert "Profiling run cancellation requested" in result
    assert str(job_id) in result
    assert "cancel_requested" in result
    assert "list_profiling_summaries" in result


def test_cancel_profiling_run_filters_by_job_key(db_session_mock):
    """Verify the WHERE clause filters by job_key='run-profile'."""
    from sqlalchemy.sql.elements import BinaryExpression

    captured: dict = {}

    class FakeSession:
        def scalars(self, query):
            captured["clauses"] = list(query.whereclause.clauses) if query.whereclause is not None else []
            return MagicMock(first=MagicMock(return_value=None))

    fake = FakeSession()

    from testgen.mcp.tools.execution import cancel_profiling_run

    with patch("testgen.mcp.tools.execution.get_current_session", return_value=fake):
        with pytest.raises(MCPResourceNotAccessible):
            cancel_profiling_run(str(uuid4()))

    rendered = [str(c) for c in captured["clauses"] if isinstance(c, BinaryExpression)]
    assert any("job_executions.job_key" in s for s in rendered), rendered
