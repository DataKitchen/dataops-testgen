"""Tests for testgen.api.jobs — job submission, status polling, and cancellation."""

from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.jobs import (
    cancel_job,
    get_job_status,
    list_jobs,
    router,
    submit_profiling,
    submit_test_generation,
    submit_test_run,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.api.jobs"


def _mock_job(**overrides):
    defaults = {
        "id": uuid4(),
        "job_key": "run-profile",
        "status": "pending",
        "source": "api",
        "project_code": "test_project",
        "created_at": datetime.now(UTC),
        "claimed_at": None,
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }
    defaults.update(overrides)
    job = MagicMock()
    for key, value in defaults.items():
        setattr(job, key, value)
    return job


def _mock_table_group(**overrides):
    defaults = {"id": uuid4(), "project_code": "test_project"}
    defaults.update(overrides)
    tg = MagicMock()
    for key, value in defaults.items():
        setattr(tg, key, value)
    return tg


def _mock_test_suite(**overrides):
    defaults = {"id": uuid4(), "project_code": "test_project", "is_monitor": False}
    defaults.update(overrides)
    ts = MagicMock()
    for key, value in defaults.items():
        setattr(ts, key, value)
    return ts


# --- submit_profiling ---


@patch(f"{MODULE}.JobExecution")
def test_submit_profiling_success(mock_je_cls):
    table_group = _mock_table_group()
    job = _mock_job(job_key="run-profile")
    mock_je_cls.submit.return_value = job

    result = submit_profiling(table_group)

    mock_je_cls.submit.assert_called_once_with(
        job_key="run-profile",
        kwargs={"table_group_id": str(table_group.id)},
        source="api",
        project_code=table_group.project_code,
    )
    assert result.id == job.id
    assert result.created_at == job.created_at


# --- submit_test_run ---


@patch(f"{MODULE}.JobExecution")
def test_submit_test_run_success(mock_je_cls):
    test_suite = _mock_test_suite()
    job = _mock_job(job_key="run-tests")
    mock_je_cls.submit.return_value = job

    result = submit_test_run(test_suite)

    mock_je_cls.submit.assert_called_once_with(
        job_key="run-tests",
        kwargs={"test_suite_id": str(test_suite.id)},
        source="api",
        project_code=test_suite.project_code,
    )
    assert result.id == job.id


# --- submit_test_generation ---


@patch(f"{MODULE}.JobExecution")
def test_submit_test_generation_success(mock_je_cls):
    test_suite = _mock_test_suite()
    job = _mock_job(job_key="run-test-generation")
    mock_je_cls.submit.return_value = job

    result = submit_test_generation(test_suite)

    mock_je_cls.submit.assert_called_once_with(
        job_key="run-test-generation",
        kwargs={"test_suite_id": str(test_suite.id), "generation_set": "Standard"},
        source="api",
        project_code=test_suite.project_code,
    )
    assert result.id == job.id


# --- get_job_status ---


def test_get_job_status_success():
    job = _mock_job(status="running", started_at=datetime.now(UTC))

    result = get_job_status(job)

    assert result.id == job.id
    assert result.status == "running"


# --- cancel_job ---


def test_cancel_job_success():
    job = _mock_job(status="cancel_requested")
    job.request_cancel.return_value = True

    result = cancel_job(job)

    job.request_cancel.assert_called_once()
    assert result.id == job.id


def test_cancel_job_invalid_transition():
    job = _mock_job(status="completed")
    job.request_cancel.return_value = False

    with pytest.raises(HTTPException) as exc_info:
        cancel_job(job)
    assert exc_info.value.status_code == 409


# --- list_jobs ---


@patch(f"{MODULE}.JobExecution")
def test_list_jobs_returns_paginated_results(mock_je_cls):
    jobs = [_mock_job(job_key="run-profile"), _mock_job(job_key="run-tests")]
    mock_je_cls.list_for_project.return_value = (jobs, 2)

    result = list_jobs(project_code="DEFAULT", job_key=None, status=None, page=1, limit=20)

    mock_je_cls.list_for_project.assert_called_once_with(
        "DEFAULT", ANY, job_key=None, status=None, page=1, limit=20,
    )
    assert result.total == 2
    assert result.page == 1
    assert result.limit == 20
    assert len(result.items) == 2


@patch(f"{MODULE}.JobExecution")
def test_list_jobs_passes_filters(mock_je_cls):
    mock_je_cls.list_for_project.return_value = ([], 0)

    result = list_jobs(project_code="DEFAULT", job_key="run-profile", status="completed", page=2, limit=10)

    mock_je_cls.list_for_project.assert_called_once_with(
        "DEFAULT", ANY, job_key="run-profile", status="completed", page=2, limit=10,
    )
    assert result.total == 0
    assert result.items == []


@patch(f"{MODULE}.JobExecution")
def test_list_jobs_empty_project(mock_je_cls):
    mock_je_cls.list_for_project.return_value = ([], 0)

    result = list_jobs(project_code="EMPTY", job_key=None, status=None, page=1, limit=20)

    assert result.total == 0
    assert result.items == []


# --- list_jobs HTTP-level query validation ---


def _client_with_overrides() -> TestClient:
    """Build a TestClient that bypasses auth and db_session so query validation runs unimpeded."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return app


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.JobExecution")
def test_list_jobs_rejects_unknown_status(mock_je_cls, _mock_perm):
    mock_je_cls.list_for_project.return_value = ([], 0)
    client = TestClient(_client_with_overrides())

    resp = client.get("/api/v1/projects/DEFAULT/jobs?status=BOGUS")

    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"][0]["loc"] == ["query", "status"]
    assert body["detail"][0]["type"] == "enum"


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.JobExecution")
def test_list_jobs_accepts_valid_status(mock_je_cls, _mock_perm):
    mock_je_cls.list_for_project.return_value = ([], 0)
    client = TestClient(_client_with_overrides())

    resp = client.get("/api/v1/projects/DEFAULT/jobs?status=completed")

    assert resp.status_code == 200
    # Verify the status string was forwarded to the model layer.
    assert mock_je_cls.list_for_project.call_args.kwargs["status"] == "completed"
