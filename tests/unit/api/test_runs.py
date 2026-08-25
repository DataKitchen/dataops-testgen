"""Tests for testgen.api.runs — test run and profiling run retrieval."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.enums import (
    Disposition,
    GeneralType,
    HygieneDisposition,
    ImpactDimension,
    IssueLikelihood,
    PiiFlag,
    PiiRisk,
    ResultStatus,
)
from testgen.api.runs import (
    get_profiling_run,
    get_test_run,
    list_profiling_run_columns,
    list_profiling_run_hygiene_issues,
    list_profiling_run_potential_pii,
    list_profiling_runs,
    list_test_run_results,
    router,
)
from testgen.common.enums import JobStatus
from testgen.common.models.hygiene_issue import (
    HygieneIssue,
    HygieneIssueCounts,
    HygieneIssueListRow,
    IssueCounts,
    PotentialPiiCounts,
)
from testgen.common.models.profile_result import ColumnProfileRow, ColumnSort, ProfileResult
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunHistoryRow
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_result import ResultStatusCounts, TestResult, TestResultStatus, TestRunResultRow
from testgen.common.pii_masking import PII_REDACTED

pytestmark = pytest.mark.unit

MODULE = "testgen.api.runs"

TEST_SUITE_ID = uuid4()
TABLE_GROUP_ID = uuid4()


def _mock_result_row(**overrides):
    defaults = {
        "test_definition_id": uuid4(),
        "test_type": "Unique",
        "test_type_name": "Unique Values",
        "schema_name": "demo",
        "table_name": "orders",
        "column_names": "amount",
        "status": TestResultStatus.Failed,
        "result_measure": "3",
        "threshold_value": "0",
        "message": "Duplicate values: 3",
        "test_time": datetime.now(UTC),
        "disposition": None,
    }
    defaults.update(overrides)
    return TestRunResultRow(**defaults)


def _result_clauses_sql(mock_list) -> str:
    """Compile the WHERE clauses passed to list_for_run (args after test_run_id) to SQL."""
    clauses = mock_list.call_args.args[1:]
    return " ".join(
        str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})) for c in clauses
    )


def _no_filters(**overrides):
    kwargs = {
        "status": None,
        "table_name": None,
        "column_name": None,
        "test_type": None,
        "disposition": None,
        "page": 1,
        "limit": 20,
    }
    kwargs.update(overrides)
    return kwargs


def _mock_job(**overrides):
    defaults = {
        "id": uuid4(),
        "status": "completed",
        "project_code": "test_project",
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    job = MagicMock()
    for key, value in defaults.items():
        setattr(job, key, value)
    return job


def _mock_test_run(**overrides):
    defaults = {
        "id": uuid4(),
        "test_suite_id": TEST_SUITE_ID,
        "dq_score_test_run": 0.95,
    }
    defaults.update(overrides)
    run = MagicMock()
    for key, value in defaults.items():
        setattr(run, key, value)
    return run


def _mock_profiling_run(**overrides):
    defaults = {
        "id": uuid4(),
        "table_groups_id": TABLE_GROUP_ID,
        "dq_score_profiling": 0.88,
        "table_ct": 10,
        "column_ct": 50,
        "record_ct": 1000,
    }
    defaults.update(overrides)
    run = MagicMock()
    for key, value in defaults.items():
        setattr(run, key, value)
    return run


# --- get_test_run ---


@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.TestRun")
def test_get_test_run_completed(mock_tr_cls, mock_result_cls, mock_session):
    job = _mock_job()
    mock_tr_cls.get.return_value = _mock_test_run()
    mock_result_cls.count_by_status.return_value = ResultStatusCounts(
        passed=90, failed=5, warning=3, error=2, log=0, dismissed=12,
    )
    mock_session.return_value.scalar.return_value = TABLE_GROUP_ID

    result = get_test_run(job)

    assert result.id == job.id
    assert result.status == "completed"
    assert result.test_suite_id == TEST_SUITE_ID
    assert result.table_group_id == TABLE_GROUP_ID
    assert result.result is not None
    assert result.result.score == 0.95
    assert result.result.result_counts.passed == 90
    assert result.result.result_counts.failed == 5
    assert result.result.result_counts.dismissed == 12


@patch(f"{MODULE}.TestRun")
def test_get_test_run_pending_no_run(mock_tr_cls):
    job = _mock_job(status="pending", started_at=None, completed_at=None)
    mock_tr_cls.get.return_value = None

    result = get_test_run(job)

    assert result.id == job.id
    assert result.status == "pending"
    assert result.test_suite_id is None
    assert result.table_group_id is None
    assert result.result is None


# --- get_profiling_run ---


@patch(f"{MODULE}.HygieneIssue")
@patch(f"{MODULE}.ProfilingRun")
def test_get_profiling_run_completed(mock_pr_cls, mock_issue_cls):
    job = _mock_job()
    mock_pr_cls.get.return_value = _mock_profiling_run()
    mock_issue_cls.count_for_run.return_value = IssueCounts(
        hygiene_issues=HygieneIssueCounts(definite=5, likely=3, possible=8),
        potential_pii=PotentialPiiCounts(high=4, moderate=6),
        dismissed=2,
    )

    result = get_profiling_run(job)

    assert result.id == job.id
    assert result.status == "completed"
    assert result.table_group_id == TABLE_GROUP_ID
    assert result.result is not None
    assert result.result.score == 0.88
    assert result.result.table_ct == 10
    assert result.result.issue_counts.hygiene_issues.definite == 5
    assert result.result.issue_counts.hygiene_issues.likely == 3
    assert result.result.issue_counts.hygiene_issues.possible == 8
    assert result.result.issue_counts.potential_pii.high == 4
    assert result.result.issue_counts.potential_pii.moderate == 6
    assert result.result.issue_counts.dismissed == 2


@patch(f"{MODULE}.ProfilingRun")
def test_get_profiling_run_pending_no_run(mock_pr_cls):
    job = _mock_job(status="pending", started_at=None, completed_at=None)
    mock_pr_cls.get.return_value = None

    result = get_profiling_run(job)

    assert result.id == job.id
    assert result.status == "pending"
    assert result.table_group_id is None
    assert result.result is None


# --- list_test_run_results: envelope + field/enum mapping ---


@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_list_results_envelope_and_mapping(mock_list):
    job = _mock_job()
    row = _mock_result_row(test_type="Unique", status=TestResultStatus.Failed, message="dup", disposition=None)
    mock_list.return_value = ([row], 7)

    result = list_test_run_results(job, **_no_filters(page=2, limit=5))

    assert result.total == 7
    assert result.page == 2
    assert result.limit == 5
    assert len(result.items) == 1
    item = result.items[0]
    assert item.test_type == "Unique"  # raw code, not a display name
    assert item.result_status == ResultStatus.failed  # title-case DB value -> lowercase API enum
    assert item.result_message == "dup"  # ORM attr `message` -> field `result_message`
    assert item.disposition == Disposition.no_decision  # NULL -> no_decision (not confirmed)
    # test_run_id (job.id) is the scope; page/limit are forwarded as kwargs.
    assert mock_list.call_args.args[0] == job.id
    assert mock_list.call_args.kwargs == {"page": 2, "limit": 5}


@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_list_results_empty_envelope(mock_list):
    result = list_test_run_results(_mock_job(), **_no_filters())
    assert result.items == []
    assert result.total == 0
    assert result.page == 1


@pytest.mark.parametrize(
    "db_status,expected",
    [
        (TestResultStatus.Passed, ResultStatus.passed),
        (TestResultStatus.Failed, ResultStatus.failed),
        (TestResultStatus.Warning, ResultStatus.warning),
        (TestResultStatus.Error, ResultStatus.error),
        (TestResultStatus.Log, ResultStatus.log),
        (None, None),
    ],
)
@patch.object(TestResult, "list_for_run")
def test_list_results_status_render(mock_list, db_status, expected):
    mock_list.return_value = ([_mock_result_row(status=db_status)], 1)
    item = list_test_run_results(_mock_job(), **_no_filters()).items[0]
    assert item.result_status == expected


@pytest.mark.parametrize(
    "db_disposition,expected",
    [
        (None, Disposition.no_decision),
        ("", Disposition.no_decision),
        ("Confirmed", Disposition.confirmed),
        ("Dismissed", Disposition.dismissed),
        ("Inactive", Disposition.muted),
        ("Bogus", Disposition.no_decision),
    ],
)
@patch.object(TestResult, "list_for_run")
def test_list_results_disposition_render(mock_list, db_disposition, expected):
    mock_list.return_value = ([_mock_result_row(disposition=db_disposition)], 1)
    item = list_test_run_results(_mock_job(), **_no_filters()).items[0]
    assert item.disposition == expected



@patch(f"{MODULE}.get_current_session")
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_list_results_rejects_unknown_test_type(mock_list, mock_session):
    mock_session.return_value.scalar.return_value = None

    with pytest.raises(HTTPException) as err:
        list_test_run_results(_mock_job(), **_no_filters(test_type="Not A Test Type"))

    assert err.value.status_code == 400
    assert err.value.detail["errors"][0]["code"] == "unknown_test_type"
    mock_list.assert_not_called()


@patch(f"{MODULE}.get_current_session")
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_list_results_accepts_known_test_type(mock_list, mock_session):
    mock_session.return_value.scalar.return_value = "Dupe_Rows"

    list_test_run_results(_mock_job(), **_no_filters(test_type="Dupe_Rows"))

    assert "test_results.test_type = 'Dupe_Rows'" in _result_clauses_sql(mock_list)


@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_rejects_unknown_issue_type(mock_list, _mock_perm, mock_session):
    mock_session.return_value.scalar.return_value = None

    with pytest.raises(HTTPException) as err:
        list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters(issue_type="Non-Standard Blank Values"))

    assert err.value.status_code == 400
    assert err.value.detail["errors"][0]["code"] == "unknown_issue_type"
    mock_list.assert_not_called()

# --- list_test_run_results: filter clause building ---


@patch(f"{MODULE}._validate_test_type")
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_list_results_builds_filter_clauses(mock_list, _mock_validate):
    list_test_run_results(
        _mock_job(),
        **_no_filters(status=ResultStatus.failed, table_name="orders", column_name="amount", test_type="Unique"),
    )
    sql = _result_clauses_sql(mock_list)
    assert "'Failed'" in sql  # status mapped to DB value
    assert "'orders'" in sql
    assert "'amount'" in sql  # column_name -> column_names column
    assert "'Unique'" in sql


@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_disposition_omitted_returns_active(mock_list):
    list_test_run_results(_mock_job(), **_no_filters(disposition=None))
    sql = _result_clauses_sql(mock_list)
    # Active = confirmed + no_decision (NULL); dismissed/muted excluded.
    assert "IS NULL" in sql
    assert "'Confirmed'" in sql
    assert "'Dismissed'" not in sql
    assert "'Inactive'" not in sql


@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_disposition_confirmed_excludes_nulls(mock_list):
    list_test_run_results(_mock_job(), **_no_filters(disposition=Disposition.confirmed))
    sql = _result_clauses_sql(mock_list)
    assert "'Confirmed'" in sql
    assert "IS NULL" not in sql  # explicit confirmed no longer sweeps in undecided rows


@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_disposition_no_decision_is_null(mock_list):
    list_test_run_results(_mock_job(), **_no_filters(disposition=Disposition.no_decision))
    sql = _result_clauses_sql(mock_list)
    assert "IS NULL" in sql
    assert "'Confirmed'" not in sql


@pytest.mark.parametrize(
    "disposition,db_value",
    [(Disposition.dismissed, "'Dismissed'"), (Disposition.muted, "'Inactive'")],
)
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_disposition_dismissed_muted_map_to_db(mock_list, disposition, db_value):
    list_test_run_results(_mock_job(), **_no_filters(disposition=disposition))
    assert db_value in _result_clauses_sql(mock_list)


# --- list_test_run_results: HTTP-level query validation ---


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return TestClient(app)


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_http_rejects_unknown_status(_mock_list, mock_sess, _mock_perm):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/test-runs/{uuid4()}/results?status=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "status"]


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_http_rejects_unknown_disposition(_mock_list, mock_sess, _mock_perm):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/test-runs/{uuid4()}/results?disposition=foo")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "disposition"]


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_http_accepts_no_decision(mock_list, mock_sess, _mock_perm):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/test-runs/{uuid4()}/results?disposition=no_decision")
    assert resp.status_code == 200
    mock_list.assert_called_once()


@pytest.mark.parametrize("query", ["page=0", "limit=0", "limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_http_rejects_out_of_range_pagination(_mock_list, mock_sess, _mock_perm, query):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/test-runs/{uuid4()}/results?{query}")
    assert resp.status_code == 422


# --- list_profiling_runs ---


def _mock_history_row(**overrides):
    defaults = {
        "job_execution_id": uuid4(),
        "table_group_id": TABLE_GROUP_ID,
        "status": JobStatus.COMPLETED,
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "error_message": None,
        "profiling_score": 0.88,
        "table_ct": 10,
        "column_ct": 50,
        "record_ct": 1000,
        "data_point_ct": 500,
    }
    defaults.update(overrides)
    return ProfilingRunHistoryRow(**defaults)


def _mock_table_group(**overrides):
    defaults = {"id": TABLE_GROUP_ID, "project_code": "test_project"}
    defaults.update(overrides)
    tg = MagicMock()
    for key, value in defaults.items():
        setattr(tg, key, value)
    return tg


def _zero_issue_counts() -> IssueCounts:
    return IssueCounts(
        hygiene_issues=HygieneIssueCounts(),
        potential_pii=PotentialPiiCounts(),
        dismissed=0,
    )


@patch.object(HygieneIssue, "count_for_runs")
@patch.object(ProfilingRun, "list_for_table_group")
def test_list_profiling_runs_envelope_and_counts_merge(mock_list, mock_counts):
    row = _mock_history_row()
    mock_list.return_value = ([row], 3)
    mock_counts.return_value = {
        row.job_execution_id: IssueCounts(
            hygiene_issues=HygieneIssueCounts(definite=1, likely=2, possible=3),
            potential_pii=PotentialPiiCounts(high=4, moderate=5),
            dismissed=6,
        ),
    }

    result = list_profiling_runs(_mock_table_group(), status=None, page=2, limit=5)

    assert result.total == 3
    assert result.page == 2
    assert result.limit == 5
    assert len(result.items) == 1
    item = result.items[0]
    assert item.job_execution_id == row.job_execution_id
    assert item.table_group_id == TABLE_GROUP_ID
    assert item.profiling_score == 0.88
    assert item.data_point_ct == 500
    assert item.issue_counts.hygiene_issues.definite == 1
    assert item.issue_counts.potential_pii.high == 4
    assert item.issue_counts.dismissed == 6
    # table_group.id is the scope; no filter clauses when status is None.
    assert mock_list.call_args.args == (TABLE_GROUP_ID,)
    assert mock_list.call_args.kwargs == {"page": 2, "limit": 5}
    mock_counts.assert_called_once_with([row.job_execution_id])


@patch.object(HygieneIssue, "count_for_runs", return_value={})
@patch.object(ProfilingRun, "list_for_table_group", return_value=([], 0))
def test_list_profiling_runs_empty_envelope(_mock_list, mock_counts):
    result = list_profiling_runs(_mock_table_group(), status=None, page=1, limit=20)
    assert result.items == []
    assert result.total == 0
    mock_counts.assert_called_once_with([])


@patch.object(HygieneIssue, "count_for_runs", return_value={})
@patch.object(ProfilingRun, "list_for_table_group", return_value=([], 0))
def test_list_profiling_runs_status_filter_propagates(mock_list, _mock_counts):
    list_profiling_runs(_mock_table_group(), status=JobStatus.COMPLETED, page=1, limit=20)
    clauses = mock_list.call_args.args[1:]
    assert len(clauses) == 1
    sql = str(clauses[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "'completed'" in sql
    assert "job_executions.status" in sql


@patch.object(HygieneIssue, "count_for_runs")
@patch.object(ProfilingRun, "list_for_table_group")
def test_list_profiling_runs_missing_run_id_zeroes(mock_list, mock_counts):
    """If count_for_runs omits a run id (shouldn't happen — helper backfills — but be strict)."""
    row = _mock_history_row()
    mock_list.return_value = ([row], 1)
    mock_counts.return_value = {row.job_execution_id: _zero_issue_counts()}

    item = list_profiling_runs(_mock_table_group(), status=None, page=1, limit=20).items[0]
    assert item.issue_counts.hygiene_issues.definite == 0
    assert item.issue_counts.dismissed == 0


# HTTP-level query validation


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch.object(TableGroup, "get")
@patch.object(HygieneIssue, "count_for_runs", return_value={})
@patch.object(ProfilingRun, "list_for_table_group", return_value=([], 0))
def test_http_profiling_runs_rejects_unknown_status(_ml, _mc, mock_get, _mp):
    mock_get.return_value = _mock_table_group()
    resp = _client().get(f"/api/v1/table-groups/{uuid4()}/profiling-runs?status=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "status"]


@pytest.mark.parametrize("query", ["page=0", "limit=0", "limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch.object(TableGroup, "get")
@patch.object(HygieneIssue, "count_for_runs", return_value={})
@patch.object(ProfilingRun, "list_for_table_group", return_value=([], 0))
def test_http_profiling_runs_rejects_bad_pagination(_ml, _mc, mock_get, _mp, query):
    mock_get.return_value = _mock_table_group()
    resp = _client().get(f"/api/v1/table-groups/{uuid4()}/profiling-runs?{query}")
    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch.object(TableGroup, "get", return_value=None)
@patch.object(HygieneIssue, "count_for_runs", return_value={})
@patch.object(ProfilingRun, "list_for_table_group", return_value=([], 0))
def test_http_profiling_runs_returns_404_for_missing_table_group(_ml, _mc, _mock_get, _mp):
    resp = _client().get(f"/api/v1/table-groups/{uuid4()}/profiling-runs")
    assert resp.status_code == 404


# --- HygieneIssue.count_for_runs ---


def test_count_for_runs_empty_input_returns_empty():
    assert HygieneIssue.count_for_runs([]) == {}


@patch("testgen.common.models.hygiene_issue.get_current_session")
def test_count_for_runs_backfills_missing_run_ids(mock_session):
    """Runs with zero findings never appear in the GROUP BY output — the helper backfills zeros."""
    mock_session.return_value.execute.return_value = iter([])  # DB returns nothing
    run_ids = [uuid4(), uuid4()]

    result = HygieneIssue.count_for_runs(run_ids)

    assert set(result.keys()) == set(run_ids)
    for counts in result.values():
        assert counts.hygiene_issues.definite == 0
        assert counts.potential_pii.high == 0
        assert counts.dismissed == 0


# --- Hygiene + PII endpoints: shared helpers ---


def _mock_hygiene_row(**overrides) -> HygieneIssueListRow:
    defaults = {
        "id": uuid4(),
        "project_code": "test_project",
        "issue_type_code": "suggested_column_pk",
        "issue_type_name": "Suggested Primary Key",
        "schema_name": "demo",
        "table_name": "orders",
        "column_name": "order_id",
        "impact_dimension": "Reliability",
        "dq_dimension": "Uniqueness",
        "disposition": "Confirmed",
        "priority": "Definite",
        "detail": "Column looks like a primary key",
        "detail_redactable": False,
        "pii_flag": None,
    }
    defaults.update(overrides)
    return HygieneIssueListRow(**defaults)


def _mock_pii_row(**overrides) -> HygieneIssueListRow:
    defaults = {
        "issue_type_code": "potential_pii",
        "issue_type_name": "Potential PII",
        "column_name": "email",
        "impact_dimension": None,
        "dq_dimension": "Validity",
        "priority": "High",
        "detail": "Risk: HIGH, Type: EMAIL — column looks like PII",
        "detail_redactable": True,
        "pii_flag": "A",
    }
    return _mock_hygiene_row(**{**defaults, **overrides})


def _hygiene_clauses_sql(mock_list) -> str:
    clauses = mock_list.call_args.args[1:]
    return " ".join(
        str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})) for c in clauses
    )


def _no_hygiene_filters(**overrides):
    kwargs = {
        "user": MagicMock(id=uuid4()),
        "issue_type": None,
        "likelihood": None,
        "disposition": None,
        "page": 1,
        "limit": 20,
    }
    kwargs.update(overrides)
    return kwargs


def _no_pii_filters(**overrides):
    kwargs = {
        "user": MagicMock(id=uuid4()),
        "pii_risk": None,
        "disposition": None,
        "page": 1,
        "limit": 20,
    }
    kwargs.update(overrides)
    return kwargs


# --- list_profiling_run_hygiene_issues: envelope + field/enum mapping ---


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_list_hygiene_issues_envelope_and_mapping(mock_list, _mock_perm):
    row = _mock_hygiene_row()
    mock_list.return_value = ([row], 7)

    job = _mock_job()
    result = list_profiling_run_hygiene_issues(job, **_no_hygiene_filters(page=2, limit=5))

    assert result.total == 7
    assert result.page == 2
    assert result.limit == 5
    assert len(result.items) == 1
    item = result.items[0]
    assert item.id == row.id
    assert item.issue_type == "suggested_column_pk"  # code, not display name
    assert item.schema_name == "demo"
    assert item.likelihood == IssueLikelihood.definite
    assert item.impact_dimension == ImpactDimension.reliability
    assert item.disposition == HygieneDisposition.confirmed
    assert item.detail == "Column looks like a primary key"
    # job.id is the scope; page/limit forwarded as kwargs.
    assert mock_list.call_args.args[0] == job.id
    assert mock_list.call_args.kwargs == {"page": 2, "limit": 5}


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_list_hygiene_issues_empty_envelope(_mock_list, _mock_perm):
    result = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters())
    assert result.items == []
    assert result.total == 0
    assert result.page == 1


