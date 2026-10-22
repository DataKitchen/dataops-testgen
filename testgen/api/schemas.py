"""Pydantic request/response models for API v1 endpoints."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    Tag,
    ValidationInfo,
    field_validator,
)

from testgen.api.enums import (
    AuthenticationMethod,
    ConnectionType,
    DefaultSeverity,
    Disposition,
    GeneralType,
    HygieneDisposition,
    ImpactDimension,
    IssueLikelihood,
    MonitorSensitivity,
    MonitorThresholdMode,
    MonitorType,
    PiiFlag,
    PiiRisk,
    ResultStatus,
    ScheduleKind,
    TableState,
    TestSuiteType,
)
from testgen.common.contract_service import VerificationUnavailable
from testgen.common.enums import JobSource, JobStatus, PublicJobKey, RegenerationGroup
from testgen.common.file_declaration_schema import HEADER_DESCRIPTION, FileDeclarationShape, FileDeclarationSpec
from testgen.common.models.job_execution import EXTERNAL_URL_MAX_LENGTH, validate_caller_metadata
from testgen.common.models.suite_version import VersionState
from testgen.common.models.table_group import (
    SCHEMA_NAME_MAX_LENGTH,
    SCHEMA_NAME_PATTERN,
    table_group_defaults,
)
from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS
from testgen.common.test_definition_export_import_service import (
    ContractVersion,
    ImportConfig,
    ImportPayload,
    ImportResponse,
)

TestSuiteTypeField = Annotated[
    TestSuiteType,
    Field(description="The kind of test suite: `regular`, or `contract` for a data contract."),
]

SchemaName = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "The schema that holds the table, or the data space on Salesforce Data 360. `null` on a file "
            "connection."
        ),
    ),
]

PageNumber = Annotated[int, Field(description="The page returned, starting at 1.")]
PageLimit = Annotated[int, Field(description="The most items a page holds, as requested.")]
TotalCount = Annotated[int, Field(description="Items across all pages.")]
PAGE_ITEMS = "The resources on this page."

JOB_STATUS = (
    "Where the job is: `pending` (waiting to start), `queued` (waiting for a free worker), `claimed` (starting), "
    "`running`, `completed`, `error`, `cancel_requested` (stopping), or `canceled`. A profiling job can also be "
    "paused or interrupted and later continue: `pause_requested`, `paused`, `resume_requested`, "
    "`interrupt_requested`, and `interrupted` (stopped by a shutdown, and continued automatically). `completed`, "
    "`error`, and `canceled` are final."
)
JOB_KEY_VALUES = "`run-profile` (profiling), `run-tests` (a test run), or `run-test-generation` (test generation)"
RESULT_STATUS_VALUES = "`passed`, `failed`, `warning`, `error`, or `log`"
HYGIENE_DISPOSITION_FILTER = "Only findings with this disposition: `confirmed` (the default), `dismissed`, or `muted`."
LIKELIHOOD_VALUES = "`definite`, `likely`, or `possible`"
PII_RISK_HIGH = "`high` (e.g. passwords, Social Security numbers, tax IDs)"
PII_RISK_MODERATE = "`moderate` (e.g. names, addresses, phone numbers, email addresses)"
SCHEDULE_KIND_VALUES = "`profiling_run` (profiles a table group) or `test_run` (runs a test suite's tests)"
_ERROR_MESSAGE = "Why the job failed. `null` unless `status` is `error`."
VERSION_NUMBER = "The version's number, counting from 1."

# --- Jobs ---


class JobSubmittedResponse(BaseModel):
    """A job just submitted. Follow it with `GET /jobs/{job_id}` using its `id`."""

    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class TableGroupSchemaChange(BaseModel):
    """What changing the schema did, present only when the request changed it."""

    previous_schema_name: str = Field(description="The schema the table group read before the change.")
    schema_name: str
    definitions_repointed: int = Field(
        description="Test definitions updated to the new schema.",
    )
    missing_tables: list[str] = Field(
        default_factory=list,
        description=(
            "Tables in the table group's catalog that it no longer selects after the move, because the new "
            "schema does not have them or because the request's table filters exclude them. The change still "
            "applies. Their tests report an error on each test run, or are deactivated if the test suite "
            "deactivates tests that fail validation, and the next monitor run deletes their "
            "monitors along with the thresholds they learned."
        ),
    )


class TestRunRequest(BaseModel):
    """Options for a test run job. The body is optional."""

    model_config = ConfigDict(extra="forbid")

    match_schema_name: str | None = Field(
        default=None,
        pattern=SCHEMA_NAME_PATTERN,
        max_length=SCHEMA_NAME_MAX_LENGTH,
        description=(
            "Schema to read the second table of each referential test from, for this run only. "
            "Tests without a second table are unaffected, the stored test definitions are not changed, "
            "and the run deactivates no tests. To read the table group's own tables from another "
            "schema, change the table group's schema instead."
        ),
    )
    external_url: str | None = Field(
        default=None,
        max_length=EXTERNAL_URL_MAX_LENGTH,
        description=(
            "Link back to whatever triggered this run. Stored with the run."
        ),
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "JSON object describing what triggered this run, up to 50 top-level keys and 10,240 "
            "bytes. Stored with the run."
        ),
    )
    version: StrictInt | None = Field(
        default=None,
        ge=1,
        description=(
            "Contracts only. The number of the contract version to run. Omit to run the active version, or the "
            "draft when no version has been frozen."
        ),
    )

    @field_validator("metadata")
    @classmethod
    def _check_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if error := validate_caller_metadata(value):
            raise ValueError(error)
        return value


class JobResponse(BaseModel):
    """A job and its status."""

    id: UUID
    job_key: PublicJobKey = Field(description=f"The kind of job: {JOB_KEY_VALUES}.")
    status: JobStatus = Field(description=JOB_STATUS)
    source: JobSource = Field(
        description="What started the job: `api`, `ui`, `scheduler` (a schedule), `mcp`, `cli`, or `system` (TestGen "
        "itself, e.g. test generation into the default test suite after a table group's first profiling run)."
    )
    created_at: datetime
    claimed_at: datetime | None = Field(
        default=None,
        description="When a worker took the job, in UTC. Restamped when a paused or interrupted job is taken again. "
        "`null` until a worker takes it.",
    )
    started_at: datetime | None = Field(
        default=None,
        description="When the job started running, in UTC. Kept when a paused or interrupted job continues. `null` "
        "until it starts.",
    )
    completed_at: datetime | None = Field(
        default=None, description="When the job completed, failed, or was canceled, in UTC. `null` until then."
    )
    error_message: str | None = Field(default=None, description=_ERROR_MESSAGE)

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """A page of jobs, newest first."""

    items: list[JobResponse] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


# --- Test Runs ---


class ResultCounts(BaseModel):
    """Counts of a run's test results by status. Dismissed and muted results count only toward `dismissed`."""

    passed: int = 0
    failed: int = 0
    warning: int = 0
    error: int = 0
    log: int = 0
    dismissed: int = Field(default=0, description="Results dismissed or muted, whatever their status.")


class TestRunResult(BaseModel):
    """A test run's results, present once the run completes."""

    score: float | None = Field(
        default=None,
        description="The run's Testing Score, from 0 to 100. `null` until it has been calculated after the run "
        "completes.",
    )
    result_counts: ResultCounts


class TestRunVersion(BaseModel):
    """The contract version a run checked."""

    number: int = Field(description=VERSION_NUMBER)
    state: VersionState = Field(
        description="The version's state as of this request: `draft`, `active` (the agreement in force), or `superseded`."
    )
    counts_as_status: bool = Field(
        description="Whether the run completed a verification of the agreement in force when it started: its version "
        "was frozen before the run started, no later version had been frozen, and the run completed. `false` for a run "
        "that has not completed, for a preview (a preview stays a preview after its version is frozen), and for a "
        "check of a version already superseded."
    )


class TestRunResponse(BaseModel):
    """A test run."""

    id: UUID
    status: JobStatus = Field(description=JOB_STATUS)
    test_suite_id: UUID | None = None
    table_group_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    external_url: str | None = None
    metadata: dict[str, Any] | None = None
    result: TestRunResult | None = None
    version: TestRunVersion | None = Field(default=None, description="Contracts only. The version the run checked.")


class TestResultItem(BaseModel):
    """The result of one test in a test run."""

    test_definition_id: UUID
    test_type: str = Field(
        description="The test type, given as its code, e.g. `Dupe_Rows`. `test_type_name` gives its name."
    )
    test_type_name: str | None = None
    schema_name: SchemaName
    table_name: str | None = None
    column_names: str | None = Field(
        default=None,
        description="The column or columns the test checks, as named in the test definition. `null` for a test of a "
        "whole table.",
    )
    result_status: ResultStatus | None = Field(
        default=None,
        description="`passed`, `failed` (failed at severity Fail), `warning` (failed at severity Warning), `error` "
        "(the test could not run), or `log` (recorded without passing or failing, at severity Log).",
    )
    result_measure: str | None = Field(
        default=None,
        description="The value the test measured, in its test type's unit of measure, e.g. a count of failing rows.",
    )
    threshold_value: str | None = Field(
        default=None, description="The threshold the measure was compared with at this run."
    )
    result_message: str | None = Field(
        default=None,
        description="A message describing the result, such as why the test failed or the error that stopped it.",
    )
    test_time: datetime | None = Field(default=None, description="When the test ran: the start of its test run.")
    disposition: Disposition = Field(
        description="How the result was triaged: `confirmed` (a relevant issue), `dismissed` (not relevant for this "
        "run), `muted`, or `no_decision` (not triaged yet)."
    )


