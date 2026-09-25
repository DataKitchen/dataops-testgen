from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from enum import StrEnum
from typing import NoReturn, TypeVar
from uuid import UUID

from sqlalchemy import func, select

from testgen.common.connection_schema import (
    URL_FIELD,
    FlavorMode,
    Req,
    authentication_label,
    connection_display_values,
    infer_mode,
    schema_for,
    write_conn_field,
)
from testgen.common.date_service import parse_since
from testgen.common.enums import (
    PAUSABLE_JOB_KEYS,
    PII_FLAG_PREFIX_TO_LABEL,
    STOPPABLE_ONLY_STATUSES,
    Disposition,
    ImpactDimension,
    IssueLikelihood,
    JobKey,
    JobStatus,
    MonitorCalculation,
    MonitorType,
    PiiRisk,
    QualityDimension,
    SuiteType,
    run_duration_seconds,
)
from testgen.common.flavors import (
    FLAVOR_CODE_TO_FAMILY,
    FLAVOR_CODE_TO_LABEL,
    SqlFlavorLabel,
    fixed_max_threads,
)
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import (
    GENERAL_TYPE_TO_CODE,
    ColumnOrderBy,
    GeneralType,
    ProfileMetric,
    SuggestedDataType,
)
from testgen.common.models.hygiene_issue import HygieneIssue, HygieneIssueType
from testgen.common.models.notification_settings import (
    MonitorNotificationTrigger,
    NotificationEvent,
    NotificationSettings,
    ProfilingRunNotificationTrigger,
    TestRunNotificationTrigger,
)
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.project import Project
from testgen.common.models.scheduler import SCHEDULABLE_JOB_KEYS, JobSchedule
from testgen.common.models.scores import ScoreCategory, ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import Severity, TestDefinition, TestDefinitionNote, TestType
from testgen.common.models.test_result import TestResult, TestResultStatus
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions
from testgen.mcp.services.source_data_protection import mcp_source_data_protected
from testgen.mcp.tools.markdown import MdDoc

# User-facing label for ``Disposition.INACTIVE`` is "Muted" — accept that label on input.
_DISPOSITION_USER_TO_DB: dict[str, Disposition] = {
    "Confirmed": Disposition.CONFIRMED,
    "Dismissed": Disposition.DISMISSED,
    "Muted": Disposition.INACTIVE,
}
_DISPOSITION_DB_TO_USER: dict[Disposition, str] = {v: k for k, v in _DISPOSITION_USER_TO_DB.items()}
# Filter accepts only the regular likelihoods — PII rows are filtered separately via ``pii_risk``.
_FILTERABLE_LIKELIHOODS = frozenset({IssueLikelihood.DEFINITE, IssueLikelihood.LIKELY, IssueLikelihood.POSSIBLE})


class DocGroup(StrEnum):
    """User-facing groupings for tools on the supported-tools doc page.

    Each tool module declares ``_DOC_GROUP = DocGroup.<member>``; the
    ``deploy/build_mcp_docs.py`` script reads these values to organize
    the page.
    """

    DISCOVER = "Discover what TestGen knows about"
    INVESTIGATE = "Investigate quality issues"
    BROWSE_PROFILING = "Browse profiling results"
    MONITORS = "Browse monitor health and events"
    TRIGGER = "Trigger profiling, tests, and test generation"
    SCORING = "Track data quality scores"
    MANAGE = "Manage TestGen configuration"


def parse_uuid(value: str, label: str = "ID") -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as err:
        raise MCPUserError(f"Invalid {label}: `{value}` is not a valid UUID.") from err


_ParsedEnum = TypeVar("_ParsedEnum", bound=StrEnum)
_MappedValue = TypeVar("_MappedValue")


def match_enum(value: str, enum_cls: type[_ParsedEnum]) -> _ParsedEnum | None:
    """Look up an enum member by its value, ignoring case and surrounding whitespace.

    Returns ``None`` when nothing matches so callers can shape their own error message.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return next((member for member in enum_cls if member.value.lower() == normalized), None)


def match_mapping(value: str, mapping: Mapping[str, _MappedValue]) -> _MappedValue | None:
    """Look up a string-keyed mapping, ignoring case and surrounding whitespace.

    Returns ``None`` when nothing matches so callers can shape their own error message.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return next((mapped for key, mapped in mapping.items() if key.lower() == normalized), None)


def parse_enum(value: str, enum_cls: type[_ParsedEnum], label: str) -> _ParsedEnum:
    member = match_enum(value, enum_cls)
    if member is None:
        valid = ", ".join(m.value for m in enum_cls)
        raise MCPUserError(f"Invalid {label} `{value}`. Valid values: {valid}")
    return member


def parse_result_status(value: str) -> TestResultStatus:
    return parse_enum(value, TestResultStatus, "status")


def validate_page(value: int) -> None:
    if value < 1:
        raise MCPUserError(f"Invalid page `{value}`: must be >= 1.")


def validate_limit(value: int, max_limit: int) -> None:
    if not 1 <= value <= max_limit:
        raise MCPUserError(f"Invalid limit `{value}`: must be between 1 and {max_limit}.")


def parse_since_arg(value: str, label: str = "since", *, today: date | None = None) -> date:
    try:
        return parse_since(value, today=today)
    except ValueError as err:
        raise MCPUserError(f"Invalid `{label}`: {err}") from err


def parse_impact_dimension(value: str) -> ImpactDimension:
    return parse_enum(value, ImpactDimension, "impact_dimension")


def parse_quality_dimension(value: str) -> QualityDimension:
    return parse_enum(value, QualityDimension, "quality_dimension")


def parse_severity(value: str) -> Severity:
    """Validate a test-suite default severity. Accepts ``Fail`` or ``Warning``."""
    return parse_enum(value, Severity, "severity")


class SuiteTypeLabel(StrEnum):
    """User-facing values accepted for the ``suite_type`` argument on test-suite creation."""

    REGULAR = "Regular"
    CONTRACT = "Contract"


SUITE_TYPE_LABEL_TO_INTERNAL: dict[SuiteTypeLabel, SuiteType] = {
    SuiteTypeLabel.REGULAR: SuiteType.REGULAR,
    SuiteTypeLabel.CONTRACT: SuiteType.CONTRACT,
}


def parse_suite_type(value: str) -> SuiteType:
    """Validate a ``suite_type`` value. Accepts ``Regular`` or ``Contract``.

    Monitor suites are created through monitoring setup, not through this argument, so
    ``Monitor`` is not a valid value here.
    """
    label = parse_enum(value, SuiteTypeLabel, "suite_type")
    return SUITE_TYPE_LABEL_TO_INTERNAL[label]


_SUITE_TYPE_INTERNAL_TO_LABEL: dict[SuiteType, SuiteTypeLabel] = {
    v: k for k, v in SUITE_TYPE_LABEL_TO_INTERNAL.items()
}


def format_suite_type_label(suite_type: SuiteType | str) -> str:
    """Map a stored ``suite_type`` to its user-facing display label.

    Only ``regular`` and ``contract`` are mapped — monitor suites are created and managed
    through a separate surface and never reach this function.
    """
    return _SUITE_TYPE_INTERNAL_TO_LABEL[SuiteType(suite_type)].value