# --- list_profiling_run_potential_pii: envelope + field/enum mapping ---


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_list_potential_pii_envelope_and_mapping(mock_list, _mock_perm):
    row = _mock_pii_row()
    mock_list.return_value = ([row], 3)

    result = list_profiling_run_potential_pii(_mock_job(), **_no_pii_filters(page=1, limit=10))

    assert result.total == 3
    assert result.limit == 10
    assert len(result.items) == 1
    item = result.items[0]
    assert item.id == row.id
    assert item.issue_type == "potential_pii"
    assert item.pii_risk == PiiRisk.high
    assert item.disposition == HygieneDisposition.confirmed
    assert not hasattr(item, "likelihood")  # PII item has no likelihood field
    assert not hasattr(item, "impact_dimension")  # PII item has no impact_dimension field


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_list_potential_pii_empty_envelope(_mock_list, _mock_perm):
    result = list_profiling_run_potential_pii(_mock_job(), **_no_pii_filters())
    assert result.items == []
    assert result.total == 0


# --- Hygiene endpoint: filter clause building ---


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_partition_clause_always_excludes_pii(mock_list, _mock_perm):
    list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters())
    sql = _hygiene_clauses_sql(mock_list)
    assert "profile_anomaly_types.issue_likelihood != 'Potential PII'" in sql


