"""API v1 — job submission and status polling."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.schemas import (
    JobResponse,
    JobSubmittedResponse,
    SubmitProfilingRequest,
    SubmitTestGenerationRequest,
    SubmitTestRunRequest,
)
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

router = APIRouter(prefix="/api/v1", tags=["jobs"], dependencies=[Depends(db_session)])

_require_user = Depends(get_authorized_user)


def _api_error(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"errors": [{"code": code, "detail": detail}]})


@router.post(
    "/profiling-runs",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_profiling(body: SubmitProfilingRequest, user=_require_user):
    """Submit a profiling job for a table group."""
    table_group = TableGroup.get(body.table_group_id)
    if not table_group:
        raise _api_error(404, "table_group_not_found", "Table group not found")

    job = JobExecution.submit(
        job_key="run-profile",
        kwargs={"table_group_id": str(body.table_group_id)},
        source="api",
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-runs",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_test_run(body: SubmitTestRunRequest, user=_require_user):
    """Submit a test execution job for a test suite."""
    test_suite = TestSuite.get(body.test_suite_id)
    if not test_suite:
        raise _api_error(404, "test_suite_not_found", "Test suite not found")
    if test_suite.is_monitor:
        raise _api_error(400, "monitor_suite_not_allowed", "Cannot run tests on a monitor suite")

    job = JobExecution.submit(
        job_key="run-tests",
        kwargs={"test_suite_id": str(body.test_suite_id)},
        source="api",
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.post(
    "/test-generation",
    response_model=JobSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_test_generation(body: SubmitTestGenerationRequest, user=_require_user):
    """Submit a test generation job for a test suite."""
    test_suite = TestSuite.get(body.test_suite_id)
    if not test_suite:
        raise _api_error(404, "test_suite_not_found", "Test suite not found")
    if test_suite.is_monitor:
        raise _api_error(400, "monitor_suite_not_allowed", "Cannot generate tests for a monitor suite")

    job = JobExecution.submit(
        job_key="run-test-generation",
        kwargs={"test_suite_id": str(body.test_suite_id), "generation_set": "Standard"},
        source="api",
    )
    return JobSubmittedResponse.model_validate(job, from_attributes=True)


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
)
def get_job_status(job_id: UUID, user=_require_user):
    """Poll the status of a job execution."""
    job = JobExecution.get(job_id)
    if not job:
        raise _api_error(404, "job_not_found", "Job not found")
    return JobResponse.model_validate(job, from_attributes=True)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobResponse,
)
def cancel_job(job_id: UUID, user=_require_user):
    """Request cancellation of a job execution."""
    job = JobExecution.get(job_id)
    if not job:
        raise _api_error(404, "job_not_found", "Job not found")
    if not job.request_cancel():
        raise _api_error(409, "invalid_status_transition", f"Cannot cancel job in '{job.status}' status")
    return JobResponse.model_validate(job, from_attributes=True)
