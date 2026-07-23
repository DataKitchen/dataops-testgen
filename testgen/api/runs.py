"""API v1 — test run and profiling run retrieval."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

from testgen.api.deps import db_session, resolve_job, resolve_table_group
from testgen.api.enums import (
    DISPOSITION_FROM_DB,
    DISPOSITION_TO_DB,
    RESULT_STATUS_FROM_DB,
    RESULT_STATUS_TO_DB,
    Disposition,
    ResultStatus,
)
from testgen.api.schemas import (
    ErrorResponse,
    IssueCounts,
    ProfilingRunHistoryItem,
    ProfilingRunHistoryResponse,
    ProfilingRunResponse,
    ProfilingRunResult,
    ResultCounts,
    TestResultItem,
    TestResultListResponse,
    TestRunResponse,
    TestRunResult,
)
from testgen.common.enums import Disposition as DbDisposition
from testgen.common.enums import JobKey, JobStatus
from testgen.common.models import get_current_session
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunHistoryRow
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_result import TestResult, TestRunResultRow
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite

_error_responses = {
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(tags=["runs"], dependencies=[Depends(db_session)], responses=_error_responses)


@router.get(
    "/test-runs/{job_id}",
    response_model=TestRunResponse,
)
def get_test_run(job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_tests)):  # noqa: B008
    """Get a test run by the job execution ID that created it."""
    test_run = TestRun.get(job.id)

    result = None
    if test_run:
        counts = TestResult.count_by_status(test_run.id)
        result = TestRunResult(
            score=test_run.dq_score_test_run,
            result_counts=ResultCounts.model_validate(counts, from_attributes=True),
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


def _disposition_from_db(value: str | None) -> Disposition:
    """Map a stored ``disposition`` to the API enum, degrading unknown values to ``no_decision``.

    A NULL or unmapped value resolves to ``no_decision`` rather than raising, so a single odd
    row never fails serialization of the whole results page.
    """
    if not value:
        return Disposition.no_decision
    try:
        return DISPOSITION_FROM_DB[DbDisposition(value)]
    except (ValueError, KeyError):
        return Disposition.no_decision


def _to_item(row: TestRunResultRow) -> TestResultItem:
    """Map a DB-valued result row to the API item, normalizing enum casing."""
    return TestResultItem(
        test_definition_id=row.test_definition_id,
        test_type=row.test_type,
        schema_name=row.schema_name,
        table_name=row.table_name,
        column_names=row.column_names,
        result_status=RESULT_STATUS_FROM_DB.get(row.status),
        result_measure=row.result_measure,
        threshold_value=row.threshold_value,
        result_message=row.message,
        test_time=row.test_time,
        disposition=_disposition_from_db(row.disposition),
    )


@router.get(
    "/test-runs/{job_id}/results",
    response_model=TestResultListResponse,
)
def list_test_run_results(
    job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_tests),  # noqa: B008
    status: ResultStatus | None = Query(default=None),  # noqa: B008
    table_name: str | None = Query(default=None),
    column_name: str | None = Query(default=None),
    test_type: str | None = Query(default=None),
    disposition: Disposition | None = Query(default=None),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List individual results for a test run.

    Omitting ``disposition`` returns active results — confirmed and no_decision
    (excludes dismissed and muted); pass an explicit value to filter to one state.
    """
    clauses = []
    if status:
        clauses.append(TestResult.status == RESULT_STATUS_TO_DB[status])
    if table_name:
        clauses.append(TestResult.table_name == table_name)
    if column_name:
        clauses.append(TestResult.column_names == column_name)
    if test_type:
        clauses.append(TestResult.test_type == test_type)
    if disposition is None:
        # Active: confirmed plus no_decision (NULL). Dismissed/muted excluded.
        clauses.append(or_(TestResult.disposition.is_(None), TestResult.disposition == DbDisposition.CONFIRMED.value))
    elif disposition == Disposition.no_decision:
        clauses.append(TestResult.disposition.is_(None))
    else:
        clauses.append(TestResult.disposition == DISPOSITION_TO_DB[disposition].value)

    items, total = TestResult.list_for_run(job.id, *clauses, page=page, limit=limit)
    return TestResultListResponse(
        items=[_to_item(row) for row in items],
        page=page,
        limit=limit,
        total=total,
    )


@router.get(
    "/profiling-runs/{job_id}",
    response_model=ProfilingRunResponse,
)
def get_profiling_run(job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_profile)):  # noqa: B008
    """Get a profiling run by the job execution ID that created it."""
    profiling_run = ProfilingRun.get(job.id)

    result = None
    if profiling_run:
        counts = HygieneIssue.count_for_run(profiling_run.id)
        result = ProfilingRunResult(
            score=profiling_run.dq_score_profiling,
            table_ct=profiling_run.table_ct,
            column_ct=profiling_run.column_ct,
            record_ct=profiling_run.record_ct,
            issue_counts=IssueCounts.model_validate(counts, from_attributes=True),
        )

    return ProfilingRunResponse(
        id=job.id,
        status=job.status,
        table_group_id=profiling_run.table_groups_id if profiling_run else None,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=result,
    )


def _profiling_history_item(row: ProfilingRunHistoryRow, counts) -> ProfilingRunHistoryItem:
    return ProfilingRunHistoryItem(
        job_execution_id=row.job_execution_id,
        table_group_id=row.table_group_id,
        status=row.status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        profiling_score=row.profiling_score,
        table_ct=row.table_ct,
        column_ct=row.column_ct,
        record_ct=row.record_ct,
        data_point_ct=row.data_point_ct,
        error_message=row.error_message,
        issue_counts=IssueCounts.model_validate(counts, from_attributes=True),
    )


@router.get(
    "/table-groups/{table_group_id}/profiling-runs",
    response_model=ProfilingRunHistoryResponse,
)
def list_profiling_runs(
    table_group: TableGroup = resolve_table_group("view"),  # noqa: B008
    status: JobStatus | None = Query(default=None),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List profiling runs for a table group, newest first.

    Combine ``?status=completed&limit=1`` to fetch the latest completed run.
    """
    clauses = []
    if status is not None:
        clauses.append(JobExecution.status == status)

    rows, total = ProfilingRun.list_for_table_group(
        table_group.id, *clauses, page=page, limit=limit,
    )
    counts_by_run = HygieneIssue.count_for_runs([row.job_execution_id for row in rows])
    return ProfilingRunHistoryResponse(
        items=[_profiling_history_item(row, counts_by_run[row.job_execution_id]) for row in rows],
        page=page,
        limit=limit,
        total=total,
    )
