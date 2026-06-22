from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import NoReturn, TypeVar
from uuid import UUID

from sqlalchemy import select

from testgen.common.date_service import parse_since
from testgen.common.enums import (
    Disposition,
    ImpactDimension,
    IssueLikelihood,
    JobStatus,
    MonitorType,
    PiiRisk,
    QualityDimension,
)
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, FLAVOR_CODE_TO_LABEL, SqlFlavorLabel
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
from testgen.common.models.scheduler import SCHEDULABLE_JOB_KEYS, JobSchedule
from testgen.common.models.scores import ScoreCategory, ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition, TestDefinitionNote, TestType
from testgen.common.models.test_result import TestResult, TestResultStatus
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions
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


def parse_enum(value: str, enum_cls: type[_ParsedEnum], label: str) -> _ParsedEnum:
    try:
        return enum_cls(value)
    except ValueError as err:
        valid = ", ".join(member.value for member in enum_cls)
        raise MCPUserError(f"Invalid {label} `{value}`. Valid values: {valid}") from err


def parse_result_status(value: str) -> TestResultStatus:
    try:
        return TestResultStatus(value)
    except ValueError as err:
        valid = ", ".join(s.value for s in TestResultStatus)
        raise MCPUserError(f"Invalid status `{value}`. Valid values: {valid}") from err


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
    try:
        return ImpactDimension(value)
    except ValueError as err:
        valid = ", ".join(d.value for d in ImpactDimension)
        raise MCPUserError(f"Invalid impact_dimension `{value}`. Valid values: {valid}") from err


def parse_quality_dimension(value: str) -> QualityDimension:
    try:
        return QualityDimension(value)
    except ValueError as err:
        valid = ", ".join(d.value for d in QualityDimension)
        raise MCPUserError(f"Invalid quality_dimension `{value}`. Valid values: {valid}") from err


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
    try:
        return ScoreGroupBy(value)
    except ValueError as err:
        valid = ", ".join(g.value for g in ScoreGroupBy)
        raise MCPUserError(f"Invalid group_by `{value}`. Valid values: {valid}") from err


def parse_score_filter_field(value: str) -> ScoreFilterField:
    try:
        return ScoreFilterField(value)
    except ValueError as err:
        if value in {ScoreGroupBy.QUALITY_DIMENSION.value, ScoreGroupBy.IMPACT_DIMENSION.value}:
            raise MCPUserError(
                f"`{value}` is not a valid filter field — use group_by='{value}' instead"
            ) from err
        valid = ", ".join(f.value for f in ScoreFilterField)
        raise MCPUserError(f"Invalid filter field `{value}`. Valid values: {valid}") from err


def parse_score_type(value: str) -> ScoreType:
    try:
        return ScoreType(value)
    except ValueError as err:
        valid = ", ".join(s.value for s in ScoreType)
        raise MCPUserError(f"Invalid score_type `{value}`. Valid values: {valid}") from err


def parse_category(value: str) -> ScoreCategory:
    """Validate a ``category`` argument and return the stored ``ScoreCategory``.

    Accepts the display-form values exposed by ``get_quality_scores``'s
    ``group_by`` argument (e.g. ``Quality Dimension``, ``Data Source``).
    """
    try:
        arg = ScoreCategoryArg(value)
    except ValueError as err:
        valid = ", ".join(c.value for c in ScoreCategoryArg)
        raise MCPUserError(f"Invalid category `{value}`. Valid values: {valid}") from err
    return ScoreCategory(SCORE_CATEGORY_ARG_TO_COLUMN[arg])


# Maps user-facing run-status labels to underlying ``JobStatus`` values. Transient states
# (Starting/Canceling) are excluded because they're sub-second and noisy as filters.
# ``Pending`` collapses PENDING+CLAIMED; ``Canceled`` collapses CANCEL_REQUESTED+CANCELED.
_RUN_STATUS_FILTER: dict[str, list[JobStatus]] = {
    "Pending": [JobStatus.PENDING, JobStatus.CLAIMED],
    "Running": [JobStatus.RUNNING],
    "Completed": [JobStatus.COMPLETED],
    "Canceled": [JobStatus.CANCEL_REQUESTED, JobStatus.CANCELED],
    "Error": [JobStatus.ERROR],
}