@patch(f"{MODULE}._validate_issue_type")
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_issue_type_filter_uses_code(mock_list, _mock_perm, _mock_validate):
    list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters(issue_type="suggested_column_pk"))
    sql = _hygiene_clauses_sql(mock_list)
    assert "profile_anomaly_results.anomaly_id = 'suggested_column_pk'" in sql


@pytest.mark.parametrize(
    "api_value,db_value",
    [
        (IssueLikelihood.definite, "'Definite'"),
        (IssueLikelihood.likely, "'Likely'"),
        (IssueLikelihood.possible, "'Possible'"),
    ],
)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_likelihood_filter_maps_to_db(mock_list, _mock_perm, api_value, db_value):
    list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters(likelihood=api_value))
    sql = _hygiene_clauses_sql(mock_list)
    assert db_value in sql


# --- PII endpoint: filter clause building ---


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_pii_partition_clause_always_includes_only_pii(mock_list, _mock_perm):
    list_profiling_run_potential_pii(_mock_job(), **_no_pii_filters())
    sql = _hygiene_clauses_sql(mock_list)
    assert "profile_anomaly_types.issue_likelihood = 'Potential PII'" in sql


@pytest.mark.parametrize(
    "api_value,db_value",
    [(PiiRisk.high, "'High'"), (PiiRisk.moderate, "'Moderate'")],
)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_pii_risk_filter_maps_to_db(mock_list, _mock_perm, api_value, db_value):
    list_profiling_run_potential_pii(_mock_job(), **_no_pii_filters(pii_risk=api_value))
    sql = _hygiene_clauses_sql(mock_list)
    assert db_value in sql


