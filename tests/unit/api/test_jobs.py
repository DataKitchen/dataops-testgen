"""Tests for testgen.api.jobs — job submission, status polling, and cancellation."""

from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

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
from testgen.api.schemas import TestGenerationRequest, TestRunRequest
from testgen.common.enums import JobKey, PublicJobKey, SuiteType
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import SCHEMA_NAME_MAX_LENGTH

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
    defaults = {"id": uuid4(), "project_code": "test_project", "suite_type": SuiteType.REGULAR}
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
        external_url=None,
        caller_metadata=None,
    )
    assert result.id == job.id


@patch(f"{MODULE}.JobExecution")
def test_submit_test_run_passes_a_match_schema_override(mock_je_cls):
    test_suite = _mock_test_suite()
    mock_je_cls.submit.return_value = _mock_job(job_key="run-tests")

    submit_test_run(test_suite, TestRunRequest(match_schema_name="reference_2026_09_10"))

    mock_je_cls.submit.assert_called_once_with(
        job_key="run-tests",
        kwargs={"test_suite_id": str(test_suite.id), "match_schema_name": "reference_2026_09_10"},
        source="api",
        project_code=test_suite.project_code,
        external_url=None,
        caller_metadata=None,
    )


@pytest.mark.parametrize("body", [None, TestRunRequest(), TestRunRequest(match_schema_name=None)])
@patch(f"{MODULE}.JobExecution")
def test_submit_test_run_omits_the_schema_key_when_not_given(mock_je_cls, body):
    """An absent match schema must not reach kwargs, or the handler would stop falling back to
    each definition's stored one."""
    test_suite = _mock_test_suite()
    mock_je_cls.submit.return_value = _mock_job(job_key="run-tests")

    submit_test_run(test_suite, body)

    assert mock_je_cls.submit.call_args.kwargs["kwargs"] == {"test_suite_id": str(test_suite.id)}


@patch(f"{MODULE}.JobExecution")
def test_submit_test_run_passes_caller_metadata(mock_je_cls):
    test_suite = _mock_test_suite()
    mock_je_cls.submit.return_value = _mock_job(job_key="run-tests")
    metadata = {"url": "https://ci.example.com/runs/1", "system": "DataOps Automation"}

    submit_test_run(test_suite, TestRunRequest(metadata=metadata))

    assert mock_je_cls.submit.call_args.kwargs["caller_metadata"] == metadata


@pytest.mark.parametrize("body", [None, TestRunRequest()])
@patch(f"{MODULE}.JobExecution")
def test_submit_test_run_sends_no_metadata_when_none_given(mock_je_cls, body):
    mock_je_cls.submit.return_value = _mock_job(job_key="run-tests")

    submit_test_run(_mock_test_suite(), body)

    assert mock_je_cls.submit.call_args.kwargs["caller_metadata"] is None


@pytest.mark.parametrize(
    "metadata",
    [
        "not-an-object",
        [1, 2, 3],
        {str(i): i for i in range(51)},
        {"big": "x" * 10_300},
    ],
)
def test_test_run_request_rejects_unusable_metadata(metadata):
    """Stored verbatim and rendered back, so it is bounded at the edge rather than on read."""
    with pytest.raises(ValidationError):
        TestRunRequest(metadata=metadata)


def test_test_run_request_accepts_nested_metadata():
    """The shape belongs to the caller — nesting is theirs to choose."""
    metadata = {"url": "https://x/1", "ctx": {"kitchen": "prod", "attempt": 2}}

    assert TestRunRequest(metadata=metadata).metadata == metadata


@pytest.mark.parametrize(
    "schema_name",
    [
        'x" OR 1=1--',   # closes the double quote the templates wrap it in
        "x` OR 1=1--",   # and the backtick, for the flavors that use it
        "a'; DROP TABLE x; --",   # and the single quote, for the metadata reads
        "a\nb",
        "",
        "a" * (SCHEMA_NAME_MAX_LENGTH + 1),
    ],
)
def test_test_run_request_rejects_a_name_that_would_end_the_quoting(schema_name):
    with pytest.raises(ValidationError):
        TestRunRequest(match_schema_name=schema_name)


@pytest.mark.parametrize("schema_name", ["onboard_2026_09_10", "public", "_staging", "A$1"])
def test_test_run_request_accepts_bare_identifiers(schema_name):
    assert TestRunRequest(match_schema_name=schema_name).match_schema_name == schema_name


# --- submit_test_generation ---


