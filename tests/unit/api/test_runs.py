"""Tests for testgen.api.runs — test run and profiling run retrieval."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from testgen.api.runs import get_profiling_run, get_test_run
from testgen.common.models.hygiene_issue import IssueLikelihoodCounts
from testgen.common.models.test_result import ResultStatusCounts

pytestmark = pytest.mark.unit

MODULE = "testgen.api.runs"


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


@patch(f"{MODULE}.TestResult")
@patch(f"{MODULE}.TestRun")
def test_get_test_run_completed(mock_tr_cls, mock_result_cls):
    job = _mock_job()
    mock_tr_cls.get_by_id_or_job.return_value = _mock_test_run()
    mock_result_cls.count_by_status.return_value = ResultStatusCounts(
        passed=90, failed=5, warning=3, error=2, log=0, dismissed=12,
    )

    result = get_test_run(job)

    assert result.id == job.id
    assert result.status == "completed"
    assert result.started_at == job.started_at
    assert result.result is not None
    assert result.result.score == 0.95
    assert result.result.tests.passed == 90
    assert result.result.tests.failed == 5
    assert result.result.tests.dismissed == 12


@patch(f"{MODULE}.TestRun")
def test_get_test_run_pending_no_run(mock_tr_cls):
    job = _mock_job(status="pending", started_at=None, completed_at=None)
    mock_tr_cls.get_by_id_or_job.return_value = None

    result = get_test_run(job)

    assert result.id == job.id
    assert result.status == "pending"
    assert result.result is None


def test_get_test_run_rejects_monitor_suite():
    job = _mock_job(job_key="run-monitors")

    with pytest.raises(HTTPException) as exc_info:
        get_test_run(job)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {"errors": [{"code": "not_found", "detail": "Not found"}]}


# --- get_profiling_run ---


@patch(f"{MODULE}.HygieneIssue")
@patch(f"{MODULE}.ProfilingRun")
def test_get_profiling_run_completed(mock_pr_cls, mock_issue_cls):
    job = _mock_job()
    mock_pr_cls.get_by_id_or_job.return_value = _mock_profiling_run()
    mock_issue_cls.count_by_likelihood.return_value = IssueLikelihoodCounts(
        definite=5, likely=3, possible=8, dismissed=2,
    )

    result = get_profiling_run(job)

    assert result.id == job.id
    assert result.status == "completed"
    assert result.result is not None
    assert result.result.score == 0.88
    assert result.result.table_ct == 10
    assert result.result.issues.definite == 5
    assert result.result.issues.likely == 3
    assert result.result.issues.dismissed == 2


@patch(f"{MODULE}.ProfilingRun")
def test_get_profiling_run_pending_no_run(mock_pr_cls):
    job = _mock_job(status="pending", started_at=None, completed_at=None)
    mock_pr_cls.get_by_id_or_job.return_value = None

    result = get_profiling_run(job)

    assert result.id == job.id
    assert result.status == "pending"
    assert result.result is None