class ScoreGroupBy(StrEnum):
    """User-facing values accepted for the ``group_by`` argument on quality-score rollups."""

    QUALITY_DIMENSION = "Quality Dimension"
    IMPACT_DIMENSION = "Impact Dimension"
    SEMANTIC_DATA_TYPE = "Semantic Data Type"
    TABLE_GROUP = "Table Group"
    DATA_LOCATION = "Data Location"
    DATA_SOURCE = "Data Source"
    SOURCE_SYSTEM = "Source System"
    SOURCE_PROCESS = "Source Process"
    BUSINESS_DOMAIN = "Business Domain"
    STAKEHOLDER_GROUP = "Stakeholder Group"
    TRANSFORM_LEVEL = "Transform Level"
    DATA_PRODUCT = "Data Product"
    DATA_CLASSIFICATION = "Data Classification"


# Translates the user-facing label to the internal DB column name used by
# ``ScoreCategory`` and the criteria filter list.
SCORE_GROUP_BY_TO_COLUMN: dict[ScoreGroupBy, str] = {
    ScoreGroupBy.QUALITY_DIMENSION: "dq_dimension",
    ScoreGroupBy.IMPACT_DIMENSION: "impact_dimension",
    ScoreGroupBy.SEMANTIC_DATA_TYPE: "semantic_data_type",
    ScoreGroupBy.TABLE_GROUP: "table_groups_name",
    ScoreGroupBy.DATA_LOCATION: "data_location",
    ScoreGroupBy.DATA_SOURCE: "data_source",
    ScoreGroupBy.SOURCE_SYSTEM: "source_system",
    ScoreGroupBy.SOURCE_PROCESS: "source_process",
    ScoreGroupBy.BUSINESS_DOMAIN: "business_domain",
    ScoreGroupBy.STAKEHOLDER_GROUP: "stakeholder_group",
    ScoreGroupBy.TRANSFORM_LEVEL: "transform_level",
    ScoreGroupBy.DATA_PRODUCT: "data_product",
    ScoreGroupBy.DATA_CLASSIFICATION: "data_classification",
}


class ScoreFilterField(StrEnum):
    """User-facing values accepted for ``filters[].field`` on quality-score rollups.

    Same shape as ``ScoreGroupBy`` minus the two dimension values — Quality
    Dimension and Impact Dimension are valid as ``group_by``, not as filter
    fields. The duplication is deliberate: each argument has its own enum so
    the valid-value set for each is read off one StrEnum.
    """

    SEMANTIC_DATA_TYPE = "Semantic Data Type"
    TABLE_GROUP = "Table Group"
    DATA_LOCATION = "Data Location"
    DATA_SOURCE = "Data Source"
    SOURCE_SYSTEM = "Source System"
    SOURCE_PROCESS = "Source Process"
    BUSINESS_DOMAIN = "Business Domain"
    STAKEHOLDER_GROUP = "Stakeholder Group"
    TRANSFORM_LEVEL = "Transform Level"
    DATA_PRODUCT = "Data Product"
    DATA_CLASSIFICATION = "Data Classification"


SCORE_FILTER_FIELD_TO_COLUMN: dict[ScoreFilterField, str] = {
    ScoreFilterField.SEMANTIC_DATA_TYPE: "semantic_data_type",
    ScoreFilterField.TABLE_GROUP: "table_groups_name",
    ScoreFilterField.DATA_LOCATION: "data_location",
    ScoreFilterField.DATA_SOURCE: "data_source",
    ScoreFilterField.SOURCE_SYSTEM: "source_system",
    ScoreFilterField.SOURCE_PROCESS: "source_process",
    ScoreFilterField.BUSINESS_DOMAIN: "business_domain",
    ScoreFilterField.STAKEHOLDER_GROUP: "stakeholder_group",
    ScoreFilterField.TRANSFORM_LEVEL: "transform_level",
    ScoreFilterField.DATA_PRODUCT: "data_product",
    ScoreFilterField.DATA_CLASSIFICATION: "data_classification",
}


class ScoreCategoryArg(StrEnum):
    """User-facing values accepted for the ``category`` argument on scorecard CRUD.

    Same shape as ``ScoreGroupBy`` — every group-by value is also a valid
    breakdown category. Kept as a separate enum (rather than reusing
    ``ScoreGroupBy``) so each argument has its own valid-value set per the
    per-arg enum convention.
    """

    TABLE_GROUP = "Table Group"
    DATA_LOCATION = "Data Location"
    DATA_SOURCE = "Data Source"
    SOURCE_SYSTEM = "Source System"
    SOURCE_PROCESS = "Source Process"
    BUSINESS_DOMAIN = "Business Domain"
    STAKEHOLDER_GROUP = "Stakeholder Group"
    TRANSFORM_LEVEL = "Transform Level"
    QUALITY_DIMENSION = "Quality Dimension"
    IMPACT_DIMENSION = "Impact Dimension"
    DATA_PRODUCT = "Data Product"
    DATA_CLASSIFICATION = "Data Classification"


SCORE_CATEGORY_ARG_TO_COLUMN: dict[ScoreCategoryArg, str] = {
    ScoreCategoryArg.TABLE_GROUP: "table_groups_name",
    ScoreCategoryArg.DATA_LOCATION: "data_location",
    ScoreCategoryArg.DATA_SOURCE: "data_source",
    ScoreCategoryArg.SOURCE_SYSTEM: "source_system",
    ScoreCategoryArg.SOURCE_PROCESS: "source_process",
    ScoreCategoryArg.BUSINESS_DOMAIN: "business_domain",
    ScoreCategoryArg.STAKEHOLDER_GROUP: "stakeholder_group",
    ScoreCategoryArg.TRANSFORM_LEVEL: "transform_level",
    ScoreCategoryArg.QUALITY_DIMENSION: "dq_dimension",
    ScoreCategoryArg.IMPACT_DIMENSION: "impact_dimension",
    ScoreCategoryArg.DATA_PRODUCT: "data_product",
    ScoreCategoryArg.DATA_CLASSIFICATION: "data_classification",
}


class ScoreChainLeafField(StrEnum):
    """User-facing values accepted as the leaf ``field`` in a scorecard filter chain."""

    TABLE = "Table"
    COLUMN = "Column"


SCORE_CHAIN_LEAF_TO_COLUMN: dict[ScoreChainLeafField, str] = {
    ScoreChainLeafField.TABLE: "table_name",
    ScoreChainLeafField.COLUMN: "column_name",
}


class ScoreType(StrEnum):
    """User-facing values accepted for the ``score_type`` argument."""

    TOTAL = "Total"
    CDE = "CDE"


def parse_score_group_by(value: str) -> ScoreGroupBy:
    return parse_enum(value, ScoreGroupBy, "group_by")


def parse_score_filter_field(value: str) -> ScoreFilterField:
    field_value = match_enum(value, ScoreFilterField)
    if field_value is not None:
        return field_value
    group_by_only = match_enum(value, ScoreGroupBy)
    if group_by_only in {ScoreGroupBy.QUALITY_DIMENSION, ScoreGroupBy.IMPACT_DIMENSION}:
        raise MCPUserError(
            f"`{value}` is not a valid filter field — use group_by='{group_by_only.value}' instead"
        )
    valid = ", ".join(f.value for f in ScoreFilterField)
    raise MCPUserError(f"Invalid filter field `{value}`. Valid values: {valid}")