# --- Disposition semantics (shared by hygiene + PII) ---


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_disposition_omitted_returns_active(mock_list, _mock_perm):
    """Omitted disposition includes NULLs (COALESCED to Confirmed) and stored Confirmed rows."""
    list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters(disposition=None))
    sql = _hygiene_clauses_sql(mock_list)
    assert "IS NULL" in sql
    assert "'Confirmed'" in sql
    assert "'Dismissed'" not in sql
    assert "'Inactive'" not in sql


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_disposition_confirmed_matches_omitted(mock_list, _mock_perm):
    """Explicit confirmed still sweeps in NULLs — hygiene has no no_decision state."""
    list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters(disposition=HygieneDisposition.confirmed))
    sql = _hygiene_clauses_sql(mock_list)
    assert "IS NULL" in sql
    assert "'Confirmed'" in sql


@pytest.mark.parametrize(
    "api_value,db_value",
    [(HygieneDisposition.dismissed, "'Dismissed'"), (HygieneDisposition.muted, "'Inactive'")],
)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_disposition_dismissed_muted_map_to_db(mock_list, _mock_perm, api_value, db_value):
    list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters(disposition=api_value))
    sql = _hygiene_clauses_sql(mock_list)
    assert db_value in sql
    assert "IS NULL" not in sql  # dismissed/muted rows are never NULL in storage


