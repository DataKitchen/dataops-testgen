from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import SuiteType
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite as RealTestSuite
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


# --- run_tests on contracts --------------------------------------------------


def _contract_suite():
    suite = _mock_test_suite(name="Orders")
    suite.suite_type = SuiteType.CONTRACT
    return suite


def _run(suite, version=None, *, target=None, loaded=None, term_total=3, active=True):
    from testgen.mcp.tools.execution import run_tests

    with (
        patch("testgen.mcp.tools.execution.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.execution.resolve_contract_version", return_value=target),
        patch("testgen.mcp.tools.execution.get_current_session") as session,
        patch.object(SuiteVersion, "get", return_value=loaded),
        patch.object(SuiteVersion, "is_active", return_value=active),
        patch("testgen.mcp.tools.execution.TestDefinition.list_for_suite", return_value=([], term_total)),
        patch("testgen.mcp.tools.execution.JobExecution.submit", return_value=MagicMock(id=uuid4())) as submit,
    ):
        session.return_value.scalar.return_value = uuid4()
        return run_tests(str(suite.id), version=version), submit


def test_running_a_contract_without_a_version_stamps_the_run_version(db_session_mock):
    v3 = SuiteVersion(id=uuid4(), version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC))
    out, submit = _run(_contract_suite(), target=None, loaded=v3)
    assert submit.call_args.kwargs["kwargs"]["version_id"] == str(v3.id)
    assert "**Version:** v3 active" in out
    assert "will not count" not in out


def test_running_the_draft_says_it_will_not_count(db_session_mock):
    draft = SuiteVersion(id=uuid4(), version=4)
    out, submit = _run(_contract_suite(), version=4, target=draft)
    assert submit.call_args.kwargs["kwargs"]["version_id"] == str(draft.id)
    assert "**Version:** v4 draft" in out
    assert "will not count as the contract's status" in out
    assert out.index("**Version:**") < out.index("will not count") < out.index("Use `list_test_runs`")


