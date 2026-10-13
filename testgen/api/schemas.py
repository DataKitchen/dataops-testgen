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
    DefaultSeverityInput,
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
)
from testgen.common.enums import JobSource, JobStatus, PublicJobKey
from testgen.common.file_declaration_schema import HEADER_DESCRIPTION, FileDeclarationShape, FileDeclarationSpec
from testgen.common.models.job_execution import EXTERNAL_URL_MAX_LENGTH, validate_caller_metadata
from testgen.common.models.table_group import (
    SCHEMA_NAME_MAX_LENGTH,
    SCHEMA_NAME_PATTERN,
    table_group_defaults,
)
from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS
from testgen.common.test_definition_export_import_service import ImportConfig, ImportPayload, ImportResponse

SchemaName = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "Schema the item belongs to. Null when the connection's database type organizes "
            "its data without one."
        ),
    ),
]

# --- Jobs ---


class JobSubmittedResponse(BaseModel):
    """Returned on 202 Accepted after successful job submission."""

    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class TableGroupUpdateRequest(BaseModel):
    """Fields to change on a table group. Omitted fields are left unchanged. A field sent as `null`,
    a body with nothing to change, and unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    schema_name: str | None = Field(
        default=None,
        pattern=SCHEMA_NAME_PATTERN,
        max_length=SCHEMA_NAME_MAX_LENGTH,
        description=(
            "Database connections only. Schema to read the table group's tables from. When it changes, "
            "profiling, test generation, monitors, and test runs read the new schema, and tests keep their history. "
            "Referential tests keep the schema of their second table."
        ),
    )


class TableGroupSchemaChange(BaseModel):
    """What changing the schema did, present only when the request changed it."""

    previous_schema_name: str
    schema_name: str
    definitions_repointed: int = Field(
        description="Test definitions updated to the new schema.",
    )
    missing_tables: list[str] = Field(
        default_factory=list,
        description=(
            "Tables in the table group that the new schema does not have. The change still applies. "
            "Their tests report an error on each test run, or are deactivated if the test suite "
            "deactivates tests that fail validation, and the next monitor run deletes their "
            "monitors along with the thresholds they learned."
        ),
    )


class TestRunRequest(BaseModel):
    """Optional body for a test run submission."""

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
            "Link back to whatever triggered this run, shown on the test results page."
        ),
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "JSON object describing what triggered this run, up to 50 top-level keys and 10,240 "
            "bytes. Stored with the run and shown on the test results page."
        ),
    )

    @field_validator("metadata")
    @classmethod
    def _check_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if error := validate_caller_metadata(value):
            raise ValueError(error)
        return value


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
    external_url: str | None = None
    metadata: dict[str, Any] | None = None
    result: TestRunResult | None = None


class TestResultItem(BaseModel):
    """One individual test result within a test run."""

    test_definition_id: UUID
    test_type: str
    test_type_name: str | None = None
    schema_name: SchemaName
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
    schema_name: SchemaName
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
    schema_name: SchemaName
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

    schema_name: SchemaName
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


class ErrorBody(BaseModel):
    """The ``detail`` of a business logic error response."""

    errors: list[ErrorDetail]


class ErrorResponse(BaseModel):
    """Standardized error response for business logic errors (400, 404, 409)."""

    detail: ErrorBody


# --- Test Definition Export/Import (wire types) ---


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ImportConfig
    payload: ImportPayload


class ImportStrictErrorBody(ErrorBody):
    """The ``detail`` of the apply_strict error response."""

    import_result: ImportResponse


class ImportStrictError(BaseModel):
    """400 response for apply_strict when entries would be skipped."""

    detail: ImportStrictErrorBody


# --- Test Generation ---


class TestGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class _NamedDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Display name for the destination (unique per project, case-insensitive).")


class EmailDestinationCreate(_NamedDestination):
    type: Literal["email"]
    recipients: list[str] = Field(min_length=1, description="One or more well-formed email addresses.")


class WebhookDestinationCreate(_NamedDestination):
    type: Literal["webhook"]
    webhook_type: WebhookTypeLiteral = Field(description="Webhook sub-type: Slack, Microsoft Teams, or Generic.")
    url: str = Field(description="HTTPS URL to POST to. Stored encrypted; never returned in full after save.")
    auth_header_name: str | None = Field(
        default=None,
        description="Authorization header name (Generic webhooks only).",
    )
    auth_header_value: str | None = Field(
        default=None,
        description="Authorization header value (Generic webhooks only). Stored encrypted; never returned.",
    )


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
    """A destination is either an email recipient list or a webhook; `type` selects the shape."""


class EmailDestinationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["email"] = Field(description="Must match the stored destination type.")
    name: str | None = None
    recipients: list[str] | None = Field(default=None, min_length=1)


class WebhookDestinationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["webhook"] = Field(description="Must match the stored destination type.")
    name: str | None = None
    webhook_type: WebhookTypeLiteral | None = None
    url: str | None = Field(default=None, description="Replace the stored URL.")
    auth_header_name: str | None = None
    auth_header_value: str | None = Field(
        default=None,
        description="Replace the stored auth header value. Empty string clears it.",
    )


_DestinationUpdatePayload = Annotated[
    Annotated[EmailDestinationUpdate, Tag("email")]
    | Annotated[WebhookDestinationUpdate, Tag("webhook")],
    Discriminator("type"),
]


# Same RootModel wrapper rationale as DestinationCreate.
class DestinationUpdate(RootModel[_DestinationUpdatePayload]):
    """Fields to change on a destination; `type` must match the stored destination type.

    A field sent as `null`, a body with nothing to change besides `type`, and unknown fields are
    rejected.
    """


class EmailDestinationResponse(BaseModel):
    id: UUID
    type: Literal["email"] = "email"
    project_code: str
    name: str
    recipients: list[str]
    rule_count: int


class WebhookDestinationResponse(BaseModel):
    id: UUID
    type: Literal["webhook"] = "webhook"
    project_code: str
    name: str
    webhook_type: WebhookTypeLiteral
    url_masked: str
    auth_header_name: str | None = None
    has_auth_header: bool
    rule_count: int


DestinationResponse = Annotated[
    Annotated[EmailDestinationResponse, Tag("email")]
    | Annotated[WebhookDestinationResponse, Tag("webhook")],
    Discriminator("type"),
]


class DestinationListResponse(BaseModel):
    # Field order matches the ``items / page / limit / total`` shape every other
    # list response in this file (``JobListResponse``, ``TestResultListResponse``,
    # ``HygieneIssueListResponse``, etc.) so a paging client can iterate without
    # branching on which endpoint it hit.
    items: list[DestinationResponse]
    page: int
    limit: int
    total: int


class DestinationDeleteResponse(BaseModel):
    id: UUID
    deleted_rule_count: int


# ---------- Rule schemas ----------


class InlineAddressing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["inline"]
    recipients: list[str] = Field(min_length=1)


class DestinationAddressing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["destination"]
    destination_id: UUID


AddressingIn = Annotated[
    Annotated[InlineAddressing, Tag("inline")]
    | Annotated[DestinationAddressing, Tag("destination")],
    Discriminator("kind"),
]


class InlineAddressingOut(BaseModel):
    kind: Literal["inline"] = "inline"
    recipients: list[str]


class DestinationAddressingOut(BaseModel):
    kind: Literal["destination"] = "destination"
    destination_id: UUID
    destination_name: str | None = None
    destination_type: str | None = None


AddressingOut = Annotated[
    Annotated[InlineAddressingOut, Tag("inline")]
    | Annotated[DestinationAddressingOut, Tag("destination")],
    Discriminator("kind"),
]


class TestRunRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["test_run"]
    addressing: AddressingIn
    test_suite_id: UUID | None = Field(default=None, description="Scope to a specific test suite; omit for project-wide.")
    trigger: TestRunTrigger = "on_failures"


class ProfilingRunRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["profiling_run"]
    addressing: AddressingIn
    table_group_id: UUID | None = Field(default=None, description="Scope to a specific table group; omit for project-wide.")
    trigger: ProfilingRunTrigger = "on_changes"


# The table group is derived from the suite rather than accepted: the suite-to-table-group
# link is 1:1, so a supplied value could only agree or conflict, and the delivery path
# resolves the table group from the suite regardless.
class MonitorRunRuleCreate(BaseModel):
    """A monitor rule is scoped by its monitor suite; the table group is derived from it."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["monitor_run"]
    addressing: AddressingIn
    test_suite_id: UUID
    table_name: str | None = None


class ScoreDropRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["score_drop"]
    addressing: AddressingIn
    score_definition_id: UUID
    total_threshold: float | None = None
    cde_threshold: float | None = None


_RuleCreatePayload = Annotated[
    Annotated[TestRunRuleCreate, Tag("test_run")]
    | Annotated[ProfilingRunRuleCreate, Tag("profiling_run")]
    | Annotated[MonitorRunRuleCreate, Tag("monitor_run")]
    | Annotated[ScoreDropRuleCreate, Tag("score_drop")],
    Discriminator("event"),
]


# Same RootModel wrapper rationale as DestinationCreate.
class RuleCreate(RootModel[_RuleCreatePayload]):
    """A notification rule; `event` selects which scope and trigger fields apply."""


class RuleUpdate(BaseModel):
    """Change the fields you want to change. Event and scope entity are immutable.

    Optional fields on score-drop and monitor-run rules are cleared with their `clear_*` flag.
    A field sent as `null`, a field sent together with its `clear_*` flag, a body with nothing to
    change, and unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    addressing: AddressingIn | None = None
    trigger: str | None = None
    total_threshold: float | None = None
    cde_threshold: float | None = None
    table_name: str | None = None
    clear_total_threshold: bool = Field(
        default=False,
        description="Set to ``true`` to clear the total-score threshold on a "
        "score-drop rule. At least one threshold must remain set after the call.",
    )
    clear_cde_threshold: bool = Field(
        default=False,
        description="Set to ``true`` to clear the CDE-score threshold on a "
        "score-drop rule. At least one threshold must remain set after the call.",
    )
    clear_table_name: bool = Field(
        default=False,
        description="Set to ``true`` to drop the optional table filter from a "
        "monitor-run rule (the rule then fires for any table in the table group).",
    )


class _RuleResponseBase(BaseModel):
    id: UUID
    project_code: str
    enabled: bool
    addressing: AddressingOut


class TestRunRuleResponse(_RuleResponseBase):
    event: Literal["test_run"] = "test_run"
    test_suite_id: UUID | None = None
    trigger: TestRunTrigger


class ProfilingRunRuleResponse(_RuleResponseBase):
    event: Literal["profiling_run"] = "profiling_run"
    table_group_id: UUID | None = None
    trigger: ProfilingRunTrigger


class MonitorRunRuleResponse(_RuleResponseBase):
    event: Literal["monitor_run"] = "monitor_run"
    test_suite_id: UUID
    table_group_id: UUID
    trigger: MonitorRunTrigger = "on_anomalies"
    table_name: str | None = None


class ScoreDropRuleResponse(_RuleResponseBase):
    event: Literal["score_drop"] = "score_drop"
    score_definition_id: UUID  # score-drop rules always carry a scorecard id
    total_threshold: float | None = None
    cde_threshold: float | None = None


RuleResponse = Annotated[
    Annotated[TestRunRuleResponse, Tag("test_run")]
    | Annotated[ProfilingRunRuleResponse, Tag("profiling_run")]
    | Annotated[MonitorRunRuleResponse, Tag("monitor_run")]
    | Annotated[ScoreDropRuleResponse, Tag("score_drop")],
    Discriminator("event"),
]


class RuleListResponse(BaseModel):
    items: list[RuleResponse]
    page: int
    limit: int
    total: int


# --- Connections ---


class ConnectionItem(BaseModel):
    """One connection in a project listing."""

    connection_id: int
    connection_name: str
    project_code: str
    connection_type: ConnectionType = Field(
        description="The connection's type: a database, such as Snowflake, or a file data source, such as Amazon S3."
    )
    table_group_count: int


class ConnectionListResponse(BaseModel):
    """Paginated list of a project's connections."""

    items: list[ConnectionItem]
    page: int
    limit: int
    total: int


