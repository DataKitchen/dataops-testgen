from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.hygiene_issue import Disposition, HygieneIssue, IssueLikelihood
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.pii_masking import PII_REDACTED
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions, _mcp_project_permissions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_row(**overrides):
    base = {
        "id": uuid4(),
        "project_code": "demo",
        "issue_type_name": "Non-Standard Blank Values",
        "schema_name": "demo",
        "table_name": "orders",
        "column_name": "frame_size",
        "impact_dimension": "Usability",
        "dq_dimension": "Completeness",
        "disposition": Disposition.CONFIRMED,
        "priority": "Definite",
        "detail": "Dummy: 5",
        "detail_redactable": False,
        "pii_flag": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _search_row(**overrides):
    base = {
        "id": uuid4(),
        "project_code": "demo",
        "issue_type_name": "Non-Standard Blank Values",
        "table_groups_name": "default",
        "job_execution_id": uuid4(),
        "started_at": datetime(2026, 5, 1),
        "schema_name": "demo",
        "table_name": "orders",
        "column_name": "frame_size",
        "impact_dimension": "Usability",
        "dq_dimension": "Completeness",
        "disposition": Disposition.CONFIRMED,
        "priority": "Definite",
        "detail": "Dummy: 5",
        "detail_redactable": False,
        "pii_flag": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _detail_row(**overrides):
    base = {
        "id": uuid4(),
        "project_code": "demo",
        "issue_type_name": "Non-Standard Blank Values",
        "type_description": "Description body.",
        "suggested_action": "Suggested action body.",
        "schema_name": "demo",
        "table_name": "orders",
        "column_name": "frame_size",
        "dq_dimension": "Completeness",
        "impact_dimension": "Usability",
        "disposition": Disposition.CONFIRMED,
        "priority": "Definite",
        "detail": "Dummy: 5",
        "detail_redactable": False,
        "pii_flag": None,
        "job_execution_id": uuid4(),
        "started_at": datetime(2026, 5, 1),
        "column_general_type": "A",
        "column_db_data_type": "varchar(50)",
        "column_record_ct": 100,
        "column_null_value_ct": 5,
        "column_distinct_value_ct": 50,
    }
    base.update(overrides)
    return MagicMock(**base)


def _mock_table_group(project_code="demo"):
    tg = MagicMock()
    tg.id = uuid4()
    tg.project_code = project_code
    return tg


def _mock_run(project_code="demo"):
    run = MagicMock()
    run.id = uuid4()
    run.job_execution_id = uuid4()
    run.table_groups_id = uuid4()
    run.project_code = project_code
    return run


def _compiled_clauses(call_args) -> str:
    """Compile every positional arg of a model-method call to Postgres SQL."""
    pieces = []
    for arg in call_args.args:
        try:
            pieces.append(str(arg.compile(dialect=postgresql.dialect())))
        except (AttributeError, TypeError):
            pieces.append(str(arg))
    return "\n".join(pieces)


def _set_full_perms(permission="view"):
    """Manually set a permission context. Used for helpers that read the contextvar
    directly without going through @mcp_permission (e.g. _resolve_profile_run_je_id)."""
    perms = MagicMock(spec=ProjectPermissions)
    perms.memberships = {"demo": "role_a"}
    perms.permission = permission
    perms.username = "test_user"
    perms.allowed_codes = ["demo"]
    perms.codes_allowed_to.return_value = ["demo"]
    perms.has_access.side_effect = lambda code: code in ["demo"]
    return _mcp_project_permissions.set(perms)


# ---------------------------------------------------------------------------
# _redact_detail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "redactable,pii_flag,project_in_view_pii,should_redact",
    [
        (True, "B/NAME/Individual", False, True),
        (True, "B/NAME/Individual", True, False),
        (True, None, False, False),
        (False, "B/NAME/Individual", False, False),
        (False, None, True, False),
        (None, None, False, False),
    ],
)
def test_redact_detail_matrix(redactable, pii_flag, project_in_view_pii, should_redact):
    from testgen.mcp.tools.hygiene_issues import _redact_detail

    row = _list_row(
        detail_redactable=redactable,
        pii_flag=pii_flag,
        detail="ssn=123-45-6789",
        project_code="demo",
    )
    view_pii_codes = {"demo"} if project_in_view_pii else set()
    result = _redact_detail(row, view_pii_codes)

    assert (result == PII_REDACTED) is should_redact
    if not should_redact:
        assert result == "ssn=123-45-6789"


def test_redact_detail_view_pii_per_project():
    from testgen.mcp.tools.hygiene_issues import _redact_detail

    row = _list_row(detail_redactable=True, pii_flag="B/NAME", detail="raw", project_code="proj_b")
    assert _redact_detail(row, {"proj_a"}) == PII_REDACTED


# ---------------------------------------------------------------------------
# _build_likelihood_clause
# ---------------------------------------------------------------------------


def _compile_clause(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))


