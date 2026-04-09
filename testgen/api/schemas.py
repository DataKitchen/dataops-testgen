"""Pydantic request/response models for API v1 endpoints."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, field_validator

from testgen.common.models.job_execution import JobStatus

# --- Jobs ---


class JobKey(StrEnum):
    run_profile = "run-profile"
    run_tests = "run-tests"
    run_monitors = "run-monitors"
    run_test_generation = "run-test-generation"


class JobSource(StrEnum):
    api = "api"
    ui = "ui"
    scheduler = "scheduler"
    mcp = "mcp"
    cli = "cli"
    backfill = "backfill"


class JobSubmittedResponse(BaseModel):
    """Returned on 202 Accepted after successful job submission."""

    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    """Full job execution record returned by status and cancel endpoints."""

    id: UUID
    job_key: JobKey
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


class TestBreakdown(BaseModel):
    """Counts of test results by outcome status."""

    passed: int = 0
    failed: int = 0
    warning: int = 0
    error: int = 0
    log: int = 0
    dismissed: int = 0


class TestRunResult(BaseModel):
    """Run-specific data populated when execution completes."""

    score: float | None = None
    tests: TestBreakdown


class TestRunResponse(BaseModel):
    """Test run returned by GET /test-runs/{id}."""

    id: UUID
    status: JobStatus
    test_suite_id: UUID | None = None
    table_group_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TestRunResult | None = None


# --- Profiling Runs ---


class IssueBreakdown(BaseModel):
    """Counts of hygiene issues by likelihood category."""

    definite: int = 0
    likely: int = 0
    possible: int = 0
    dismissed: int = 0


class ProfilingRunResult(BaseModel):
    """Run-specific data populated when profiling completes."""

    score: float | None = None
    table_ct: int | None = None
    column_ct: int | None = None
    record_ct: int | None = None
    issues: IssueBreakdown


class ProfilingRunResponse(BaseModel):
    """Profiling run returned by GET /profiling-runs/{id}."""

    id: UUID
    status: JobStatus
    table_group_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: ProfilingRunResult | None = None


# --- Errors ---


class ErrorDetail(BaseModel):
    """A single error entry."""

    code: str
    detail: str


class ErrorResponse(BaseModel):
    """Standardized error response for business logic errors (400, 404, 409)."""

    errors: list[ErrorDetail]


# --- Test Definition Export/Import ---


class Origin(StrEnum):
    manual = "manual"
    auto = "auto"
    both = "both"


class ImportMode(StrEnum):
    preview = "preview"
    apply = "apply"
    apply_strict = "apply_strict"


class OnMatch(StrEnum):
    overwrite_all = "overwrite_all"
    overwrite_unlocked = "overwrite_unlocked"
    skip = "skip"


class OnNew(StrEnum):
    skip = "skip"
    create = "create"
    create_and_lock = "create_and_lock"


class OnAbsence(StrEnum):
    do_nothing = "do_nothing"
    delete_all = "delete_all"
    delete_unlocked = "delete_unlocked"


class ImportAction(StrEnum):
    create = "create"
    update = "update"
    skip = "skip"
    delete = "delete"


class ImportReason(StrEnum):
    matched = "matched"
    no_match = "no_match"
    policy = "policy"
    locked = "locked"
    invalid_test_type = "invalid_test_type"
    invalid_table = "invalid_table"
    missing_external_id = "missing_external_id"
    absent = "absent"


# Non-None defaults must match the ORM column defaults in TestDefinition:
#   test_active=True (YNString default="Y"), lock_refresh=False (YNString default="N"),
#   skip_errors=0 (ZeroIfEmptyInteger), window_days=0 (ZeroIfEmptyInteger),
#   history_lookback=0 (Column default=0).
# On export, the model_serializer omits fields matching these defaults to keep the file compact.
# On import, model_fields_set distinguishes explicit from defaulted.
class TestDefinitionExport(BaseModel):
    """Test definition fields included in the export/import file."""

    model_config = {"from_attributes": True}

    # Matching / identity
    test_type: str
    external_id: UUID | None = None
    last_auto_gen_date: datetime | None = None

    # Definition fields
    table_name: str | None = None
    column_name: str | None = None
    test_description: str | None = None
    test_active: bool = True
    severity: str | None = None
    lock_refresh: bool = False
    export_to_observability: bool | None = None
    skip_errors: int = 0

    # Calibration fields
    baseline_ct: str | None = None
    baseline_unique_ct: str | None = None
    baseline_value: str | None = None
    baseline_value_ct: str | None = None
    threshold_value: str | None = None
    baseline_sum: str | None = None
    baseline_avg: str | None = None
    baseline_sd: str | None = None
    lower_tolerance: str | None = None
    upper_tolerance: str | None = None

    # Subset / grouping
    subset_condition: str | None = None
    groupby_names: str | None = None
    having_condition: str | None = None
    window_date_column: str | None = None
    window_days: int = 0

    # Referential
    match_schema_name: str | None = None
    match_table_name: str | None = None
    match_column_names: str | None = None
    match_subset_condition: str | None = None
    match_groupby_names: str | None = None
    match_having_condition: str | None = None

    # Query / history
    custom_query: str | None = None
    history_calculation: str | None = None
    history_calculation_upper: str | None = None
    history_lookback: int = 0

    @field_validator("skip_errors", "window_days", "history_lookback", mode="before")
    @classmethod
    def _coerce_none_to_zero(cls, v: int | None) -> int:
        return v if v is not None else 0


class ExportSource(BaseModel):
    project_code: str
    test_suite: str
    table_group: str
    table_group_schema: str
    exported_at: datetime
    testgen_version: str | None = None


class ExportDocument(BaseModel):
    version: int = 1
    source: ExportSource
    definitions: list[TestDefinitionExport]


# --- Import ---


class ImportConfig(BaseModel):
    mode: ImportMode
    on_match: OnMatch
    on_new: OnNew
    on_absence: OnAbsence


class ImportPayload(BaseModel):
    """Import payload — same structure as an export document, but definitions are typed."""

    version: int = 1
    source: ExportSource | None = None
    definitions: list[TestDefinitionExport]


class ImportRequest(BaseModel):
    config: ImportConfig
    payload: ImportPayload


class ImportItemTD(BaseModel):
    idx: int | None = None
    target_id: UUID | None = None


class ImportItem(BaseModel):
    action: ImportAction
    reason: ImportReason
    tds: list[ImportItemTD]


class ImportSummary(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0


class ImportResponse(BaseModel):
    summary: ImportSummary
    items: list[ImportItem]


class ImportStrictError(ErrorResponse):
    """400 response for apply_strict when entries would be skipped."""

    import_result: ImportResponse
