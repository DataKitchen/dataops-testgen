"""Pydantic request/response models for API v1 endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from testgen.api.enums import (
    Disposition,
    GeneralType,
    HygieneDisposition,
    ImpactDimension,
    IssueLikelihood,
    MonitorThresholdMode,
    MonitorType,
    PiiFlag,
    PiiRisk,
    ResultStatus,
    TableState,
)
from testgen.common.enums import JobSource, JobStatus, PublicJobKey
from testgen.common.test_definition_export_import_service import ImportConfig, ImportPayload, ImportResponse

# --- Jobs ---


class JobSubmittedResponse(BaseModel):
    """Returned on 202 Accepted after successful job submission."""

    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    """Full job execution record returned by status and cancel endpoints."""

    id: UUID
    job_key: PublicJobKey
    status: JobStatus
    source: JobSource
    created_at: datetime
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """Paginated list of job executions."""

    items: list[JobResponse]
    page: int
    limit: int
    total: int


# --- Test Runs ---


class ResultCounts(BaseModel):
    """Counts of test results by outcome status, with dismissed results separated."""

    passed: int = 0
    failed: int = 0
    warning: int = 0
    error: int = 0
    log: int = 0
    dismissed: int = 0


class TestRunResult(BaseModel):
    """Run-specific data populated when execution completes."""

    score: float | None = None
    result_counts: ResultCounts


class TestRunResponse(BaseModel):
    """Test run returned by GET /test-runs/{id}."""

    id: UUID
    status: JobStatus
    test_suite_id: UUID | None = None
    table_group_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TestRunResult | None = None


class TestResultItem(BaseModel):
    """One individual test result within a test run."""

    test_definition_id: UUID
    test_type: str
    test_type_name: str | None = None
    schema_name: str
    table_name: str | None = None
    column_names: str | None = None
    result_status: ResultStatus | None = None
    result_measure: str | None = None
    threshold_value: str | None = None
    result_message: str | None = None
    test_time: datetime | None = None
    disposition: Disposition


class TestResultListResponse(BaseModel):
    """Paginated list of individual test results."""

    items: list[TestResultItem]
    page: int
    limit: int
    total: int


# --- Profiling Runs ---


class HygieneIssueCounts(BaseModel):
    """Counts of active data-quality hygiene issues by likelihood category."""

    definite: int = 0
    likely: int = 0
    possible: int = 0


class PotentialPiiCounts(BaseModel):
    """Counts of active Potential PII findings by risk level."""

    high: int = 0
    moderate: int = 0


class IssueCounts(BaseModel):
    """Profiling-finding breakdown: active counts by kind, plus a single dismissed total."""

    hygiene_issues: HygieneIssueCounts
    potential_pii: PotentialPiiCounts
    dismissed: int = 0


class ProfilingRunResult(BaseModel):
    """Run-specific data populated when profiling completes."""

    score: float | None = None
    table_ct: int | None = None
    column_ct: int | None = None
    record_ct: int | None = None
    issue_counts: IssueCounts


class ProfilingRunResponse(BaseModel):
    """Profiling run returned by GET /profiling-runs/{id}."""

    id: UUID
    status: JobStatus
    table_group_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: ProfilingRunResult | None = None


class ProfilingRunHistoryItem(BaseModel):
    """One profiling run in a table group's history."""

    job_execution_id: UUID
    table_group_id: UUID
    status: JobStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    profiling_score: float | None = None
    table_ct: int | None = None
    column_ct: int | None = None
    record_ct: int | None = None
    data_point_ct: int | None = None
    error_message: str | None = None
    issue_counts: IssueCounts


class ProfilingRunHistoryResponse(BaseModel):
    """Paginated profiling-run history for a table group, newest first."""

    items: list[ProfilingRunHistoryItem]
    page: int
    limit: int
    total: int


class HygieneIssueItem(BaseModel):
    """One data-quality hygiene issue in a profiling run."""

    id: UUID
    issue_type: str
    issue_type_name: str
    schema_name: str
    table_name: str
    column_name: str
    likelihood: IssueLikelihood | None = None
    impact_dimension: ImpactDimension | None = None
    detail: str
    disposition: HygieneDisposition


class HygieneIssueListResponse(BaseModel):
    """Paginated hygiene issues for a profiling run."""

    items: list[HygieneIssueItem]
    page: int
    limit: int
    total: int


class PotentialPiiItem(BaseModel):
    """One Potential PII finding in a profiling run."""

    id: UUID
    issue_type: str
    issue_type_name: str
    schema_name: str
    table_name: str
    column_name: str
    pii_risk: PiiRisk | None = None
    detail: str
    disposition: HygieneDisposition


class PotentialPiiListResponse(BaseModel):
    """Paginated Potential PII findings for a profiling run."""

    items: list[PotentialPiiItem]
    page: int
    limit: int
    total: int


# --- Scores ---