def parse_run_status_filter(value: str) -> list[JobStatus]:
    """Map a user-facing run status label (e.g. ``Pending``) to the underlying ``JobStatus`` values."""
    statuses = _RUN_STATUS_FILTER.get(value)
    if statuses is None:
        valid = ", ".join(_RUN_STATUS_FILTER.keys())
        raise MCPUserError(f"Invalid status `{value}`. Valid values: {valid}")
    return statuses


class FailureGroupBy(StrEnum):
    """User-facing values accepted for the ``group_by`` argument on ``get_failure_summary``."""

    TEST_TYPE = "test_type"
    TABLE = "table"
    COLUMN = "column"


def parse_failure_group_by(value: str) -> FailureGroupBy:
    try:
        return FailureGroupBy(value)
    except ValueError as err:
        valid = ", ".join(g.value for g in FailureGroupBy)
        raise MCPUserError(f"Invalid group_by `{value}`. Valid values: {valid}") from err


def format_run_duration(started_at: datetime | None, completed_at: datetime | None) -> str | None:
    """Render an elapsed duration as ``Xs`` / ``Xm Ys`` / ``Xh Ym``. Returns ``None`` if either bound is missing."""
    if not started_at or not completed_at:
        return None
    seconds = int((completed_at - started_at).total_seconds())
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


# Monitor type — internal ``test_type`` value ↔ user-facing short label (the form
# callers pass and the form rendered in output).
_MONITOR_TYPE_USER_TO_DB: dict[str, MonitorType] = {
    "freshness": MonitorType.FRESHNESS,
    "volume": MonitorType.VOLUME,
    "schema": MonitorType.SCHEMA,
    "metric": MonitorType.METRIC,
}


def parse_monitor_type(value: str, label: str = "monitor_type") -> MonitorType:
    """Validate a user-facing monitor type label and return the stored ``MonitorType``.

    Accepts ``freshness`` / ``volume`` / ``schema`` / ``metric``. ``label`` names the
    caller's argument in the error message — pass ``"anomaly_type"`` when the
    public arg is named differently from ``monitor_type``.
    """
    db_value = _MONITOR_TYPE_USER_TO_DB.get(value)
    if db_value is None:
        valid = ", ".join(_MONITOR_TYPE_USER_TO_DB)
        raise MCPUserError(f"Invalid {label} `{value}`. Valid values: {valid}")
    return db_value


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
    try:
        return MonitorTableSort(value)
    except ValueError as err:
        valid = ", ".join(s.value for s in MonitorTableSort)
        raise MCPUserError(f"Invalid sort_by `{value}`. Valid values: {valid}") from err


def parse_disposition(value: str) -> Disposition:
    """Validate a user-facing disposition label and return the stored ``Disposition``.

    Accepts ``Confirmed``, ``Dismissed``, ``Muted`` (user-facing labels). The DB encodes
    ``INACTIVE`` for "Muted" — see ``Disposition``.
    """
    db_value = _DISPOSITION_USER_TO_DB.get(value)
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
    if value == _NO_DECISION:
        return None
    db_value = _DISPOSITION_USER_TO_DB.get(value)
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
        try:
            likelihood = IssueLikelihood(value)
        except ValueError:
            invalid.append(value)
            continue
        if likelihood not in _FILTERABLE_LIKELIHOODS:
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
    code = _PII_CATEGORY_TO_CODE.get(value)
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
    try:
        member = GeneralType(value)
    except ValueError as err:
        valid = ", ".join(t.value for t in GeneralType)
        raise MCPUserError(f"Invalid general_type `{value}`. Valid values: {valid}") from err
    return GENERAL_TYPE_TO_CODE[member]


def parse_suggested_data_type(value: str) -> SuggestedDataType:
    try:
        return SuggestedDataType(value)
    except ValueError as err:
        valid = ", ".join(t.value for t in SuggestedDataType)
        raise MCPUserError(f"Invalid suggested_data_type `{value}`. Valid values: {valid}") from err


