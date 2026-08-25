"""API v1 — test run and profiling run retrieval."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

from testgen.api.deps import db_session, get_authorized_user, has_project_permission, resolve_job, resolve_table_group
from testgen.api.enums import (
    DISPOSITION_FROM_DB,
    DISPOSITION_TO_DB,
    GENERAL_TYPE_FROM_DB,
    HYGIENE_DISPOSITION_FROM_DB,
    HYGIENE_DISPOSITION_TO_DB,
    IMPACT_DIMENSION_FROM_DB,
    LIKELIHOOD_FROM_DB,
    LIKELIHOOD_TO_DB,
    PII_RISK_FROM_DB,
    PII_RISK_TO_DB,
    RESULT_STATUS_FROM_DB,
    RESULT_STATUS_TO_DB,
    Disposition,
    HygieneDisposition,
    ImpactDimension,
    IssueLikelihood,
    PiiRisk,
    ResultStatus,
    pii_flag_from_db,
)
from testgen.api.schemas import (
    ErrorResponse,
    HygieneIssueCounts,
    HygieneIssueItem,
    HygieneIssueListResponse,
    IssueCounts,
    PotentialPiiCounts,
    PotentialPiiItem,
    PotentialPiiListResponse,
    ProfilingColumnItem,
    ProfilingColumnListResponse,
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
from testgen.common.enums import ImpactDimension as DbImpactDimension
from testgen.common.enums import IssueLikelihood as DbIssueLikelihood
from testgen.common.enums import JobKey, JobStatus
from testgen.common.enums import PiiRisk as DbPiiRisk
from testgen.common.models import get_current_session
from testgen.common.models.hygiene_issue import HygieneIssue, HygieneIssueListRow, HygieneIssueType
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profile_result import ColumnProfileRow, ColumnSort, ProfileResult
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunHistoryRow
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_result import TestResult, TestRunResultRow
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.common.models.user import User
from testgen.common.pii_masking import PII_REDACTED

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
        test_type_name=row.test_type_name,
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


def _hygiene_disposition_clauses(disposition: HygieneDisposition | None):
    """WHERE clauses for the hygiene-issue disposition filter.

    Hygiene issues COALESCE NULL disposition to Confirmed, so omitting the filter
    or passing ``confirmed`` both return rows whose stored disposition is
    Confirmed or NULL. Explicit ``dismissed`` / ``muted`` match the stored DB
    value directly.
    """
    if disposition is None or disposition == HygieneDisposition.confirmed:
        return [or_(HygieneIssue.disposition.is_(None), HygieneIssue.disposition == DbDisposition.CONFIRMED.value)]
    return [HygieneIssue.disposition == HYGIENE_DISPOSITION_TO_DB[disposition].value]


def _hygiene_disposition_from_db(value: str | None) -> HygieneDisposition:
    """Render a stored disposition through the hygiene API enum.

    NULL and unmapped values render as ``confirmed`` to mirror the COALESCE default
    used by every hygiene read path — one odd row cannot fail serialization.
    """
    if not value:
        return HygieneDisposition.confirmed
    try:
        return HYGIENE_DISPOSITION_FROM_DB[DbDisposition(value)]
    except (ValueError, KeyError):
        return HygieneDisposition.confirmed


def _impact_dimension_from_db(value: str | None) -> ImpactDimension | None:
    if not value:
        return None
    try:
        return IMPACT_DIMENSION_FROM_DB[DbImpactDimension(value)]
    except (ValueError, KeyError):
        return None


def _likelihood_from_db(value: str | None) -> IssueLikelihood | None:
    if not value:
        return None
    try:
        return LIKELIHOOD_FROM_DB[DbIssueLikelihood(value)]
    except (ValueError, KeyError):
        return None


def _pii_risk_from_db(value: str | None) -> PiiRisk | None:
    if not value:
        return None
    try:
        return PII_RISK_FROM_DB[DbPiiRisk(value)]
    except (ValueError, KeyError):
        return None


def _redact_detail(row: HygieneIssueListRow, can_view_pii: bool) -> str:
    """Redact ``detail`` to ``PII_REDACTED`` when the caller lacks ``view_pii`` and
    the row is PII-flagged. Matches the triad check used across MCP + UI."""
    if not can_view_pii and row.detail_redactable and row.pii_flag:
        return PII_REDACTED
    return row.detail


def _to_hygiene_item(row: HygieneIssueListRow, can_view_pii: bool) -> HygieneIssueItem:
    return HygieneIssueItem(
        id=row.id,
        issue_type=row.issue_type_code,
        issue_type_name=row.issue_type_name,
        schema_name=row.schema_name,
        table_name=row.table_name,
        column_name=row.column_name,
        likelihood=_likelihood_from_db(row.priority),
        impact_dimension=_impact_dimension_from_db(row.impact_dimension),
        detail=_redact_detail(row, can_view_pii),
        disposition=_hygiene_disposition_from_db(row.disposition),
    )


def _to_pii_item(row: HygieneIssueListRow, can_view_pii: bool) -> PotentialPiiItem:
    return PotentialPiiItem(
        id=row.id,
        issue_type=row.issue_type_code,
        issue_type_name=row.issue_type_name,
        schema_name=row.schema_name,
        table_name=row.table_name,
        column_name=row.column_name,
        pii_risk=_pii_risk_from_db(row.priority),
        detail=_redact_detail(row, can_view_pii),
        disposition=_hygiene_disposition_from_db(row.disposition),
    )


@router.get(
    "/profiling-runs/{job_id}/hygiene-issues",
    response_model=HygieneIssueListResponse,
)
def list_profiling_run_hygiene_issues(
    job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_profile),  # noqa: B008
    user: User = Depends(get_authorized_user),  # noqa: B008
    issue_type: str | None = Query(default=None),
    likelihood: IssueLikelihood | None = Query(default=None),  # noqa: B008
    disposition: HygieneDisposition | None = Query(default=None),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List data-quality hygiene issues for a profiling run.

    Excludes Potential PII findings, which are listed by
    ``/profiling-runs/{job_id}/potential-pii``. Omitting ``disposition``
    returns confirmed issues; pass ``dismissed`` or ``muted`` to filter to
    those states. Callers without ``view_pii`` on the run's project see
    ``[PII Redacted]`` in ``detail`` for PII-flagged rows.
    """
    clauses = [HygieneIssueType.likelihood != DbIssueLikelihood.POTENTIAL_PII.value]
    if issue_type:
        clauses.append(HygieneIssue.type_id == issue_type)
    if likelihood:
        clauses.append(HygieneIssueType.likelihood == LIKELIHOOD_TO_DB[likelihood].value)
    clauses.extend(_hygiene_disposition_clauses(disposition))

    rows, total = HygieneIssue.list_for_run(job.id, *clauses, page=page, limit=limit)
    can_view_pii = has_project_permission(user, job.project_code, "view_pii")
    return HygieneIssueListResponse(
        items=[_to_hygiene_item(row, can_view_pii) for row in rows],
        page=page,
        limit=limit,
        total=total,
    )


