"""API v1 — test run and profiling run retrieval."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from testgen.api.deps import db_session, resolve_job
from testgen.api.schemas import (
    ErrorResponse,
    IssueBreakdown,
    JobKey,
    ProfilingRunResponse,
    ProfilingRunResult,
    TestBreakdown,
    TestRunResponse,
    TestRunResult,
)
from testgen.common.models import get_current_session
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite

_error_responses = {
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(prefix="/api/v1", tags=["runs"], dependencies=[Depends(db_session)], responses=_error_responses)


@router.get(
    "/test-runs/{job_id}",
    response_model=TestRunResponse,
)
def get_test_run(job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_tests)):  # noqa: B008
    """Get a test run by the job execution ID that created it."""
    test_run = TestRun.get_by_id_or_job(job.id)

    result = None
    if test_run:
        counts = TestResult.count_by_status(test_run.id)
        result = TestRunResult(
            score=test_run.dq_score_test_run,
            tests=TestBreakdown(
                passed=counts.passed,
                failed=counts.failed,
                warning=counts.warning,
                error=counts.error,
                log=counts.log,
                dismissed=counts.dismissed,
            ),
        )

    test_suite_id = test_run.test_suite_id if test_run else None
    table_group_id = None
    if test_suite_id:
        table_group_id = get_current_session().scalar(
            select(TestSuite.table_groups_id).where(TestSuite.id == test_suite_id)
        )

    return TestRunResponse(
        id=job.id,
        status=job.status,
        test_suite_id=test_suite_id,
        table_group_id=table_group_id,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=result,
    )


@router.get(
    "/profiling-runs/{job_id}",
    response_model=ProfilingRunResponse,
)
def get_profiling_run(job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_profile)):  # noqa: B008
    """Get a profiling run by the job execution ID that created it."""
    profiling_run = ProfilingRun.get_by_id_or_job(job.id)

    result = None
    if profiling_run:
        counts = HygieneIssue.count_by_likelihood(profiling_run.id)
        result = ProfilingRunResult(
            score=profiling_run.dq_score_profiling,
            table_ct=profiling_run.table_ct,
            column_ct=profiling_run.column_ct,
            record_ct=profiling_run.record_ct,
            issues=IssueBreakdown(
                definite=counts.definite,
                likely=counts.likely,
                possible=counts.possible,
                dismissed=counts.dismissed,
            ),
        )

    return ProfilingRunResponse(
        id=job.id,
        status=job.status,
        table_group_id=profiling_run.table_groups_id if profiling_run else None,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=result,
    )
