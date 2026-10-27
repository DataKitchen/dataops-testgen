"""API v1 — job submission, status polling, and listing."""

from typing import Any

from fastapi import APIRouter, Depends, Query, status

from testgen.api.deps import (
    CONTRACT_VERSION_ERRORS,
    LimitQuery,
    PageQuery,
    api_error,
    contract_version_error,
    db_session,
    resolve_job,
    resolve_project_code,
    resolve_table_group,
    resolve_test_suite,
)
from testgen.api.schemas import (
    JOB_KEY_VALUES,
    ErrorResponse,
    JobListResponse,
    JobResponse,
    JobSubmittedResponse,
    TestGenerationRequest,
    TestGenerationSubmittedResponse,
    TestRunRequest,
    TestRunSubmittedResponse,
)
from testgen.commands.test_generation import (
    TestsNeedProfilingError,
    parse_regeneration_groups,
    resolve_generation_profile_run,
    unprofiled_regeneration_note,
)
from testgen.common import contract_service
from testgen.common.audit.runs import RunOperation
from testgen.common.database.table_group_service import unsupported_schema_override
from testgen.common.enums import (
    TEST_SUITE_TYPES,
    JobKey,
    JobSource,
    JobStatus,
    PublicJobKey,
    RegenerationGroup,
    SuiteType,
)
from testgen.common.generation_set_service import resolve_generation_sets
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.suite_version import VersionState, format_version
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.run_service import launch_run, request_run_transition
from testgen.common.test_definition_export_import_service import ContractVersion

_error_responses = {
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(tags=["Jobs"], dependencies=[Depends(db_session, scope="function")], responses=_error_responses)


@router.post(
    "/table-groups/{table_group_id}/profiling-runs",
    summary="Submit a profiling job",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_profiling(table_group: TableGroup = resolve_table_group("edit")):  # noqa: B008
    """Profiles the table group's tables, as its table filters or file declarations select them."""
    job = launch_run(
        job_key=JobKey.run_profile,
        kwargs={"table_group_id": str(table_group.id)},
        source=JobSource.api,
        project_code=table_group.project_code,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-suites/{test_suite_id}/test-runs",
    summary="Submit a test run job",
    response_model=TestRunSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "A version given for a suite that is not a contract or one the contract does not hold, "
            "a contract version with no active tests, or a schema override the connection type does not take",
        },
    },
)
def submit_test_run(
    test_suite: TestSuite = resolve_test_suite("edit", TEST_SUITE_TYPES),  # noqa: B008
    body: TestRunRequest | None = None,
):
    """Runs against the table group's schema; a contract runs one of its versions.

    `schema_name`, `table_names`, `match_schema_name`, `match_table_names`, and `variables` change
    what this run reads, for this run only; each one left out keeps the stored value. The stored
    test definitions and the data catalog are not changed, and the run deactivates no tests. Each
    test is validated against the table the run reads, and its results report the test's own schema
    and table names.

    A contract runs its active version, or its draft when no version has been frozen, unless
    `version` names another. Only a run of the active version counts as the contract's
    status; a run of the draft or of a superseded version does not.
    """
    if body and (refusal := unsupported_schema_override(
        test_suite.table_groups_id,
        schema_name=body.schema_name,
        match_schema_name=body.match_schema_name,
    )):
        raise api_error(400, "schema_override_not_supported", refusal)

    try:
        target = contract_service.run_target(test_suite, body.version if body else None)
    except CONTRACT_VERSION_ERRORS as error:
        raise contract_version_error(error) from error
    except contract_service.NoActiveTestsError as error:
        raise api_error(
            400,
            "no_active_tests",
            f"{format_version(error.version.version, error.state)} of this contract has no active tests to run.",
        ) from error

    kwargs: dict[str, Any] = {"test_suite_id": str(test_suite.id)}
    if body:
        for field in ("schema_name", "table_names", "match_schema_name", "match_table_names"):
            if value := getattr(body, field):
                kwargs[field] = value
    if target is not None:
        kwargs["version_id"] = str(target.version.id)

    job = launch_run(
        job_key=JobKey.run_tests,
        kwargs=kwargs,
        source=JobSource.api,
        project_code=test_suite.project_code,
        external_url=body.external_url if body else None,
        caller_metadata=body.metadata if body else None,
    )
    if target is None:
        return TestRunSubmittedResponse(id=job.id, created_at=job.created_at)
    return TestRunSubmittedResponse(
        id=job.id,
        created_at=job.created_at,
        version=ContractVersion(number=target.version.version, state=target.state),
        note=target.note,
    )