def parse_score_type(value: str) -> ScoreType:
    return parse_enum(value, ScoreType, "score_type")


def parse_category(value: str) -> ScoreCategory:
    """Validate a ``category`` argument and return the stored ``ScoreCategory``.

    Accepts the display-form values exposed by ``get_quality_scores``'s
    ``group_by`` argument (e.g. ``Quality Dimension``, ``Data Source``).
    """
    arg = parse_enum(value, ScoreCategoryArg, "category")
    return ScoreCategory(SCORE_CATEGORY_ARG_TO_COLUMN[arg])


# Maps user-facing run-status labels to underlying ``JobStatus`` values. Transient states
# (Starting/Canceling) are excluded because they're sub-second and noisy as filters.
# ``Pending`` collapses PENDING+CLAIMED; ``Canceled`` collapses CANCEL_REQUESTED+CANCELED.
# ``Interrupted`` and ``Paused`` each cover a run stopped partway through, whether it is still
# stopping or already parked -- what separates them is whether it picks itself back up.
_RUN_STATUS_FILTER: dict[str, list[JobStatus]] = {
    "Pending": [JobStatus.PENDING, JobStatus.CLAIMED],
    "Running": [JobStatus.RUNNING],
    "Interrupted": [JobStatus.INTERRUPT_REQUESTED, JobStatus.INTERRUPTED],
    "Paused": [JobStatus.PAUSE_REQUESTED, JobStatus.PAUSED, JobStatus.RESUME_REQUESTED],
    "Completed": [JobStatus.COMPLETED],
    "Canceled": [JobStatus.CANCEL_REQUESTED, JobStatus.CANCELED],
    "Error": [JobStatus.ERROR],
}


def _run_status_filters_for(job_key: JobKey) -> dict[str, list[JobStatus]]:
    """Narrow the filter labels to the ones a run of this ``job_key`` can actually hold."""
    if job_key in PAUSABLE_JOB_KEYS:
        return _RUN_STATUS_FILTER
    return {
        label: statuses
        for label, statuses in _RUN_STATUS_FILTER.items()
        if not STOPPABLE_ONLY_STATUSES.issuperset(statuses)
    }


def run_status_filter_options(job_key: JobKey) -> str:
    """Render the status labels a run of this ``job_key`` can be filtered by, for a tool argument."""
    return ", ".join(_run_status_filters_for(job_key))


def parse_run_status_filter(value: str, job_key: JobKey) -> list[JobStatus]:
    """Map a user-facing run status label (e.g. ``Pending``) to the underlying ``JobStatus`` values.

    A label naming a status this ``job_key`` can never reach is rejected, so a caller filtering
    on it gets an error rather than an empty result.
    """
    filters = _run_status_filters_for(job_key)
    statuses = match_mapping(value, filters)
    if statuses is None:
        raise MCPUserError(f"Invalid status `{value}`. Valid values: {', '.join(filters)}")
    return statuses


class FailureGroupBy(StrEnum):
    """User-facing values accepted for the ``group_by`` argument on ``get_failure_summary``."""

    TEST_TYPE = "test_type"
    TABLE = "table"
    COLUMN = "column"


def parse_failure_group_by(value: str) -> FailureGroupBy:
    return parse_enum(value, FailureGroupBy, "group_by")


def format_run_duration(active_seconds: float | None, status: str) -> str | None:
    """Render how long a run worked as ``Xs`` / ``Xm Ys`` / ``Xh Ym``, or ``None`` if still working.

    Reports the time the run worked, which for one that stopped and continued is less than the
    span between its start and its end.
    """
    resolved = run_duration_seconds(active_seconds, status)
    if resolved is None:
        return None
    seconds = int(resolved)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def next_scheduled_run(
    job_key: str, kwargs_filter: dict[str, str | list[str]], project_code: str,
) -> datetime | None:
    """Return the next firing of an active ``JobSchedule`` matching ``job_key`` and a kwargs
    filter. When multiple schedules match, the soonest next-firing wins.
    """
    schedules = JobSchedule.select_active_by_kwargs(project_code, job_key, kwargs_filter)
    if not schedules:
        return None
    return min(s.get_sample_triggering_timestamps(1)[0] for s in schedules)


# Monitor type — internal ``test_type`` value ↔ user-facing short label
_MONITOR_TYPE_USER_TO_DB: dict[str, MonitorType] = {
    "Freshness": MonitorType.FRESHNESS,
    "Volume": MonitorType.VOLUME,
    "Schema": MonitorType.SCHEMA,
    "Metric": MonitorType.METRIC,
}


def parse_monitor_type(value: str, label: str = "monitor_type") -> MonitorType:
    """Validate a user-facing monitor type label and return the stored ``MonitorType``.

    Accepts ``Freshness`` / ``Volume`` / ``Schema`` / ``Metric`` in any casing. ``label``
    names the caller's argument in the error message — pass ``"anomaly_type"`` when the
    public arg is named differently from ``monitor_type``.
    """
    db_value = match_mapping(value, _MONITOR_TYPE_USER_TO_DB)
    if db_value is None:
        valid = ", ".join(_MONITOR_TYPE_USER_TO_DB)
        raise MCPUserError(f"Invalid {label} `{value}`. Valid values: {valid}")
    return db_value


_HISTORICAL_CALCULATIONS = tuple(m for m in MonitorCalculation if m is not MonitorCalculation.PREDICT)


def parse_monitor_calculation(value: str, label: str) -> MonitorCalculation:
    """Validate a user-facing calculation label and return the stored ``MonitorCalculation``.

    Accepts ``Value`` / ``Minimum`` / ``Maximum`` / ``Sum`` / ``Average`` / ``Expression``
    (Title Case as rendered in tool output) or any other casing. ``label`` names the
    caller's argument in the error message — pass ``"lower_bound_calculation"`` or
    ``"upper_bound_calculation"``.
    """
    member = match_enum(value, MonitorCalculation)
    if member is None or member not in _HISTORICAL_CALCULATIONS:
        valid = ", ".join(m.value for m in _HISTORICAL_CALCULATIONS)
        raise MCPUserError(f"Invalid {label} `{value}`. Valid values: {valid}")
    return member


class MonitorTableSort(StrEnum):
    """User-facing values accepted for the ``sort_by`` argument on ``list_monitored_tables``.

    When an ``anomaly_type`` filter is set, ``anomaly_count_desc`` sorts by that type's
    count; with no filter, it sorts by total anomalies across all types.
    """

    TABLE_NAME = "table_name"
    ANOMALY_COUNT_DESC = "anomaly_count_desc"
    LATEST_UPDATE_DESC = "latest_update_desc"
    ROW_COUNT_CHANGE_DESC = "row_count_change_desc"


def parse_monitor_table_sort(value: str) -> MonitorTableSort:
    return parse_enum(value, MonitorTableSort, "sort_by")