def parse_column_order_by(value: str) -> ColumnOrderBy:
    try:
        return ColumnOrderBy(value)
    except ValueError as err:
        valid = ", ".join(o.value for o in ColumnOrderBy)
        raise MCPUserError(f"Invalid order_by `{value}`. Valid values: {valid}") from err


def parse_profile_metrics(values: list[str]) -> list[ProfileMetric]:
    """Validate a list of profile metric names. Empties out with one error listing all invalids."""
    if not values:
        raise MCPUserError("`metrics` cannot be empty — name at least one metric to trend.")
    parsed: list[ProfileMetric] = []
    invalid: list[str] = []
    for value in values:
        try:
            parsed.append(ProfileMetric(value))
        except ValueError:
            invalid.append(value)
    if invalid:
        valid = ", ".join(m.value for m in ProfileMetric)
        raise MCPUserError(f"Invalid metrics {invalid}. Valid values: {valid}")
    return parsed


# ``pii_flag`` encodes risk as a single-character prefix: ``A`` (High), ``B`` (Moderate), ``C`` (Low).
_PII_RISK_LEVEL_TO_CODE: dict[str, str] = {"High": "A", "Moderate": "B", "Low": "C"}


def parse_pii_risk_level(value: str) -> str:
    """Validate a column-profile pii_risk_level filter and return the stored prefix code."""
    code = _PII_RISK_LEVEL_TO_CODE.get(value)
    if code is None:
        valid = ", ".join(_PII_RISK_LEVEL_TO_CODE)
        raise MCPUserError(f"Invalid pii_risk_level `{value}`. Valid values: {valid}")
    return code


def parse_pii_risk_list(values: list[str]) -> list[PiiRisk]:
    parsed: list[PiiRisk] = []
    invalid: list[str] = []
    for value in values:
        try:
            parsed.append(PiiRisk(value))
        except ValueError:
            invalid.append(value)
    if invalid:
        valid = ", ".join(r.value for r in PiiRisk)
        raise MCPUserError(f"Invalid pii_risk values {invalid}. Valid values: {valid}")
    return parsed


def resolve_test_type(short_name: str) -> str:
    """Resolve a test type short name to its internal code."""
    matches = TestType.select_where(TestType.test_name_short == short_name)
    if not matches:
        raise MCPUserError(
            f"Unknown test type: `{short_name}`. Use the testgen://test-types resource to see available types."
        )
    return matches[0].test_type


def resolve_issue_type(name: str) -> str:
    """Resolve a hygiene issue type human label to its internal id (case-sensitive exact match)."""
    matches = HygieneIssueType.select_where(HygieneIssueType.name == name)
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


# Entity resolution helpers — see mcp-roadmap.md "Entity Resolution Helpers" guideline.
# Extract a new resolve_<entity> here when a second caller needs the same parse-uuid +
# perm-scoped lookup + collapsed-error pattern.

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
        TestSuite.is_monitor.isnot(True),
        TestSuite.project_code.in_(perms.allowed_codes),
    )
    if suite is None:
        raise MCPResourceNotAccessible("Test suite", test_suite_id)
    return suite


def resolve_monitored_table_group(table_group_id: str) -> tuple[TableGroup, TestSuite | None]:
    """Resolve a table group ID and look up its linked monitor suite.

    Returns ``(table_group, monitor_suite)``. ``monitor_suite`` is ``None`` when the
    table group has no ``monitor_test_suite_id`` set, or that pointer doesn't resolve
    to an ``is_monitor=True`` suite — callers render the "not monitored" output in
    that case rather than raising an inaccessible error. Raises
    ``MCPResourceNotAccessible`` when the table group itself is missing or out of
    scope.
    """
    tg = resolve_table_group(table_group_id)
    if tg.monitor_test_suite_id is None:
        return tg, None
    suite = TestSuite.get(tg.monitor_test_suite_id, TestSuite.is_monitor.is_(True))
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
            TestSuite.is_monitor.isnot(True),
            TestSuite.project_code.in_(perms.allowed_codes),
        )
    )
    td = get_current_session().scalars(query).first()
    if td is None:
        raise MCPResourceNotAccessible("Test definition", test_definition_id)
    return td


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
            TestSuite.is_monitor.isnot(True),
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
            TestSuite.is_monitor.isnot(True),
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
    """Validate a user-facing ``sql_flavor`` value and return ``(label, code, family)``."""
    try:
        label = SqlFlavorLabel(value)
    except ValueError as err:
        valid = ", ".join(f.value for f in SqlFlavorLabel)
        raise MCPUserError(f"Invalid sql_flavor `{value}`. Valid values: {valid}") from err
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


