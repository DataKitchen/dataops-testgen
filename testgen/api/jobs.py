"""API v1 — job submission and status polling."""

from fastapi import APIRouter, Depends, status

from testgen.api.deps import api_error, db_session, resolve_job, resolve_table_group, resolve_test_suite
from testgen.api.schemas import JobResponse, JobSubmittedResponse
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

router = APIRouter(prefix="/api/v1", tags=["jobs"], dependencies=[Depends(db_session)])


@router.post(
    "/table-groups/{table_group_id}/profiling-runs",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_profiling(table_group: TableGroup = resolve_table_group("edit")):
    """Submit a profiling job for a table group."""
    job = JobExecution.submit(
        job_key="run-profile",
        kwargs={"table_group_id": str(table_group.id)},
        source="api",
        project_code=table_group.project_code,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-suites/{test_suite_id}/test-runs",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_test_run(test_suite: TestSuite = resolve_test_suite("edit")):
    """Submit a test execution job for a test suite."""
    if test_suite.is_monitor:
        raise api_error(400, "monitor_suite_not_allowed", "Cannot run tests on a monitor suite")

    job = JobExecution.submit(
        job_key="run-tests",
        kwargs={"test_suite_id": str(test_suite.id)},
        source="api",
        project_code=test_suite.project_code,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-suites/{test_suite_id}/test-generation",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_test_generation(test_suite: TestSuite = resolve_test_suite("edit")):
    """Submit a test generation job for a test suite."""
    if test_suite.is_monitor:
        raise api_error(400, "monitor_suite_not_allowed", "Cannot generate tests for a monitor suite")

    job = JobExecution.submit(
        job_key="run-test-generation",
        kwargs={"test_suite_id": str(test_suite.id), "generation_set": "Standard"},
        source="api",
        project_code=test_suite.project_code,
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
)
def get_job_status(job: JobExecution = resolve_job("view")):
    """Poll the status of a job execution."""
    return JobResponse.model_validate(job, from_attributes=True)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobResponse,
)
def cancel_job(job: JobExecution = resolve_job("edit")):
    """Request cancellation of a job execution."""
    if not job.request_cancel():
        raise api_error(409, "invalid_status_transition", f"Cannot cancel job in '{job.status}' status")
    return JobResponse.model_validate(job, from_attributes=True)