def parse_disposition(value: str) -> Disposition:
    """Validate a user-facing disposition label and return the stored ``Disposition``.

    Accepts ``Confirmed``, ``Dismissed``, ``Muted`` (user-facing labels). The DB encodes
    ``INACTIVE`` for "Muted" — see ``Disposition``.
    """
    db_value = match_mapping(value, _DISPOSITION_USER_TO_DB)
    if db_value is None:
        valid = ", ".join(sorted(_DISPOSITION_USER_TO_DB))
        raise MCPUserError(f"Invalid disposition `{value}`. Valid values: {valid}")
    return db_value


_NO_DECISION = "No Decision"


def parse_test_result_disposition(value: str) -> Disposition | None:
    """Validate a user-facing test-result disposition and return the stored value.

    Accepts ``Confirmed``, ``Dismissed``, ``Muted``, and ``No Decision``. ``Muted``
    maps to ``Disposition.INACTIVE``; ``No Decision`` clears the disposition (returns
    ``None`` → NULL).
    """
    if isinstance(value, str) and value.strip().lower() == _NO_DECISION.lower():
        return None
    db_value = match_mapping(value, _DISPOSITION_USER_TO_DB)
    if db_value is None:
        valid = ", ".join([*_DISPOSITION_USER_TO_DB, _NO_DECISION])
        raise MCPUserError(f"Invalid disposition `{value}`. Valid values: {valid}")
    return db_value


def format_disposition(value: Disposition | str) -> str:
    """Map a stored disposition to its user-facing label (``INACTIVE`` → "Muted")."""
    try:
        return _DISPOSITION_DB_TO_USER[Disposition(value)]
    except ValueError:
        return str(value)


def parse_issue_likelihood_list(values: list[str]) -> list[IssueLikelihood]:
    parsed: list[IssueLikelihood] = []
    invalid: list[str] = []
    for value in values:
        likelihood = match_enum(value, IssueLikelihood)
        if likelihood is None or likelihood not in _FILTERABLE_LIKELIHOODS:
            invalid.append(value)
            continue
        parsed.append(likelihood)
    if invalid:
        valid = ", ".join(sorted(v.value for v in _FILTERABLE_LIKELIHOODS))
        raise MCPUserError(f"Invalid issue_likelihood values {invalid}. Valid values: {valid}")
    return parsed


# Maps the user-facing display label to the stored ``pii_flag`` middle segment
# (``A/<CODE>/<detail>``). Mirrors ``_PII_TYPE_MAP`` in ``profiling.py``.
_PII_CATEGORY_TO_CODE: dict[str, str] = {
    "ID": "ID",
    "Name": "NAME",
    "Demographic": "DEMO",
    "Contact": "CONTACT",
}


def build_ilike_pattern(raw: str) -> str:
    """Prepare a free-text input for an ``ILIKE`` clause.

    Escapes literal underscores (which column names commonly contain) so they
    match as themselves rather than as the SQL single-character wildcard. When
    the input contains an explicit ``%``, honor it as the caller's wildcard;
    otherwise wrap the input with ``%...%`` for substring match.

    Pair with ``column.ilike(pattern, escape="\\\\")`` at the call site.
    """
    escaped = raw.replace("_", r"\_")
    return escaped if "%" in escaped else f"%{escaped}%"


def parse_pii_category(value: str) -> str:
    """Validate a pii_category value and return the stored ``pii_flag`` middle segment."""
    code = match_mapping(value, _PII_CATEGORY_TO_CODE)
    if code is None:
        valid = ", ".join(_PII_CATEGORY_TO_CODE)
        raise MCPUserError(f"Invalid pii_category `{value}`. Valid values: {valid}")
    return code


def parse_general_type(value: str) -> str:
    """Validate a user-facing ``general_type`` word and return the stored single-letter code.

    Accepts ``Alpha`` / ``Numeric`` / ``Datetime`` / ``Boolean`` / ``Time`` / ``Other``;
    returns ``A`` / ``N`` / ``D`` / ``B`` / ``T`` / ``X`` respectively (the values stored
    on ``data_column_chars.general_type``).
    """
    return GENERAL_TYPE_TO_CODE[parse_enum(value, GeneralType, "general_type")]


def parse_suggested_data_type(value: str) -> SuggestedDataType:
    return parse_enum(value, SuggestedDataType, "suggested_data_type")


def parse_column_order_by(value: str) -> ColumnOrderBy:
    return parse_enum(value, ColumnOrderBy, "order_by")


def parse_profile_metrics(values: list[str]) -> list[ProfileMetric]:
    """Validate a list of profile metric names. Empties out with one error listing all invalids."""
    if not values:
        raise MCPUserError("`metrics` cannot be empty — name at least one metric to trend.")
    parsed: list[ProfileMetric] = []
    invalid: list[str] = []
    for value in values:
        metric = match_enum(value, ProfileMetric)
        if metric is None:
            invalid.append(value)
        else:
            parsed.append(metric)
    if invalid:
        valid = ", ".join(m.value for m in ProfileMetric)
        raise MCPUserError(f"Invalid metrics {invalid}. Valid values: {valid}")
    return parsed


# Reverse of ``PII_FLAG_PREFIX_TO_LABEL`` — for validating a user-supplied label and returning
# the stored prefix code.
_PII_RISK_LABEL_TO_PREFIX: dict[str, str] = {v: k for k, v in PII_FLAG_PREFIX_TO_LABEL.items()}


def parse_pii_risk_level(value: str) -> str:
    """Validate a column-profile pii_risk_level filter and return the stored prefix code."""
    code = match_mapping(value, _PII_RISK_LABEL_TO_PREFIX)
    if code is None:
        valid = ", ".join(_PII_RISK_LABEL_TO_PREFIX)
        raise MCPUserError(f"Invalid pii_risk_level `{value}`. Valid values: {valid}")
    return code


def parse_pii_risk_list(values: list[str]) -> list[PiiRisk]:
    parsed: list[PiiRisk] = []
    invalid: list[str] = []
    for value in values:
        risk = match_enum(value, PiiRisk)
        if risk is None:
            invalid.append(value)
        else:
            parsed.append(risk)
    if invalid:
        valid = ", ".join(r.value for r in PiiRisk)
        raise MCPUserError(f"Invalid pii_risk values {invalid}. Valid values: {valid}")
    return parsed


def resolve_test_type(short_name: str) -> str:
    """Resolve a test type short name to its internal code, ignoring case and surrounding whitespace.

    The stored name is trimmed too, so a type whose reference data carries stray whitespace
    stays matchable by the name the catalog advertises.
    """
    matches = TestType.select_where(
        func.lower(func.trim(TestType.test_name_short)) == short_name.strip().lower()
    )
    if not matches:
        raise MCPUserError(
            f"Unknown test type: `{short_name}`. Use the testgen://test-types resource to see available types."
        )
    return matches[0].test_type


def resolve_issue_type(name: str) -> str:
    """Resolve a hygiene issue type human label to its internal id, ignoring case and surrounding whitespace."""
    matches = HygieneIssueType.select_where(
        func.lower(func.trim(HygieneIssueType.name)) == name.strip().lower()
    )
    if not matches:
        raise MCPUserError(
            f"Unknown hygiene issue type: `{name}`. "
            "Use the testgen://hygiene-issue-types resource to see available types."
        )
    return matches[0].id