@router.get(
    "/profiling-runs/{job_id}/potential-pii",
    response_model=PotentialPiiListResponse,
)
def list_profiling_run_potential_pii(
    job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_profile),  # noqa: B008
    user: User = Depends(get_authorized_user),  # noqa: B008
    pii_risk: PiiRisk | None = Query(default=None),  # noqa: B008
    disposition: HygieneDisposition | None = Query(default=None),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List Potential PII findings for a profiling run.

    Companion to ``/profiling-runs/{job_id}/hygiene-issues``. Omitting
    ``disposition`` returns confirmed findings; pass ``dismissed`` or
    ``muted`` to filter to those states. Callers without ``view_pii`` on
    the run's project see ``[PII Redacted]`` in ``detail``.
    """
    clauses = [HygieneIssueType.likelihood == DbIssueLikelihood.POTENTIAL_PII.value]
    if pii_risk:
        clauses.append(HygieneIssue.priority == PII_RISK_TO_DB[pii_risk].value)
    clauses.extend(_hygiene_disposition_clauses(disposition))

    rows, total = HygieneIssue.list_for_run(job.id, *clauses, page=page, limit=limit)
    can_view_pii = has_project_permission(user, job.project_code, "view_pii")
    return PotentialPiiListResponse(
        items=[_to_pii_item(row, can_view_pii) for row in rows],
        page=page,
        limit=limit,
        total=total,
    )


def _to_column_item(row: ColumnProfileRow) -> ProfilingColumnItem:
    return ProfilingColumnItem(
        schema_name=row.schema_name,
        table_name=row.table_name,
        column_name=row.column_name,
        general_type=GENERAL_TYPE_FROM_DB.get(row.general_type) if row.general_type else None,
        functional_data_type=row.functional_data_type,
        db_data_type=row.db_data_type,
        datatype_suggestion=row.datatype_suggestion,
        pii_flag=pii_flag_from_db(row.pii_flag),
        critical_data_element=row.critical_data_element,
        record_ct=row.record_ct,
        null_value_ct=row.null_value_ct,
        distinct_value_ct=row.distinct_value_ct,
        filled_value_ct=row.filled_value_ct,
        profiling_score=row.profiling_score,
        testing_score=row.testing_score,
        issue_counts=IssueCounts(
            hygiene_issues=HygieneIssueCounts(
                definite=row.definite,
                likely=row.likely,
                possible=row.possible,
            ),
            potential_pii=PotentialPiiCounts(
                high=row.high,
                moderate=row.moderate,
            ),
            dismissed=row.dismissed,
        ),
    )


# No PII masking on this endpoint: none of the returned fields are in ``PROFILING_PII_FIELDS``
# (see ``testgen.common.pii_masking``). Deep per-column stats (``top_freq_values``,
# ``min_text``/``max_text``, ``min_value``/``max_value``, ``min_date``/``max_date``,
# distribution buckets) belong to a later column-detail endpoint that will import
# ``mask_profiling_pii``.
@router.get(
    "/profiling-runs/{job_id}/columns",
    response_model=ProfilingColumnListResponse,
)
def list_profiling_run_columns(
    job: JobExecution = resolve_job("view", JobExecution.job_key == JobKey.run_profile),  # noqa: B008
    table_name: str | None = Query(default=None),
    sort: ColumnSort = Query(default=ColumnSort.hygiene_severity),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List per-column profiles for a profiling run.

    The default ``hygiene_severity`` sort orders columns worst-first by the tuple
    ``(definite, likely, possible, high, moderate)`` — a column with any Definite hygiene
    issue outranks any column with none regardless of lower-severity counts. Use
    ``sort=table`` for a stable per-table listing (schema, table, column position).

    ``table_name`` is a case-sensitive exact match: source-system casing is preserved.

    ``profiling_score``, ``testing_score``, and ``pii_flag`` on each returned item reflect
    the column's current values from the catalog — a column that has been re-profiled
    since the pinned run still reports the latest scores and classification.
    """
    clauses = []
    if table_name is not None:
        clauses.append(ProfileResult.table_name == table_name)

    rows, total = ProfileResult.list_columns_for_run(
        job.id,
        *clauses,
        sort=sort,
        page=page,
        limit=limit,
    )
    return ProfilingColumnListResponse(
        items=[_to_column_item(row) for row in rows],
        page=page,
        limit=limit,
        total=total,
    )