# ===========================================================================
# Connection-parameter contract (MCP input vocabulary)
#
# The per-flavor connection shape: which auth modes exist and which fields each
# needs, keyed by their UI labels (which double as ``connection_params`` keys).
# This is MCP-only input vocabulary + parsing — it mirrors the per-flavor JS
# forms in ``ui/static/js/components/connection_form.js`` (NOT sourced from
# Python), and drives both the connection tools and the
# ``testgen://connection-parameters/{flavor}`` resource. Field labels map to the
# (often leaky) ``Connection`` columns here so the tool's arg surface speaks the
# target-DB vocabulary.
# ===========================================================================


class ConnectionMode(StrEnum):
    PASSWORD = "Password"  # noqa: S105 — auth-mode label, not a credential
    KEY_PAIR = "Key-Pair"
    MANAGED_IDENTITY = "Managed Identity"
    ACCESS_TOKEN = "Access Token"  # noqa: S105 — auth-mode label, not a credential
    SERVICE_PRINCIPAL = "Service Principal (OAuth)"
    JWT_BEARER = "JWT Bearer Flow"
    CLIENT_CREDENTIALS = "Client Credentials Flow"
    SERVICE_ACCOUNT = "Service Account Key"


class Req(StrEnum):
    REQUIRED = "required"  # always required in this mode
    REQUIRED_UNLESS_URL = "required_unless_url"  # required only in host mode
    OPTIONAL = "optional"


@dataclass(frozen=True)
class ConnField:
    label: str  # exact UI label == connection_params key
    column: str  # Connection ORM attribute it maps to
    requirement: Req
    secret: bool = False


@dataclass(frozen=True)
class FlavorMode:
    mode: ConnectionMode | None  # None for single-auth flavors
    fields: tuple[ConnField, ...]  # excludes the URL field
    supports_url: bool  # whether the URL alternative is offered
    # Columns forced regardless of supplied params (auth flags, Databricks PAT user).
    sets: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FlavorSchema:
    code: str
    label: str
    modes: tuple[FlavorMode, ...]
    url_field: ConnField | None  # the shared URL field when any mode supports_url


# -- reusable field definitions ---------------------------------------------

_HOST = ConnField("Host", "project_host", Req.REQUIRED_UNLESS_URL)
_PORT = ConnField("Port", "project_port", Req.REQUIRED_UNLESS_URL)
_DATABASE = ConnField("Database", "project_db", Req.REQUIRED_UNLESS_URL)
_SERVICE_NAME = ConnField("Service Name", "project_db", Req.REQUIRED_UNLESS_URL)
_USERNAME = ConnField("Username", "project_user", Req.REQUIRED)
_PASSWORD_OPT = ConnField("Password", "project_pw_encrypted", Req.OPTIONAL, secret=True)
_PASSWORD_REQ = ConnField("Password", "project_pw_encrypted", Req.REQUIRED, secret=True)
_WAREHOUSE = ConnField("Warehouse", "warehouse", Req.OPTIONAL)
_PRIVATE_KEY = ConnField("Private Key", "private_key", Req.REQUIRED, secret=True)
_PRIVATE_KEY_PASSPHRASE = ConnField("Private Key Passphrase", "private_key_passphrase", Req.OPTIONAL, secret=True)
_URL = ConnField("URL", "url", Req.REQUIRED)

# Databricks
_HTTP_PATH_RU = ConnField("HTTP Path", "http_path", Req.REQUIRED_UNLESS_URL)
_HTTP_PATH_REQ = ConnField("HTTP Path", "http_path", Req.REQUIRED)
_HOST_REQ = ConnField("Host", "project_host", Req.REQUIRED)
_PORT_REQ = ConnField("Port", "project_port", Req.REQUIRED)
_CATALOG = ConnField("Catalog", "project_db", Req.REQUIRED_UNLESS_URL)
_CATALOG_REQ = ConnField("Catalog", "project_db", Req.REQUIRED)
_ACCESS_TOKEN = ConnField("Access Token", "project_pw_encrypted", Req.REQUIRED, secret=True)
_CLIENT_ID = ConnField("Client ID", "project_user", Req.REQUIRED)
_CLIENT_SECRET = ConnField("Client Secret", "project_pw_encrypted", Req.REQUIRED, secret=True)