def format_page_info(total: int, page: int, limit: int) -> str:
    """Shared pagination summary line for MCP tool output.

    Returns empty for a zero total *or* when ``page`` is past the last page \u2014
    the caller's own "no rows on page N" message is more useful than a
    ``Showing 6\u20135 of 5`` nonsense range.
    """
    if total == 0:
        return ""
    start = (page - 1) * limit + 1
    if start > total:
        return ""
    end = min(start + limit - 1, total)
    return f"Showing {start}\u2013{end} of {total} (page {page})."


def format_page_footer(total: int, page: int, limit: int) -> str:
    """Pagination footer hint — returns empty string if on the last page."""
    total_pages = (total + limit - 1) // limit
    if page >= total_pages:
        return ""
    return f"_Page {page} of {total_pages}. Use `page={page + 1}` for more._"


def _default_render_diff_value(value: object) -> str | None:
    """Default formatter for before/after cells in :func:`render_diff_table`.

    * ``bool`` → ``"Yes"`` / ``"No"``
    * ``None`` or ``""`` → ``None`` (rendered as em-dash by the table cell)
    * else → ``str(value)``
    """
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None or value == "":
        return None
    return str(value)


def render_diff_table(
    doc: MdDoc,
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    attrs: Sequence[str],
    labels: Mapping[str, str],
    secret_attrs: frozenset[str] = frozenset(),
    value_renderer: Callable[[object], str | None] | None = None,
) -> bool:
    """Emit a ``Field / Before / After`` table for attrs whose values changed.

    Update tools across the MCP surface share this shape: snapshot before, apply
    field-by-field, snapshot after, render the delta. The shared helper keeps the
    ordering, label lookup, and secret redaction consistent.

    Args:
        doc: ``MdDoc`` to append the table to.
        before / after: same-shape dicts of the snapshot keyed by attr name.
            Only entries in ``attrs`` are inspected.
        attrs: ordered tuple of attrs to consider; controls row order.
        labels: attr → user-facing label for the first column.
        secret_attrs: attrs whose values must not be echoed (API keys, passwords).
            Rendered as ``[secret]`` when present, em-dash when absent — distinct
            from a "rotated" cue. Tools that need to communicate rotation
            specifically (e.g. ``update_connection``) keep their own renderer.
        value_renderer: override for the non-secret cells. Defaults to
            :func:`_default_render_diff_value`.

    Returns ``True`` if at least one row was rendered, ``False`` when nothing
    changed (lets the caller emit a "No fields changed" message instead).
    """
    changed = {attr for attr in attrs if before.get(attr) != after.get(attr)}
    if not changed:
        return False
    render = value_renderer or _default_render_diff_value
    rows: list[list[object]] = []
    for attr in attrs:
        if attr not in changed:
            continue
        if attr in secret_attrs:
            b = "[secret]" if before.get(attr) else None
            a = "[secret]" if after.get(attr) else None
        else:
            b = render(before.get(attr))
            a = render(after.get(attr))
        rows.append([labels.get(attr, attr), b, a])
    doc.table(["Field", "Before", "After"], rows, code=[0])
    return True


# Entity resolution helpers — see mcp-roadmap.md "Entity Resolution Helpers" guideline.
# Extract a new resolve_<entity> here when a second caller needs the same parse-uuid +
# perm-scoped lookup + collapsed-error pattern.


def resolve_project(project_code: str) -> Project:
    """Resolve a project code to a Project, scoped to the user's allowed projects.

    Collapses missing-or-inaccessible into a single ``MCPResourceNotAccessible`` so
    callers can't enumerate whether a project they can't see exists.
    """
    perms = get_project_permissions()
    project = Project.get(project_code, Project.project_code.in_(perms.allowed_codes))
    if project is None:
        raise MCPResourceNotAccessible("Project", project_code)
    return project


def resolve_connection(connection_id: int) -> Connection:
    """Resolve a connection ID, collapsing missing-or-inaccessible into one error path."""
    perms = get_project_permissions()
    conn = Connection.get(
        connection_id,
        Connection.project_code.in_(perms.allowed_codes),
    )
    if conn is None:
        raise MCPResourceNotAccessible("Connection", str(connection_id))
    return conn


def resolve_table_group(table_group_id: str) -> TableGroup:
    """Resolve a TG ID, collapsing missing-or-inaccessible into one error path."""
    tg_uuid = parse_uuid(table_group_id, "table_group_id")
    perms = get_project_permissions()
    tg = TableGroup.get(tg_uuid, TableGroup.project_code.in_(perms.allowed_codes))
    if tg is None:
        raise MCPResourceNotAccessible("Table group", table_group_id)
    return tg


def resolve_hygiene_issue(issue_id: str) -> HygieneIssue:
    """Resolve a hygiene issue ID, collapsing missing-or-inaccessible into one error path."""
    issue_uuid = parse_uuid(issue_id, "issue_id")
    perms = get_project_permissions()
    issue = HygieneIssue.get(issue_uuid, HygieneIssue.project_code.in_(perms.allowed_codes))
    if issue is None:
        raise MCPResourceNotAccessible("Hygiene issue", issue_id)
    return issue


def resolve_test_suite(test_suite_id: str) -> TestSuite:
    """Resolve a regular (non-monitor) test suite ID, collapsing missing-or-inaccessible into one error path."""
    suite_uuid = parse_uuid(test_suite_id, "test_suite_id")
    perms = get_project_permissions()
    suite = TestSuite.get(
        suite_uuid,
        TestSuite.suite_type == SuiteType.REGULAR,
        TestSuite.project_code.in_(perms.allowed_codes),
    )
    if suite is None:
        raise MCPResourceNotAccessible("Test suite", test_suite_id)
    return suite


def resolve_monitored_table_group(table_group_id: str) -> tuple[TableGroup, TestSuite | None]:
    """Resolve a table group ID and look up its linked monitor suite.

    Returns ``(table_group, monitor_suite)``. ``monitor_suite`` is ``None`` when the
    table group has no ``monitor_test_suite_id`` set, or that pointer doesn't resolve
    to a monitor suite — callers render the "not monitored" output in
    that case rather than raising an inaccessible error. Raises
    ``MCPResourceNotAccessible`` when the table group itself is missing or out of
    scope.
    """
    tg = resolve_table_group(table_group_id)
    if tg.monitor_test_suite_id is None:
        return tg, None
    suite = TestSuite.get(tg.monitor_test_suite_id, TestSuite.suite_type == SuiteType.MONITOR)
    return tg, suite


def resolve_profiling_run(job_execution_id: str) -> ProfilingRun:
    """Resolve a profiling run by id-or-JE-id, scoped to allowed projects.

    Collapses missing-or-inaccessible into a single ``MCPResourceNotAccessible``
    so callers don't leak existence of runs they shouldn't see.
    """
    run_uuid = parse_uuid(job_execution_id, "job_execution_id")
    run = ProfilingRun.get(run_uuid)
    perms = get_project_permissions()
    if run is None or not perms.has_access(run.project_code):
        raise MCPResourceNotAccessible("Profiling run", job_execution_id)
    return run


def resolve_scorecard(scorecard_id: str) -> ScoreDefinition:
    """Resolve a scorecard ID, collapsing missing-or-inaccessible into one error path."""
    parse_uuid(scorecard_id, "scorecard_id")
    perms = get_project_permissions()
    sd = ScoreDefinition.get(scorecard_id)
    if sd is None or not perms.has_access(sd.project_code):
        raise MCPResourceNotAccessible("Scorecard", scorecard_id)
    return sd