@pytest.mark.parametrize(
    "db_value,expected",
    [
        (None, HygieneDisposition.confirmed),
        ("", HygieneDisposition.confirmed),
        ("Confirmed", HygieneDisposition.confirmed),
        ("Dismissed", HygieneDisposition.dismissed),
        ("Inactive", HygieneDisposition.muted),
        ("Bogus", HygieneDisposition.confirmed),
    ],
)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_hygiene_disposition_render(mock_list, _mock_perm, db_value, expected):
    mock_list.return_value = ([_mock_hygiene_row(disposition=db_value)], 1)
    item = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters()).items[0]
    assert item.disposition == expected


# --- Priority render mapping ---


@pytest.mark.parametrize(
    "db_priority,expected",
    [
        ("Definite", IssueLikelihood.definite),
        ("Likely", IssueLikelihood.likely),
        ("Possible", IssueLikelihood.possible),
        (None, None),
        ("Garbage", None),
    ],
)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_hygiene_likelihood_render(mock_list, _mock_perm, db_priority, expected):
    mock_list.return_value = ([_mock_hygiene_row(priority=db_priority)], 1)
    item = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters()).items[0]
    assert item.likelihood == expected


@pytest.mark.parametrize(
    "db_priority,expected",
    [("High", PiiRisk.high), ("Moderate", PiiRisk.moderate), (None, None), ("Weak", None)],
)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_pii_risk_render(mock_list, _mock_perm, db_priority, expected):
    mock_list.return_value = ([_mock_pii_row(priority=db_priority)], 1)
    item = list_profiling_run_potential_pii(_mock_job(), **_no_pii_filters()).items[0]
    assert item.pii_risk == expected


