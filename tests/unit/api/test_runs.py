"""Tests for testgen.api.runs — test run and profiling run retrieval."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.enums import Disposition, ResultStatus
from testgen.api.runs import get_profiling_run, get_test_run, list_test_run_results, router
from testgen.common.models.hygiene_issue import HygieneIssueCounts, IssueCounts, PotentialPiiCounts
from testgen.common.models.test_result import ResultStatusCounts, TestResult, TestResultStatus, TestRunResultRow

pytestmark = pytest.mark.unit

MODULE = "testgen.api.runs"

TEST_SUITE_ID = uuid4()
TABLE_GROUP_ID = uuid4()


def _mock_result_row(**overrides):
    defaults = {
        "test_definition_id": uuid4(),
        "test_type": "Unique",
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
        ("Confirmed", Disposition.confirmed),
        ("Dismissed", Disposition.dismissed),
        ("Inactive", Disposition.muted),
    ],
)
@patch.object(TestResult, "list_for_run")
def test_list_results_disposition_render(mock_list, db_disposition, expected):
    mock_list.return_value = ([_mock_result_row(disposition=db_disposition)], 1)
    item = list_test_run_results(_mock_job(), **_no_filters()).items[0]
    assert item.disposition == expected


# --- list_test_run_results: filter clause building ---


@patch.object(TestResult, "list_for_run", return_value=([], 0))
def test_list_results_builds_filter_clauses(mock_list):
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