class ScoreBreakdownRow(BaseModel):
    """One row of the group_by breakdown returned by the ``scores`` endpoint.

    Rows are ordered by ``impact`` descending — the actionable signal for which
    group is dragging the score down the most."""

    value: str | None = Field(
        description="The group value (e.g. ``reliability`` for ``impact_dimension``, ``sales_db`` for ``data_source``). Null when the underlying data isn't classified into a group (e.g. an issue type with no ``impact_dimension`` assigned).",
    )
    score: float | None = Field(
        description="Testing Score for this group (0-100). Null when the group has no scored data points.",
    )
    impact: float = Field(
        description="Contribution to the overall score's affected data points, 0-100.",
    )


class ScoresResponse(BaseModel):
    """Quality Score rollup for a project.

    Overall scores are always populated. ``breakdown`` is present iff ``group_by``
    was supplied on the request; rows are ordered by ``impact`` descending. Scores
    can be null when the filtered slice has no scored data points."""

    total: float | None = Field(
        description="Overall Testing Score across all data in the filtered slice (0-100).",
    )
    cde: float | None = Field(
        description="Testing Score restricted to critical data elements in the filtered slice (0-100).",
    )
    profiling: float | None = Field(
        description="Profiling component of the total score (0-100).",
    )
    testing: float | None = Field(
        description="Testing component of the total score (0-100).",
    )
    breakdown: list[ScoreBreakdownRow] | None = Field(
        default=None,
        description="Breakdown rows for the requested ``group_by``, ordered by ``impact`` descending. Absent when no ``group_by`` was provided.",
    )


class ProfilingColumnItem(BaseModel):
    """One column's profile within a profiling run.

    ``profiling_score``, ``testing_score``, and ``pii_flag`` reflect the column's current
    catalog values — a column that has been re-profiled since the pinned run still
    reports the latest scores and classification.
    """

    schema_name: str
    table_name: str
    column_name: str
    general_type: GeneralType | None = None
    functional_data_type: str | None = None
    db_data_type: str | None = None
    datatype_suggestion: str | None = None
    pii_flag: PiiFlag | None = None
    critical_data_element: bool = False
    record_ct: int | None = None
    null_value_ct: int | None = None
    distinct_value_ct: int | None = None
    filled_value_ct: int | None = None
    profiling_score: float | None = None
    testing_score: float | None = None
    issue_counts: IssueCounts


class ProfilingColumnListResponse(BaseModel):
    """Paginated per-column profiles for a profiling run."""

    items: list[ProfilingColumnItem]
    page: int
    limit: int
    total: int


# --- Errors ---


class ErrorDetail(BaseModel):
    """A single error entry."""

    code: str
    detail: str


class ErrorResponse(BaseModel):
    """Standardized error response for business logic errors (400, 404, 409)."""

    errors: list[ErrorDetail]


# --- Test Definition Export/Import (wire types) ---


class ImportRequest(BaseModel):
    config: ImportConfig
    payload: ImportPayload


class ImportStrictError(ErrorResponse):
    """400 response for apply_strict when entries would be skipped."""

    import_result: ImportResponse


# --- Test Generation ---


class TestGenerationRequest(BaseModel):
    generation_sets: list[str] | None = None


# --- Monitors ---


class MonitorTypeSummary(BaseModel):
    """Per-type monitoring state for a table (single-instance types)."""

    monitor_id: UUID | None = None
    anomalies: int = 0
    is_training: bool | None = None
    is_pending: bool = True


class SchemaMonitorSummary(BaseModel):
    """Schema monitor state (no training mode; carries structural-change counts)."""

    monitor_id: UUID | None = None
    anomalies: int = 0
    is_pending: bool = True
    column_adds: int = 0
    column_drops: int = 0
    column_mods: int = 0


class MetricMonitorSummary(BaseModel):
    """One metric monitor (per column) on a table."""

    monitor_id: UUID
    metric_name: str | None = None
    anomalies: int = 0
    is_training: bool | None = None
    is_pending: bool = True


class MonitorTableRow(BaseModel):
    """Monitoring summary for a single table within the lookback window."""

    model_config = {"populate_by_name": True}

    table_name: str
    row_count: int | None = None
    previous_row_count: int | None = None
    latest_update: datetime | None = None
    table_state: TableState | None = None
    freshness: MonitorTypeSummary
    volume: MonitorTypeSummary
    # JSON key is "schema"; the Python attr is "schema_" to avoid shadowing BaseModel.schema.
    schema_: SchemaMonitorSummary = Field(alias="schema")
    metrics: list[MetricMonitorSummary]


class MonitorTotals(BaseModel):
    """Group-wide totals across all monitored tables."""

    lookback: int
    lookback_start: datetime | None = None
    lookback_end: datetime | None = None
    total_monitored_tables: int
    freshness_anomalies: int
    volume_anomalies: int
    schema_anomalies: int
    metric_anomalies: int


class MonitorSummaryListResponse(BaseModel):
    """Paginated per-table monitoring summary with group totals."""

    items: list[MonitorTableRow]
    page: int
    limit: int
    total: int
    totals: MonitorTotals


class MonitorSeriesResponse(BaseModel):
    """A single monitor's lookback time-series with a self-contained header."""

    monitor_id: UUID
    type: MonitorType
    threshold_mode: MonitorThresholdMode
    table_name: str
    column_name: str | None = None
    lookback: int
    is_training: bool
    current_bands: dict | None = None
    points: list[dict]
