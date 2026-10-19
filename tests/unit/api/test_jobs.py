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
from testgen.common import contract_service
from testgen.common.contract_service import RunTarget
from testgen.common.enums import JobKey, PublicJobKey, SuiteType
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.suite_version import SuiteVersion, VersionState
from testgen.common.models.table_group import SCHEMA_NAME_MAX_LENGTH
from testgen.common.test_definition_export_import_service import ContractVersion

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



def _submit_contract(regenerate=None, *, profiled=True):
    test_suite = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    with (
        patch(f"{MODULE}.resolve_generation_sets", return_value=["Contract"]),
        patch(f"{MODULE}.TableGroup") as mock_tg_cls,
        patch(f"{MODULE}.resolve_generation_profile_run", return_value=uuid4() if profiled else None),
        patch(f"{MODULE}.JobExecution") as mock_je_cls,
        patch(f"{MODULE}.TestDefinition.resolve_writable", return_value=(DRAFT_ID, {})),
        patch(f"{MODULE}.SuiteVersion.get", return_value=MagicMock(version=5)),
    ):
        mock_tg_cls.get.return_value = MagicMock(table_groups_name="orders_tg")
        mock_je_cls.submit.return_value = _mock_job(job_key="run-test-generation")
        body = TestGenerationRequest(regenerate=regenerate) if regenerate is not None else None
        result = submit_test_generation(test_suite, body)
    return result, mock_je_cls.submit


DRAFT_ID = uuid4()


def test_submit_test_generation_names_the_draft_a_contract_generates_into():
    result, _ = _submit_contract()

    assert result.version == ContractVersion(number=5, state=VersionState.DRAFT)


def test_submit_test_generation_names_no_version_for_a_regular_suite():
    with (
        patch(f"{MODULE}.resolve_generation_sets", return_value=["Standard"]),
        patch(f"{MODULE}.JobExecution") as mock_je_cls,
        patch(f"{MODULE}.TestDefinition.resolve_writable") as resolve_writable,
    ):
        mock_je_cls.submit.return_value = _mock_job(job_key="run-test-generation")
        result = submit_test_generation(_mock_test_suite(), None)

    assert result.version is None
    resolve_writable.assert_not_called()


def test_submit_test_generation_submits_a_contract_regenerating_everything_by_default():
    result, submit = _submit_contract()

    assert submit.call_args.kwargs["kwargs"]["generation_sets"] == ["Contract"]
    assert submit.call_args.kwargs["kwargs"]["regenerate"] == ["tests", "profiling", "governance"]
    assert result.regenerate == ["tests", "profiling", "governance"]
    assert result.note is None


def test_submit_test_generation_passes_a_contracts_chosen_groups_in_order():
    result, submit = _submit_contract(["governance", "tests"])

    assert submit.call_args.kwargs["kwargs"]["regenerate"] == ["tests", "governance"]
    assert result.regenerate == ["tests", "governance"]


def test_submit_test_generation_says_what_an_unprofiled_contract_skips():
    result, submit = _submit_contract(["profiling", "governance"], profiled=False)

    submit.assert_called_once()
    assert result.note == "Table group `orders_tg` has not been profiled, so the values profiling observed are not refreshed."


def test_submit_test_generation_refuses_tests_alone_for_an_unprofiled_contract():
    with pytest.raises(HTTPException) as excinfo:
        _submit_contract(["tests"], profiled=False)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["errors"][0]["code"] == "table_group_not_profiled"


@patch(f"{MODULE}.JobExecution")
def test_submit_test_generation_refuses_groups_for_a_regular_suite(mock_je_cls):
    with pytest.raises(HTTPException) as excinfo:
        submit_test_generation(_mock_test_suite(), TestGenerationRequest(regenerate=["tests"]))

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["errors"][0]["code"] == "regeneration_groups_not_allowed"
    mock_je_cls.submit.assert_not_called()


def test_test_generation_request_refuses_an_empty_list_of_groups():
    with pytest.raises(ValidationError, match="at least 1 item"):
        TestGenerationRequest(regenerate=[])


def test_test_generation_request_refuses_an_unknown_group():
    with pytest.raises(ValidationError, match="'tests', 'profiling' or 'governance'"):
        TestGenerationRequest(regenerate=["docs"])