@router.post(
    "/test-suites/{test_suite_id}/test-generation",
    summary="Submit a test generation job",
    response_model=TestGenerationSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={400: {"model": ErrorResponse, "description": "Invalid generation set or regeneration groups"}},
)
def submit_test_generation(
    test_suite: TestSuite = resolve_test_suite("edit", TEST_SUITE_TYPES),  # noqa: B008
    body: TestGenerationRequest | None = None,
):
    """Generates from the test suite's stored generation sets when none are given,
    falling back to Standard. A contract always generates its own fixed set of test types into
    its draft version and generates the draft's metadata. Before its table group has been
    profiled, the metadata is generated from the data catalog alone and only schema conformance tests are
    created.

    The value hash test types (Match Text, Numeric and Date Hash, their Keyed variants, and Match
    Epoch Sum, in the Table Comparison set) are generated only from a profiling run that computed
    value hashes. That needs `profile_table_comparison` on the table group and a profiling run
    since it was turned on; otherwise they are not generated.

    For a contract, `regenerate` chooses what is refreshed; omit it to refresh everything. Tests
    alone cannot be regenerated before the table group has been profiled.
    """
    regenerate = body.regenerate if body else None
    is_contract = test_suite.suite_type == SuiteType.CONTRACT
    if regenerate is not None and not is_contract:
        raise api_error(400, "regeneration_groups_not_allowed", "Regeneration groups apply to contracts only.")
    try:
        generation_sets = resolve_generation_sets(test_suite, body.generation_sets if body else None)
    except ValueError as error:
        raise api_error(400, "invalid_generation_set", str(error)) from error

    groups: list[RegenerationGroup] | None = None
    note = None
    version = None
    if is_contract:
        table_group = TableGroup.get(test_suite.table_groups_id)
        profiled = resolve_generation_profile_run(table_group) is not None
        try:
            groups = parse_regeneration_groups(
                list(RegenerationGroup) if regenerate is None else regenerate, has_profiling_run=profiled
            )
        except TestsNeedProfilingError as error:
            raise api_error(400, "table_group_not_profiled", str(error)) from error
        if not profiled:
            note = unprofiled_regeneration_note(table_group.table_groups_name, groups)
        version = ContractVersion(number=contract_service.generation_destination(test_suite), state=VersionState.DRAFT)

    job = JobExecution.submit(
        job_key=JobKey.run_test_generation,
        kwargs={
            "test_suite_id": str(test_suite.id),
            "generation_sets": generation_sets,
            **({"regenerate": [str(group) for group in groups]} if groups else {}),
        },
        source=JobSource.api,
        project_code=test_suite.project_code,
    )
    return TestGenerationSubmittedResponse(
        id=job.id, created_at=job.created_at, version=version, regenerate=groups, note=note
    )


@router.get(
    "/jobs/{job_id}",
    summary="Read a job",
    response_model=JobResponse,
)
def get_job_status(job: JobExecution = resolve_job("view")):  # noqa: B008
    """A job's status and timestamps, and its error message when it failed.

    Poll it after submitting a job until `status` is `completed`, `error`, or `canceled`.
    """
    return JobResponse.model_validate(job, from_attributes=True)


@router.post(
    "/jobs/{job_id}/cancel",
    summary="Cancel a job",
    response_model=JobResponse,
    responses={409: {"model": ErrorResponse, "description": "The job has already finished"}},
)
def cancel_job(job: JobExecution = resolve_job("edit")):  # noqa: B008
    """Asks a job that has not finished to stop. Repeating the request changes nothing.

    The returned `status` is `cancel_requested` until the job stops, then `canceled`.
    """
    if not request_run_transition(job, RunOperation.CANCELED):
        raise api_error(409, "invalid_status_transition", f"Cannot cancel job in '{job.status}' status")
    return JobResponse.model_validate(job, from_attributes=True)


@router.get(
    "/projects/{project_code}/jobs",
    summary="List jobs",
    response_model=JobListResponse,
)
def list_jobs(
    project_code: str = resolve_project_code("view"),
    job_key: PublicJobKey | None = Query(  # noqa: B008
        default=None, description=f"Only jobs of this kind: {JOB_KEY_VALUES}."
    ),
    status: JobStatus | None = Query(  # noqa: B008
        default=None, description="Only jobs in this status, e.g. `completed`. Values as in the job's `status`."
    ),
    page: int = PageQuery,
    limit: int = LimitQuery,
):
    """Profiling, test run, and test generation jobs in a project, newest first."""
    items, total = JobExecution.list_for_project(
        project_code,
        JobExecution.job_key.in_(list(PublicJobKey)),
        job_key=job_key,
        status=status,
        page=page,
        limit=limit,
    )
    return JobListResponse(
        items=[JobResponse.model_validate(job, from_attributes=True) for job in items],
        page=page,
        limit=limit,
        total=total,
    )
