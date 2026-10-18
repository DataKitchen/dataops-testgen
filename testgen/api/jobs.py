"""API v1 — job submission, status polling, and listing."""

from fastapi import APIRouter, Depends, Query, status

from testgen.api.deps import (
    api_error,
    db_session,
    resolve_job,
    resolve_project_code,
    resolve_table_group,
    resolve_test_suite,
)
from testgen.api.schemas import (
    ErrorResponse,
    JobListResponse,
    JobResponse,
    JobSubmittedResponse,
    TestGenerationRequest,
    TestGenerationSubmittedResponse,
    TestRunRequest,
)
from testgen.commands.test_generation import (
    TestsNeedProfilingError,
    parse_regeneration_groups,
    resolve_generation_profile_run,
    unprofiled_regeneration_note,
)
from testgen.common.enums import JobKey, JobSource, JobStatus, PublicJobKey, RegenerationGroup, SuiteType
from testgen.common.generation_set_service import resolve_generation_sets
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

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
    """Submit a profiling job for a table group."""
    job = JobExecution.submit(
        job_key=JobKey.run_profile,
        kwargs={"table_group_id": str(table_group.id)},
        source=JobSource.api,
        project_code=table_group.project_code,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-suites/{test_suite_id}/test-runs",
    summary="Submit a test run",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_test_run(
    test_suite: TestSuite = resolve_test_suite("edit"),  # noqa: B008
    body: TestRunRequest | None = None,
):
    """Submit a test execution job for a test suite.

    Runs against the table group's schema. A referential test's comparison schema can be
    overridden for this run.
    """
    kwargs: dict[str, str] = {"test_suite_id": str(test_suite.id)}
    if body and body.match_schema_name:
        kwargs["match_schema_name"] = body.match_schema_name

    job = JobExecution.submit(
        job_key=JobKey.run_tests,
        kwargs=kwargs,
        source=JobSource.api,
        project_code=test_suite.project_code,
        external_url=body.external_url if body else None,
        caller_metadata=body.metadata if body else None,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-suites/{test_suite_id}/test-generation",
    summary="Submit a test generation job",
    response_model=TestGenerationSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={400: {"model": ErrorResponse, "description": "Invalid generation set or regeneration groups"}},
)
def submit_test_generation(
    test_suite: TestSuite = resolve_test_suite("edit", (SuiteType.REGULAR, SuiteType.CONTRACT)),  # noqa: B008
    body: TestGenerationRequest | None = None,
):
    """Submit a test generation job for a test suite or a contract.

    Generates from the test suite's stored generation sets when none are given,
    falling back to Standard. A contract always generates its own fixed set of test types into
    its draft version and generates the draft's metadata. Before its table group has been
    profiled, the metadata is generated from the data catalog alone and only schema conformance tests are
    created.

    The value hash test types (Match Text, Numeric and Date Hash, their Keyed variants, and Match
    Epoch Sum, in the Table Comparison set) are generated only from a profiling run that computed
    value hashes. That needs ``profile_table_comparison`` on the table group and a profiling run
    since it was turned on; otherwise they are not generated.

    For a contract, ``regenerate`` chooses what is refreshed; omit it to refresh everything. Tests
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
    return TestGenerationSubmittedResponse(id=job.id, created_at=job.created_at, regenerate=groups, note=note)


@router.get(
    "/jobs/{job_id}",
    summary="Poll a job's status",
    response_model=JobResponse,
)
def get_job_status(job: JobExecution = resolve_job("view")):  # noqa: B008
    """Poll the status of a job execution."""
    return JobResponse.model_validate(job, from_attributes=True)


@router.post(
    "/jobs/{job_id}/cancel",
    summary="Cancel a job",
    response_model=JobResponse,
    responses={409: {"model": ErrorResponse, "description": "Invalid status transition"}},
)
def cancel_job(job: JobExecution = resolve_job("edit")):  # noqa: B008
    """Request cancellation of a job execution."""
    if not job.request_cancel():
        raise api_error(409, "invalid_status_transition", f"Cannot cancel job in '{job.status}' status")
    return JobResponse.model_validate(job, from_attributes=True)


@router.get(
    "/projects/{project_code}/jobs",
    summary="List jobs",
    response_model=JobListResponse,
)
def list_jobs(
    project_code: str = resolve_project_code("view"),
    job_key: PublicJobKey | None = Query(default=None),  # noqa: B008
    status: JobStatus | None = Query(default=None),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List job executions for a project, with optional filters and pagination."""
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