def test_running_a_superseded_version_says_it_will_not_count(db_session_mock):
    v2 = SuiteVersion(id=uuid4(), version=2, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    out, _ = _run(_contract_suite(), version=2, target=v2, active=False)
    assert "v2 superseded" in out
    assert "will not count" in out


def test_running_a_version_with_no_active_tests_is_refused(db_session_mock):
    draft = SuiteVersion(id=uuid4(), version=4)
    with pytest.raises(MCPUserError, match="v4 draft of contract `Orders` has no active tests to run"):
        _run(_contract_suite(), version=4, target=draft, term_total=0)


def test_only_active_tests_count_toward_a_runnable_version(db_session_mock):
    draft = SuiteVersion(id=uuid4(), version=4)
    with patch("testgen.mcp.tools.execution.TestDefinition.list_for_suite", return_value=([], 3)) as listing:
        from testgen.mcp.tools.execution import run_tests

        with (
            patch("testgen.mcp.tools.execution.resolve_test_suite", return_value=_contract_suite()),
            patch("testgen.mcp.tools.execution.resolve_contract_version", return_value=draft),
            patch.object(SuiteVersion, "is_active", return_value=False),
            patch("testgen.mcp.tools.execution.JobExecution.submit", return_value=MagicMock(id=uuid4())),
        ):
            run_tests(str(uuid4()), version=4)
    assert listing.call_args.kwargs["test_active"] is True


def test_running_a_regular_suite_is_unchanged(db_session_mock):
    suite = _contract_suite()
    suite.suite_type = SuiteType.REGULAR
    out, submit = _run(suite)
    assert submit.call_args.kwargs["kwargs"] == {"test_suite_id": str(suite.id)}
    assert "Version" not in out


def test_running_a_version_of_a_regular_suite_is_refused(db_session_mock):
    from testgen.mcp.tools.execution import run_tests

    suite = _mock_test_suite()
    suite.suite_type = SuiteType.REGULAR
    with (
        patch("testgen.mcp.tools.execution.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.execution.JobExecution.submit") as submit,
        pytest.raises(MCPUserError, match="is not a contract, so it keeps no versions"),
    ):
        run_tests(str(suite.id), version=2)
    submit.assert_not_called()


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
    assert "list_test_runs" in result


def test_run_tests_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.execution import run_tests

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        run_tests("not-a-uuid")


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_run_tests_passes_a_match_schema_override(mock_suite_cls, mock_job_exec, db_session_mock):
    suite_id = uuid4()
    mock_suite_cls.get.return_value = _mock_test_suite(suite_id=suite_id)
    mock_job_exec.submit.return_value = MagicMock(id=uuid4())

    from testgen.mcp.tools.execution import run_tests

    run_tests(str(suite_id), match_schema_name="reference_2026_09_10")

    assert mock_job_exec.submit.call_args.kwargs["kwargs"] == {
        "test_suite_id": str(suite_id),
        "match_schema_name": "reference_2026_09_10",
    }


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_run_tests_passes_caller_metadata(mock_suite_cls, mock_job_exec, db_session_mock):
    suite_id = uuid4()
    mock_suite_cls.get.return_value = _mock_test_suite(suite_id=suite_id)
    mock_job_exec.submit.return_value = MagicMock(id=uuid4())

    from testgen.mcp.tools.execution import run_tests

    run_tests(str(suite_id), metadata={"url": "https://ci.example.com/runs/1"})

    assert mock_job_exec.submit.call_args.kwargs["caller_metadata"] == {
        "url": "https://ci.example.com/runs/1",
    }


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_run_tests_rejects_metadata_that_is_not_an_object(mock_suite_cls, mock_job_exec, db_session_mock):
    suite_id = uuid4()
    mock_suite_cls.get.return_value = _mock_test_suite(suite_id=suite_id)

    from testgen.mcp.tools.execution import run_tests

    with pytest.raises(MCPUserError, match="metadata must be a JSON object"):
        run_tests(str(suite_id), metadata="not-an-object")

    mock_job_exec.submit.assert_not_called()


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_run_tests_rejects_a_schema_that_would_end_the_quoting(
    mock_suite_cls, mock_job_exec, db_session_mock
):
    """The value is substituted into generated SQL inside quote characters, so a name carrying
    one would close them. Rejected before a job is queued."""
    suite_id = uuid4()
    mock_suite_cls.get.return_value = _mock_test_suite(suite_id=suite_id)

    from testgen.mcp.tools.execution import run_tests

    with pytest.raises(MCPUserError, match="match_schema_name must not contain"):
        run_tests(str(suite_id), match_schema_name='x" OR 1=1--')

    mock_job_exec.submit.assert_not_called()


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


@patch("testgen.mcp.tools.execution.resolve_generation_sets", return_value=["Standard"])
@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_defaults_to_stored_sets(mock_suite_cls, mock_job_exec, mock_resolve, db_session_mock):
    suite_id = uuid4()
    suite = _mock_test_suite(suite_id=suite_id)
    mock_suite_cls.get.return_value = suite
    submitted = MagicMock(id=uuid4())
    mock_job_exec.submit.return_value = submitted

    from testgen.mcp.tools.execution import generate_tests

    result = generate_tests(str(suite_id))

    mock_resolve.assert_called_once_with(suite, None)
    call_kwargs = mock_job_exec.submit.call_args.kwargs
    assert call_kwargs["job_key"] == "run-test-generation"
    assert call_kwargs["kwargs"] == {"test_suite_id": str(suite_id), "generation_sets": ["Standard"]}
    assert call_kwargs["source"] == "mcp"

    assert "Test generation submitted for `Quality Suite`" in result
    assert str(submitted.id) in result
    assert "Pending" in result
    assert "list_tests" in result
    assert "verify the new definitions appear" in result


@patch("testgen.mcp.tools.execution.resolve_generation_sets", return_value=["Standard", "Plugin_Set"])
@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_accepts_a_set_list(mock_suite_cls, mock_job_exec, mock_resolve, db_session_mock):
    suite_id = uuid4()
    mock_suite_cls.get.return_value = _mock_test_suite(suite_id=suite_id)
    mock_job_exec.submit.return_value = MagicMock(id=uuid4())

    from testgen.mcp.tools.execution import generate_tests

    generate_tests(str(suite_id), ["Standard", "Plugin_Set"])

    assert mock_job_exec.submit.call_args.kwargs["kwargs"]["generation_sets"] == [
        "Standard",
        "Plugin_Set",
    ]


@patch(
    "testgen.mcp.tools.execution.resolve_generation_sets",
    side_effect=ValueError("Unknown generation sets: Nope."),
)
@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_rejects_unknown_set(mock_suite_cls, mock_job_exec, _mock_resolve, db_session_mock):
    suite_id = uuid4()
    mock_suite_cls.get.return_value = _mock_test_suite(suite_id=suite_id)

    from testgen.mcp.tools.execution import generate_tests

    with pytest.raises(MCPUserError, match="Unknown generation sets: Nope."):
        generate_tests(str(suite_id), ["Nope"])

    mock_job_exec.submit.assert_not_called()


@patch("testgen.mcp.tools.execution.resolve_generation_profile_run", return_value=uuid4())
@patch("testgen.mcp.tools.execution.TableGroup")
@patch("testgen.mcp.tools.execution.resolve_generation_sets", return_value=["Contract"])
@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_submits_a_profiled_contract(
    mock_suite_cls, mock_job_exec, _mock_resolve, _mock_tg, _mock_run, db_session_mock
):
    suite_id = uuid4()
    suite = _mock_test_suite(suite_id=suite_id)
    suite.suite_type = SuiteType.CONTRACT
    mock_suite_cls.get.return_value = suite
    mock_job_exec.submit.return_value = MagicMock(id=uuid4())

    from testgen.mcp.tools.execution import generate_tests

    out = generate_tests(str(suite_id))

    assert mock_job_exec.submit.call_args.kwargs["kwargs"] == {
        "test_suite_id": str(suite_id), "generation_sets": ["Contract"],
    }
    assert "Contract" in out
    assert "Test suite" not in out


@patch("testgen.mcp.tools.execution.resolve_generation_profile_run", return_value=None)
@patch("testgen.mcp.tools.execution.TableGroup")
@patch("testgen.mcp.tools.execution.resolve_generation_sets", return_value=["Contract"])
@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_submits_an_unprofiled_contract_and_says_no_tests_will_be_generated(
    mock_suite_cls, mock_job_exec, _mock_resolve, mock_tg, _mock_run, db_session_mock
):
    suite = _mock_test_suite(suite_id=uuid4())
    suite.suite_type = SuiteType.CONTRACT
    mock_suite_cls.get.return_value = suite
    mock_tg.get.return_value = MagicMock(table_groups_name="orders_tg")
    mock_job_exec.submit.return_value = MagicMock(id=uuid4())

    from testgen.mcp.tools.execution import generate_tests

    out = generate_tests(str(suite.id))

    mock_job_exec.submit.assert_called_once()
    assert "`orders_tg` has not been profiled" in out
    assert "run_profiling" in out


@patch("testgen.mcp.tools.execution.JobExecution")
@patch("testgen.mcp.tools.common.TestSuite")
def test_generate_tests_resolves_regular_and_contract_suites_only(mock_suite_cls, _mock_job_exec, db_session_mock):
    mock_suite_cls.suite_type = RealTestSuite.suite_type
    mock_suite_cls.project_code = RealTestSuite.project_code
    mock_suite_cls.get.return_value = None

    from testgen.mcp.tools.execution import generate_tests

    with pytest.raises(MCPResourceNotAccessible):
        generate_tests(str(uuid4()))

    clauses = mock_suite_cls.get.call_args.args[1:]
    admitted = RealTestSuite.suite_type.in_((SuiteType.REGULAR, SuiteType.CONTRACT))
    assert any(clause.compare(admitted) for clause in clauses)


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


def _generate(suite, *, draft=None):
    from testgen.mcp.tools.execution import generate_tests

    events = []
    with (
        patch("testgen.mcp.tools.execution.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.execution.resolve_generation_sets", return_value=["Standard"]),
        patch("testgen.mcp.tools.execution.TableGroup"),
        patch("testgen.mcp.tools.execution.resolve_generation_profile_run", return_value=uuid4()),
        patch.object(
            TestDefinition,
            "resolve_writable",
            side_effect=lambda *_: events.append("open draft") or (draft.id, {}),
        ) as route,
        patch.object(SuiteVersion, "get", side_effect=lambda version_id: draft if version_id == draft.id else None),
        patch(
            "testgen.mcp.tools.execution.JobExecution.submit",
            side_effect=lambda **_: events.append("submit") or MagicMock(id=uuid4()),
        ) as submit,
    ):
        out = generate_tests(str(suite.id))
    return out, route, submit, events


def test_generating_for_a_frozen_only_contract_opens_the_draft_before_submitting(db_session_mock):
    suite = _contract_suite()
    draft = SuiteVersion(id=uuid4(), version=4)
    out, route, submit, events = _generate(suite, draft=draft)
    assert route.call_args.args == (suite.id,)
    assert events == ["open draft", "submit"]
    assert submit.call_args.kwargs["kwargs"]["test_suite_id"] == str(suite.id)
    assert "**Version:** v4 draft" in out


def test_generating_for_a_regular_suite_opens_no_draft_and_names_no_version(db_session_mock):
    suite = _mock_test_suite()
    suite.suite_type = SuiteType.REGULAR
    out, route, submit, _ = _generate(suite, draft=SuiteVersion(id=uuid4(), version=1))
    route.assert_not_called()
    submit.assert_called_once()
    assert "Version" not in out


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
    mock_compute.return_value = ProjectPermissions(memberships={"some_project": "role_c"}, permission="edit", username="test_user")

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
        with pytest.raises(MCPUserError, match=r"Cannot cancel.*current status is Completed"):
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
    assert "cancel_requested" not in result
    assert "Canceling" in result
    assert "list_test_runs" in result


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
        with pytest.raises(MCPUserError, match=r"Cannot cancel.*current status is Error"):
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
    assert "cancel_requested" not in result
    assert "Canceling" in result
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