# --- Impact dimension render (hygiene endpoint only) ---


@pytest.mark.parametrize(
    "db_value,expected",
    [
        ("Reliability", ImpactDimension.reliability),
        ("Conformance", ImpactDimension.conformance),
        ("Regularity", ImpactDimension.regularity),
        ("Usability", ImpactDimension.usability),
        (None, None),
        ("Garbage", None),
    ],
)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_hygiene_impact_dimension_render(mock_list, _mock_perm, db_value, expected):
    mock_list.return_value = ([_mock_hygiene_row(impact_dimension=db_value)], 1)
    item = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters()).items[0]
    assert item.impact_dimension == expected


# --- PII redaction ---


@patch(f"{MODULE}.has_project_permission", return_value=False)
@patch.object(HygieneIssue, "list_for_run")
def test_hygiene_detail_redacted_when_no_view_pii(mock_list, _mock_perm):
    row = _mock_hygiene_row(detail_redactable=True, pii_flag="A/PHONE/...", detail="+15555551234")
    mock_list.return_value = ([row], 1)
    item = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters()).items[0]
    assert item.detail == PII_REDACTED


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_hygiene_detail_visible_with_view_pii(mock_list, _mock_perm):
    row = _mock_hygiene_row(detail_redactable=True, pii_flag="A/PHONE/...", detail="+15555551234")
    mock_list.return_value = ([row], 1)
    item = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters()).items[0]
    assert item.detail == "+15555551234"


@patch(f"{MODULE}.has_project_permission", return_value=False)
@patch.object(HygieneIssue, "list_for_run")
def test_hygiene_detail_not_redacted_without_pii_flag(mock_list, _mock_perm):
    """No pii_flag from ProfileResult means no PII in this column — detail stays visible."""
    row = _mock_hygiene_row(detail_redactable=True, pii_flag=None, detail="something")
    mock_list.return_value = ([row], 1)
    item = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters()).items[0]
    assert item.detail == "something"


@patch(f"{MODULE}.has_project_permission", return_value=False)
@patch.object(HygieneIssue, "list_for_run")
def test_hygiene_detail_not_redacted_when_not_redactable(mock_list, _mock_perm):
    """detail_redactable=False means the issue type doesn't leak PII in detail — never redact."""
    row = _mock_hygiene_row(detail_redactable=False, pii_flag="A/PHONE/...", detail="something")
    mock_list.return_value = ([row], 1)
    item = list_profiling_run_hygiene_issues(_mock_job(), **_no_hygiene_filters()).items[0]
    assert item.detail == "something"


@patch(f"{MODULE}.has_project_permission", return_value=False)
@patch.object(HygieneIssue, "list_for_run")
def test_pii_detail_redacted_when_no_view_pii(mock_list, _mock_perm):
    row = _mock_pii_row(detail="Risk: HIGH, Type: EMAIL — user@example.com")
    mock_list.return_value = ([row], 1)
    item = list_profiling_run_potential_pii(_mock_job(), **_no_pii_filters()).items[0]
    assert item.detail == PII_REDACTED