# BigQuery / Salesforce
_SERVICE_ACCOUNT_KEY = ConnField("Service Account Key", "service_account_key", Req.REQUIRED, secret=True)
_LOGIN_URL = ConnField("Login URL", "project_host", Req.REQUIRED)
_CONSUMER_KEY = ConnField("Consumer Key", "project_user", Req.REQUIRED)
_SF_USERNAME = ConnField("Username", "project_db", Req.REQUIRED)
_CONSUMER_SECRET = ConnField("Consumer Secret", "project_pw_encrypted", Req.REQUIRED, secret=True)


def _host_auth_schema(code: str, *, db_field: ConnField = _DATABASE) -> FlavorSchema:
    """Single-mode host/URL flavors (PostgreSQL, Redshift, MSSQL, Oracle, SAP HANA)."""
    return FlavorSchema(
        code=code,
        label=FLAVOR_CODE_TO_LABEL[code],
        modes=(
            FlavorMode(mode=None, fields=(_HOST, _PORT, db_field, _USERNAME, _PASSWORD_OPT), supports_url=True),
        ),
        url_field=_URL,
    )


def _azure_schema(code: str) -> FlavorSchema:
    return FlavorSchema(
        code=code,
        label=FLAVOR_CODE_TO_LABEL[code],
        modes=(
            FlavorMode(
                mode=ConnectionMode.PASSWORD,
                fields=(_HOST, _PORT, _DATABASE, _USERNAME, _PASSWORD_OPT),
                supports_url=True,
                sets={"connect_with_identity": False},
            ),
            FlavorMode(
                mode=ConnectionMode.MANAGED_IDENTITY,
                fields=(_HOST, _PORT, _DATABASE),
                supports_url=True,
                sets={"connect_with_identity": True},
            ),
        ),
        url_field=_URL,
    )


FLAVOR_CONNECTION_SCHEMA: dict[str, FlavorSchema] = {
    "postgresql": _host_auth_schema("postgresql"),
    "redshift": _host_auth_schema("redshift"),
    "redshift_spectrum": _host_auth_schema("redshift_spectrum"),
    "mssql": _host_auth_schema("mssql"),
    "oracle": _host_auth_schema("oracle", db_field=_SERVICE_NAME),
    "sap_hana": _host_auth_schema("sap_hana"),
    "azure_mssql": _azure_schema("azure_mssql"),
    "synapse_mssql": _azure_schema("synapse_mssql"),
    "snowflake": FlavorSchema(
        code="snowflake",
        label=FLAVOR_CODE_TO_LABEL["snowflake"],
        modes=(
            FlavorMode(
                mode=ConnectionMode.KEY_PAIR,
                fields=(_HOST, _PORT, _DATABASE, _USERNAME, _WAREHOUSE, _PRIVATE_KEY, _PRIVATE_KEY_PASSPHRASE),
                supports_url=True,
                sets={"connect_by_key": True},
            ),
            FlavorMode(
                mode=ConnectionMode.PASSWORD,
                fields=(_HOST, _PORT, _DATABASE, _USERNAME, _WAREHOUSE, _PASSWORD_REQ),
                supports_url=True,
                sets={"connect_by_key": False},
            ),
        ),
        url_field=_URL,
    ),
    "databricks": FlavorSchema(
        code="databricks",
        label=FLAVOR_CODE_TO_LABEL["databricks"],
        modes=(
            FlavorMode(
                mode=ConnectionMode.ACCESS_TOKEN,
                fields=(_HOST, _PORT, _HTTP_PATH_RU, _CATALOG, _ACCESS_TOKEN),
                supports_url=True,
                # PAT auth: the username is always the literal 'token'.
                sets={"connect_by_key": False, "project_user": "token"},
            ),
            FlavorMode(
                mode=ConnectionMode.SERVICE_PRINCIPAL,
                fields=(_HOST_REQ, _PORT_REQ, _HTTP_PATH_REQ, _CATALOG_REQ, _CLIENT_ID, _CLIENT_SECRET),
                supports_url=False,
                sets={"connect_by_key": True},
            ),
        ),
        url_field=_URL,
    ),
    "bigquery": FlavorSchema(
        code="bigquery",
        label=FLAVOR_CODE_TO_LABEL["bigquery"],
        modes=(FlavorMode(mode=None, fields=(_SERVICE_ACCOUNT_KEY,), supports_url=False),),
        url_field=None,
    ),
    "salesforce_data360": FlavorSchema(
        code="salesforce_data360",
        label=FLAVOR_CODE_TO_LABEL["salesforce_data360"],
        modes=(
            FlavorMode(
                mode=ConnectionMode.JWT_BEARER,
                fields=(_LOGIN_URL, _CONSUMER_KEY, _SF_USERNAME, _PRIVATE_KEY),
                supports_url=False,
                sets={"connect_by_key": True},
            ),
            FlavorMode(
                mode=ConnectionMode.CLIENT_CREDENTIALS,
                fields=(_LOGIN_URL, _CONSUMER_KEY, _CONSUMER_SECRET),
                supports_url=False,
                sets={"connect_by_key": False},
            ),
        ),
        url_field=None,
    ),
}


