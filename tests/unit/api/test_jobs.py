"""Tests for testgen.api.jobs — job submission and status polling endpoints."""

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
from testgen.api.schemas import SubmitProfilingRequest, SubmitTestGenerationRequest, SubmitTestRunRequest

pytestmark = pytest.mark.unit

MODULE = "testgen.api.jobs"


def _mock_job(**overrides):
    defaults = {
        "id": uuid4(),
        "job_key": "run-profile",
        "status": "pending",
        "source": "api",
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


# --- submit_profiling ---


@patch(f"{MODULE}.JobExecution")
@patch(f"{MODULE}.TableGroup")
def test_submit_profiling_success(mock_tg_cls, mock_je_cls):
    table_group_id = uuid4()
    mock_tg_cls.get.return_value = MagicMock()

    job = _mock_job(job_key="run-profile")
    mock_je_cls.submit.return_value = job

    body = SubmitProfilingRequest(table_group_id=table_group_id)
    result = submit_profiling(body, user=MagicMock())

    mock_tg_cls.get.assert_called_once_with(table_group_id)
    mock_je_cls.submit.assert_called_once_with(
        job_key="run-profile",
        kwargs={"table_group_id": str(table_group_id)},
        source="api",
    )
    assert result.id == job.id
    assert result.created_at == job.created_at


@patch(f"{MODULE}.TableGroup")
def test_submit_profiling_table_group_not_found(mock_tg_cls):
    mock_tg_cls.get.return_value = None

    body = SubmitProfilingRequest(table_group_id=uuid4())
    with pytest.raises(HTTPException) as exc_info:
        submit_profiling(body, user=MagicMock())
    assert exc_info.value.status_code == 404


# --- submit_test_run ---


@patch(f"{MODULE}.JobExecution")
@patch(f"{MODULE}.TestSuite")
def test_submit_test_run_success(mock_ts_cls, mock_je_cls):
    test_suite_id = uuid4()
    mock_suite = MagicMock()
    mock_suite.is_monitor = False
    mock_ts_cls.get.return_value = mock_suite

    job = _mock_job(job_key="run-tests")
    mock_je_cls.submit.return_value = job

    body = SubmitTestRunRequest(test_suite_id=test_suite_id)
    result = submit_test_run(body, user=MagicMock())

    mock_ts_cls.get.assert_called_once_with(test_suite_id)
    mock_je_cls.submit.assert_called_once_with(
        job_key="run-tests",
        kwargs={"test_suite_id": str(test_suite_id)},
        source="api",
    )
    assert result.id == job.id


@patch(f"{MODULE}.TestSuite")
def test_submit_test_run_not_found(mock_ts_cls):
    mock_ts_cls.get.return_value = None

    body = SubmitTestRunRequest(test_suite_id=uuid4())
    with pytest.raises(HTTPException) as exc_info:
        submit_test_run(body, user=MagicMock())
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["errors"][0]["code"] == "test_suite_not_found"


@patch(f"{MODULE}.TestSuite")
def test_submit_test_run_rejects_monitor_suite(mock_ts_cls):
    mock_suite = MagicMock()
    mock_suite.is_monitor = True
    mock_ts_cls.get.return_value = mock_suite

    body = SubmitTestRunRequest(test_suite_id=uuid4())
    with pytest.raises(HTTPException) as exc_info:
        submit_test_run(body, user=MagicMock())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["errors"][0]["code"] == "monitor_suite_not_allowed"


# --- submit_test_generation ---


@patch(f"{MODULE}.JobExecution")
@patch(f"{MODULE}.TestSuite")
def test_submit_test_generation_success(mock_ts_cls, mock_je_cls):
    test_suite_id = uuid4()
    mock_suite = MagicMock()
    mock_suite.is_monitor = False
    mock_ts_cls.get.return_value = mock_suite

    job = _mock_job(job_key="run-test-generation")
    mock_je_cls.submit.return_value = job

    body = SubmitTestGenerationRequest(test_suite_id=test_suite_id)
    result = submit_test_generation(body, user=MagicMock())

    mock_je_cls.submit.assert_called_once_with(
        job_key="run-test-generation",
        kwargs={"test_suite_id": str(test_suite_id), "generation_set": "Standard"},
        source="api",
    )
    assert result.id == job.id


@patch(f"{MODULE}.TestSuite")
def test_submit_test_generation_rejects_monitor_suite(mock_ts_cls):
    mock_suite = MagicMock()
    mock_suite.is_monitor = True
    mock_ts_cls.get.return_value = mock_suite

    body = SubmitTestGenerationRequest(test_suite_id=uuid4())
    with pytest.raises(HTTPException) as exc_info:
        submit_test_generation(body, user=MagicMock())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["errors"][0]["code"] == "monitor_suite_not_allowed"


# --- get_job_status ---


@patch(f"{MODULE}.JobExecution")
def test_get_job_status_success(mock_je_cls):
    job = _mock_job(status="running", started_at=datetime.now(UTC))
    mock_je_cls.get.return_value = job

    result = get_job_status(job.id, user=MagicMock())

    mock_je_cls.get.assert_called_once_with(job.id)
    assert result.id == job.id
    assert result.status == "running"


@patch(f"{MODULE}.JobExecution")
def test_get_job_status_not_found(mock_je_cls):
    mock_je_cls.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_job_status(uuid4(), user=MagicMock())
    assert exc_info.value.status_code == 404


# --- cancel_job ---


@patch(f"{MODULE}.JobExecution")
def test_cancel_job_success(mock_je_cls):
    job = _mock_job(status="cancel_requested")
    job.request_cancel.return_value = True
    mock_je_cls.get.return_value = job

    result = cancel_job(job.id, user=MagicMock())

    job.request_cancel.assert_called_once()
    assert result.id == job.id


@patch(f"{MODULE}.JobExecution")
def test_cancel_job_invalid_transition(mock_je_cls):
    job = _mock_job(status="completed")
    job.request_cancel.return_value = False
    mock_je_cls.get.return_value = job

    with pytest.raises(HTTPException) as exc_info:
        cancel_job(job.id, user=MagicMock())
    assert exc_info.value.status_code == 409