class TestResultListResponse(BaseModel):
    """A page of test results."""

    items: list[TestResultItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


# --- Profiling Runs ---


class HygieneIssueCounts(BaseModel):
    """Counts of active hygiene issues by likelihood."""

    definite: int = 0
    likely: int = 0
    possible: int = 0


class PotentialPiiCounts(BaseModel):
    """Counts of active Potential PII findings by risk level."""

    high: int = 0
    moderate: int = 0


class IssueCounts(BaseModel):
    """A profiling run's findings: active hygiene issues by likelihood, active Potential PII findings by risk, and
    the number dismissed or muted.
    """

    hygiene_issues: HygieneIssueCounts = Field(description="Active hygiene issues, by likelihood.")
    potential_pii: PotentialPiiCounts = Field(description="Active Potential PII findings, by risk level.")
    dismissed: int = Field(default=0, description="Findings dismissed or muted, of either kind.")


_RUN_PROFILING_SCORE = (
    "The run's Profiling Score, from 0 to 100. `null` until it has been calculated after the run completes."
)
_TABLE_CT = "Tables the run profiled."
_COLUMN_CT = "Columns the run profiled."
_RECORD_CT = "Rows across the tables the run profiled."


class ProfilingRunResult(BaseModel):
    """A profiling run's results, present once the run completes."""

    score: float | None = Field(default=None, description=_RUN_PROFILING_SCORE)
    table_ct: int | None = Field(default=None, description=_TABLE_CT)
    column_ct: int | None = Field(default=None, description=_COLUMN_CT)
    record_ct: int | None = Field(default=None, description=_RECORD_CT)
    issue_counts: IssueCounts


class ProfilingRunResponse(BaseModel):
    """A profiling run."""

    id: UUID
    status: JobStatus = Field(description=JOB_STATUS)
    table_group_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: ProfilingRunResult | None = None


class ProfilingRunHistoryItem(BaseModel):
    """One profiling run in a table group's history."""

    job_execution_id: UUID
    table_group_id: UUID
    status: JobStatus = Field(description=JOB_STATUS)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    profiling_score: float | None = Field(default=None, description=_RUN_PROFILING_SCORE)
    table_ct: int | None = Field(default=None, description=_TABLE_CT)
    column_ct: int | None = Field(default=None, description=_COLUMN_CT)
    record_ct: int | None = Field(default=None, description=_RECORD_CT)
    data_point_ct: int | None = Field(
        default=None, description="Data points the run profiled: each column's row count, summed across columns."
    )
    error_message: str | None = Field(default=None, description=_ERROR_MESSAGE)
    issue_counts: IssueCounts


class ProfilingRunHistoryResponse(BaseModel):
    """A page of profiling runs, newest first."""

    items: list[ProfilingRunHistoryItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


_ISSUE_TYPE = "The issue type's ID, e.g. `1002`. `issue_type_name` gives its name."
_FINDING_DETAIL = (
    "What profiling found, e.g. the values or patterns involved. `[PII Redacted]` for a column flagged as PII when "
    "the caller cannot view PII."
)
_HYGIENE_DISPOSITION = (
    "How the finding was triaged: `confirmed` (the default for an untriaged finding), `dismissed` (not relevant for "
    "this run), or `muted` (no longer flagged for this column in later runs)."
)


class HygieneIssueItem(BaseModel):
    """One hygiene issue a profiling run found."""

    id: UUID
    issue_type: str = Field(description=_ISSUE_TYPE)
    issue_type_name: str
    schema_name: SchemaName
    table_name: str
    column_name: str
    likelihood: IssueLikelihood | None = Field(
        default=None,
        description="How strongly the issue indicates a data problem: `definite`, `likely`, or `possible` (a "
        "speculative finding that may be benign).",
    )
    impact_dimension: ImpactDimension | None = Field(
        default=None,
        description="The issue type's impact dimension: `reliability`, `conformance`, `regularity`, or `usability`. "
        "`null` when the issue type has none.",
    )
    detail: str = Field(description=_FINDING_DETAIL)
    disposition: HygieneDisposition = Field(description=_HYGIENE_DISPOSITION)


class HygieneIssueListResponse(BaseModel):
    """A page of hygiene issues."""

    items: list[HygieneIssueItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


class PotentialPiiItem(BaseModel):
    """One Potential PII finding from a profiling run."""

    id: UUID
    issue_type: str = Field(description=_ISSUE_TYPE)
    issue_type_name: str
    schema_name: SchemaName
    table_name: str
    column_name: str
    pii_risk: PiiRisk | None = Field(default=None, description=f"{PII_RISK_HIGH} or {PII_RISK_MODERATE}.")
    detail: str = Field(description=_FINDING_DETAIL)
    disposition: HygieneDisposition = Field(description=_HYGIENE_DISPOSITION)


class PotentialPiiListResponse(BaseModel):
    """A page of Potential PII findings."""

    items: list[PotentialPiiItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


# --- Scores ---


class ScoreBreakdownRow(BaseModel):
    """One group in a score breakdown."""

    value: str | None = Field(
        description="The group's value, e.g. `reliability` when grouped by `impact_dimension`, or `sales_db` when "
        "grouped by `data_source`. `null` for data in no group, e.g. an issue type with no `impact_dimension`.",
    )
    score: float | None = Field(
        description="The group's Total Score or CDE Score, as `score_type` selects, from 0 to 100. `null` when the "
        "group has no scored data points.",
    )
    impact: float = Field(
        description="How much of the score this group's affected data costs: its affected profiling data points as a "
        "percentage of all profiling data points, plus the same for test data points.",
    )


class ScoresResponse(BaseModel):
    """A project's scores. A score is `null` when the filtered data has no scored data points."""

    total: float | None = Field(
        description="The Total Score of the filtered data, from 0 to 100.",
    )
    cde: float | None = Field(
        description="The CDE Score: the Total Score of the critical data elements in the filtered data, from 0 to 100.",
    )
    profiling: float | None = Field(
        description="The Profiling Score: the part of the Total Score from hygiene issues, from 0 to 100.",
    )
    testing: float | None = Field(
        description="The Testing Score: the part of the Total Score from test results, from 0 to 100.",
    )
    breakdown: list[ScoreBreakdownRow] | None = Field(
        default=None,
        description="The groups of `group_by`, largest `impact` first. Absent when `group_by` is not given.",
    )


class ProfilingColumnItem(BaseModel):
    """One column's profile from a profiling run.

    `profiling_score`, `testing_score`, and `pii_flag` are the column's latest values in the data catalog, so a
    column profiled again after this run reports its latest scores and classification.
    """

    schema_name: SchemaName
    table_name: str
    column_name: str
    general_type: GeneralType | None = Field(
        default=None,
        description="The column's broad type as profiling sees it: `alpha` (text), `numeric`, `datetime` (date or "
        "timestamp), `boolean`, `time` (time of day), or `other`.",
    )
    functional_data_type: str | None = Field(
        default=None,
        description="What profiling infers the column holds, e.g. an email address, a phone number, or a "
        "transaction date.",
    )
    db_data_type: str | None = Field(default=None, description="The column's data type as the database declares it.")
    datatype_suggestion: str | None = Field(
        default=None,
        description="A data type that fits the values profiling found, which can be narrower than the declared one.",
    )
    pii_flag: PiiFlag | None = Field(
        default=None,
        description=f"The column's personally identifiable information (PII) classification: {PII_RISK_HIGH}, "
        f"{PII_RISK_MODERATE}, `low` (e.g. user IDs, routing numbers), or `manual` (flagged by hand, with no risk "
        "level). `null` when the column is not flagged.",
    )
    critical_data_element: bool = Field(
        default=False,
        description="Whether the column, or its table, is flagged as a critical data element (CDE).",
    )
    record_ct: int | None = Field(default=None, description="Rows in the table at this run.")
    null_value_ct: int | None = Field(default=None, description="Rows where the column is null.")
    distinct_value_ct: int | None = Field(default=None, description="Distinct non-null values in the column.")
    filled_value_ct: int | None = Field(
        default=None,
        description="Values that stand in for a blank, such as `N/A`, `unknown`, or a run of dashes.",
    )
    profiling_score: float | None = Field(
        default=None, description="The column's Profiling Score, from 0 to 100. `null` when not calculated."
    )
    testing_score: float | None = Field(
        default=None,
        description="The column's Testing Score, from 0 to 100, from the latest completed test runs of its table "
        "group's test suites. `null` when no test in those runs checks the column.",
    )
    issue_counts: IssueCounts


class ProfilingColumnListResponse(BaseModel):
    """A page of column profiles."""

    items: list[ProfilingColumnItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


# --- Errors ---


class ErrorDetail(BaseModel):
    """One error."""

    code: str = Field(description="A machine-readable error code, e.g. `unknown_test_type`.")
    detail: str = Field(description="What went wrong, in words.")


class ErrorBody(BaseModel):
    """The errors a request caused."""

    errors: list[ErrorDetail] = Field(description="One entry per problem found.")


class ErrorResponse(BaseModel):
    """An error response, with one entry per problem found."""

    detail: ErrorBody


# --- Test Definition Export/Import (wire types) ---


class ImportRequest(BaseModel):
    """A test definition document to import, and how to import it."""

    model_config = ConfigDict(extra="forbid")

    config: ImportConfig = Field(
        description="How the import treats matched, new, and absent test definitions, and whether it applies them."
    )
    payload: ImportPayload = Field(description="The document to import, in the form an export returns.")


class ImportStrictErrorBody(ErrorBody):
    """The errors that stopped a strict import, and the import as it would have applied."""

    import_result: ImportResponse = Field(description="The import as it would have applied. Nothing was written.")


class ImportStrictError(BaseModel):
    """The response when `apply_strict` would skip entries. Nothing is applied."""

    detail: ImportStrictErrorBody


# --- Test Generation ---


_REGENERATION_GROUPS = (
    "`tests` (tests from the latest profiling, locked tests kept), `profiling` (functional types, keys, formats, and "
    "profiled values), or `governance` (descriptions, tags, classification, and the critical data element, PII, and "
    "excluded data element flags, from the data catalog)."
)


class TestGenerationRequest(BaseModel):
    """Options for a test generation job. The body is optional."""

    model_config = ConfigDict(extra="forbid")

    generation_sets: list[str] | None = Field(
        default=None,
        description="Generation sets to generate tests from, by name, e.g. `Standard` or `Table Comparison`. Omit to "
        "use the test suite's stored generation sets, or `Standard` when it has none. A contract accepts only "
        "`Contract`, and generates from it when this is omitted.",
    )
    regenerate: list[RegenerationGroup] | None = Field(
        default=None,
        min_length=1,
        description=(
            f"Contracts only. What to regenerate; omit to refresh everything: {_REGENERATION_GROUPS} Replaces edits "
            "made to these in the contract. Columns and their types are always refreshed."
        ),
    )


class TestRunSubmittedResponse(JobSubmittedResponse):
    """A test run job just submitted. Follow it with `GET /jobs/{job_id}` using its `id`."""

    version: ContractVersion | None = Field(default=None, description="Contracts only. The version the run checks.")
    note: str | None = Field(
        default=None,
        description="Contracts only. Why the run will not count as the contract's status, judged from the version's "
        "state at submission.",
    )


class TestGenerationSubmittedResponse(JobSubmittedResponse):
    """A test generation job just submitted. Follow it with `GET /jobs/{job_id}` using its `id`."""

    version: ContractVersion | None = Field(
        default=None, description="Contracts only. The draft the job generates into."
    )
    regenerate: list[RegenerationGroup] | None = Field(
        default=None,
        description=f"Contracts only. The groups the job regenerates: {_REGENERATION_GROUPS}",
    )
    note: str | None = Field(
        default=None,
        description="Contracts only. What the job skips because the table group has not been profiled.",
    )


# --- Monitors ---


_MONITOR_ID = (
    "Reads the monitor's results from `GET /monitors/{monitor_id}/series`. `null` when the table has no monitor of "
    "this type."
)
_MONITOR_ANOMALIES = "Anomalies the monitor flagged in the lookback window."
_MONITOR_IS_TRAINING = (
    "Whether the monitor's latest run was still training, gathering results before it flags anomalies."
)
_MONITOR_IS_PENDING = "Whether the monitor has no results in the lookback window yet."
_LOOKBACK = "Monitor runs in the lookback window: the table group's `lookback_runs` setting."


class MonitorTypeSummary(BaseModel):
    """The state of a table's Freshness or Volume monitor."""

    monitor_id: UUID | None = Field(default=None, description=_MONITOR_ID)
    anomalies: int = Field(default=0, description=_MONITOR_ANOMALIES)
    is_training: bool | None = Field(
        default=None,
        description=f"{_MONITOR_IS_TRAINING} `null` when that run has no result for this monitor.",
    )
    is_pending: bool = Field(default=True, description=_MONITOR_IS_PENDING)


class SchemaMonitorSummary(BaseModel):
    """The state of a table's Schema monitor, with counts of the column changes it found."""

    monitor_id: UUID | None = Field(default=None, description=_MONITOR_ID)
    anomalies: int = Field(default=0, description="Schema changes flagged in the lookback window.")
    is_pending: bool = Field(
        default=True,
        description="Whether no monitor has results for the table in the lookback window. The Schema monitor records "
        "a result only when the schema changes.",
    )
    column_adds: int = Field(default=0, description="Columns added to the table in the lookback window.")
    column_drops: int = Field(default=0, description="Columns dropped from the table in the lookback window.")
    column_mods: int = Field(
        default=0, description="Columns whose data type or properties changed in the lookback window."
    )


class MetricMonitorSummary(BaseModel):
    """The state of one Metric monitor on a table."""

    monitor_id: UUID
    metric_name: str | None = Field(default=None, description="The name given to the metric.")
    anomalies: int = Field(default=0, description=_MONITOR_ANOMALIES)
    is_training: bool | None = Field(default=None, description=_MONITOR_IS_TRAINING)
    is_pending: bool = Field(default=True, description=_MONITOR_IS_PENDING)


class MonitorTableRow(BaseModel):
    """One table's monitors over the lookback window."""

    model_config = {"populate_by_name": True}

    table_name: str
    row_count: int | None = Field(
        default=None,
        description="Rows in the table at the latest monitor run, from its Volume monitor. `null` when that run has "
        "no Volume result for the table.",
    )
    previous_row_count: int | None = Field(
        default=None,
        description="Rows in the table at the start of the lookback window, from the Volume monitor. Compare with "
        "`row_count` for the change over the window.",
    )
    latest_update: datetime | None = Field(
        default=None,
        description="When the table was last updated, as estimated by the latest Freshness monitor run, in UTC. "
        "`null` when that run has no Freshness result for the table.",
    )
    table_state: TableState | None = Field(
        default=None,
        description="A structural change to the table in the lookback window: `added`, `dropped` (when the latest "
        "change dropped it), or `modified` (columns added, dropped, or changed). `null` when its structure did not "
        "change.",
    )
    freshness: MonitorTypeSummary
    volume: MonitorTypeSummary
    # JSON key is "schema"; the Python attr is "schema_" to avoid shadowing BaseModel.schema.
    schema_: SchemaMonitorSummary = Field(alias="schema")
    metrics: list[MetricMonitorSummary]


class MonitorTotals(BaseModel):
    """Totals across every monitored table in the table group."""

    lookback: int = Field(description=f"{_LOOKBACK} `0` before monitors have run.")
    lookback_start: datetime | None = Field(
        default=None,
        description="When the run just before the lookback window started: the baseline the window's changes are "
        "measured from, or the earliest run when there are fewer runs than the window. `null` before monitors have "
        "run.",
    )
    lookback_end: datetime | None = Field(
        default=None, description="When the latest monitor run started. `null` before monitors have run."
    )
    total_monitored_tables: int = Field(
        description="Tables with monitors in the table group, including tables dropped within the lookback window."
    )
    freshness_anomalies: int = Field(description="Freshness anomalies across all tables in the lookback window.")
    volume_anomalies: int = Field(description="Volume anomalies across all tables in the lookback window.")
    schema_anomalies: int = Field(description="Schema anomalies across all tables in the lookback window.")
    metric_anomalies: int = Field(description="Metric anomalies across all tables in the lookback window.")


class MonitorSummaryListResponse(BaseModel):
    """A page of monitored tables, with totals for the whole table group."""

    items: list[MonitorTableRow] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount
    totals: MonitorTotals


class MonitorSeriesResponse(BaseModel):
    """A monitor's results over its lookback window."""

    monitor_id: UUID
    type: MonitorType = Field(
        description="`freshness`, `volume`, `schema`, or `metric`. Decides the fields of each item in `points` and of "
        "`current_bands`."
    )
    threshold_mode: MonitorThresholdMode = Field(
        description="How the monitor's thresholds are set: `prediction_model` (forecast from its history), "
        "`historical_calculation` (calculated from its recent results, e.g. their minimum and maximum), `static` "
        "(fixed bounds), or `not_applicable` (a schema monitor, which has none)."
    )
    table_name: str
    column_name: str | None = Field(
        default=None, description="Metric monitors only. The metric's name. `null` for other monitor types."
    )
    lookback: int = Field(description=_LOOKBACK)
    is_training: bool = Field(description=_MONITOR_IS_TRAINING)
    current_bands: dict | None = None
    points: list[dict]


# --- Notifications ---

WebhookTypeLiteral = Literal["slack", "microsoft_teams", "generic"]

# ``destination_type`` is the polymorphic discriminator on the row and only ever
# holds ``email`` or ``webhook``; the three webhook subtypes live in
# ``config["webhook_type"]``. Advertising the subtypes on the list-filter query
# would let clients see them in the OpenAPI enum, but every such query would
# then return zero rows.
DestinationTypeFilter = Literal["email", "webhook"]

TestRunTrigger = Literal["always", "on_failures", "on_warnings", "on_changes"]
ProfilingRunTrigger = Literal["always", "on_changes"]
MonitorRunTrigger = Literal["on_anomalies"]


# ---------- Destination schemas ----------

_DESTINATION_NAME = "Display name, unique within the project regardless of case."
_RECIPIENTS = "Email addresses to send to, at least one."
_WEBHOOK_TYPE = "`slack`, `microsoft_teams`, or `generic`."
_WEBHOOK_URL = "HTTPS URL each notification is posted to. Stored encrypted, and returned only masked."
_AUTH_HEADER_NAME = "Generic webhooks only. Name of a header sent with each notification, e.g. `Authorization`."
_AUTH_HEADER_VALUE = (
    "Generic webhooks only. Value of the `auth_header_name` header. Stored encrypted and never returned."
)
_DESTINATION_TYPE = "`email` or `webhook`, matching the destination's type."
_RULE_COUNT = "Notification rules that send to this destination."
_ADDRESSING = (
    "Who the rule notifies: `inline` with its own `recipients`, or `destination` with the `destination_id` of a "
    "notification destination in the project."
)
_TEST_RUN_TRIGGER = (
    "When the rule sends: `always`, `on_failures` (the run has failed or errored tests), `on_warnings` (the run has "
    "warnings, failures, or errors), or `on_changes` (a test's result became failed, warning, or error since the "
    "previous run). A run that errors or is canceled sends for every trigger."
)
_PROFILING_RUN_TRIGGER = (
    "When the rule sends: `always` or `on_changes` (the run found hygiene issues the previous run did not). A run "
    "that errors or is canceled sends for both."
)
_RULE_EVENT = (
    "What the rule watches: `test_run`, `profiling_run`, `monitor_run`, or `score_drop`. Selects the rule's other "
    "fields."
)
_INLINE_KIND = "`inline`: the rule sends email to the addresses in `recipients`."
_DESTINATION_KIND = "`destination`: the rule sends to the saved destination `destination_id`."
_RULE_TEST_SUITE = "Only runs of this test suite, regular or contract. `null` covers every test suite in the project."
_RULE_TABLE_GROUP = "Only profiling runs of this table group. `null` covers every table group in the project."
_RULE_MONITOR_SUITE = "The monitor suite whose anomalies the rule reports."
_RULE_TABLE_NAME = "Only anomalies on this table. `null` covers every table in the table group."
_RULE_SCORECARD = "The scorecard whose scores the rule watches."
_TOTAL_THRESHOLD = "Send when the Total Score drops to below this value, from 0 to 100."
_CDE_THRESHOLD = "Send when the CDE Score drops to below this value, from 0 to 100."
_RULE_ENABLED = "Whether the rule sends notifications. `false` while the rule is paused."




class _NamedDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description=_DESTINATION_NAME)


class EmailDestinationCreate(_NamedDestination):
    """An email recipient list."""

    type: Literal["email"]
    recipients: list[str] = Field(min_length=1, description=_RECIPIENTS)


class WebhookDestinationCreate(_NamedDestination):
    """A webhook."""

    type: Literal["webhook"]
    webhook_type: WebhookTypeLiteral = Field(description=_WEBHOOK_TYPE)
    url: str = Field(description=_WEBHOOK_URL)
    auth_header_name: str | None = Field(default=None, description=_AUTH_HEADER_NAME)
    auth_header_value: str | None = Field(default=None, description=_AUTH_HEADER_VALUE)


_DestinationCreatePayload = Annotated[
    Annotated[EmailDestinationCreate, Tag("email")]
    | Annotated[WebhookDestinationCreate, Tag("webhook")],
    Discriminator("type"),
]


# FastAPI strips Annotated (and the Discriminator inside it) from a bare alias used
# as a Body annotation, which drops the discriminator from the generated schema and
# Pydantic's type-based routing. The RootModel wrapper keeps both; read the inner
# instance via .root.
class DestinationCreate(RootModel[_DestinationCreatePayload]):
    """An email recipient list or a webhook. `type` selects which."""


class EmailDestinationUpdate(BaseModel):
    """Fields to change on an email recipient list."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["email"] = Field(description=_DESTINATION_TYPE)
    name: str | None = Field(default=None, description=_DESTINATION_NAME)
    recipients: list[str] | None = Field(
        default=None, min_length=1, description=f"{_RECIPIENTS} Replaces the whole list."
    )


class WebhookDestinationUpdate(BaseModel):
    """Fields to change on a webhook."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["webhook"] = Field(description=_DESTINATION_TYPE)
    name: str | None = Field(default=None, description=_DESTINATION_NAME)
    webhook_type: WebhookTypeLiteral | None = Field(default=None, description=_WEBHOOK_TYPE)
    url: str | None = Field(default=None, description=_WEBHOOK_URL)
    auth_header_name: str | None = Field(default=None, description=f'{_AUTH_HEADER_NAME} Send `""` to clear it.')
    auth_header_value: str | None = Field(
        default=None, description=f'{_AUTH_HEADER_VALUE} Send `""` to clear it.'
    )


_DestinationUpdatePayload = Annotated[
    Annotated[EmailDestinationUpdate, Tag("email")]
    | Annotated[WebhookDestinationUpdate, Tag("webhook")],
    Discriminator("type"),
]


# Same RootModel wrapper rationale as DestinationCreate.
class DestinationUpdate(RootModel[_DestinationUpdatePayload]):
    """Fields to change on a destination. `type` must match the destination's type.

    A field sent as `null`, a body with nothing to change besides `type`, and unknown fields are
    rejected.
    """


class EmailDestinationResponse(BaseModel):
    """An email recipient list."""

    id: UUID
    type: Literal["email"] = "email"
    project_code: str
    name: str = Field(description=_DESTINATION_NAME)
    recipients: list[str] = Field(description=_RECIPIENTS)
    rule_count: int = Field(description=_RULE_COUNT)


class WebhookDestinationResponse(BaseModel):
    """A webhook."""

    id: UUID
    type: Literal["webhook"] = "webhook"
    project_code: str
    name: str = Field(description=_DESTINATION_NAME)
    webhook_type: WebhookTypeLiteral = Field(description=_WEBHOOK_TYPE)
    url_masked: str = Field(
        description="The webhook URL, masked after its first path segment, e.g. "
        "`https://hooks.slack.com/services/•••`."
    )
    auth_header_name: str | None = Field(default=None, description=_AUTH_HEADER_NAME)
    has_auth_header: bool = Field(description="Whether an `auth_header_value` is set.")
    rule_count: int = Field(description=_RULE_COUNT)


DestinationResponse = Annotated[
    Annotated[EmailDestinationResponse, Tag("email")]
    | Annotated[WebhookDestinationResponse, Tag("webhook")],
    Discriminator("type"),
]


class DestinationListResponse(BaseModel):
    """A page of notification destinations."""

    items: list[DestinationResponse] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


class DestinationDeleteResponse(BaseModel):
    """The deleted destination and how many rules were deleted with it."""

    id: UUID
    deleted_rule_count: int = Field(description="Notification rules deleted along with the destination.")


# ---------- Rule schemas ----------


class InlineAddressing(BaseModel):
    """Recipients listed on the rule itself."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["inline"] = Field(description=_INLINE_KIND)
    recipients: list[str] = Field(min_length=1, description=_RECIPIENTS)


class DestinationAddressing(BaseModel):
    """A notification destination in the project."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["destination"] = Field(description=_DESTINATION_KIND)
    destination_id: UUID


AddressingIn = Annotated[
    Annotated[InlineAddressing, Tag("inline")]
    | Annotated[DestinationAddressing, Tag("destination")],
    Discriminator("kind"),
]


class InlineAddressingOut(BaseModel):
    """Recipients listed on the rule itself."""

    kind: Literal["inline"] = Field(default="inline", description=_INLINE_KIND)
    recipients: list[str] = Field(description=_RECIPIENTS)


class DestinationAddressingOut(BaseModel):
    """A notification destination in the project."""

    kind: Literal["destination"] = Field(default="destination", description=_DESTINATION_KIND)
    destination_id: UUID
    destination_name: str | None = None
    destination_type: str | None = Field(default=None, description="`email` or `webhook`.")


AddressingOut = Annotated[
    Annotated[InlineAddressingOut, Tag("inline")]
    | Annotated[DestinationAddressingOut, Tag("destination")],
    Discriminator("kind"),
]


class TestRunRuleCreate(BaseModel):
    """A rule that sends after test runs."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["test_run"] = Field(description=_RULE_EVENT)
    addressing: AddressingIn = Field(description=_ADDRESSING)
    test_suite_id: UUID | None = Field(default=None, description=_RULE_TEST_SUITE)
    trigger: TestRunTrigger = Field(default="on_failures", description=_TEST_RUN_TRIGGER)


class ProfilingRunRuleCreate(BaseModel):
    """A rule that sends after profiling runs."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["profiling_run"] = Field(description=_RULE_EVENT)
    addressing: AddressingIn = Field(description=_ADDRESSING)
    table_group_id: UUID | None = Field(default=None, description=_RULE_TABLE_GROUP)
    trigger: ProfilingRunTrigger = Field(default="on_changes", description=_PROFILING_RUN_TRIGGER)


# The table group is derived from the suite rather than accepted: the suite-to-table-group
# link is 1:1, so a supplied value could only agree or conflict, and the delivery path
# resolves the table group from the suite regardless.
class MonitorRunRuleCreate(BaseModel):
    """A rule that sends when monitors find anomalies. It covers the monitor suite's table group."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["monitor_run"] = Field(description=_RULE_EVENT)
    addressing: AddressingIn = Field(description=_ADDRESSING)
    test_suite_id: UUID = Field(description=_RULE_MONITOR_SUITE)
    table_name: str | None = Field(default=None, description=_RULE_TABLE_NAME)


class ScoreDropRuleCreate(BaseModel):
    """A rule that sends when a scorecard's score drops below a threshold. Set at least one of `total_threshold`
    and `cde_threshold`.
    """

    model_config = ConfigDict(extra="forbid")

    event: Literal["score_drop"] = Field(description=_RULE_EVENT)
    addressing: AddressingIn = Field(description=_ADDRESSING)
    score_definition_id: UUID = Field(description=_RULE_SCORECARD)
    total_threshold: float | None = Field(default=None, description=_TOTAL_THRESHOLD)
    cde_threshold: float | None = Field(default=None, description=_CDE_THRESHOLD)


_RuleCreatePayload = Annotated[
    Annotated[TestRunRuleCreate, Tag("test_run")]
    | Annotated[ProfilingRunRuleCreate, Tag("profiling_run")]
    | Annotated[MonitorRunRuleCreate, Tag("monitor_run")]
    | Annotated[ScoreDropRuleCreate, Tag("score_drop")],
    Discriminator("event"),
]


# Same RootModel wrapper rationale as DestinationCreate.
class RuleCreate(RootModel[_RuleCreatePayload]):
    """A notification rule. `event` selects which scope and trigger fields apply."""


class RuleUpdate(BaseModel):
    """Fields to change on a rule. The event and scope cannot be changed.

    Optional fields on score-drop and monitor-run rules are cleared with their `clear_*` flag.
    A field sent as `null`, a field sent together with its `clear_*` flag, a body with nothing to
    change, and unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = Field(default=None, description="`false` pauses the rule, `true` resumes it.")
    addressing: AddressingIn | None = Field(default=None, description=_ADDRESSING)
    trigger: str | None = Field(
        default=None,
        description="The rule's trigger: `always`, `on_failures`, `on_warnings`, or `on_changes` for a test-run rule; "
        "`always` or `on_changes` for a profiling-run rule; `on_anomalies` for a monitor-run rule. Score-drop rules "
        "have none.",
    )
    total_threshold: float | None = Field(default=None, description=f"Score-drop rules only. {_TOTAL_THRESHOLD}")
    cde_threshold: float | None = Field(default=None, description=f"Score-drop rules only. {_CDE_THRESHOLD}")
    table_name: str | None = Field(default=None, description=f"Monitor-run rules only. {_RULE_TABLE_NAME}")
    clear_total_threshold: bool = Field(
        default=False,
        description="Score-drop rules only. Send `true` to clear the Total Score threshold. At least one threshold "
        "must stay set.",
    )
    clear_cde_threshold: bool = Field(
        default=False,
        description="Score-drop rules only. Send `true` to clear the CDE Score threshold. At least one threshold "
        "must stay set.",
    )
    clear_table_name: bool = Field(
        default=False,
        description="Monitor-run rules only. Send `true` to clear the table filter, so the rule covers every table "
        "in the table group.",
    )


class _RuleResponseBase(BaseModel):
    id: UUID
    project_code: str
    enabled: bool = Field(description=_RULE_ENABLED)
    addressing: AddressingOut = Field(description=_ADDRESSING)


class TestRunRuleResponse(_RuleResponseBase):
    """A rule that sends after test runs."""

    event: Literal["test_run"] = Field(default="test_run", description=_RULE_EVENT)
    test_suite_id: UUID | None = Field(default=None, description=_RULE_TEST_SUITE)
    trigger: TestRunTrigger = Field(description=_TEST_RUN_TRIGGER)


class ProfilingRunRuleResponse(_RuleResponseBase):
    """A rule that sends after profiling runs."""

    event: Literal["profiling_run"] = Field(default="profiling_run", description=_RULE_EVENT)
    table_group_id: UUID | None = Field(default=None, description=_RULE_TABLE_GROUP)
    trigger: ProfilingRunTrigger = Field(description=_PROFILING_RUN_TRIGGER)


class MonitorRunRuleResponse(_RuleResponseBase):
    """A rule that sends when monitors find anomalies."""

    event: Literal["monitor_run"] = Field(default="monitor_run", description=_RULE_EVENT)
    test_suite_id: UUID = Field(description=_RULE_MONITOR_SUITE)
    table_group_id: UUID = Field(description="The monitor suite's table group.")
    trigger: MonitorRunTrigger = Field(
        default="on_anomalies", description="`on_anomalies`: the rule sends when a monitor run flags an anomaly."
    )
    table_name: str | None = Field(default=None, description=_RULE_TABLE_NAME)


class ScoreDropRuleResponse(_RuleResponseBase):
    """A rule that sends when a scorecard's score drops below a threshold."""

    event: Literal["score_drop"] = Field(default="score_drop", description=_RULE_EVENT)
    score_definition_id: UUID = Field(description=_RULE_SCORECARD)
    total_threshold: float | None = Field(default=None, description=_TOTAL_THRESHOLD)
    cde_threshold: float | None = Field(default=None, description=_CDE_THRESHOLD)


RuleResponse = Annotated[
    Annotated[TestRunRuleResponse, Tag("test_run")]
    | Annotated[ProfilingRunRuleResponse, Tag("profiling_run")]
    | Annotated[MonitorRunRuleResponse, Tag("monitor_run")]
    | Annotated[ScoreDropRuleResponse, Tag("score_drop")],
    Discriminator("event"),
]


class RuleListResponse(BaseModel):
    """A page of notification rules."""

    items: list[RuleResponse] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


# --- Connections ---


class ConnectionItem(BaseModel):
    """One connection in a project listing."""

    connection_id: int
    connection_name: str
    project_code: str
    connection_type: ConnectionType = Field(
        description="The connection's type: a database, such as Snowflake, or a file data source, such as Amazon S3."
    )
    table_group_count: int = Field(description="Table groups on the connection.")


class ConnectionListResponse(BaseModel):
    """A page of connections."""

    items: list[ConnectionItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


class ConnectionResponse(BaseModel):
    """A connection's configuration.

    Connection parameters vary by connection type, so they are grouped under
    `settings` rather than given fixed top-level fields: a Snowflake connection
    carries `host` / `database` / `warehouse` / `username`, while a
    Salesforce Data 360 connection carries `login_url` / `username` /
    `consumer_key`, and an Amazon S3 connection carries `base_uri` / `region`. Keys
    are stable per connection type and authentication method, and are named for what the
    data source calls each value.

    Credentials are never included — no password, private key, token, or
    service-account key.
    """

    connection_id: int
    connection_name: str
    project_code: str
    connection_type: ConnectionType = Field(
        description="The connection's type: a database, such as Snowflake, or a file data source, such as Amazon S3."
    )
    authentication: AuthenticationMethod | None = Field(
        default=None,
        description=(
            "How the connection authenticates to its data source. `null` for a connection type that "
            "takes no credentials, such as Local Files. One of `password`, `key_pair`, `access_token`, "
            "`service_principal`, `managed_identity`, `jwt_bearer`, `client_credentials`, `service_account`, "
            "`access_keys`, `iam_role`, `account_key`, or `public`. `public` reads without credentials."
        ),
    )
    max_threads: int | None = Field(default=None, description="Queries TestGen runs against the connection at a time.")
    max_expression_length: int | None = Field(
        default=None, description="Maximum character length of a generated query expression."
    )
    settings: dict[str, str] = Field(
        description="Connection parameters for this connection type, excluding credentials."
    )


# --- Table Groups ---


class TableGroupItem(BaseModel):
    """One table group in a project listing, with its size and latest activity."""

    table_group_id: UUID
    table_group_name: str
    schema_name: str | None = Field(
        default=None,
        description="Database connections only. The schema that holds the tables, or the data space on Salesforce "
        "Data 360. `null` on a file connection.",
    )
    project_code: str
    connection_id: int
    connection_name: str | None = None
    table_count: int = Field(description="Tables in the table group's data catalog.")
    column_count: int | None = Field(
        default=None, description="Columns across those tables. `null` when the catalog is empty."
    )
    row_count: int | None = Field(
        default=None,
        description="Rows across those tables, approximate where the exact count is not known. `null` when the "
        "catalog is empty.",
    )
    last_profiled_at: datetime | None = None
    last_tested_at: datetime | None = None
    profiling_score: float | None = Field(
        default=None,
        description="The table group's Profiling Score, from 0 to 100, from its latest profiling. `null` before it has "
        "been profiled.",
    )
    testing_score: float | None = Field(
        default=None,
        description="The table group's Testing Score, from 0 to 100, from its latest test runs. `null` before it has "
        "been tested.",
    )
    quality_score: float | None = Field(
        default=None,
        description="The table group's Total Score, from 0 to 100, which combines its Profiling Score and Testing "
        "Score, or is whichever of the two exists. `null` when neither does.",
    )


class TableGroupListResponse(BaseModel):
    """A page of table groups."""

    items: list[TableGroupItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


class CatalogTags(BaseModel):
    """Labels for grouping and filtering the Quality Score breakdown.

    They describe a dataset's origin and ownership and do not affect profiling or
    test execution.
    """

    model_config = ConfigDict(extra="forbid")

    data_source: str | None = None
    source_system: str | None = None
    source_process: str | None = None
    data_location: str | None = None
    business_domain: str | None = None
    stakeholder_group: str | None = None
    transform_level: str | None = None
    data_product: str | None = None
    data_classification: str | None = None


class FileDeclaration(FileDeclarationShape):
    """One table on a file connection, named by the path its rows come from."""


class FileDeclarationCreate(FileDeclarationSpec):
    """One table to declare on a file connection, named by the path its rows come from.

    Unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    header: StrictBool | None = Field(default=None, description=HEADER_DESCRIPTION)


# Descriptions shared by the table group response and requests; the requests each add what omitting or clearing a
# field does.
_TG_DESCRIPTIONS = {
    "table_group_name": "Unique within the project; 3 to 40 characters.",
    "schema_name": "The schema that holds the tables, or the data space on Salesforce Data 360.",
    "file_declarations": "The table group's tables, one per file or pattern.",
    "table_set": "Database connections only. Table names to restrict the group to.",
    "include_masks": (
        "Database connections only. Table names or patterns a table must match to be included. `%` matches any"
        " characters; every other character, `_` included, matches itself."
    ),
    "exclude_masks": (
        "Database connections only. Table names or patterns that exclude a matching table, including one named in"
        " `table_set`. `%` matches any characters; every other character, `_` included, matches itself."
    ),
    "profile_id_column_mask": (
        "Column name pattern marking ID columns, not case-sensitive. `%` matches any characters; every other"
        " character, `_` included, matches itself."
    ),
    "profile_sk_column_mask": (
        "Column name pattern marking surrogate key columns, not case-sensitive. `%` matches any characters; every"
        " other character, `_` included, matches itself."
    ),
    "profile_use_sampling": (
        "Compute pattern and character analysis, and the list of frequent values, from a sample of each table's"
        " rows. Record counts, distinct values, minimums, maximums, and average lengths and values always cover"
        " the full table."
    ),
    "profile_sample_percent": "Percent of rows to sample, from 1 to 100, unless that falls below the sample minimum.",
    "profile_sample_min_count": "Minimum number of rows in any sample, when the table has that many.",
    "profiling_delay_days": "Days to wait before new profiling results are used to generate tests.",
    "profile_flag_cdes": "Flag likely critical data elements during profiling.",
    "profile_flag_pii": "Flag columns that likely hold personally identifiable information during profiling.",
    "profile_exclude_xde": "Skip columns marked as excluded data elements when profiling.",
    "profile_table_comparison": (
        "Collect value hashes during profiling, which Table Comparison test generation needs for tests that"
        " detect changed, moved, or swapped values. Adds profiling time. Has no effect on SAP HANA and"
        " Salesforce Data 360 connections."
    ),
    "include_in_dashboard": "Show the table group on the project dashboard.",
}


class TableGroupResponse(BaseModel):
    """A table group's full configuration."""

    table_group_id: UUID
    table_group_name: str
    schema_name: str | None = Field(
        default=None,
        description="Database connections only. The schema that holds the tables, or the data space on Salesforce "
        "Data 360. `null` on a file connection.",
    )
    project_code: str
    connection_id: int
    default_test_suite_id: UUID | None = None
    description: str | None = None

    table_set: list[str] = Field(
        default_factory=list,
        description="Database connections only. Table names the group is restricted to. Empty when the group is "
        "defined by masks alone, and on a file connection.",
    )
    include_masks: list[str] = Field(default_factory=list, description=_TG_DESCRIPTIONS["include_masks"])
    exclude_masks: list[str] = Field(default_factory=list, description=_TG_DESCRIPTIONS["exclude_masks"])
    file_declarations: list[FileDeclaration] | None = Field(
        default=None,
        description="File connections only. The table group's tables, one per file or pattern. `null` on a database "
        "connection.",
    )
    profile_id_column_mask: str | None = Field(default=None, description=_TG_DESCRIPTIONS["profile_id_column_mask"])
    profile_sk_column_mask: str | None = Field(default=None, description=_TG_DESCRIPTIONS["profile_sk_column_mask"])

    profile_use_sampling: bool = Field(description=_TG_DESCRIPTIONS["profile_use_sampling"])
    profile_sample_percent: int | None = Field(default=None, description=_TG_DESCRIPTIONS["profile_sample_percent"])
    profile_sample_min_count: int | None = Field(
        default=None, description=_TG_DESCRIPTIONS["profile_sample_min_count"]
    )
    profiling_delay_days: int | None = Field(default=None, description=_TG_DESCRIPTIONS["profiling_delay_days"])
    profile_flag_cdes: bool = Field(description=_TG_DESCRIPTIONS["profile_flag_cdes"])
    profile_flag_pii: bool = Field(description=_TG_DESCRIPTIONS["profile_flag_pii"])
    profile_exclude_xde: bool = Field(description=_TG_DESCRIPTIONS["profile_exclude_xde"])
    profile_table_comparison: bool = Field(description=_TG_DESCRIPTIONS["profile_table_comparison"])
    include_in_dashboard: bool = Field(description=_TG_DESCRIPTIONS["include_in_dashboard"])

    catalog_tags: CatalogTags


class TableGroupUpdateResponse(TableGroupResponse):
    """The table group as it now stands, plus what a schema change did."""

    schema_change: TableGroupSchemaChange | None = None
    catalog_error: str | None = Field(
        default=None,
        description=(
            "Set when the update changed which tables belong to the table group and the data catalog could not "
            "be rewritten: the target could not be read or written, or, without a schema move, no table matches "
            "the table group's filters. The update is saved, and the catalog keeps the tables it had before until "
            "the table group is profiled or tested."
        ),
    )


class TableGroupCreateResponse(TableGroupResponse):
    """The created table group, plus whether its data catalog could be read from the target."""

    catalog_error: str | None = Field(
        default=None,
        description=(
            "Set when the data catalog could not be read from the target. The table group is created, "
            "and its catalog stays empty until the table group is profiled or tested."
        ),
    )


_TABLE_GROUP_DEFAULTS = table_group_defaults()

_REPLACES_LIST = "Replaces the whole list. Send every entry to keep, not only the ones that changed."


def _create_setting(name: str) -> Any:
    return Field(default=_TABLE_GROUP_DEFAULTS[name], description=_TG_DESCRIPTIONS[name])


class TableGroupCreate(BaseModel):
    """A table group to create on a connection.

    Omitted optional fields, and fields sent as `null`, take the default shown.
    Unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    table_group_name: str = Field(description=_TG_DESCRIPTIONS["table_group_name"])
    schema_name: str | None = Field(
        default=None,
        description=f"Database connections only, and required there. {_TG_DESCRIPTIONS['schema_name']}",
    )
    file_declarations: list[FileDeclarationCreate] | None = Field(
        default=None,
        description=f"File connections only, and required there. {_TG_DESCRIPTIONS['file_declarations']}",
    )
    description: str | None = None

    table_set: list[str] | None = Field(
        default=None,
        description=f"{_TG_DESCRIPTIONS['table_set']} Omit to define the group by masks alone.",
    )
    include_masks: list[str] | None = Field(
        default=None,
        description=f"{_TG_DESCRIPTIONS['include_masks']} Omit to use the installation's default include mask.",
    )
    exclude_masks: list[str] | None = Field(
        default=None,
        description=(
            f"{_TG_DESCRIPTIONS['exclude_masks']} Omit to use the installation's default exclude mask; send an empty"
            " list to exclude nothing."
        ),
    )
    profile_id_column_mask: str | None = _create_setting("profile_id_column_mask")
    profile_sk_column_mask: str | None = _create_setting("profile_sk_column_mask")

    profile_use_sampling: StrictBool | None = _create_setting("profile_use_sampling")
    profile_sample_percent: StrictInt | None = _create_setting("profile_sample_percent")
    profile_sample_min_count: StrictInt | None = _create_setting("profile_sample_min_count")
    profiling_delay_days: StrictInt | None = _create_setting("profiling_delay_days")
    profile_flag_cdes: StrictBool | None = _create_setting("profile_flag_cdes")
    profile_flag_pii: StrictBool | None = _create_setting("profile_flag_pii")
    profile_exclude_xde: StrictBool | None = _create_setting("profile_exclude_xde")
    profile_table_comparison: StrictBool | None = _create_setting("profile_table_comparison")
    include_in_dashboard: StrictBool | None = _create_setting("include_in_dashboard")

    catalog_tags: CatalogTags | None = None
    add_scorecard: StrictBool = Field(
        default=True, description="Also create a scorecard for the table group."
    )


def _update_field(name: str, then: str = "") -> Any:
    return Field(default=None, description=f"{_TG_DESCRIPTIONS[name]} {then}".strip())


class TableGroupUpdateRequest(BaseModel):
    """Fields to change on a table group. Omitted fields are left unchanged.

    Clear a field by sending it empty: `""` for text, `[]` for a list. A field sent as `null`, a catalog
    tag sent as `null`, a body with nothing to change, and unknown fields are rejected. The connection
    and project cannot be changed.
    """

    model_config = ConfigDict(extra="forbid")

    table_group_name: str | None = _update_field("table_group_name")
    schema_name: str | None = Field(
        default=None,
        pattern=SCHEMA_NAME_PATTERN,
        max_length=SCHEMA_NAME_MAX_LENGTH,
        description=(
            f"Database connections only. {_TG_DESCRIPTIONS['schema_name']} When it changes, profiling, test "
            "generation, monitors, and test runs read the new schema, and tests keep their history. Referential "
            "tests keep the schema of their second table."
        ),
    )
    file_declarations: list[FileDeclarationCreate] | None = Field(
        default=None,
        description=f"File connections only. {_TG_DESCRIPTIONS['file_declarations']} {_REPLACES_LIST}",
    )
    description: str | None = Field(default=None, description='Send `""` to clear it.')

    table_set: list[str] | None = _update_field(
        "table_set", f"{_REPLACES_LIST} Send `[]` to define the group by masks alone."
    )
    include_masks: list[str] | None = _update_field(
        "include_masks", f"{_REPLACES_LIST} Send `[]` to include every table in the schema."
    )
    exclude_masks: list[str] | None = _update_field(
        "exclude_masks", f"{_REPLACES_LIST} Send `[]` to exclude nothing."
    )
    profile_id_column_mask: str | None = _update_field("profile_id_column_mask", 'Send `""` to mark no columns.')
    profile_sk_column_mask: str | None = _update_field("profile_sk_column_mask", 'Send `""` to mark no columns.')

    profile_use_sampling: StrictBool | None = _update_field("profile_use_sampling")
    profile_sample_percent: StrictInt | None = _update_field("profile_sample_percent")
    profile_sample_min_count: StrictInt | None = _update_field("profile_sample_min_count")
    profiling_delay_days: StrictInt | None = _update_field("profiling_delay_days")
    profile_flag_cdes: StrictBool | None = _update_field("profile_flag_cdes")
    profile_flag_pii: StrictBool | None = _update_field(
        "profile_flag_pii", "Changing it requires permission to view PII."
    )
    profile_exclude_xde: StrictBool | None = _update_field("profile_exclude_xde")
    profile_table_comparison: StrictBool | None = _update_field("profile_table_comparison")
    include_in_dashboard: StrictBool | None = _update_field("include_in_dashboard")

    catalog_tags: CatalogTags | None = Field(
        default=None,
        description='Merged tag by tag: a tag that is omitted is left unchanged. Send a tag as `""` to clear it.',
    )


# --- Test Suites ---


_EXCLUDE_FROM_SCORING = "Leave the suite's test results out of scoring."
_DEACTIVATE_INVALID_TESTS = (
    "Deactivate tests that fail validation at the start of a run: a missing table or column, or a column type the "
    "test does not apply to."
)
_EXPORT_TO_OBSERVABILITY = "Export the suite's test results to DataOps Observability."
_COMPONENT_KEY = "Component identifier in DataOps Observability."
_COMPONENT_TYPE = "Component type in DataOps Observability."
_COMPONENT_NAME = "Component name in DataOps Observability."
_DEFAULT_SEVERITY = (
    "Severity for the suite's tests that set none of their own: `fail` reports a failing test as failed, `warning` "
    "as a warning, and `log` records its result without passing or failing."
)


class TestSuiteLatestRun(BaseModel):
    """The test suite's last completed test run."""

    job_execution_id: UUID = Field(description="The run's job ID, for `GET /test-runs/{job_id}`.")
    started_at: datetime | None = None
    test_count: int | None = Field(default=None, description="Tests the run executed.")
    result_counts: ResultCounts


class TestSuiteItem(BaseModel):
    """One test suite in a project listing, regular or contract, with its test count and last completed run."""

    test_suite_id: UUID
    test_suite_name: str
    project_code: str
    connection_id: int
    table_group_id: UUID
    table_group_name: str | None = None
    description: str | None = None
    suite_type: TestSuiteTypeField
    test_count: int = Field(
        description="Test definitions in the suite. For a contract, those of its draft, else of its active version."
    )
    active_version: int | None = Field(
        default=None,
        description="Contracts only. The number of the active version, the agreement in force. `null` when no "
        "version has been frozen.",
    )
    draft_version: int | None = Field(
        default=None, description="Contracts only. The number of the draft. `null` when the contract has no draft."
    )
    latest_run: TestSuiteLatestRun | None = Field(
        default=None,
        description="The last completed test run. `null` when the suite has never completed a run. For a contract, "
        "the last completed run that checked the version active when the run finished.",
    )


class TestSuiteListResponse(BaseModel):
    """A page of test suites, contracts included."""

    items: list[TestSuiteItem] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


class ContractActiveVersion(BaseModel):
    """The contract's active version: the highest frozen version, and so the agreement in force."""

    number: int = Field(description=VERSION_NUMBER)
    label: str | None = Field(default=None, description="A name for the version. `null` when it has none.")
    frozen_at: datetime = Field(description="When the version was frozen.")


class ContractRun(BaseModel):
    """A test run of the contract's active version."""

    job_execution_id: UUID = Field(description="The run's job ID, for `GET /test-runs/{job_id}`.")
    status: JobStatus = Field(description=JOB_STATUS)


class ContractVerification(BaseModel):
    """The latest completed run of the active version that started after the version was frozen."""

    job_execution_id: UUID = Field(description="The run's job ID, for `GET /test-runs/{job_id}`.")
    result: ResultStatus = Field(
        description="The run's outcome by its worst result: `failed`, else `error`, else `warning`, else `passed`."
    )
    started_at: datetime | None = None
    test_count: int | None = Field(default=None, description="Tests the run executed.")
    result_counts: ResultCounts


class ContractStatusResponse(BaseModel):
    """A contract's versions and the latest run that verified the agreement in force."""

    active_version: ContractActiveVersion | None = Field(
        default=None, description="`null` when no version has been frozen."
    )
    draft_version: int | None = Field(default=None, description="The draft's number. `null` when there is no draft.")
    tests_counted_from: int | None = Field(
        default=None,
        description="The version the test count in the test-suite list reflects: the draft, else the active "
        "version.",
    )
    latest_verification: ContractVerification | None = Field(
        default=None, description="`null` when the active version has no completed run since it was frozen."
    )
    incomplete_run: ContractRun | None = Field(
        default=None,
        description="The latest run of the active version, when it has not completed. A completed verification "
        "before it, if any, is in `latest_verification`.",
    )
    verification_unavailable: VerificationUnavailable | None = Field(
        default=None,
        description="When `latest_verification` is `null`, why: `nothing_frozen` (runs of the draft are previews), "
        "`not_run_since_frozen`, or `latest_run_incomplete` (the active version's latest run did not complete, and "
        "no earlier run did).",
    )


class TestSuiteResponse(BaseModel):
    """A test suite's configuration."""

    test_suite_id: UUID
    test_suite_name: str
    suite_type: TestSuiteTypeField
    project_code: str
    connection_id: int
    table_group_id: UUID
    description: str | None = None
    default_severity: DefaultSeverity | None = Field(
        default=None,
        description=f"{_DEFAULT_SEVERITY} `null` means each test takes its test type's severity.",
    )
    exclude_from_quality_score: bool = Field(description=_EXCLUDE_FROM_SCORING)
    deactivate_invalid_tests: bool = Field(description=_DEACTIVATE_INVALID_TESTS)
    export_to_observability: bool = Field(description=_EXPORT_TO_OBSERVABILITY)
    component_key: str | None = Field(default=None, description=_COMPONENT_KEY)
    component_type: str | None = Field(default=None, description=_COMPONENT_TYPE)
    component_name: str | None = Field(default=None, description=_COMPONENT_NAME)
    generation_sets: list[str] = Field(
        default_factory=list,
        description="Generation sets test generation uses for the suite. Empty means `Standard`.",
    )
    is_default: bool = Field(
        description="Whether this is its table group's default test suite, which the table group's first "
        "profiling run generates tests into."
    )
    contract: ContractStatusResponse | None = Field(
        default=None, description="Contracts only. Its versions and its latest verification."
    )


class ContractGeneration(BaseModel):
    """What generating a contract's tables did."""

    profiled: bool = Field(description="Whether the table group had been profiled.")
    tables_declared: list[str] = Field(description="The tables the contract declares.")
    tables_not_in_catalog: list[str] = Field(
        description="Declared tables the data catalog holds no columns for. Their schema is empty."
    )
    tables_not_profiled: list[str] = Field(
        description="Declared tables profiling has no results for. Their metadata comes from the data catalog "
        "alone and they have no tests besides schema conformance. Profile the table group, then regenerate the "
        "contract.",
    )
    quality_test_count: int = Field(description="Tests the contract holds, schema conformance tests aside.")


class ContractCustomServer(BaseModel):
    """Why the contract's server entry uses the custom type."""

    server_type: str | None = Field(
        description="The standard server type the connection maps to. `null` when it maps to none."
    )
    missing_fields: list[str] = Field(
        description="Fields `server_type` requires that the connection does not supply."
    )


class TestSuiteCreatedResponse(TestSuiteResponse):
    """A test suite just created, regular or contract."""

    generation: ContractGeneration | None = Field(
        default=None,
        description="Contracts created with `table_names` only. `null` when generation failed; see "
        "`generation_failed`.",
    )
    generation_failed: bool | None = Field(
        default=None,
        description="Contracts only. Whether generating the contract's tables failed. The contract is kept; "
        "submit test generation for it to retry.",
    )
    custom_server: ContractCustomServer | None = Field(
        default=None,
        description="Contracts only. Present when the contract's server entry uses the custom type, because the "
        "connection type maps to no standard server type or the connection does not supply the fields it requires.",
    )


class TestSuiteCreate(BaseModel):
    """A test suite to create under a table group.

    Omitted optional fields, and fields sent as `null`, take the default shown.
    Unknown fields are rejected. Test suite names need not be unique, so repeating a
    create makes a second suite with the same name.
    """

    model_config = ConfigDict(extra="forbid")

    test_suite_name: str = Field(description="Up to 200 characters.")
    suite_type: TestSuiteType = Field(
        default=TestSuiteType.regular,  # type: ignore[attr-defined]
        description="`regular` for a test suite, or `contract` for a data contract.",
    )
    table_names: list[str] | None = Field(
        default=None,
        description="Contracts only. Tables of the table group the contract declares. The contract is generated "
        "for them before the response returns. Omit to create the contract with no tables declared.",
    )
    description: str | None = None
    default_severity: DefaultSeverity | None = Field(
        default=None,
        description=f"{_DEFAULT_SEVERITY} Omit to have each test take its test type's severity.",
    )
    exclude_from_quality_score: StrictBool = Field(default=False, description=_EXCLUDE_FROM_SCORING)
    deactivate_invalid_tests: StrictBool = Field(default=False, description=_DEACTIVATE_INVALID_TESTS)
    export_to_observability: StrictBool = Field(default=False, description=_EXPORT_TO_OBSERVABILITY)
    component_key: str | None = Field(default=None, description=_COMPONENT_KEY)
    component_type: str | None = Field(default="dataset", description=_COMPONENT_TYPE)
    component_name: str | None = Field(default=None, description=_COMPONENT_NAME)
    generation_sets: list[str] | None = Field(
        default=None,
        description="Generation sets test generation uses for the suite, from those TestGen defines. "
        "Omit to use `Standard`.",
    )
    set_as_default: StrictBool = Field(
        default=False,
        description="Make this the table group's default test suite, replacing any other. The table group's "
        "first profiling run then generates tests into it; a table group that has already been profiled "
        "does not.",
    )

    @field_validator(
        "suite_type",
        "component_type",
        "exclude_from_quality_score",
        "deactivate_invalid_tests",
        "export_to_observability",
        "set_as_default",
        mode="before",
    )
    @classmethod
    def _null_takes_the_default(cls, value: Any, info: ValidationInfo) -> Any:
        return cls.model_fields[info.field_name].default if value is None else value


# --- Schedules ---


_TIMEZONE = "IANA timezone the expression is read in, e.g. `America/New_York`."


class ScheduleCreate(BaseModel):
    """A recurring schedule. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    cron_expression: str = Field(
        description="Five-field cron expression (minute, hour, day of month, month, day of week), "
        "e.g. `0 3 * * *` for every day at 3:00.",
    )
    timezone: str = Field(default="UTC", description=_TIMEZONE)


class ScheduleResponse(BaseModel):
    """A recurring profiling or test run schedule."""

    schedule_id: UUID
    kind: ScheduleKind = Field(description=f"{SCHEDULE_KIND_VALUES}.")
    project_code: str
    table_group_id: UUID | None = Field(
        default=None, description="The table group a profiling schedule profiles. `null` for a test run schedule."
    )
    test_suite_id: UUID | None = Field(
        default=None, description="The test suite a test run schedule runs. `null` for a profiling schedule."
    )
    cron_expression: str = Field(description="The expression as stored, in canonical form.")
    timezone: str = Field(description=_TIMEZONE)
    description: str | None = Field(default=None, description="The expression in words, e.g. `At 03:00`.")
    active: bool = Field(description="Whether the schedule runs. `false` while it is paused.")
    next_run_at: datetime | None = Field(
        default=None, description="When the schedule next starts a job, in UTC. `null` while it is paused."
    )


class ScheduleListResponse(BaseModel):
    """A page of schedules."""

    items: list[ScheduleResponse] = Field(description=PAGE_ITEMS)
    page: PageNumber
    limit: PageLimit
    total: TotalCount


# --- Monitoring ---

_LOOKBACK_RUNS = "Monitor runs the lookback window covers, from 1 to 200. Does not affect detection."
_REGENERATE_FRESHNESS = "Reconfigure Freshness monitors from each new profiling run."
_MIN_TRAINING_LOOKBACK = "Monitor runs needed before the prediction model starts flagging anomalies, from 20 to 1000."
_SENSITIVITY = (
    "How readily monitors flag a deviation: `high` flags smaller deviations, `low` only large ones, and `medium` "
    "falls between."
)
_MONITOR_CRON = "Five-field cron expression for when monitors run, e.g. `0 */12 * * *` for every 12 hours."
_EXCLUDE_WEEKENDS = "Leave weekends out of the prediction model's training data."
_HOLIDAY_CODES = (
    "Holiday calendars to leave out of the prediction model's training data: ISO 3166-1 alpha-2 country codes "
    "(e.g. `US`) or financial-market codes (e.g. `XNYS`)."
)


class MonitoringConfig(BaseModel):
    """A table group's full monitoring configuration.

    Omitted settings, and settings sent as `null`, take the default shown. Unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    cron_expression: str = Field(description=_MONITOR_CRON)
    timezone: str = Field(default="UTC", description=_TIMEZONE)
    lookback_runs: StrictInt = Field(default=MONITOR_SETTING_DEFAULTS["monitor_lookback"], description=_LOOKBACK_RUNS)
    regenerate_freshness: StrictBool = Field(
        default=MONITOR_SETTING_DEFAULTS["monitor_regenerate_freshness"], description=_REGENERATE_FRESHNESS
    )
    min_training_lookback: StrictInt = Field(
        default=MONITOR_SETTING_DEFAULTS["predict_min_lookback"], description=_MIN_TRAINING_LOOKBACK
    )
    sensitivity: MonitorSensitivity = Field(
        default=MonitorSensitivity(MONITOR_SETTING_DEFAULTS["predict_sensitivity"]), description=_SENSITIVITY
    )
    exclude_weekends: StrictBool = Field(
        default=MONITOR_SETTING_DEFAULTS["predict_exclude_weekends"], description=_EXCLUDE_WEEKENDS
    )
    holiday_codes: list[str] = Field(default_factory=list, description=_HOLIDAY_CODES)

    @field_validator(
        "timezone",
        "lookback_runs",
        "regenerate_freshness",
        "min_training_lookback",
        "sensitivity",
        "exclude_weekends",
        "holiday_codes",
        mode="before",
    )
    @classmethod
    def _null_takes_the_default(cls, value: Any, info: ValidationInfo) -> Any:
        if value is not None:
            return value
        field = cls.model_fields[info.field_name]
        return field.default_factory() if field.default_factory else field.default


class MonitoringUpdate(BaseModel):
    """Changes to a table group's monitoring configuration. Only the fields sent are changed.

    Send an empty `holiday_codes` list to clear the holiday calendars. A field sent as `null`, a body
    with nothing to change, and unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    cron_expression: str | None = Field(default=None, description=_MONITOR_CRON)
    timezone: str | None = Field(default=None, description=_TIMEZONE)
    lookback_runs: StrictInt | None = Field(default=None, description=_LOOKBACK_RUNS)
    regenerate_freshness: StrictBool | None = Field(default=None, description=_REGENERATE_FRESHNESS)
    min_training_lookback: StrictInt | None = Field(default=None, description=_MIN_TRAINING_LOOKBACK)
    sensitivity: MonitorSensitivity | None = Field(default=None, description=_SENSITIVITY)
    exclude_weekends: StrictBool | None = Field(default=None, description=_EXCLUDE_WEEKENDS)
    holiday_codes: list[str] | None = Field(default=None, description=_HOLIDAY_CODES)
    active: StrictBool | None = Field(
        default=None, description="`false` pauses the monitor schedule, `true` resumes it."
    )


class MonitoringResponse(BaseModel):
    """A table group's monitoring configuration and schedule."""

    table_group_id: UUID
    monitor_count: int = Field(description="Monitors on the table group.")
    cron_expression: str = Field(description="The schedule's expression as stored, in canonical form.")
    timezone: str = Field(description=_TIMEZONE)
    description: str | None = Field(default=None, description="The expression in words, e.g. `Every 12 hours`.")
    active: bool = Field(description="Whether the monitor schedule runs. `false` while it is paused.")
    next_run_at: datetime | None = Field(
        default=None, description="When monitors next run, in UTC. `null` while the schedule is paused."
    )
    lookback_runs: int | None = Field(default=None, description=_LOOKBACK_RUNS)
    regenerate_freshness: bool | None = Field(default=None, description=_REGENERATE_FRESHNESS)
    min_training_lookback: int | None = Field(default=None, description=_MIN_TRAINING_LOOKBACK)
    sensitivity: MonitorSensitivity | None = Field(default=None, description=_SENSITIVITY)
    exclude_weekends: bool | None = Field(default=None, description=_EXCLUDE_WEEKENDS)
    holiday_codes: list[str] = Field(default_factory=list, description=_HOLIDAY_CODES)