@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch.object(HygieneIssue, "list_for_run")
def test_pii_detail_visible_with_view_pii(mock_list, _mock_perm):
    row = _mock_pii_row(detail="Risk: HIGH, Type: EMAIL — user@example.com")
    mock_list.return_value = ([row], 1)
    item = list_profiling_run_potential_pii(_mock_job(), **_no_pii_filters()).items[0]
    assert item.detail == "Risk: HIGH, Type: EMAIL — user@example.com"


@patch(f"{MODULE}.has_project_permission")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_hygiene_view_pii_check_scoped_to_job_project(_mock_list, mock_perm):
    job = _mock_job(project_code="my-project")
    list_profiling_run_hygiene_issues(job, **_no_hygiene_filters())
    # view_pii permission is queried against the job's project_code, not the user's default.
    (called_user, called_project, called_perm) = mock_perm.call_args.args
    assert called_project == "my-project"
    assert called_perm == "view_pii"


# --- HTTP-level query validation ---


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_hygiene_rejects_unknown_likelihood(_ml, mock_sess, _mp1, _mp2):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/hygiene-issues?likelihood=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "likelihood"]


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_hygiene_rejects_unknown_disposition(_ml, mock_sess, _mp1, _mp2):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/hygiene-issues?disposition=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "disposition"]


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_hygiene_rejects_no_decision_disposition(_ml, mock_sess, _mp1, _mp2):
    """Hygiene's disposition enum has no ``no_decision`` — passing it must 422."""
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/hygiene-issues?disposition=no_decision")
    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_pii_rejects_unknown_pii_risk(_ml, mock_sess, _mp1, _mp2):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/potential-pii?pii_risk=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "pii_risk"]


