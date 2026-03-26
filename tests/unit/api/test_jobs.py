"""Tests for testgen.api.jobs — job submission, status polling, and cancellation."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from testgen.api.jobs import (
    cancel_job,
    get_job_status,
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


def test_submit_test_run_rejects_monitor_suite():
    test_suite = _mock_test_suite(is_monitor=True)

    with pytest.raises(HTTPException) as exc_info:
        submit_test_run(test_suite)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["errors"][0]["code"] == "monitor_suite_not_allowed"


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


def test_submit_test_generation_rejects_monitor_suite():
    test_suite = _mock_test_suite(is_monitor=True)

    with pytest.raises(HTTPException) as exc_info:
        submit_test_generation(test_suite)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["errors"][0]["code"] == "monitor_suite_not_allowed"


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