def resolve_test_definition(test_definition_id: str) -> TestDefinition:
    """Resolve a test definition ID to the live ORM model, collapsing missing-or-inaccessible.

    Filters monitor suites and project access. Returns the ORM ``TestDefinition``
    (not ``TestDefinitionSummary``) so the row can be mutated and saved.
    """
    td_uuid = parse_uuid(test_definition_id, "test_definition_id")
    perms = get_project_permissions()
    query = (
        select(TestDefinition)
        .join(TestSuite, TestDefinition.test_suite_id == TestSuite.id)
        .where(
            TestDefinition.id == td_uuid,
            TestDefinition.version_clause(),
            TestSuite.suite_type == SuiteType.REGULAR,
            TestSuite.project_code.in_(perms.allowed_codes),
        )
    )
    td = get_current_session().scalars(query).first()
    if td is None:
        raise MCPResourceNotAccessible("Test definition", test_definition_id)
    return td


def resolve_monitor(monitor_id: str) -> TestDefinition:
    """Resolve a monitor ID to the live ORM model, collapsing missing-or-inaccessible.

    A monitor is a ``TestDefinition`` row whose parent ``TestSuite`` has
    ``suite_type`` of ``monitor`` — the inverse filter from ``resolve_test_definition``.
    Scoped to allowed projects via the parent suite. Returns the ORM model so
    callers can mutate and save / delete.
    """
    monitor_uuid = parse_uuid(monitor_id, "monitor_id")
    perms = get_project_permissions()
    query = (
        select(TestDefinition)
        .join(TestSuite, TestDefinition.test_suite_id == TestSuite.id)
        .where(
            TestDefinition.id == monitor_uuid,
            TestDefinition.version_clause(),
            TestSuite.suite_type == SuiteType.MONITOR,
            TestSuite.project_code.in_(perms.allowed_codes),
        )
    )
    monitor = get_current_session().scalars(query).first()
    if monitor is None:
        raise MCPResourceNotAccessible("Monitor", monitor_id)
    return monitor


def resolve_test_result(test_result_id: str) -> TestResult:
    """Resolve a test result ID to the live ORM model, collapsing missing-or-inaccessible.

    Filters monitor suites and project access via the result's parent test suite.
    """
    result_uuid = parse_uuid(test_result_id, "test_result_id")
    perms = get_project_permissions()
    query = (
        select(TestResult)
        .join(TestSuite, TestResult.test_suite_id == TestSuite.id)
        .where(
            TestResult.id == result_uuid,
            TestSuite.suite_type == SuiteType.REGULAR,
            TestSuite.project_code.in_(perms.allowed_codes),
        )
    )
    result = get_current_session().scalars(query).first()
    if result is None:
        raise MCPResourceNotAccessible("Test result", test_result_id)
    return result


def resolve_test_note(test_note_id: str) -> TestDefinitionNote:
    """Resolve a test note ID to the live ORM model, collapsing missing-or-inaccessible.

    Filters monitor suites and project access via the note's parent test definition.
    """
    note_uuid = parse_uuid(test_note_id, "test_note_id")
    perms = get_project_permissions()
    query = (
        select(TestDefinitionNote)
        .join(TestDefinition, TestDefinitionNote.test_definition_id == TestDefinition.id)
        .join(TestSuite, TestDefinition.test_suite_id == TestSuite.id)
        .where(
            TestDefinitionNote.id == note_uuid,
            TestDefinition.version_clause(),
            TestSuite.suite_type == SuiteType.REGULAR,
            TestSuite.project_code.in_(perms.allowed_codes),
        )
    )
    note = get_current_session().scalars(query).first()
    if note is None:
        raise MCPResourceNotAccessible("Test note", test_note_id)
    return note


def resolve_schedule(schedule_id: str) -> JobSchedule:
    """Resolve a user-managed schedule ID, collapsing missing-or-inaccessible into one error path."""
    sched_uuid = parse_uuid(schedule_id, "schedule_id")
    perms = get_project_permissions()
    sched = JobSchedule.get(
        JobSchedule.id == sched_uuid,
        JobSchedule.key.in_(SCHEDULABLE_JOB_KEYS),
        JobSchedule.project_code.in_(perms.allowed_codes),
    )
    if sched is None:
        raise MCPResourceNotAccessible("Schedule", schedule_id)
    return sched


def resolve_notification(notification_id: str) -> NotificationSettings:
    """Resolve a notification ID, collapsing missing-or-inaccessible into one error path.

    Returns the polymorphic ``NotificationSettings`` subclass (TestRun / ProfilingRun /
    ScoreDrop / Monitor) so callers can read event-specific typed properties.
    """
    notif_uuid = parse_uuid(notification_id, "notification_id")
    perms = get_project_permissions()
    notif = NotificationSettings.get(
        notif_uuid,
        NotificationSettings.project_code.in_(perms.allowed_codes),
    )
    if notif is None:
        raise MCPResourceNotAccessible("Notification", notification_id)
    return notif


def resolve_destination(destination_id: str):
    """Resolve a notification-destination ID, collapsing missing-or-inaccessible into one error.

    Returns the polymorphic ``NotificationDestination`` subclass (``EmailDestination``
    / ``WebhookDestination``) so callers can read type-specific typed properties.
    Deferred import keeps ``mcp/tools/common`` importable without the destinations
    ORM (the destinations module in turn imports from ``notification_settings``,
    which imports ``NotificationDestination`` at file bottom to register the mapper).
    """
    from testgen.common.models.notification_destinations import NotificationDestination
    dest_uuid = parse_uuid(destination_id, "destination_id")
    perms = get_project_permissions()
    destination = NotificationDestination.get(
        dest_uuid,
        NotificationDestination.project_code.in_(perms.allowed_codes),
    )
    if destination is None:
        raise MCPResourceNotAccessible("Notification destination", destination_id)
    return destination


def resolve_aggregate_scope(
    project_code: str | None,
    test_suite_id: str | None = None,
    table_group_id: str | None = None,
) -> list[str]:
    """Validate optional project / test-suite / table-group scope for a cross-run aggregation.

    Resolves any supplied suite or table group (existence + access via the
    ``resolve_*`` helpers), and — when ``project_code`` is also given — requires the
    resolved entity to belong to it, raising a clear error on a cross-project mismatch
    so the query never silently returns empty. Returns the project codes to scope the
    aggregation to.
    """
    perms = get_project_permissions()
    if project_code:
        perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))

    scoped_projects: set[str] = set()
    if test_suite_id:
        suite = resolve_test_suite(test_suite_id)
        if project_code and suite.project_code != project_code:
            raise MCPUserError(
                f"Test suite `{test_suite_id}` belongs to project `{suite.project_code}`, not `{project_code}`."
            )
        scoped_projects.add(suite.project_code)
    if table_group_id:
        table_group = resolve_table_group(table_group_id)
        if project_code and table_group.project_code != project_code:
            raise MCPUserError(
                f"Table group `{table_group_id}` belongs to project `{table_group.project_code}`, not `{project_code}`."
            )
        scoped_projects.add(table_group.project_code)

    if len(scoped_projects) > 1:
        # Suite and table group resolve to different projects (only reachable when no
        # project_code pins the scope). The two filters would AND to an empty result —
        # reject rather than silently return nothing.
        raise MCPUserError("The test suite and table group belong to different projects — narrow to one scope.")

    if project_code:
        return [project_code]
    if scoped_projects:
        return list(scoped_projects)
    return perms.allowed_codes