@pytest.mark.parametrize("query", ["page=0", "limit=0", "limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_hygiene_rejects_bad_pagination(_ml, mock_sess, _mp1, _mp2, query):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/hygiene-issues?{query}")
    assert resp.status_code == 422


@pytest.mark.parametrize("query", ["page=0", "limit=0", "limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_pii_rejects_bad_pagination(_ml, mock_sess, _mp1, _mp2, query):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/potential-pii?{query}")
    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_hygiene_404_for_missing_job(_ml, mock_sess, _mp1, _mp2):
    mock_sess.return_value.scalars.return_value.first.return_value = None
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/hygiene-issues")
    assert resp.status_code == 404


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(HygieneIssue, "list_for_run", return_value=([], 0))
def test_http_pii_404_for_missing_job(_ml, mock_sess, _mp1, _mp2):
    mock_sess.return_value.scalars.return_value.first.return_value = None
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/potential-pii")
    assert resp.status_code == 404


# --- list_profiling_run_columns ---


def _mock_column_row(**overrides):
    defaults = {
        "schema_name": "demo",
        "table_name": "orders",
        "column_name": "amount",
        "general_type": "N",
        "functional_data_type": "Amount",
        "db_data_type": "NUMERIC(18,2)",
        "datatype_suggestion": "DECIMAL",
        "pii_flag": None,
        "critical_data_element": False,
        "record_ct": 1000,
        "null_value_ct": 3,
        "distinct_value_ct": 950,
        "filled_value_ct": 997,
        "profiling_score": 0.92,
        "testing_score": 0.87,
        "definite": 0,
        "likely": 0,
        "possible": 0,
        "high": 0,
        "moderate": 0,
        "dismissed": 0,
    }
    defaults.update(overrides)
    return ColumnProfileRow(**defaults)


def _column_defaults(**overrides):
    kwargs = {
        "table_name": None,
        "sort": ColumnSort.hygiene_severity,
        "page": 1,
        "limit": 20,
    }
    kwargs.update(overrides)
    return kwargs


@patch.object(ProfileResult, "list_columns_for_run")
def test_list_columns_envelope_and_item_shape(mock_list):
    row = _mock_column_row(
        pii_flag="A/NAME/full_name",
        critical_data_element=True,
        definite=2,
        likely=1,
        possible=0,
        high=3,
        moderate=4,
        dismissed=5,
    )
    mock_list.return_value = ([row], 7)

    job = _mock_job()
    result = list_profiling_run_columns(job, **_column_defaults(page=2, limit=5))

    assert result.total == 7
    assert result.page == 2
    assert result.limit == 5
    assert len(result.items) == 1
    item = result.items[0]
    assert item.schema_name == "demo"
    assert item.table_name == "orders"
    assert item.column_name == "amount"
    assert item.general_type == GeneralType.numeric
    assert item.functional_data_type == "Amount"
    assert item.db_data_type == "NUMERIC(18,2)"
    assert item.datatype_suggestion == "DECIMAL"
    assert item.pii_flag == PiiFlag.high
    assert item.critical_data_element is True
    assert item.record_ct == 1000
    assert item.null_value_ct == 3
    assert item.distinct_value_ct == 950
    assert item.filled_value_ct == 997
    assert item.profiling_score == 0.92
    assert item.testing_score == 0.87
    assert item.issue_counts.hygiene_issues.definite == 2
    assert item.issue_counts.hygiene_issues.likely == 1
    assert item.issue_counts.hygiene_issues.possible == 0
    assert item.issue_counts.potential_pii.high == 3
    assert item.issue_counts.potential_pii.moderate == 4
    assert item.issue_counts.dismissed == 5
    # The resolved job's id — not a stray one — reaches the model method.
    assert mock_list.call_args.args[0] == job.id
    assert mock_list.call_args.kwargs == {"sort": ColumnSort.hygiene_severity, "page": 2, "limit": 5}


@patch.object(ProfileResult, "list_columns_for_run", return_value=([], 0))
def test_list_columns_empty_envelope(mock_list):
    job = _mock_job()
    result = list_profiling_run_columns(job, **_column_defaults())
    assert result.items == []
    assert result.total == 0
    assert result.page == 1
    assert result.limit == 20
    assert mock_list.call_args.args[0] == job.id


@pytest.mark.parametrize(
    "db_code,expected",
    [
        ("A", GeneralType.alpha),
        ("N", GeneralType.numeric),
        ("D", GeneralType.datetime),
        ("B", GeneralType.boolean),
        ("T", GeneralType.time),
        ("X", GeneralType.other),
        (None, None),
        ("", None),
        ("bogus", None),
    ],
)
@patch.object(ProfileResult, "list_columns_for_run")
def test_list_columns_general_type_mapping(mock_list, db_code, expected):
    mock_list.return_value = ([_mock_column_row(general_type=db_code)], 1)
    item = list_profiling_run_columns(_mock_job(), **_column_defaults()).items[0]
    assert item.general_type == expected


@pytest.mark.parametrize(
    "db_value,expected",
    [
        ("A/NAME/full_name", PiiFlag.high),
        ("B/DEMO/age", PiiFlag.moderate),
        ("C/CONTACT/city", PiiFlag.low),
        ("MANUAL", PiiFlag.manual),
        ("MANUAL/USER", PiiFlag.manual),
        (None, None),
        ("", None),
        ("Z/UNKNOWN/whatever", None),
    ],
)
@patch.object(ProfileResult, "list_columns_for_run")
def test_list_columns_pii_flag_mapping(mock_list, db_value, expected):
    mock_list.return_value = ([_mock_column_row(pii_flag=db_value)], 1)
    item = list_profiling_run_columns(_mock_job(), **_column_defaults()).items[0]
    assert item.pii_flag == expected


@patch.object(ProfileResult, "list_columns_for_run")
def test_list_columns_default_sort_is_hygiene_severity(mock_list):
    mock_list.return_value = ([], 0)
    job = _mock_job()
    list_profiling_run_columns(job, **_column_defaults())
    assert mock_list.call_args.args[0] == job.id
    assert mock_list.call_args.kwargs["sort"] == ColumnSort.hygiene_severity


@patch.object(ProfileResult, "list_columns_for_run")
def test_list_columns_sort_table_propagates(mock_list):
    mock_list.return_value = ([], 0)
    job = _mock_job()
    list_profiling_run_columns(job, **_column_defaults(sort=ColumnSort.table))
    assert mock_list.call_args.args[0] == job.id
    assert mock_list.call_args.kwargs["sort"] == ColumnSort.table


@patch.object(ProfileResult, "list_columns_for_run", return_value=([], 0))
def test_list_columns_no_table_filter_when_absent(mock_list):
    job = _mock_job()
    list_profiling_run_columns(job, **_column_defaults(table_name=None))
    # Only the run id positional; no clause.
    assert mock_list.call_args.args == (job.id,)


@patch.object(ProfileResult, "list_columns_for_run", return_value=([], 0))
def test_list_columns_table_filter_case_sensitive_equality(mock_list):
    job = _mock_job()
    list_profiling_run_columns(job, **_column_defaults(table_name="Orders"))
    assert mock_list.call_args.args[0] == job.id
    clauses = mock_list.call_args.args[1:]
    assert len(clauses) == 1
    sql = str(clauses[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "profile_results.table_name = 'Orders'" in sql
    # Must not lower-case the comparand.
    assert "lower" not in sql.lower()


# HTTP-level query validation


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(ProfileResult, "list_columns_for_run", return_value=([], 0))
def test_http_columns_rejects_unknown_sort(_ml, mock_sess, _mock_perm):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/columns?sort=BOGUS")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["query", "sort"]


@pytest.mark.parametrize("query", ["page=0", "limit=0", "limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(ProfileResult, "list_columns_for_run", return_value=([], 0))
def test_http_columns_rejects_bad_pagination(_ml, mock_sess, _mock_perm, query):
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/columns?{query}")
    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.get_current_session")
@patch.object(ProfileResult, "list_columns_for_run", return_value=([], 0))
def test_http_columns_404_when_job_not_found(_ml, mock_sess, _mock_perm):
    mock_sess.return_value.scalars.return_value.first.return_value = None
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/columns")
    assert resp.status_code == 404


@patch("testgen.api.deps.has_project_permission", return_value=False)
@patch("testgen.api.deps.get_current_session")
@patch.object(ProfileResult, "list_columns_for_run", return_value=([], 0))
def test_http_columns_404_when_no_view_permission(_ml, mock_sess, _mock_perm):
    """No-view collapses into the same 404 as a missing job — no leak."""
    mock_sess.return_value.scalars.return_value.first.return_value = _mock_job()
    resp = _client().get(f"/api/v1/profiling-runs/{uuid4()}/columns")
    assert resp.status_code == 404