class ConnectionResponse(BaseModel):
    """A connection's configuration.

    Connection parameters vary by connection type, so they are grouped under
    ``settings`` rather than given fixed top-level fields: a Snowflake connection
    carries ``host`` / ``database`` / ``warehouse`` / ``username``, while a
    Salesforce Data 360 connection carries ``login_url`` / ``username`` /
    ``consumer_key``, and an Amazon S3 connection carries ``base_uri`` / ``region``. Keys
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
            "How the connection authenticates to its data source. Null for a connection type that "
            "takes no credentials, such as Local Files."
        ),
    )
    max_threads: int | None = None
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
        "Data 360. Null on a file connection.",
    )
    project_code: str
    connection_id: int
    connection_name: str | None = None
    table_count: int
    column_count: int | None = None
    row_count: int | None = None
    last_profiled_at: datetime | None = None
    last_tested_at: datetime | None = None
    profiling_score: float | None = None
    testing_score: float | None = None
    quality_score: float | None = None


class TableGroupListResponse(BaseModel):
    """Paginated list of a project's table groups."""

    items: list[TableGroupItem]
    page: int
    limit: int
    total: int


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


class TableGroupResponse(BaseModel):
    """A table group's full configuration."""

    table_group_id: UUID
    table_group_name: str
    schema_name: str | None = Field(
        default=None,
        description="Database connections only. The schema that holds the tables, or the data space on Salesforce "
        "Data 360. Null on a file connection.",
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
    include_masks: list[str] = Field(
        default_factory=list,
        description="Database connections only. SQL LIKE patterns a table must match to be included.",
    )
    exclude_masks: list[str] = Field(
        default_factory=list,
        description="Database connections only. SQL LIKE patterns that exclude a matching table.",
    )
    file_declarations: list[FileDeclaration] | None = Field(
        default=None,
        description="File connections only. The table group's tables, one per file or pattern. Null on a database "
        "connection.",
    )
    profile_id_column_mask: str | None = Field(default=None, description="SQL LIKE pattern marking ID columns.")
    profile_sk_column_mask: str | None = Field(
        default=None, description="SQL LIKE pattern marking surrogate key columns."
    )

    profile_use_sampling: bool
    profile_sample_percent: int | None = None
    profile_sample_min_count: int | None = None
    profiling_delay_days: int | None = None
    profile_flag_cdes: bool
    profile_flag_pii: bool
    profile_exclude_xde: bool
    profile_table_comparison: bool
    include_in_dashboard: bool

    catalog_tags: CatalogTags


class TableGroupUpdateResponse(TableGroupResponse):
    """The table group as it now stands, plus what a schema change did."""

    schema_change: TableGroupSchemaChange | None = None


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


class TableGroupCreate(BaseModel):
    """A table group to create on a connection.

    Omitted optional fields, and fields sent as ``null``, take the default shown.
    Unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    table_group_name: str = Field(description="Unique within the project; 3 to 40 characters.")
    schema_name: str | None = Field(
        default=None,
        description="Database connections only, and required there. The schema that holds the tables, or the data "
        "space on Salesforce Data 360.",
    )
    file_declarations: list[FileDeclarationCreate] | None = Field(
        default=None,
        description="File connections only, and required there. The table group's tables, one per file or pattern.",
    )
    description: str | None = None

    table_set: list[str] | None = Field(
        default=None,
        description="Database connections only. Table names to restrict the group to. Omit to define the group by "
        "masks alone.",
    )
    include_masks: list[str] | None = Field(
        default=None,
        description="Database connections only. SQL LIKE patterns a table must match to be included. Omit for the "
        "default include mask.",
    )
    exclude_masks: list[str] | None = Field(
        default=None,
        description=(
            "Database connections only. SQL LIKE patterns that exclude a matching table, including one named in"
            " ``table_set``. Omit for the default exclude mask; send an empty list to exclude nothing."
        ),
    )
    profile_id_column_mask: str | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_id_column_mask"], description="SQL LIKE pattern marking ID columns."
    )
    profile_sk_column_mask: str | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_sk_column_mask"],
        description="SQL LIKE pattern marking surrogate key columns.",
    )

    profile_use_sampling: StrictBool | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_use_sampling"],
        description=(
            "Base pattern and character analysis, and the list of frequent values, on a sample of each table's rows."
            " Record counts, distinct values, minimums, maximums, and average lengths and values always cover the"
            " full table."
        ),
    )
    profile_sample_percent: StrictInt | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_sample_percent"],
        description="Percent of rows to sample, from 1 to 100, unless that falls below the sample minimum.",
    )
    profile_sample_min_count: StrictInt | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_sample_min_count"],
        description="Minimum number of rows in any sample, when the table has that many.",
    )
    profiling_delay_days: StrictInt | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profiling_delay_days"],
        description="Days to wait before new profiling results are used to generate tests.",
    )
    profile_flag_cdes: StrictBool | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_flag_cdes"],
        description="Flag likely critical data elements during profiling.",
    )
    profile_flag_pii: StrictBool | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_flag_pii"],
        description="Flag columns that likely hold personally identifiable information during profiling.",
    )
    profile_exclude_xde: StrictBool | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_exclude_xde"],
        description="Skip columns marked as excluded data elements when profiling.",
    )
    profile_table_comparison: StrictBool | None = Field(
        default=_TABLE_GROUP_DEFAULTS["profile_table_comparison"],
        description=(
            "Collect value hashes during profiling, which Table Comparison test generation needs for tests that"
            " detect changed, moved, or swapped values. Adds profiling time. Has no effect on SAP HANA and"
            " Salesforce Data 360 connections."
        ),
    )
    include_in_dashboard: StrictBool | None = Field(
        default=_TABLE_GROUP_DEFAULTS["include_in_dashboard"],
        description="Show the table group on the project dashboard.",
    )

    catalog_tags: CatalogTags | None = None
    add_scorecard: StrictBool = Field(
        default=True, description="Also add a scorecard for the table group to the Quality Dashboard."
    )


# --- Test Suites ---


class TestSuiteLatestRun(BaseModel):
    """The test suite's last completed test run."""

    job_execution_id: UUID = Field(description="The run's job ID, for `GET /test-runs/{job_id}`.")
    started_at: datetime | None = None
    test_count: int | None = Field(default=None, description="Tests the run executed.")
    result_counts: ResultCounts


class TestSuiteItem(BaseModel):
    """One test suite in a list, with its test count and last completed run."""

    test_suite_id: UUID
    test_suite_name: str
    project_code: str
    connection_id: int
    table_group_id: UUID
    table_group_name: str | None = None
    description: str | None = None
    test_count: int = Field(description="Test definitions in the suite.")
    latest_run: TestSuiteLatestRun | None = Field(
        default=None, description="The last completed test run. Null when the suite has never completed a run."
    )


class TestSuiteListResponse(BaseModel):
    items: list[TestSuiteItem]
    page: int
    limit: int
    total: int


class TestSuiteResponse(BaseModel):
    """A test suite's configuration."""

    test_suite_id: UUID
    test_suite_name: str
    project_code: str
    connection_id: int
    table_group_id: UUID
    description: str | None = None
    default_severity: DefaultSeverity | None = Field(
        default=None,
        description="Severity for the suite's tests that set none of their own. Null means each test takes "
        "its test type's severity.",
    )
    exclude_from_quality_score: bool = Field(description="Whether the suite's results are left out of scoring.")
    deactivate_invalid_tests: bool = Field(
        description="Whether tests that fail validation at the start of a run (a missing table or column, or a "
        "column type the test does not apply to) are deactivated automatically.",
    )
    export_to_observability: bool
    component_key: str | None = None
    component_type: str | None = None
    component_name: str | None = None
    generation_sets: list[str] = Field(
        default_factory=list,
        description="Generation sets test generation uses for the suite. Empty means `Standard`.",
    )
    is_default: bool = Field(
        description="Whether this is its table group's default test suite, which the table group's first "
        "profiling run generates tests into."
    )


class TestSuiteCreate(BaseModel):
    """A test suite to create under a table group.

    Omitted optional fields, and fields sent as ``null``, take the default shown.
    Unknown fields are rejected. Test suite names need not be unique, so repeating a
    create makes a second suite with the same name.
    """

    model_config = ConfigDict(extra="forbid")

    test_suite_name: str = Field(description="Up to 200 characters.")
    description: str | None = None
    default_severity: DefaultSeverityInput | None = Field(
        default=None,
        description="Severity for the suite's tests that set none of their own. Omit to have each test take "
        "its test type's severity.",
    )
    exclude_from_quality_score: StrictBool = Field(
        default=False, description="Leave the suite's results out of the Quality Score."
    )
    deactivate_invalid_tests: StrictBool = Field(
        default=False,
        description="Whether tests that fail validation at the start of a run (a missing table or column, or a "
        "column type the test does not apply to) are deactivated automatically. Defaults to False.",
    )
    export_to_observability: StrictBool = Field(
        default=False, description="Export the suite's test results to DataOps Observability."
    )
    component_key: str | None = Field(default=None, description="Component identifier in DataOps Observability.")
    component_type: str | None = Field(default="dataset", description="Component type in DataOps Observability.")
    component_name: str | None = Field(default=None, description="Component name in DataOps Observability.")
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


class ScheduleCreate(BaseModel):
    """A recurring schedule. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    cron_expression: str = Field(
        description="Five-field cron expression (minute, hour, day of month, month, day of week), "
        "e.g. `0 3 * * *` for every day at 3:00.",
    )
    timezone: str = Field(default="UTC", description="IANA timezone the expression is read in.")


class ScheduleResponse(BaseModel):
    """A recurring profiling or test run schedule."""

    schedule_id: UUID
    kind: ScheduleKind
    project_code: str
    table_group_id: UUID | None = Field(
        default=None, description="The table group a profiling schedule profiles. Null for a test run schedule."
    )
    test_suite_id: UUID | None = Field(
        default=None, description="The test suite a test run schedule runs. Null for a profiling schedule."
    )
    cron_expression: str = Field(description="The expression as stored, in canonical form.")
    timezone: str
    description: str | None = Field(default=None, description="The expression in words, e.g. `At 03:00`.")
    active: bool = Field(description="False when the schedule is paused in the TestGen UI.")
    next_run_at: datetime | None = Field(
        default=None, description="When the schedule next starts a job, in UTC. Null while it is paused."
    )


class ScheduleListResponse(BaseModel):
    items: list[ScheduleResponse]
    page: int
    limit: int
    total: int


# --- Monitoring ---

_LOOKBACK_RUNS = "Monitor runs summarized on the monitors dashboard, from 1 to 200. Does not affect detection."
_REGENERATE_FRESHNESS = "Reconfigure Freshness monitors from each new profiling run."
_MIN_TRAINING_LOOKBACK = "Monitor runs needed before the prediction model starts flagging anomalies, from 20 to 1000."
_SENSITIVITY = "How readily monitors flag a deviation."
_EXCLUDE_WEEKENDS = "Leave weekends out of the prediction model's training data."
_HOLIDAY_CODES = (
    "Holiday calendars to leave out of the prediction model's training data: ISO 3166-1 alpha-2 country codes "
    "(e.g. `US`) or financial-market codes (e.g. `XNYS`)."
)


class MonitoringConfig(BaseModel):
    """A table group's full monitoring configuration.

    Omitted settings, and settings sent as ``null``, take the default shown. Unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    cron_expression: str = Field(
        description="Five-field cron expression for when monitors run, e.g. `0 */12 * * *` for every 12 hours."
    )
    timezone: str = Field(default="UTC", description="IANA timezone the expression is read in.")
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

    cron_expression: str | None = None
    timezone: str | None = None
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
    timezone: str
    description: str | None = Field(default=None, description="The expression in words, e.g. `Every 12 hours`.")
    active: bool = Field(description="False while the monitor schedule is paused.")
    next_run_at: datetime | None = Field(
        default=None, description="When monitors next run, in UTC. Null while the schedule is paused."
    )
    lookback_runs: int | None = Field(default=None, description=_LOOKBACK_RUNS)
    regenerate_freshness: bool | None = Field(default=None, description=_REGENERATE_FRESHNESS)
    min_training_lookback: int | None = Field(default=None, description=_MIN_TRAINING_LOOKBACK)
    sensitivity: MonitorSensitivity | None = Field(default=None, description=_SENSITIVITY)
    exclude_weekends: bool | None = Field(default=None, description=_EXCLUDE_WEEKENDS)
    holiday_codes: list[str] = Field(default_factory=list, description=_HOLIDAY_CODES)