# Notification event-type labels.

class NotificationEventLabel(StrEnum):
    """User-facing values for notification event types."""

    TEST_RUN = "Test Run"
    PROFILING_RUN = "Profiling Run"
    SCORE_DROP = "Score Drop"
    MONITOR_RUN = "Monitor Alert"


NOTIFICATION_EVENT_LABEL_TO_INTERNAL: dict[NotificationEventLabel, NotificationEvent] = {
    NotificationEventLabel.TEST_RUN: NotificationEvent.test_run,
    NotificationEventLabel.PROFILING_RUN: NotificationEvent.profiling_run,
    NotificationEventLabel.SCORE_DROP: NotificationEvent.score_drop,
    NotificationEventLabel.MONITOR_RUN: NotificationEvent.monitor_run,
}

_NOTIFICATION_EVENT_INTERNAL_TO_LABEL: dict[NotificationEvent, NotificationEventLabel] = {
    v: k for k, v in NOTIFICATION_EVENT_LABEL_TO_INTERNAL.items()
}


def format_notification_event(event: NotificationEvent | str) -> str:
    """Map a stored notification event to its user-facing label."""
    return _NOTIFICATION_EVENT_INTERNAL_TO_LABEL[NotificationEvent(event)].value


# Notification trigger labels — one StrEnum per event type. Same wording the end user sees in the UI:
# ``ui/views/test_runs.py:249-254``, ``ui/views/profiling_runs.py:265-268``,
# ``ui/views/monitors_dashboard.py:323-326``.

class TestRunTriggerLabel(StrEnum):
    ALWAYS = "Always"
    ON_FAILURES = "On test failures"
    ON_WARNINGS = "On test failures and warnings"
    ON_CHANGES = "On new test failures and warnings"


TEST_RUN_TRIGGER_LABEL_TO_INTERNAL: dict[TestRunTriggerLabel, TestRunNotificationTrigger] = {
    TestRunTriggerLabel.ALWAYS: TestRunNotificationTrigger.always,
    TestRunTriggerLabel.ON_FAILURES: TestRunNotificationTrigger.on_failures,
    TestRunTriggerLabel.ON_WARNINGS: TestRunNotificationTrigger.on_warnings,
    TestRunTriggerLabel.ON_CHANGES: TestRunNotificationTrigger.on_changes,
}


class ProfilingRunTriggerLabel(StrEnum):
    ALWAYS = "Always"
    ON_CHANGES = "On new hygiene issues"


PROFILING_RUN_TRIGGER_LABEL_TO_INTERNAL: dict[ProfilingRunTriggerLabel, ProfilingRunNotificationTrigger] = {
    ProfilingRunTriggerLabel.ALWAYS: ProfilingRunNotificationTrigger.always,
    ProfilingRunTriggerLabel.ON_CHANGES: ProfilingRunNotificationTrigger.on_changes,
}


class MonitorTriggerLabel(StrEnum):
    ON_ANOMALIES = "On anomalies"


MONITOR_TRIGGER_LABEL_TO_INTERNAL: dict[MonitorTriggerLabel, MonitorNotificationTrigger] = {
    MonitorTriggerLabel.ON_ANOMALIES: MonitorNotificationTrigger.on_anomalies,
}

_TEST_RUN_TRIGGER_INTERNAL_TO_LABEL = {v: k for k, v in TEST_RUN_TRIGGER_LABEL_TO_INTERNAL.items()}
_PROFILING_RUN_TRIGGER_INTERNAL_TO_LABEL = {v: k for k, v in PROFILING_RUN_TRIGGER_LABEL_TO_INTERNAL.items()}
_MONITOR_TRIGGER_INTERNAL_TO_LABEL = {v: k for k, v in MONITOR_TRIGGER_LABEL_TO_INTERNAL.items()}


def format_notification_trigger(event: NotificationEvent | str, settings: dict | None) -> str | None:
    """Map a notification's stored trigger value to its user-facing label.

    Returns ``None`` for ``score_drop`` (no trigger — thresholds drive it) or when
    ``settings`` carries no ``trigger`` key.
    """
    raw = settings.get("trigger") if settings else None
    if raw is None:
        return None
    event_enum = NotificationEvent(event)
    if event_enum is NotificationEvent.test_run:
        return _TEST_RUN_TRIGGER_INTERNAL_TO_LABEL[TestRunNotificationTrigger(raw)].value
    if event_enum is NotificationEvent.profiling_run:
        return _PROFILING_RUN_TRIGGER_INTERNAL_TO_LABEL[ProfilingRunNotificationTrigger(raw)].value
    if event_enum is NotificationEvent.monitor_run:
        return _MONITOR_TRIGGER_INTERNAL_TO_LABEL[MonitorNotificationTrigger(raw)].value
    return None


# Flavor display labels are the single source of truth in ``common/flavors.py``
# (shared with the UI page). These maps just re-shape them for the MCP layer.
SQL_FLAVOR_CODE_TO_LABEL: dict[str, SqlFlavorLabel] = dict(FLAVOR_CODE_TO_LABEL)
SQL_FLAVOR_LABEL_TO_CODE: dict[SqlFlavorLabel, str] = {
    label: code for code, label in FLAVOR_CODE_TO_LABEL.items()
}
SQL_FLAVOR_CODE_TO_FAMILY: dict[str, str] = dict(FLAVOR_CODE_TO_FAMILY)


def parse_sql_flavor(value: str) -> tuple[SqlFlavorLabel, str, str]:
    """Validate a user-facing ``sql_flavor`` value and return ``(label, code, family)``.

    Accepts either the display label (``Azure SQL Database``) or the flavor code
    (``azure_mssql``), in any casing. The code is accepted because it is the slug in
    ``testgen://connection-parameters/<code>`` resource URIs.
    """
    label = match_enum(value, SqlFlavorLabel)
    if label is None:
        label = match_mapping(value, SQL_FLAVOR_CODE_TO_LABEL)
    if label is None:
        valid = ", ".join(f.value for f in SqlFlavorLabel)
        raise MCPUserError(f"Invalid sql_flavor `{value}`. Valid values: {valid}")
    code = SQL_FLAVOR_LABEL_TO_CODE[label]
    return label, code, SQL_FLAVOR_CODE_TO_FAMILY[code]


def format_flavor_label(sql_flavor_code: str | None) -> str:
    """Map a stored ``sql_flavor_code`` to its user-facing display label.

    Returns the raw code as a fallback when the code is not in the registry — defensive
    against a never-shipping-but-still-stored value rather than letting an LLM see ``None``.
    """
    if sql_flavor_code is None:
        return ""
    label = SQL_FLAVOR_CODE_TO_LABEL.get(sql_flavor_code)
    return label.value if label else sql_flavor_code