def test_submit_test_generation_resolves_regular_suites_and_contracts():
    with (
        patch("testgen.api.deps.TestSuite") as mock_ts_cls,
        patch("testgen.api.deps.has_project_permission", return_value=True),
    ):
        mock_ts_cls.get.return_value = None
        resp = TestClient(_client_with_overrides()).post(f"/api/v1/test-suites/{uuid4()}/test-generation")

    assert resp.status_code == 404
    mock_ts_cls.suite_type.in_.assert_called_once_with((SuiteType.REGULAR, SuiteType.CONTRACT))


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


# --- submit_test_run on contracts ---


def _run_contract(body=None, *, target=None, error=None):
    test_suite = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    with (
        patch(f"{MODULE}.contract_service.run_target", return_value=target, side_effect=error) as run_target,
        patch(f"{MODULE}.JobExecution") as mock_je_cls,
    ):
        mock_je_cls.submit.return_value = _mock_job(job_key="run-tests")
        result = submit_test_run(test_suite, body)
    return result, mock_je_cls.submit, run_target


def test_submit_test_run_stamps_a_contract_run_with_its_version():
    version = SuiteVersion(id=uuid4(), version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC))
    result, submit, run_target = _run_contract(target=RunTarget(version, VersionState.ACTIVE))

    assert run_target.call_args.args[1] is None
    assert submit.call_args.kwargs["kwargs"]["version_id"] == str(version.id)
    assert result.version == ContractVersion(number=3, state=VersionState.ACTIVE)
    assert result.counts_as_status is True
    assert result.note is None


@pytest.mark.parametrize(
    ("state", "note"),
    [
        (VersionState.DRAFT, "previews a version that is not frozen"),
        (VersionState.SUPERSEDED, "checks a superseded version"),
    ],
)
def test_submit_test_run_says_when_a_contract_run_will_not_count(state, note):
    version = SuiteVersion(id=uuid4(), version=2)
    result, _, run_target = _run_contract(TestRunRequest(version=2), target=RunTarget(version, state))

    assert run_target.call_args.args[1] == 2
    assert result.counts_as_status is False
    assert note in result.note


def test_submit_test_run_refuses_a_contract_version_with_no_active_tests():
    suite = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    error = contract_service.NoActiveTestsError(suite, SuiteVersion(id=uuid4(), version=4), VersionState.DRAFT)

    with pytest.raises(HTTPException) as excinfo:
        _run_contract(TestRunRequest(version=4), error=error)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["errors"] == [
        {"code": "no_active_tests", "detail": "v4 draft of this contract has no active tests to run."}
    ]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (contract_service.NotAContractError(MagicMock()), "not_a_contract"),
        (contract_service.UnknownVersionError(MagicMock(), 9, 3), "unknown_version"),
    ],
)
def test_submit_test_run_refuses_a_version_the_suite_does_not_hold(error, code):
    with pytest.raises(HTTPException) as excinfo:
        _run_contract(TestRunRequest(version=9), error=error)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["errors"][0]["code"] == code


def test_submit_test_run_names_no_version_for_a_regular_suite():
    with patch(f"{MODULE}.JobExecution") as mock_je_cls:
        mock_je_cls.submit.return_value = _mock_job(job_key="run-tests")
        result = submit_test_run(_mock_test_suite(), None)

    assert (result.version, result.counts_as_status, result.note) == (None, None, None)


@pytest.mark.parametrize("version", [0, -1, "2", 1.5])
def test_test_run_request_rejects_a_version_that_is_not_a_positive_number(version):
    with pytest.raises(ValidationError):
        TestRunRequest(version=version)


@pytest.mark.parametrize(
    ("path", "suite_types"),
    [
        ("test-runs", (SuiteType.REGULAR, SuiteType.CONTRACT)),
        ("test-generation", (SuiteType.REGULAR, SuiteType.CONTRACT)),
    ],
)
def test_suite_submissions_resolve_regular_suites_and_contracts(path, suite_types):
    with (
        patch("testgen.api.deps.TestSuite") as mock_deps_cls,
        patch("testgen.api.deps.has_project_permission", return_value=True),
    ):
        mock_deps_cls.get.return_value = None
        resp = TestClient(_client_with_overrides()).post(f"/api/v1/test-suites/{uuid4()}/{path}")

    assert resp.status_code == 404
    mock_deps_cls.suite_type.in_.assert_called_once_with(suite_types)