def schema_for(code: str) -> FlavorSchema:
    """Return the connection schema for a flavor code. Raises ``KeyError`` if unknown."""
    return FLAVOR_CONNECTION_SCHEMA[code]


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


def infer_mode(connection: Connection) -> ConnectionMode | None:
    """Reverse of a mode's ``sets`` flags — derive the active mode from a stored
    connection so update/validation can pick the right field set without the
    caller re-supplying ``connection_mode``.
    """
    code = connection.sql_flavor_code
    schema = FLAVOR_CONNECTION_SCHEMA.get(code)
    if schema is None or (len(schema.modes) == 1 and schema.modes[0].mode is None):
        return None

    if code in {"azure_mssql", "synapse_mssql"}:
        return ConnectionMode.MANAGED_IDENTITY if connection.connect_with_identity else ConnectionMode.PASSWORD
    if code == "snowflake":
        return ConnectionMode.KEY_PAIR if connection.connect_by_key else ConnectionMode.PASSWORD
    if code == "databricks":
        return ConnectionMode.SERVICE_PRINCIPAL if connection.connect_by_key else ConnectionMode.ACCESS_TOKEN
    if code == "salesforce_data360":
        return ConnectionMode.JWT_BEARER if connection.connect_by_key else ConnectionMode.CLIENT_CREDENTIALS
    return None


def _mode_for_connection(connection: Connection) -> FlavorMode:
    """Pick the FlavorMode matching a connection's current flags (for validation)."""
    schema = schema_for(connection.sql_flavor_code)
    if len(schema.modes) == 1:
        return schema.modes[0]
    active = infer_mode(connection)
    for fmode in schema.modes:
        if fmode.mode == active:
            return fmode
    return schema.modes[0]


def connection_display_fields(connection: Connection) -> list[ConnField]:
    """Active-mode fields (plus the URL field when in URL mode), in schema order.

    For rendering a connection back to the user with the flavor-specific UI label
    for each populated column (e.g. ``Catalog`` for Databricks, ``Login URL`` for
    Salesforce). Callers skip secrets and empty values.
    """
    schema = schema_for(connection.sql_flavor_code)
    fields = list(_mode_for_connection(connection).fields)
    if schema.url_field is not None and getattr(connection, "connect_by_url", False):
        fields.append(schema.url_field)
    return fields