def resolve_mode(code: str, mode_label: str | None) -> FlavorMode:
    """Resolve the ``FlavorMode`` for a flavor + supplied ``connection_mode`` label.

    Single-mode flavors take no ``connection_mode`` (passing one is an error).
    Multi-mode flavors require a valid one.
    """
    schema = schema_for(code)
    if len(schema.modes) == 1 and schema.modes[0].mode is None:
        if mode_label is not None:
            raise MCPUserError(f"{schema.label} does not take a connection_mode.")
        return schema.modes[0]

    valid = [str(m.mode) for m in schema.modes if m.mode is not None]
    if mode_label is None:
        raise MCPUserError(f"{schema.label} requires a connection_mode. Valid values: {', '.join(valid)}.")
    for fmode in schema.modes:
        if fmode.mode is not None and str(fmode.mode) == mode_label:
            return fmode
    raise MCPUserError(
        f"Invalid connection_mode `{mode_label}` for {schema.label}. Valid values: {', '.join(valid)}."
    )


def apply_connection_params(
    connection: Connection,
    code: str,
    mode_label: str | None,
    params: dict[str, object],
) -> None:
    """Map a label-keyed ``connection_params`` dict onto a ``Connection``.

    * Resolves the mode and applies its forced ``sets`` columns (auth flags,
      Databricks PAT ``project_user='token'``).
    * Maps each supplied label to its ``Connection`` column (casting ``Port``).
    * Toggles ``connect_by_url`` from the presence of ``URL`` vs the host-group
      fields, rejecting an ambiguous mix.

    Raises ``MCPUserError`` on unknown keys, an unsupported / conflicting ``URL``,
    or an invalid / missing mode.
    """
    fmode = resolve_mode(code, mode_label)
    fields_by_label = {f.label: f for f in fmode.fields}
    url_fields = {f.label for f in fmode.fields if f.requirement is Req.REQUIRED_UNLESS_URL}

    valid_keys = set(fields_by_label)
    if fmode.supports_url:
        valid_keys.add(URL_FIELD.label)
    unknown = [key for key in params if key not in valid_keys]
    if unknown:
        raise MCPUserError(
            f"Unknown connection_params for {schema_for(code).label}: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(valid_keys))}."
        )

    has_url = URL_FIELD.label in params
    provided_url_fields = [key for key in params if key in url_fields]
    if has_url and not fmode.supports_url:
        raise MCPUserError(f"{schema_for(code).label} does not support URL connections in this mode.")
    if has_url and provided_url_fields:
        raise MCPUserError(
            f"Provide either a `URL` or host fields ({', '.join(sorted(url_fields))}), not both."
        )

    # Forced columns first so explicit params can't be clobbered by sets.
    for attr, value in fmode.sets.items():
        setattr(connection, attr, value)

    # mssql-family SPN identity: two fields packed into project_user as
    # ``<cid>@<tid>``. Enforce both-or-neither.
    is_spn_compound = (
        "Client ID" in fields_by_label
        and "Tenant ID" in fields_by_label
        and fields_by_label["Client ID"].column == "project_user"
        and fields_by_label["Tenant ID"].column == "project_user"
    )
    if is_spn_compound:
        cid = params.get("Client ID")
        tid = params.get("Tenant ID")
        if bool(cid) != bool(tid):
            raise MCPUserError(
                "Service Principal auth requires both `Client ID` and `Tenant ID`; provide either both or neither."
            )
        if cid and tid:
            if "@" in str(cid) or "@" in str(tid):
                raise MCPUserError(
                    "`Client ID` and `Tenant ID` must not contain `@`; the compound identifier is built automatically."
                )
            connection.project_user = f"{cid}@{tid}"
        else:
            existing = connection.project_user or ""
            if existing.count("@") != 1 or not all(existing.split("@")):
                raise MCPUserError(
                    "Service Principal auth requires `Client ID` and `Tenant ID`; no valid stored identity to fall back on."
                )

    for label, value in params.items():
        if label == URL_FIELD.label:
            continue
        if is_spn_compound and label in ("Client ID", "Tenant ID"):
            continue
        write_conn_field(connection, fields_by_label[label], value)

    if has_url:
        connection.connect_by_url = True
        connection.url = str(params[URL_FIELD.label])
    elif provided_url_fields:
        connection.connect_by_url = False
    if not fmode.supports_url:
        # An existing URL-mode configuration would otherwise carry
        # ``connect_by_url=True`` into the SPN+URL guard downstream.
        connection.connect_by_url = False


def reject_fixed_max_threads(sql_flavor_code: str, max_threads: int | None) -> None:
    """Raise when ``max_threads`` is a value other than the one its flavor fixes.

    ``None`` and the fixed value itself are both accepted.
    """
    fixed = fixed_max_threads(sql_flavor_code)
    if max_threads is not None and fixed is not None and max_threads != fixed:
        label = FLAVOR_CODE_TO_LABEL.get(sql_flavor_code, sql_flavor_code)
        raise MCPUserError(
            f"`max_threads` cannot be set for {label}. It runs inside TestGen rather than on a "
            f"separate database server, so its thread count is fixed at {fixed}."
        )


def effective_mode(connection: Connection, connection_mode: str | None) -> str | None:
    """Mode label to apply: the explicit override, else the connection's current mode."""
    if connection_mode is not None:
        return connection_mode
    inferred = infer_mode(connection)
    return str(inferred) if inferred is not None else None


def raise_validation_error(errors: list[str], header: str) -> NoReturn:
    bullets = "\n".join(f"- {err}" for err in errors)
    raise MCPUserError(f"{header}\n\n{bullets}")


def render_connection_body(doc: MdDoc, connection: Connection) -> None:
    """Render every non-secret connection field below the heading.

    Encrypted columns are filtered out via ``ConnField.secret``.
    """
    doc.field("ID", connection.connection_id, code=True)
    doc.field("Project", connection.project_code, code=True)
    doc.field("Type", format_flavor_label(connection.sql_flavor_code))

    # Each populated, non-secret field under its flavor-specific label
    # (e.g. "Catalog" for Databricks, "Login URL" for Salesforce).
    for fld, value in connection_display_values(connection):
        doc.field(fld.label, value, code=fld.column != "project_port")

    if (authentication := authentication_label(connection)) is not None:
        doc.field("Authentication", authentication)
    if connection.max_threads is not None:
        # The pinned value, not the stored column: a flavor that fixes its thread count runs at
        # that count whatever the column says, and reporting the column sends an operator looking
        # for a parallelism they never had.
        doc.field("Max Threads", connection.effective_max_threads)
    if connection.max_query_chars is not None:
        doc.field("Max Expression Length", connection.max_query_chars)


_TARGET_DB_ERROR_WITHHELD = (
    "The target database reported an error. Its text is withheld by the source-data "
    "protection policy on this install, because driver messages quote the value that "
    "caused them."
)


def target_db_error_text(message: str | None) -> str | None:
    """Render a target-database error message, withholding its text under the protection mode.

    Driver errors quote the offending datum — ``invalid input syntax for type integer:
    "alice@example.com"`` — so the text carries source data even though the error itself
    is useful signal. Returns ``message`` unchanged when the mode is off.
    """
    if message and mcp_source_data_protected():
        return _TARGET_DB_ERROR_WITHHELD
    return message