def test_build_likelihood_clause_neither_returns_none():
    from testgen.mcp.tools.hygiene_issues import _build_likelihood_clause

    assert _build_likelihood_clause(None, None) is None


def test_build_likelihood_clause_likelihood_only_excludes_pii():
    from testgen.mcp.tools.hygiene_issues import _build_likelihood_clause

    sql = _compile_clause(_build_likelihood_clause([IssueLikelihood.DEFINITE], None))
    assert "profile_anomaly_types.issue_likelihood IN" in sql
    assert "Potential PII" not in sql


def test_build_likelihood_clause_pii_only_uses_priority_hybrid():
    from testgen.mcp.tools.hygiene_issues import _build_likelihood_clause

    sql = _compile_clause(_build_likelihood_clause(None, ["High"]))
    assert "profile_anomaly_types.issue_likelihood =" in sql
    # priority hybrid expands to a CASE expression in SQL:
    assert "CASE" in sql


def test_build_likelihood_clause_both_returns_or_combination():
    from testgen.mcp.tools.hygiene_issues import _build_likelihood_clause

    sql = _compile_clause(_build_likelihood_clause([IssueLikelihood.DEFINITE], ["High"]))
    assert " OR " in sql
    assert "issue_likelihood IN" in sql
    assert "issue_likelihood =" in sql