def connection_field_labels(connection: Connection) -> dict[str, str]:
    """Map each ``Connection`` column to its flavor/mode-specific UI label.

    Used to label diff output. Columns outside the active mode fall back to the
    caller's generic labels.
    """
    schema = schema_for(connection.sql_flavor_code)
    labels = {fld.column: fld.label for fld in _mode_for_connection(connection).fields}
    if schema.url_field is not None:
        labels[schema.url_field.column] = schema.url_field.label
    return labels


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
        valid_keys.add(_URL.label)
    unknown = [key for key in params if key not in valid_keys]
    if unknown:
        raise MCPUserError(
            f"Unknown connection_params for {schema_for(code).label}: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(valid_keys))}."
        )

    has_url = _URL.label in params
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

    for label, value in params.items():
        if label == _URL.label:
            continue
        column = fields_by_label[label].column
        setattr(connection, column, str(value) if column == "project_port" and value is not None else value)

    if has_url:
        connection.connect_by_url = True
        connection.url = str(params[_URL.label])
    elif provided_url_fields:
        connection.connect_by_url = False


# -- field-requirement validation -------------------------------------------

_CONNECTION_NAME_MIN = 3
_CONNECTION_NAME_MAX = 40
_MAX_THREADS_MIN = 1
_MAX_THREADS_MAX = 8
_MAX_QUERY_CHARS_MIN = 500
_MAX_QUERY_CHARS_MAX = 50000


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _required_fields_for(connection: Connection) -> list[ConnField]:
    """Schema fields that must be non-empty for this connection's flavor + active
    mode, accounting for the URL alternative.
    """
    fmode = _mode_for_connection(connection)
    using_url = fmode.supports_url and bool(connection.connect_by_url)

    required: list[ConnField] = []
    for fld in fmode.fields:
        if fld.requirement is Req.REQUIRED:
            required.append(fld)
        elif fld.requirement is Req.REQUIRED_UNLESS_URL and not using_url:
            required.append(fld)

    schema = schema_for(connection.sql_flavor_code)
    if using_url and schema.url_field is not None:
        required.append(schema.url_field)
    return required


def validate_connection_fields(connection: Connection) -> list[str]:
    """Return every validation error (empty list = valid).

    Mirrors the per-flavor JS form validators in
    ``ui/static/js/components/connection_form.js``. The connection tools call this
    and raise their user-facing error containing the bullets. Field errors use the
    UI label (e.g. ``Host``) so the LLM sees the same wording as a UI user.
    """
    errors: list[str] = []
    flavor_label = FLAVOR_CODE_TO_LABEL.get(connection.sql_flavor_code, connection.sql_flavor_code)

    name = connection.connection_name
    if _missing(name):
        errors.append("`connection_name` is required.")
    elif not (_CONNECTION_NAME_MIN <= len(name.strip()) <= _CONNECTION_NAME_MAX):
        errors.append(
            f"`connection_name` must be between {_CONNECTION_NAME_MIN} and {_CONNECTION_NAME_MAX} characters."
        )

    for fld in _required_fields_for(connection):
        if _missing(getattr(connection, fld.column, None)):
            errors.append(f"`{fld.label}` is required for {flavor_label}.")

    threads = connection.max_threads
    if threads is not None and not (_MAX_THREADS_MIN <= threads <= _MAX_THREADS_MAX):
        errors.append(f"`max_threads` must be between {_MAX_THREADS_MIN} and {_MAX_THREADS_MAX}.")

    query_chars = connection.max_query_chars
    if query_chars is not None and not (_MAX_QUERY_CHARS_MIN <= query_chars <= _MAX_QUERY_CHARS_MAX):
        errors.append(f"`max_query_chars` must be between {_MAX_QUERY_CHARS_MIN} and {_MAX_QUERY_CHARS_MAX}.")

    return errors


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
    for fld in connection_display_fields(connection):
        if fld.secret:
            continue
        value = getattr(connection, fld.column, None)
        if value in (None, ""):
            continue
        doc.field(fld.label, value, code=fld.column != "project_port")

    doc.field("Authentication", authentication_label(connection))
    if connection.max_threads is not None:
        doc.field("Max Threads", connection.max_threads)
    if connection.max_query_chars is not None:
        doc.field("Max Expression Length", connection.max_query_chars)


def authentication_label(connection: Connection) -> str:
    """The connection's auth method: the active connection mode for multi-mode
    flavors, else the implicit method (service account key, else password).
    """
    mode = infer_mode(connection)
    if mode is not None:
        return str(mode)
    if connection.service_account_key:
        return "Service Account Key"
    return "Password"
