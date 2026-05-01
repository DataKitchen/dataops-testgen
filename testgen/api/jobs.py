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
from testgen.api.schemas import ErrorResponse, JobKey, JobListResponse, JobResponse, JobSource, JobSubmittedResponse
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

_error_responses = {
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(prefix="/api/v1", tags=["Jobs"], dependencies=[Depends(db_session)], responses=_error_responses)


@router.post(
    "/table-groups/{table_group_id}/profiling-runs",
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
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_test_run(test_suite: TestSuite = resolve_test_suite("edit")):  # noqa: B008
    """Submit a test execution job for a test suite."""
    job = JobExecution.submit(
        job_key=JobKey.run_tests,
        kwargs={"test_suite_id": str(test_suite.id)},
        source=JobSource.api,
        project_code=test_suite.project_code,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-suites/{test_suite_id}/test-generation",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_test_generation(test_suite: TestSuite = resolve_test_suite("edit")):  # noqa: B008
    """Submit a test generation job for a test suite."""
    job = JobExecution.submit(
        job_key=JobKey.run_test_generation,
        kwargs={"test_suite_id": str(test_suite.id), "generation_set": "Standard"},
        source=JobSource.api,
        project_code=test_suite.project_code,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
)
def get_job_status(job: JobExecution = resolve_job("view")):  # noqa: B008
    """Poll the status of a job execution."""
    return JobResponse.model_validate(job, from_attributes=True)


@router.post(
    "/jobs/{job_id}/cancel",
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
    response_model=JobListResponse,
)
def list_jobs(
    project_code: str = resolve_project_code("view"),
    job_key: JobKey | None = Query(default=None),  # noqa: B008
    status: JobStatus | None = Query(default=None),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List job executions for a project, with optional filters and pagination."""
    items, total = JobExecution.list_for_project(
        project_code,
        JobExecution.source != "system",
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