@patch(f"{MODULE}.resolve_generation_sets", return_value=["Standard"])
@patch(f"{MODULE}.JobExecution")
def test_submit_test_generation_defaults_to_stored_sets(mock_je_cls, mock_resolve):
    test_suite = _mock_test_suite()
    job = _mock_job(job_key="run-test-generation")
    mock_je_cls.submit.return_value = job

    result = submit_test_generation(test_suite)

    mock_resolve.assert_called_once_with(test_suite, None)
    mock_je_cls.submit.assert_called_once_with(
        job_key="run-test-generation",
        kwargs={"test_suite_id": str(test_suite.id), "generation_sets": ["Standard"]},
        source="api",
        project_code=test_suite.project_code,
    )
    assert result.id == job.id


@patch(f"{MODULE}.resolve_generation_sets", return_value=["Standard", "Plugin_Set"])
@patch(f"{MODULE}.JobExecution")
def test_submit_test_generation_accepts_a_set_list(mock_je_cls, mock_resolve):
    test_suite = _mock_test_suite()
    mock_je_cls.submit.return_value = _mock_job(job_key="run-test-generation")

    submit_test_generation(test_suite, TestGenerationRequest(generation_sets=["Standard", "Plugin_Set"]))

    mock_resolve.assert_called_once_with(test_suite, ["Standard", "Plugin_Set"])
    assert mock_je_cls.submit.call_args.kwargs["kwargs"]["generation_sets"] == ["Standard", "Plugin_Set"]


@patch(f"{MODULE}.resolve_generation_sets", side_effect=ValueError("Unknown generation sets: Nope."))
@patch(f"{MODULE}.JobExecution")
def test_submit_test_generation_rejects_unknown_set(mock_je_cls, _mock_resolve):
    test_suite = _mock_test_suite()

    with pytest.raises(HTTPException) as excinfo:
        submit_test_generation(test_suite, TestGenerationRequest(generation_sets=["Nope"]))

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["errors"][0]["code"] == "invalid_generation_set"
    assert "Nope" in excinfo.value.detail["errors"][0]["detail"]
    mock_je_cls.submit.assert_not_called()


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
    app.include_router(router, prefix="/api/v1")
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


# --- internal job-kind exclusion ---
# JobResponse.job_key is typed PublicJobKey, which is only safe because every path
# that builds a JobResponse excludes internal job kinds. These pin that invariant.


def test_public_job_key_excludes_internal_kinds():
    public = {member.value for member in PublicJobKey}
    assert public == {"run-profile", "run-tests", "run-test-generation"}
    internal = {
        "run-monitors",
        "refresh-data-catalog",
        "run-score-update",
        "recalculate-project-scores",
        "refresh-run-scores",
        "recalculate-score-card",
        "run-data-cleanup",
    }
    assert public.isdisjoint(internal)
    # Every public value must be a real JobKey.
    assert public <= {member.value for member in JobKey}


@patch.object(JobExecution, "list_for_project", return_value=([], 0))
def test_list_jobs_filters_to_public_job_kinds(_mock_list):
    list_jobs(project_code="DEFAULT", job_key=None, status=None, page=1, limit=20)

    clause = _mock_list.call_args.args[1]
    sql = str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "run-profile" in sql
    assert "run-tests" in sql
    assert "run-test-generation" in sql
    for internal in (
        "run-monitors",
        "refresh-data-catalog",
        "run-score-update",
        "recalculate-project-scores",
        "refresh-run-scores",
        "recalculate-score-card",
        "run-data-cleanup",
    ):
        assert internal not in sql


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.JobExecution")
def test_list_jobs_rejects_internal_job_key(mock_je_cls, _mock_perm):
    mock_je_cls.list_for_project.return_value = ([], 0)
    client = TestClient(_client_with_overrides())

    resp = client.get("/api/v1/projects/DEFAULT/jobs?job_key=run-data-cleanup")

    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"][0]["loc"] == ["query", "job_key"]
    assert body["detail"][0]["type"] == "enum"


@patch(f"{MODULE}.JobExecution")
def test_submit_test_run_passes_the_link_and_metadata_separately(mock_je_cls):
    """The link is its own field, so it reaches its own column rather than riding inside metadata."""
    test_suite = _mock_test_suite()
    mock_je_cls.submit.return_value = _mock_job(job_key="run-tests")

    submit_test_run(
        test_suite,
        TestRunRequest(external_url="https://ci.example.com/runs/8891", metadata={"order_run_id": "8891"}),
    )

    call = mock_je_cls.submit.call_args.kwargs
    assert call["external_url"] == "https://ci.example.com/runs/8891"
    assert call["caller_metadata"] == {"order_run_id": "8891"}