# ---------------------------------------------------------------------------
# _resolve_profile_run_je_id
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
def test_resolve_je_id_table_group_branch(mock_latest, mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import _resolve_profile_run_je_id

    tg = _mock_table_group()
    mock_resolve_tg.return_value = tg
    expected_je = uuid4()
    mock_latest.return_value = expected_je

    token = _set_full_perms()
    try:
        result = _resolve_profile_run_je_id(job_execution_id=None, table_group_id=str(uuid4()))
    finally:
        _mcp_project_permissions.reset(token)

    assert result == expected_je
    mock_latest.assert_called_once_with(tg.id)


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
def test_resolve_je_id_table_group_no_completed_runs(mock_latest, mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import _resolve_profile_run_je_id

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = None

    token = _set_full_perms()
    try:
        with pytest.raises(MCPUserError, match="No completed profiling runs"):
            _resolve_profile_run_je_id(job_execution_id=None, table_group_id=str(uuid4()))
    finally:
        _mcp_project_permissions.reset(token)


@patch("testgen.mcp.tools.hygiene_issues.TableGroup")
@patch.object(ProfilingRun, "get_by_id_or_job")
def test_resolve_je_id_je_branch_unknown_run(mock_get, mock_tg_cls, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import _resolve_profile_run_je_id

    mock_get.return_value = None

    token = _set_full_perms()
    try:
        with pytest.raises(MCPResourceNotAccessible):
            _resolve_profile_run_je_id(job_execution_id=str(uuid4()), table_group_id=None)
    finally:
        _mcp_project_permissions.reset(token)


@patch("testgen.mcp.tools.hygiene_issues.TableGroup")
@patch.object(ProfilingRun, "get_by_id_or_job")
def test_resolve_je_id_je_branch_inaccessible_tg(mock_get, mock_tg_cls, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import _resolve_profile_run_je_id

    mock_get.return_value = _mock_run()
    mock_tg_cls.get.return_value = _mock_table_group(project_code="forbidden")

    token = _set_full_perms()  # only has access to "demo", not "forbidden"
    try:
        with pytest.raises(MCPResourceNotAccessible):
            _resolve_profile_run_je_id(job_execution_id=str(uuid4()), table_group_id=None)
    finally:
        _mcp_project_permissions.reset(token)


# ---------------------------------------------------------------------------
# list_hygiene_issues
# ---------------------------------------------------------------------------


def test_list_hygiene_issues_both_args_rejected(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    with pytest.raises(MCPUserError, match="Pass either"):
        list_hygiene_issues(job_execution_id=str(uuid4()), table_group_id=str(uuid4()))


def test_list_hygiene_issues_neither_arg_rejected(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    with pytest.raises(MCPUserError, match="Provide either"):
        list_hygiene_issues()


def test_list_hygiene_issues_invalid_je_uuid(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        list_hygiene_issues(job_execution_id="not-a-uuid")


@patch("testgen.mcp.tools.hygiene_issues.TableGroup")
@patch.object(ProfilingRun, "get_by_id_or_job")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_resolves_via_je_id(mock_list, mock_get, mock_tg_cls, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    run = _mock_run()
    mock_get.return_value = run
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_list.return_value = ([], 0)

    list_hygiene_issues(job_execution_id=str(uuid4()))

    assert mock_list.call_args.args[0] == run.job_execution_id


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_resolves_via_table_group(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    expected_je = uuid4()
    mock_latest.return_value = expected_je
    mock_list.return_value = ([], 0)

    list_hygiene_issues(table_group_id=str(uuid4()))

    assert mock_list.call_args.args[0] == expected_je


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_happy_path_renders_fields(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    issue_id = uuid4()
    mock_list.return_value = ([_list_row(id=issue_id, detail="Dummy Values: 5")], 1)

    result = list_hygiene_issues(table_group_id=str(uuid4()))

    assert "[Definite]" in result
    assert "Non-Standard Blank Values" in result
    assert "`frame_size` in `orders`" in result
    assert str(issue_id) in result
    assert "Impact Dimension" in result
    assert "Quality Dimension" in result
    assert "Disposition" in result
    assert "Confirmed" in result
    assert "Dummy Values: 5" in result


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_table_level_heading(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    mock_list.return_value = ([_list_row(column_name=None)], 1)

    result = list_hygiene_issues(table_group_id=str(uuid4()))
    assert "on `orders`" in result
    assert "` in `" not in result


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_priority_unknown_fallback(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    mock_list.return_value = ([_list_row(priority=None)], 1)

    assert "[Unknown]" in list_hygiene_issues(table_group_id=str(uuid4()))


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_empty(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    mock_list.return_value = ([], 0)

    result = list_hygiene_issues(table_group_id=str(uuid4()))
    assert "_No hygiene issues match the supplied filters._" in result


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_pagination_footer(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    mock_list.return_value = ([_list_row(), _list_row()], 100)

    result = list_hygiene_issues(table_group_id=str(uuid4()), limit=2, page=1)
    assert "Showing 1–2 of 100" in result  # noqa: RUF001 — page-info formatter uses EN DASH
    assert "page=2" in result


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_disposition_default_coalesces_to_confirmed(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    mock_list.return_value = ([], 0)

    list_hygiene_issues(table_group_id=str(uuid4()))

    sql = _compiled_clauses(mock_list.call_args)
    assert "coalesce(profile_anomaly_results.disposition" in sql


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
def test_list_hygiene_issues_invalid_disposition(mock_latest, mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()

    with pytest.raises(MCPUserError, match="Invalid disposition"):
        list_hygiene_issues(table_group_id=str(uuid4()), disposition="bogus")


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
def test_list_hygiene_issues_invalid_quality_dimension(mock_latest, mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()

    with pytest.raises(MCPUserError, match="Invalid quality_dimension"):
        list_hygiene_issues(table_group_id=str(uuid4()), quality_dimension="X")


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
def test_list_hygiene_issues_invalid_impact_dimension(mock_latest, mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()

    with pytest.raises(MCPUserError, match="Invalid impact_dimension"):
        list_hygiene_issues(table_group_id=str(uuid4()), impact_dimension="X")


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
def test_list_hygiene_issues_invalid_likelihood(mock_latest, mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()

    with pytest.raises(MCPUserError, match="Invalid issue_likelihood"):
        list_hygiene_issues(table_group_id=str(uuid4()), issue_likelihood=["Bogus"])


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
def test_list_hygiene_issues_invalid_pii_risk(mock_latest, mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()

    with pytest.raises(MCPUserError, match="Invalid pii_risk"):
        list_hygiene_issues(table_group_id=str(uuid4()), pii_risk=["Low"])


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_passes_project_codes_clause(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    mock_list.return_value = ([], 0)

    list_hygiene_issues(table_group_id=str(uuid4()))

    sql = _compiled_clauses(mock_list.call_args)
    assert "profile_anomaly_results.project_code IN" in sql


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
def test_list_hygiene_issues_invalid_page(mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()

    with pytest.raises(MCPUserError, match="Invalid page"):
        list_hygiene_issues(table_group_id=str(uuid4()), page=0)


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
def test_list_hygiene_issues_limit_above_max(mock_resolve_tg, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()

    with pytest.raises(MCPUserError, match="between 1 and 200"):
        list_hygiene_issues(table_group_id=str(uuid4()), limit=201)


@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_pii_redacted_when_no_view_pii(
    mock_list, mock_latest, mock_resolve_tg, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    row = _list_row(detail_redactable=True, pii_flag="B/NAME/Individual", detail="ssn=123")
    mock_list.return_value = ([row], 1)

    # Default mcp_user has role_a; TEST_PERM_MATRIX has no "view_pii" entry → redaction applies.
    result = list_hygiene_issues(table_group_id=str(uuid4()))
    assert PII_REDACTED in result
    assert "ssn=123" not in result


@patch("testgen.mcp.permissions._compute_project_permissions")
@patch("testgen.mcp.tools.hygiene_issues.resolve_table_group")
@patch.object(ProfilingRun, "get_latest_complete_je_id_for_table_group")
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_pii_visible_when_view_pii_granted(
    mock_list, mock_latest, mock_resolve_tg, mock_compute, db_session_mock,
):
    from testgen.mcp.tools.hygiene_issues import list_hygiene_issues

    perms = MagicMock(spec=ProjectPermissions)
    perms.allowed_codes = ["demo"]
    perms.codes_allowed_to.return_value = ["demo"]
    perms.has_access.side_effect = lambda code: code == "demo"
    mock_compute.return_value = perms

    mock_resolve_tg.return_value = _mock_table_group()
    mock_latest.return_value = uuid4()
    row = _list_row(detail_redactable=True, pii_flag="B/NAME/Individual", detail="ssn=123")
    mock_list.return_value = ([row], 1)

    result = list_hygiene_issues(table_group_id=str(uuid4()))
    assert "ssn=123" in result
    assert PII_REDACTED not in result


# ---------------------------------------------------------------------------
# get_hygiene_issue
# ---------------------------------------------------------------------------


def test_get_hygiene_issue_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_hygiene_issue(issue_id="bogus")


@patch.object(HygieneIssue, "get_with_context")
def test_get_hygiene_issue_not_found_collapses_to_not_accessible(mock_get, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    mock_get.return_value = None

    with pytest.raises(MCPResourceNotAccessible):
        get_hygiene_issue(issue_id=str(uuid4()))


@patch.object(HygieneIssue, "get_with_context")
def test_get_hygiene_issue_passes_project_codes_clause(mock_get, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    mock_get.return_value = _detail_row()

    get_hygiene_issue(issue_id=str(uuid4()))

    sql = _compiled_clauses(mock_get.call_args)
    assert "profile_anomaly_results.project_code IN" in sql


@patch.object(HygieneIssue, "get_with_context")
def test_get_hygiene_issue_renders_full_detail(mock_get, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    mock_get.return_value = _detail_row()

    result = get_hygiene_issue(issue_id=str(uuid4()))

    assert "[Definite]" in result
    assert "Issue ID" in result
    assert "Schema" in result
    assert "Table" in result
    assert "Column" in result
    assert "Impact Dimension" in result
    assert "Quality Dimension" in result
    assert "Disposition" in result
    assert "## Suggested Action" in result
    assert "Suggested action body." in result
    assert "## Issue Type Description" in result
    assert "Description body." in result
    assert "## Column Profile" in result
    assert "## Profiling Run" in result


@patch.object(HygieneIssue, "get_with_context")
def test_get_hygiene_issue_table_level_omits_column(mock_get, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    mock_get.return_value = _detail_row(column_name=None)
    result = get_hygiene_issue(issue_id=str(uuid4()))

    assert "on `orders`" in result
    assert "` in `" not in result


@patch.object(HygieneIssue, "get_with_context")
def test_get_hygiene_issue_omits_column_profile_when_no_data(mock_get, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    mock_get.return_value = _detail_row(
        column_general_type=None, column_db_data_type=None,
        column_record_ct=None, column_null_value_ct=None, column_distinct_value_ct=None,
    )
    result = get_hygiene_issue(issue_id=str(uuid4()))
    assert "## Column Profile" not in result


@patch.object(HygieneIssue, "get_with_context")
def test_get_hygiene_issue_renders_null_rate(mock_get, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    mock_get.return_value = _detail_row(column_record_ct=1000, column_null_value_ct=50)
    result = get_hygiene_issue(issue_id=str(uuid4()))
    assert "Null Rate" in result
    assert "5.00%" in result


@patch.object(HygieneIssue, "get_with_context")
def test_get_hygiene_issue_skips_null_rate_when_record_ct_zero(mock_get, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import get_hygiene_issue

    mock_get.return_value = _detail_row(column_record_ct=0, column_null_value_ct=0)
    result = get_hygiene_issue(issue_id=str(uuid4()))
    assert "Null Rate" not in result


# ---------------------------------------------------------------------------
# update_hygiene_issue
# ---------------------------------------------------------------------------


@pytest.fixture
def disposition_perms():
    """Grant 'disposition' permission on demo (the conftest's matrix omits it)."""
    perms = MagicMock(spec=ProjectPermissions)
    perms.memberships = {"demo": "role_a"}
    perms.permission = "disposition"
    perms.username = "test_user"
    perms.allowed_codes = ["demo"]
    perms.codes_allowed_to.return_value = ["demo"]
    perms.has_access.side_effect = lambda code: code in ["demo"]

    with patch("testgen.mcp.permissions._compute_project_permissions", return_value=perms):
        yield perms


def test_update_hygiene_issue_invalid_uuid(db_session_mock, disposition_perms):
    from testgen.mcp.tools.hygiene_issues import update_hygiene_issue

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        update_hygiene_issue(issue_id="bogus", disposition="Confirmed")


def test_update_hygiene_issue_invalid_disposition(db_session_mock, disposition_perms):
    from testgen.mcp.tools.hygiene_issues import update_hygiene_issue

    with pytest.raises(MCPUserError, match="Invalid disposition"):
        update_hygiene_issue(issue_id=str(uuid4()), disposition="Bogus")


@patch.object(HygieneIssue, "update_disposition")
def test_update_hygiene_issue_muted_maps_to_inactive(mock_update, db_session_mock, disposition_perms):
    from testgen.mcp.tools.hygiene_issues import update_hygiene_issue

    mock_update.return_value = True
    update_hygiene_issue(issue_id=str(uuid4()), disposition="Muted")

    args = mock_update.call_args.args
    assert args[1] == Disposition.INACTIVE


@patch.object(HygieneIssue, "update_disposition")
def test_update_hygiene_issue_returns_success_markdown(mock_update, db_session_mock, disposition_perms):
    from testgen.mcp.tools.hygiene_issues import update_hygiene_issue

    mock_update.return_value = True
    issue_id = str(uuid4())
    result = update_hygiene_issue(issue_id=issue_id, disposition="Dismissed")

    assert "Updated hygiene issue" in result
    assert issue_id in result
    assert "Dismissed" in result


@patch.object(HygieneIssue, "update_disposition")
def test_update_hygiene_issue_not_updated_collapses_to_not_accessible(
    mock_update, db_session_mock, disposition_perms,
):
    from testgen.mcp.tools.hygiene_issues import update_hygiene_issue

    mock_update.return_value = False
    with pytest.raises(MCPResourceNotAccessible):
        update_hygiene_issue(issue_id=str(uuid4()), disposition="Confirmed")


@patch.object(HygieneIssue, "update_disposition")
def test_update_hygiene_issue_passes_project_scope_clause(
    mock_update, db_session_mock, disposition_perms,
):
    from testgen.mcp.tools.hygiene_issues import update_hygiene_issue

    mock_update.return_value = True
    update_hygiene_issue(issue_id=str(uuid4()), disposition="Confirmed")

    # Trailing args after (issue_uuid, db_disposition) are the *clauses
    clauses = mock_update.call_args.args[2:]
    sql = "\n".join(str(c.compile(dialect=postgresql.dialect())) for c in clauses)
    assert "profile_anomaly_results.project_code IN" in sql


def test_update_hygiene_issue_uses_disposition_permission():
    """Pin the permission name. Silent downgrade to 'view' would be a write-side leak."""
    import testgen.mcp.tools.hygiene_issues as mod

    closure = {c.cell_contents for c in mod.update_hygiene_issue.__wrapped__.__closure__}
    assert "disposition" in closure


# ---------------------------------------------------------------------------
# search_hygiene_issues
# ---------------------------------------------------------------------------


@patch.object(HygieneIssue, "search")
def test_search_no_args_uses_allowed_codes(mock_search, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    mock_search.return_value = ([], 0)
    search_hygiene_issues()

    sql = _compiled_clauses(mock_search.call_args)
    assert "profile_anomaly_results.project_code IN" in sql


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_search_inaccessible_project_rejected(mock_compute, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    perms = MagicMock(spec=ProjectPermissions)
    perms.memberships = {"demo": "role_a"}
    perms.permission = "view"
    perms.username = "test_user"
    perms.allowed_codes = ["demo"]
    perms.has_access.side_effect = lambda c: c == "demo"
    perms.verify_access.side_effect = lambda _code, not_found: (_ for _ in ()).throw(not_found)
    mock_compute.return_value = perms

    with pytest.raises(MCPResourceNotAccessible):
        search_hygiene_issues(project_code="forbidden")


def test_search_invalid_tg_uuid(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        search_hygiene_issues(table_group_id="bogus")


@patch.object(HygieneIssue, "search")
def test_search_table_group_filter_in_clause(mock_search, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    mock_search.return_value = ([], 0)
    search_hygiene_issues(table_group_id=str(uuid4()))

    sql = _compiled_clauses(mock_search.call_args)
    assert "profile_anomaly_results.table_groups_id =" in sql


@patch.object(HygieneIssue, "search")
def test_search_since_translates_to_started_at_clause(mock_search, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    mock_search.return_value = ([], 0)
    search_hygiene_issues(since="7 days")

    sql = _compiled_clauses(mock_search.call_args)
    assert "job_executions.started_at >=" in sql
    assert "profiling_runs.profiling_starttime" not in sql


def test_search_invalid_since_rejected(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    with pytest.raises(MCPUserError):
        search_hygiene_issues(since="not a date")


@patch.object(HygieneIssue, "search")
def test_search_happy_path_renders_search_row_fields(mock_search, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    je_id = uuid4()
    mock_search.return_value = ([_search_row(table_groups_name="dim-tables", job_execution_id=je_id)], 1)

    result = search_hygiene_issues()

    assert "Hygiene Issue Search" in result
    assert "Table Group" in result
    assert "dim-tables" in result
    assert "Profiling Run" in result
    assert str(je_id) in result
    assert "Run Date" in result


@patch.object(HygieneIssue, "search")
def test_search_empty_returns_no_match_message(mock_search, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    mock_search.return_value = ([], 0)
    result = search_hygiene_issues()
    assert "_No hygiene issues match the supplied filters._" in result


def test_search_invalid_page(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    with pytest.raises(MCPUserError, match="Invalid page"):
        search_hygiene_issues(page=0)


def test_search_invalid_limit(db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    with pytest.raises(MCPUserError, match="between 1 and 200"):
        search_hygiene_issues(limit=201)


@patch("testgen.mcp.tools.hygiene_issues.resolve_issue_type")
@patch.object(HygieneIssue, "search")
def test_search_issue_type_filter_resolved(mock_search, mock_resolve, db_session_mock):
    from testgen.mcp.tools.hygiene_issues import search_hygiene_issues

    mock_resolve.return_value = "1015"
    mock_search.return_value = ([], 0)
    search_hygiene_issues(issue_type="Personally Identifiable Information")

    sql = _compiled_clauses(mock_search.call_args)
    assert "profile_anomaly_results.anomaly_id =" in sql
