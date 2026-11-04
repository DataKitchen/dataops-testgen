import hashlib
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from itertools import zip_longest
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    FetchedValue,
    ForeignKey,
    String,
    Text,
    TypeDecorator,
    asc,
    delete,
    exists,
    func,
    insert,
    inspect,
    or_,
    select,
    text,
    true,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import case, literal

from testgen.common import query_variables
from testgen.common.audit.actions import AuditTargetType
from testgen.common.audit.fields import AuditFields
from testgen.common.audit.names import object_name
from testgen.common.audit.safety import isolated_read
from testgen.common.clean_sql import NonNumericValueError, normalize_value_list, parse_value_list
from testgen.common.database.database_service import get_flavor_service
from testgen.common.enums import (
    MANAGED_TEST_TYPES,
    VALUE_LIST_TEST_TYPES,
    MonitorCalculation,
    MonitorType,
    OdcsDimension,
    SuiteType,
    TestScope,
)
from testgen.common.models import Base, get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, YNString, ZeroIfEmptyInteger
from testgen.common.models.entity import Entity, EntityMinimal
from testgen.common.models.suite_version import (
    FrozenVersionError,
    RemovedInDraftError,
    SuiteVersion,
    UnmatchedInDraftError,
)
from testgen.common.models.test_suite import TestSuite
from testgen.utils import is_uuid4

TestRunStatus = Literal["Running", "Complete", "Error", "Cancelled"]


class TestRunType(StrEnum):
    """The engine that executes a test (stored on ``test_types.run_type``)."""

    QUERY = "QUERY"
    CAT = "CAT"
    METADATA = "METADATA"


class Severity(StrEnum):
    FAIL = "Fail"
    WARNING = "Warning"
    LOG = "Log"


class TestAlgorithm(StrEnum):
    """SQL-derived algorithm family for a test type (faceted picker axis)."""

    BOUNDARY_CHECK = "Boundary check"
    COUNTING = "Counting"
    PATTERN_REGEX = "Pattern / regex"
    SET_LOOKUP = "Set / lookup"
    STATISTICAL_DRIFT = "Statistical drift"
    AGGREGATE_RECONCILIATION = "Aggregate reconciliation"
    FRESHNESS_TIME = "Freshness / time"
    SCHEMA_METADATA = "Schema / metadata"
    CUSTOM_SQL = "Custom SQL"


class StatisticalTechnique(StrEnum):
    """Named statistical technique a test type uses to evaluate its measure."""

    COHENS_D = "Cohen's D"
    COHENS_H = "Cohen's H"
    OUTLIER_DETECTION = "Outlier Detection"
    SD_SHIFT = "SD Shift"
    JENSEN_SHANNON_DIVERGENCE = "Jensen-Shannon Divergence"
    PREDICTIVE_MODEL = "Predictive Model"


class TestCriteria(StrEnum):
    """What a test type needs to be set up (faceted picker axis).

    Derived, not stored: ``derive_test_criteria`` is the single source of truth, shared by the
    UI lookup and MCP so the value never drifts between surfaces.
    """

    DEFINED_RULE = "Defined Rule"
    DEFINED_THRESHOLD = "Defined Threshold"
    DEFINED_VALUE = "Defined Value"
    LIST_OF_VALUES = "List of Values"
    REFERENCE_DATASET = "Reference Dataset"
    CUSTOM_CRITERIA = "Custom Criteria"


# Predefined validity/integrity rules — the user just enables them; the rule itself is fixed
# (dedup/uniqueness and standard format validators). Not separable from structural attributes
# alone: e.g. Valid_Month is structurally identical to the Defined-Value test Pattern_Match
# (both column-scoped, Pattern / regex, with baseline_value + threshold_value params).
_DEFINED_RULE_TESTS = frozenset({
    "Dupe_Rows", "Unique", "Email_Format", "Street_Addr_Pattern",
    "Valid_Characters", "Valid_Month", "Valid_US_Zip", "Valid_US_Zip3", "Valid_US_CA_Zip",
})
# The user asserts the expected value/pattern the column should hold (a constant, a regex
# baseline, or simply that a value is present). Enumerated for the same reason as above.
_DEFINED_VALUE_TESTS = frozenset({
    "Constant", "Pattern_Match", "Required",
})


def derive_test_criteria(
    test_type: str,
    test_scope: str | None,
    algorithm: str | None,
) -> TestCriteria:
    """Classify a test type by the kind of setup it requires.

    Single source of truth for the Criteria facet — call from both the UI lookup and MCP rather
    than reproducing the rules. Scope and algorithm resolve the cleanly-typed buckets (referential
    is checked before Set / lookup so Combo_Match stays Reference Dataset). Defined Rule, Defined
    Value, and Defined Threshold can't be told apart from structural attributes, so the first two
    are enumerated and Defined Threshold is the fallthrough. Custom Criteria covers the custom
    scope and any scope whose algorithm is Custom SQL. Outside the referential scope, Aggregate
    reconciliation compares a measure with a stored baseline, which makes it Defined Value.
    """
    if test_scope == "custom" or algorithm == TestAlgorithm.CUSTOM_SQL:
        return TestCriteria.CUSTOM_CRITERIA
    if test_scope == "referential":
        return TestCriteria.REFERENCE_DATASET
    if algorithm == TestAlgorithm.SET_LOOKUP:
        return TestCriteria.LIST_OF_VALUES
    if algorithm == TestAlgorithm.AGGREGATE_RECONCILIATION:
        return TestCriteria.DEFINED_VALUE
    if test_type in _DEFINED_RULE_TESTS:
        return TestCriteria.DEFINED_RULE
    if test_type in _DEFINED_VALUE_TESTS:
        return TestCriteria.DEFINED_VALUE
    return TestCriteria.DEFINED_THRESHOLD


class InvalidTestDefinitionFields(ValueError):
    """Aggregated field-level validation errors. ``errors``: ``dict[field_name, reason]``."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _is_blank(value: object) -> bool:
    # NullIfEmptyString columns turn ``""`` into NULL on write — treat both as cleared.
    return value is None or (isinstance(value, str) and not value.strip())


CUSTOM_METADATA_MAX_KEYS = 50
CUSTOM_METADATA_MAX_BYTES = 10_240

MISSING_TEST_DEFINITION_MESSAGE = "Test definition no longer exists."


class MissingTestDefinitionError(ValueError):
    """Raised when a write targets a test definition that has been deleted."""

# The key under custom_metadata reserved for ODCS quality-rule fields (dimension, tags,
# customProperties, ...) that a contract render promotes onto the rule it emits. Kept here,
# beside the validator that enforces its shape, rather than in the odcs package: the package
# imports models, not the other way around, and a later task imports this constant from here.
ODCS_RULE_METADATA_KEY = "odcs"


def validate_custom_metadata(value: object) -> str | None:
    """Return an error message if ``value`` is not a valid ``custom_metadata`` payload, else ``None``.

    ``custom_metadata`` must be a JSON object (key-value pairs), bounded in key count and serialized
    size. A value under the reserved ``odcs`` key, when present, must itself be a JSON object, and
    any of its ``dimension``, ``tags``, ``customProperties``, ``authoritativeDefinitions``,
    ``name``, ``description``, ``businessImpact``, ``method``, ``schedule``, or ``scheduler`` fields it carries must
    conform to the shape a rendered contract document requires. An unrecognized key at the
    subtree's own top level is accepted -- it is simply not emitted at render, which keeps a
    document written by a newer TestGen readable by an older one. That tolerance does not extend
    inside ``customProperties`` or ``authoritativeDefinitions`` entries: each entry's item shape is
    sealed in the pinned ODCS schema (``additionalProperties: false``), so a stray key there is
    invalid ODCS permanently, not a field a future TestGen might define -- accepting one here would
    let a term save cleanly and then block its contract version's freeze weeks later. Shared by
    every write path — ``TestDefinition.validate`` (UI/CLI/MCP) and the ``TestDefinitionExport``
    import schema — so the rule has a single definition.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        return "must be a JSON object of key-value pairs"
    if len(value) > CUSTOM_METADATA_MAX_KEYS:
        return f"must have at most {CUSTOM_METADATA_MAX_KEYS} keys"
    if len(json.dumps(value)) > CUSTOM_METADATA_MAX_BYTES:
        return f"must be at most {CUSTOM_METADATA_MAX_BYTES} bytes when serialized as JSON"
    if ODCS_RULE_METADATA_KEY in value:
        return _validate_odcs_rule_metadata(value[ODCS_RULE_METADATA_KEY])
    return None


# Reserved-subtree fields that must be strings when present. Only these six carry that
# constraint -- ``dimension``, ``tags``, ``customProperties`` and ``authoritativeDefinitions``
# each have their own list-of-objects shape instead.
_ODCS_STRING_FIELDS = ("name", "description", "businessImpact", "method", "schedule", "scheduler")

# The pinned ODCS schema's ``CustomProperty``/``AuthoritativeDefinitions`` item objects are
# sealed (``additionalProperties: false``); a stray key inside one is invalid ODCS
# permanently, so it is rejected here rather than accepted and left to break a freeze weeks
# later. Mirrors the schema's own field lists -- kept here as a plain hardcoded list rather
# than read from the bundled schema file, since this module is not allowed to import the
# ``odcs`` package (that package imports models, not the other way around). Ordered as the
# schema lists them: ``common.odcs.quality_rules`` rebuilds each entry in this order.
ODCS_CUSTOM_PROPERTY_FIELDS: tuple[str, ...] = ("id", "property", "value", "description", "vendor")
ODCS_CUSTOM_PROPERTY_REQUIRED_FIELDS = frozenset({"property", "value"})
ODCS_AUTHORITATIVE_DEFINITION_FIELDS: tuple[str, ...] = ("id", "url", "type", "description")
ODCS_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS = frozenset({"url", "type"})

# ``$defs.StableId`` from the pinned ODCS schema -- the type both ``CustomProperty.id`` and
# ``AuthoritativeDefinitions[].id`` are a ``$ref`` to. A value here that does not match is the
# same failure shape as a stray key: it saves cleanly and then blocks the version's freeze.
#
# The rule's own ``id`` (``contract_term_id``) needs no equivalent check: a minted id comes from
# ``slugify_term_id`` (``^[A-Za-z0-9_-]+$``, a strict subset of this pattern), and an imported one
# arrives in a document already validated against the schema.
ODCS_STABLE_ID_PATTERN = re.compile(r"^[^\s.#/\\@!%&^]+$")


def _valid_sealed_entries(items: object, required: frozenset[str], allowed: tuple[str, ...]) -> bool:
    """Whether ``items`` is a list of objects, each carrying every ``required`` key, no key
    outside ``allowed``, and an ``id`` (when present) that is a string matching
    ``ODCS_STABLE_ID_PATTERN`` -- the shape a sealed ODCS item schema demands."""
    if not isinstance(items, list):
        return False
    for entry in items:
        if not isinstance(entry, dict) or not (required <= entry.keys()) or not (entry.keys() <= set(allowed)):
            return False
        entry_id = entry.get("id")
        if entry_id is not None and not (isinstance(entry_id, str) and ODCS_STABLE_ID_PATTERN.match(entry_id)):
            return False
    return True


def _validate_odcs_rule_metadata(subtree: object) -> str | None:
    """Return an error message if the reserved ``odcs`` subtree is malformed, else ``None``."""
    if not isinstance(subtree, dict):
        return f"`{ODCS_RULE_METADATA_KEY}` must be a JSON object"

    dimension = subtree.get("dimension")
    if dimension is not None:
        try:
            OdcsDimension(dimension)
        except ValueError:
            allowed = ", ".join(f"`{member.value}`" for member in OdcsDimension)
            return f"`{ODCS_RULE_METADATA_KEY}.dimension` must be one of {allowed} (got `{dimension}`)"

    for field in _ODCS_STRING_FIELDS:
        value = subtree.get(field)
        if value is not None and not isinstance(value, str):
            return f"`{ODCS_RULE_METADATA_KEY}.{field}` must be a string"

    tags = subtree.get("tags")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
        return f"`{ODCS_RULE_METADATA_KEY}.tags` must be a list of strings"

    custom_properties = subtree.get("customProperties")
    if custom_properties is not None and not _valid_sealed_entries(
        custom_properties, ODCS_CUSTOM_PROPERTY_REQUIRED_FIELDS, ODCS_CUSTOM_PROPERTY_FIELDS
    ):
        return (
            f"`{ODCS_RULE_METADATA_KEY}.customProperties` must be a list of objects, each with a "
            f"`property` and a `value`, no keys other than {sorted(ODCS_CUSTOM_PROPERTY_FIELDS)}, and an "
            f"`id` (when present) matching `{ODCS_STABLE_ID_PATTERN.pattern}`"
        )

    authoritative_definitions = subtree.get("authoritativeDefinitions")
    if authoritative_definitions is not None and not _valid_sealed_entries(
        authoritative_definitions, ODCS_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS, ODCS_AUTHORITATIVE_DEFINITION_FIELDS
    ):
        return (
            f"`{ODCS_RULE_METADATA_KEY}.authoritativeDefinitions` must be a list of objects, each with "
            f"a `url` and a `type`, no keys other than {sorted(ODCS_AUTHORITATIVE_DEFINITION_FIELDS)}, and an "
            f"`id` (when present) matching `{ODCS_STABLE_ID_PATTERN.pattern}`"
        )

    return None


TERM_ID_MAX_LENGTH = 100
_DIGEST_LENGTH = 8

_INVALID = re.compile(r"[^A-Za-z0-9_-]+")
_REPEATS = re.compile(r"_{2,}")


def slugify_term_id(*parts: str | None) -> str:
    """Build a term identity from natural-key parts, matching ``^[A-Za-z0-9_-]+$``.

    Each part is reduced to the allowed character set and the surviving parts are joined with
    ``-``, bounded to ``TERM_ID_MAX_LENGTH``. Raises ``ValueError`` when no part survives.

    The identity sits in a unique index, so a key the reduction does not render exactly carries
    a digest of the raw parts and stays distinct from every key that reduces the same way. The
    reduction loses information wherever it collapses a run of disallowed characters, cuts at
    the bound, keeps a ``-`` that then reads as the one joining parts, or drops an absent part
    and shifts the ones after it. The result stays a pure function of the parts.
    """
    slugged = []
    for part in parts:
        if not part:
            continue
        cleaned = _REPEATS.sub("_", _INVALID.sub("_", part.strip())).strip("_-")
        if cleaned:
            slugged.append(cleaned)

    if not slugged:
        raise ValueError("no part of the natural key survives slugification")

    joined = "-".join(slugged)
    present = [part for part in parts if part]
    renders_exactly = (
        present == slugged
        and present == list(parts[: len(present)])
        and not any("-" in part for part in slugged)
        and len(joined) <= TERM_ID_MAX_LENGTH
    )
    if renders_exactly:
        return joined

    # Joined on a character no identifier carries, so the digest tells apart the keys the
    # reduction cannot -- including ones differing only in how many parts they have.
    raw_key = "\x00".join(part or "" for part in parts)
    digest = hashlib.sha256(raw_key.encode()).hexdigest()[:_DIGEST_LENGTH]
    kept = joined[: TERM_ID_MAX_LENGTH - _DIGEST_LENGTH - 1].rstrip("-_")
    return f"{kept}-{digest}"


class ParamFieldsMixin:
    """Parsed access to default_parm_columns/prompts/help metadata.

    Mixed into both TestTypeSummary (dataclass) and TestType (ORM model).
    """

    @property
    def param_columns(self) -> set[str]:
        """Column names declared as editable parameters for this test type."""
        return {column for column, _, _ in self.param_fields}

    @property
    def param_fields(self) -> list[tuple[str, str, str]]:
        """Parsed parameter metadata as (column, prompt, help) tuples, preserving order."""
        if not self.default_parm_columns:
            return []
        columns = [c.strip() for c in self.default_parm_columns.split(",")]
        prompts = [p.strip() for p in self.default_parm_prompts.split(",")] if self.default_parm_prompts else []
        helps = [h.strip() for h in self.default_parm_help.split("|")] if self.default_parm_help else []
        # Pad prompts with column names (sensible fallback) and helps with ""
        prompts.extend(columns[len(prompts):])
        return list(zip_longest(columns, prompts, helps, fillvalue=""))


@dataclass
class TestTypeSummary(ParamFieldsMixin, EntityMinimal):
    test_name_short: str
    default_test_description: str
    measure_uom: str
    measure_uom_description: str
    default_parm_columns: str
    default_parm_prompts: str
    default_parm_help: str
    default_parm_required: str
    default_severity: str
    test_scope: TestScope
    dq_dimension: str
    default_impact_dimension: str
    usage_notes: str


@dataclass
class TestDefinitionSummary(TestTypeSummary):
    id: UUID
    table_groups_id: UUID
    profile_run_id: UUID
    test_type: str
    test_suite_id: UUID
    test_description: str
    schema_name: str
    table_name: str
    column_name: str
    skip_errors: int
    baseline_ct: str
    baseline_unique_ct: str
    baseline_value: str
    baseline_value_ct: str
    threshold_value: str
    baseline_sum: str
    baseline_avg: str
    baseline_sd: str
    lower_tolerance: str
    upper_tolerance: str
    subset_condition: str
    groupby_names: str
    having_condition: str
    window_date_column: str
    window_days: int
    match_schema_name: str
    match_table_name: str
    match_column_names: str
    match_subset_condition: str
    match_groupby_names: str
    match_having_condition: str
    custom_query: str
    history_calculation: str
    history_calculation_upper: str
    history_lookback: int
    test_active: bool
    test_definition_status: str
    severity: str
    lock_refresh: bool
    last_auto_gen_date: datetime
    profiling_as_of_date: datetime
    last_manual_update: datetime
    export_to_observability: bool
    prediction: dict[str, dict[str, float]] | None
    flagged: bool
    impact_dimension: str | None
    external_url: str | None
    custom_metadata: dict | None
    version_id: UUID

    @property
    def display_name(self) -> str:
        """Human-readable test type name, falling back to the internal code."""
        return self.test_name_short or self.test_type


@dataclass
class TestDefinitionMinimal(EntityMinimal):
    id: UUID
    table_groups_id: UUID
    test_type: str
    test_suite_id: UUID
    schema_name: str
    table_name: str
    column_name: str
    test_active: bool
    lock_refresh: bool
    test_name_short: str


class ThresholdMode(StrEnum):
    """How a monitor's bounds are determined — derived from which fields on the
    definition are populated. Values match the UI selector labels."""
    PREDICTION = "Prediction Model"
    HISTORICAL = "Historical Calculation"
    STATIC = "Static Thresholds"
    NONE = "N/A"


def derive_threshold_mode(
    test_type: str,
    history_calculation: str | None,
    history_calculation_upper: str | None,
    lower_tolerance: str | None,
    upper_tolerance: str | None,
) -> tuple[ThresholdMode, str | None, str | None]:
    """Pick a monitor's threshold mode and the bounds tuple that applies under it.

    Detection mirrors the UI form (``test_definition_form.js``): a
    ``history_calculation`` of exactly ``"PREDICT"`` flags Prediction mode; any
    other non-empty value flags Historical (not available for Freshness); empty
    falls through to Static — the default for Freshness / Volume / Metric.
    Schema never has thresholds.

    Bounds returned per mode:

    * Prediction: ``None, None``. Runtime bounds live in the per-run prediction
      JSONB; they are not configuration and do not surface here.
    * Historical: ``(history_calculation, history_calculation_upper)`` — stored
      as expressions like ``"Minimum"`` / ``"Maximum"`` that the execution layer
      evaluates against the lookback window.
    * Static for Freshness: ``(None, upper_tolerance)``. Only an upper bound applies.
    * Static (Volume / Metric): ``(lower_tolerance, upper_tolerance)``.
    """
    if test_type == MonitorType.SCHEMA.value:
        return ThresholdMode.NONE, None, None
    if history_calculation == MonitorCalculation.PREDICT:
        return ThresholdMode.PREDICTION, None, None
    if history_calculation and test_type != MonitorType.FRESHNESS.value:
        return ThresholdMode.HISTORICAL, history_calculation, history_calculation_upper
    if test_type == MonitorType.FRESHNESS.value:
        return ThresholdMode.STATIC, None, upper_tolerance
    return ThresholdMode.STATIC, lower_tolerance, upper_tolerance


@dataclass
class MonitorForecastPoint(EntityMinimal):
    """One future forecast point read from a Prediction-Model monitor's stored
    ``prediction`` JSONB. Each point is a ``(test_time, lower_bound, upper_bound)``
    triple at a specific upcoming timestamp; collectively they extend the
    historical event series forward under the suite's active prediction
    sensitivity. Surfaced as a separate forecast section on
    ``list_monitor_events``, never as an event."""
    test_time: datetime
    lower_bound: float | None
    upper_bound: float | None


def forecast_points_from_prediction(
    prediction: dict | None,
    sensitivity: str,
) -> list[MonitorForecastPoint]:
    """Extract forecast points for a sensitivity from a monitor's stored
    ``prediction`` JSONB, sorted by time ascending (nearest future point
    first).

    The JSONB is keyed as ``"lower_tolerance|<sensitivity>" → {epoch_ms: value}``
    and ``"upper_tolerance|<sensitivity>" → {epoch_ms: value}`` — matches the
    format the dashboard reads at ``monitors_dashboard.py`` via
    ``datetime.fromtimestamp(int(timestamp) / 1000.0, UTC)``. Returns ``[]``
    when the monitor isn't in Prediction Model mode (no JSONB) or when the
    sensitivity has no stored series. Standalone so it works against either
    the ``TestDefinition`` ORM row or the ``TestDefinitionSummary`` dataclass
    — both carry the same ``prediction`` field shape.
    """
    if not prediction:
        return []
    lower_series = prediction.get(f"lower_tolerance|{sensitivity}") or {}
    upper_series = prediction.get(f"upper_tolerance|{sensitivity}") or {}
    if not lower_series and not upper_series:
        return []

    all_keys = sorted(set(lower_series) | set(upper_series), key=int)
    points: list[MonitorForecastPoint] = []
    for k in all_keys:
        ts = datetime.fromtimestamp(int(k) / 1000.0, UTC)
        lower = lower_series.get(k)
        upper = upper_series.get(k)
        points.append(MonitorForecastPoint(
            test_time=ts,
            lower_bound=float(lower) if lower is not None else None,
            upper_bound=float(upper) if upper is not None else None,
        ))
    return points


@dataclass
class MonitorConfig(EntityMinimal):
    """One configured monitor — produced by ``TestDefinition.list_monitor_configs_for_table``.

    ``threshold_mode`` is derived from the underlying definition's
    ``history_calculation``: ``"PREDICT"`` flags Prediction Model; any other
    non-empty value flags Historical Calculation (not available for Freshness);
    empty falls through to Static — the default for Freshness, Volume, and
    Metric. Schema_Drift is presence-only and reports N/A.

    ``threshold_lower`` / ``threshold_upper`` carry the bounds active under
    the current mode — static tolerances for Static, history-calc expressions
    (e.g. ``"Minimum"`` / ``"Maximum"``) for Historical, ``None`` for
    Prediction (the runtime bands live on each event, not the configuration).
    For Freshness in Static mode only the upper bound applies.

    ``metric_name`` is the user-defined name for a Metric monitor (stored on
    the underlying definition's ``column_name`` column, but it is the metric's
    name rather than a column reference). ``custom_query`` is the metric's SQL
    expression. Both are only set for ``Metric_Trend``.
    """
    monitor_id: UUID
    test_type: str
    table_name: str
    metric_name: str | None
    threshold_mode: ThresholdMode
    threshold_lower: str | None
    threshold_upper: str | None
    custom_query: str | None


class QueryString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, _dialect) -> str | None:
        if value and isinstance(value, str):
            value = value.strip()
            if value.endswith(";"):
                value = value[:-1]
        return value or None


def _enum_by_value(enum_cls: type[StrEnum]) -> Enum:
    """Map a StrEnum to its VARCHAR column by member value (not name) so reads return enum members.

    These columns store the display value (e.g. ``"Boundary check"``), which differs from the enum
    member name, so the default name-based mapping would not round-trip.
    """
    return Enum(enum_cls, native_enum=False, values_callable=lambda cls: [member.value for member in cls])


# Scopes whose tests carry a column_name: the column under test (column), a "Test Focus" label
# (custom), or the aggregate expression or categorical column list under test (referential).
COLUMN_NAME_SCOPES: frozenset[str] = frozenset({TestScope.COLUMN, TestScope.CUSTOM, TestScope.REFERENTIAL})

# Test types that are never offered as regular tests: the monitor types, which only monitor suites
# generate and manage, and the managed types, whose definitions TestGen creates and removes itself.
NON_PUBLIC_TEST_TYPES: frozenset[str] = frozenset(
    {*(monitor_type.value for monitor_type in MonitorType), *MANAGED_TEST_TYPES}
)


class ManagedTestDefinitionError(ValueError):
    """Raised when a write would delete, move or copy a definition of a managed test type."""

    def __init__(self) -> None:
        super().__init__(
            "TestGen manages this test and removes it when what it checks goes away. "
            "It cannot be deleted, moved, or copied on its own."
        )


class TestType(ParamFieldsMixin, Entity):
    __tablename__ = "test_types"

    _get_by = "test_type"

    id: str = Column(String)
    test_type: str = Column(String, primary_key=True, nullable=False)
    test_name_short: str = Column(String)
    test_name_long: str = Column(String)
    test_description: str = Column(String)
    except_message: str = Column(String)
    measure_uom: str = Column(String)
    measure_uom_description: str = Column(String)
    selection_criteria: str = Column(Text)
    dq_score_prevalence_formula: str = Column(Text)
    dq_score_risk_factor: str = Column(Text)
    column_name_prompt: str = Column(Text)
    column_name_help: str = Column(Text)
    default_parm_columns: str = Column(Text)
    default_parm_values: str = Column(Text)
    default_parm_prompts: str = Column(Text)
    default_parm_help: str = Column(Text)
    default_parm_required: str = Column(Text)
    default_severity: str = Column(String)
    run_type: TestRunType = Column(String)
    test_scope: TestScope = Column(String)
    dq_dimension: str = Column(String)
    impact_dimension: str = Column(String)
    health_dimension: str = Column(String)
    algorithm: TestAlgorithm | None = Column(_enum_by_value(TestAlgorithm))
    statistical_technique: StatisticalTechnique | None = Column(_enum_by_value(StatisticalTechnique))
    threshold_description: str = Column(String)
    usage_notes: str = Column(String)
    active: str = Column(String)
    uploaded_version: str | None = Column(String(20))
    ai_redact_values: bool = Column(Boolean, default=False, nullable=False)
    """Whether this type's ``result_measure`` can carry an actual source-data value
    rather than a violation count or a normalized statistic. Surfaces that withhold
    source data from an AI consumer drop the measure only for flagged types."""
    null_measure_fails: bool = Column(Boolean, default=False, nullable=False)
    """Whether a CAT test of this type fails when its measure is NULL, instead of passing."""
    column_general_types: list[str] | None = Column(postgresql.ARRAY(String))
    """General type codes of the columns a column-scope test of this type works on. None means any."""
    exact_measures: list[str] | None = Column(postgresql.ARRAY(String))
    """Profile measures this type needs measured exactly; it is not generated on a column where one is not."""

    # Unmapped columns: generation_template, result_visualization, result_visualization_params, overrides

    @property
    def criteria(self) -> TestCriteria:
        """Setup-kind facet, derived via the shared classifier (see ``derive_test_criteria``)."""
        return derive_test_criteria(self.test_type, self.test_scope, self.algorithm)

    _summary_columns = (
        *[key for key in TestTypeSummary.__annotations__.keys() if key not in ("default_test_description", "default_impact_dimension")],
        test_description.label("default_test_description"),
        impact_dimension.label("default_impact_dimension"),
    )

    @classmethod
    def select_summary_where(cls, *clauses) -> Iterable[TestTypeSummary]:
        results = cls._select_columns_where(cls._summary_columns, *clauses)
        return [TestTypeSummary(**row) for row in results]

    @classmethod
    def is_public(cls):
        """WHERE clause restricting a test-type catalog to the types offered as regular tests."""
        return cls.test_type.notin_(NON_PUBLIC_TEST_TYPES)

    @property
    def redacts_values(self) -> bool:
        """Whether this type's ``result_measure`` can carry a source-data value.

        ``NULL`` reads as redacted, so the answer stays safe on a database where the
        column was added without its backfill.
        """
        return self.ai_redact_values is not False

    @classmethod
    def value_redacted_types(cls, rows: Iterable["TestType"] | None = None) -> frozenset[str]:
        """Test type codes whose ``result_measure`` can carry a source-data value.

        Pass ``rows`` to classify test types already in hand; omit it to query. Rows
        must cover every type, not just the active ones — a result outlives the
        deactivation of its type, and its measure is classified the same either way.
        """
        return frozenset(
            row.test_type for row in (cls.select_where() if rows is None else rows) if row.redacts_values
        )


def required_fields_for(test_type: TestType) -> set[str]:
    """Fields that must be present and non-empty for the given test type.

    - Column, custom and referential tests implicitly require ``column_name``.
    - Tests that read a physical table implicitly require ``table_name`` — every scope except
      ``tablegroup`` (which spans the whole group) and the ``CUSTOM`` test type (whose
      ``custom_query`` supplies its own FROM clause; the table is only an output label).
    - ``default_parm_required`` is a CSV of ``Y``/``N``/``A`` aligned with ``default_parm_columns``;
      positions marked ``Y`` are required.
    """
    required: set[str] = set()
    if test_type.test_scope in COLUMN_NAME_SCOPES:
        required.add("column_name")
    if test_type.test_scope != "tablegroup" and test_type.test_type != "CUSTOM":
        required.add("table_name")
    return required | _param_fields_flagged(test_type, "Y")


def one_of_fields_for(test_type: TestType) -> list[str]:
    """Parameters of which at least one must be present and non-empty, in configured order.

    These are the positions marked ``A`` in ``default_parm_required``.
    """
    flagged = _param_fields_flagged(test_type, "A")
    return [col for col in _param_columns(test_type) if col in flagged]


# `test_definitions` columns a write sets that the schema bounds, and their widths in characters.
# Must match the column widths in 030_initialize_new_schema_structure.sql.
_COLUMN_WIDTHS: dict[str, int] = {
    "test_description": 1000,
    "schema_name": 100,
    "table_name": 100,
    "column_name": 500,
    "baseline_ct": 1000,
    "baseline_unique_ct": 1000,
    "baseline_value": 1000,
    "baseline_value_ct": 1000,
    "threshold_value": 1000,
    "baseline_sum": 1000,
    "baseline_avg": 1000,
    "baseline_sd": 1000,
    "lower_tolerance": 1000,
    "upper_tolerance": 1000,
    "subset_condition": 500,
    "having_condition": 500,
    "window_date_column": 100,
    "match_schema_name": 100,
    "match_table_name": 100,
    "match_column_names": 200,
    "match_subset_condition": 500,
    "match_having_condition": 500,
    "history_calculation": 1000,
    "history_calculation_upper": 1000,
    "contract_term_id": 100,
}
_UNBOUNDED_TEXT_COLUMNS = ("groupby_names", "match_groupby_names", "custom_query", "external_url")
_INTEGER_COLUMNS = ("skip_errors", "window_days", "history_lookback")
_MAX_INTEGER = 2**31 - 1


def _storage_errors(value_of: Callable[[str], object]) -> dict[str, str]:
    """Fields whose value the ``test_definitions`` column cannot store, mapped to the reason.

    ``value_of`` returns a field's value by name.
    """
    errors: dict[str, str] = {}
    for field in (*_COLUMN_WIDTHS, *_UNBOUNDED_TEXT_COLUMNS, *_INTEGER_COLUMNS):
        value = value_of(field)
        if value is None:
            continue
        if isinstance(value, dict | list):
            errors[field] = "must be a single value"
        elif field in _INTEGER_COLUMNS and not _is_storable_integer(value):
            errors[field] = "must be a whole number"
        elif (width := _COLUMN_WIDTHS.get(field)) and len(str(value)) > width:
            errors[field] = f"must be at most {width} characters"
    return errors


def _is_storable_integer(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str):
        if value == "":
            return True
        digits = value.strip()
        if not (digits.isascii() and digits.lstrip("+-").isdigit()):
            return False
        value = int(digits)
    return isinstance(value, int) and abs(value) <= _MAX_INTEGER


def missing_required_fields(test_type: TestType, value_of: Callable[[str], object]) -> dict[str, str]:
    """Required fields of ``test_type`` that are blank, mapped to the reason.

    ``value_of`` returns a field's value by name. Covers the fields from
    :func:`required_fields_for` and the group from :func:`one_of_fields_for`.
    """
    errors = {
        field: f"required for test type `{test_type.test_name_short}`"
        for field in required_fields_for(test_type)
        if _is_blank(value_of(field))
    }
    one_of = one_of_fields_for(test_type)
    if one_of and all(_is_blank(value_of(field)) for field in one_of):
        listed = ", ".join(f"`{field}`" for field in one_of)
        for field in one_of:
            errors[field] = f"at least one of {listed} is required for test type `{test_type.test_name_short}`"
    return errors


def test_definition_errors(test_type: TestType, value_of: Callable[[str], object]) -> dict[str, str]:
    """Fields of a test definition of ``test_type`` that are invalid, mapped to the reason.

    ``value_of`` returns a field's value by name. Empty when the definition is valid.
    """
    errors: dict[str, str] = {}

    severity = value_of("severity")
    if severity:
        try:
            Severity(severity)
        except ValueError:
            valid = ", ".join(f"`{member.value}`" for member in Severity)
            errors["severity"] = f"must be one of {valid} (got `{severity}`)"

    if test_type.test_scope not in COLUMN_NAME_SCOPES and not _is_blank(value_of("column_name")):
        errors["column_name"] = (
            f"test type `{test_type.test_name_short}` has scope `{test_type.test_scope}`; "
            f"column_name does not apply to this scope"
        )

    if not _is_blank(value_of("custom_query")) and "custom_query" not in test_type.param_columns:
        errors["custom_query"] = (
            f"test type `{test_type.test_name_short}` does not accept a custom query"
        )
    elif variable_error := query_variables.validate_declarations(value_of("custom_query")):
        errors["custom_query"] = variable_error

    if not _is_blank(value_of("subset_condition")) and "subset_condition" not in test_type.param_columns:
        errors["subset_condition"] = (
            f"test type `{test_type.test_name_short}` does not accept a record subset condition"
        )

    metadata_error = validate_custom_metadata(value_of("custom_metadata"))
    if metadata_error:
        errors["custom_metadata"] = metadata_error

    errors.update(missing_required_fields(test_type, value_of))
    errors.update(_storage_errors(value_of))
    return errors


def stores_empty_string(table_groups_id: UUID | None) -> bool:
    """Whether the database a table group's connection reaches keeps the empty string apart from NULL."""
    # connection imports, through table_group and monitor, this module
    from testgen.common.models.connection import Connection

    connection = Connection.get_by_table_group(table_groups_id) if table_groups_id else None
    return get_flavor_service(connection.sql_flavor).stores_empty_string if connection else True


def stored_value_list(
    test_type: str,
    baseline_value: str | None,
    general_type: str | None,
    empty_string_stored: Callable[[], bool] = lambda: True,
) -> str | None:
    """Return ``baseline_value`` as a test of ``test_type`` on a column of ``general_type`` stores it.

    A value-list type's list is rewritten by ``normalize_value_list``, as numbers for a numeric column.
    Any other value is returned unchanged.

    Args:
        empty_string_stored: Returns whether the column's database keeps the empty string apart from NULL,
            called only for a list holding nothing else. When it does not, the list is refused, since it
            would match nothing.

    Raises:
        InvalidTestDefinitionFields: A numeric column's list holds a value that is not a number, or the
            list holds only the empty string where the database stores it as NULL.
    """
    if test_type not in VALUE_LIST_TEST_TYPES or _is_blank(baseline_value):
        return baseline_value
    try:
        value_list = normalize_value_list(baseline_value, numeric=general_type == "N")
    except NonNumericValueError as error:
        raise InvalidTestDefinitionFields(
            {"baseline_value": f"contains a value that is not a number: {error.value}"}
        ) from error
    if not any(parse_value_list(value_list)) and not empty_string_stored():
        raise InvalidTestDefinitionFields(
            {"baseline_value": "on Oracle the empty string is NULL, so the list must hold at least one other value"}
        )
    return value_list


def _param_columns(test_type: TestType) -> list[str]:
    return [c.strip() for c in (test_type.default_parm_columns or "").split(",")]


def _param_fields_flagged(test_type: TestType, flag: str) -> set[str]:
    if not test_type.default_parm_required:
        return set()
    flags = [v.strip().upper() for v in test_type.default_parm_required.split(",")]
    return {col for col, value in zip(_param_columns(test_type), flags, strict=False) if value == flag}


def _audit_name(definition: "TestDefinition") -> str | None:
    """The test's type and what it runs on, as audit records name it."""
    with isolated_read() as session:
        label = session.scalar(select(TestType.test_name_short).where(TestType.test_type == definition.test_type))
    return object_name(label or definition.test_type, definition.table_name, definition.column_name)


def _audit_project(definition: "TestDefinition") -> str | None:
    with isolated_read() as session:
        return session.scalar(select(TestSuite.project_code).where(TestSuite.id == definition.test_suite_id))


AUDIT_STATE_FIELDS = ("lock_refresh", "flagged")
AUDIT_PLACEMENT_FIELDS = ("test_suite_id", "table_groups_id", "schema_name")


class TestDefinition(Entity):
    __tablename__ = "test_definitions"
    __audit__: ClassVar = AuditFields(
        target_type=AuditTargetType.TEST_DEFINITION,
        name=_audit_name,
        project=_audit_project,
        values=(
            "test_type", "test_description", "table_name", "column_name", "skip_errors",
            "baseline_ct", "baseline_unique_ct", "baseline_value", "baseline_value_ct", "threshold_value",
            "baseline_sum", "baseline_avg", "baseline_sd", "lower_tolerance", "upper_tolerance",
            "subset_condition", "groupby_names", "having_condition", "window_date_column", "window_days",
            "match_schema_name", "match_table_name", "match_column_names", "match_subset_condition",
            "match_groupby_names", "match_having_condition", "history_calculation", "history_calculation_upper",
            "history_lookback", "custom_query", "test_active", "severity", "export_to_observability",
            "impact_dimension", "external_url", "custom_metadata", *AUDIT_STATE_FIELDS, *AUDIT_PLACEMENT_FIELDS,
        ),
    )

    # default=uuid4: Python-side ID for ORM inserts (enables batch flush without per-row round-trips).
    # server_default: fallback for raw SQL inserts in test generation templates that omit the id column.
    id: UUID = Column(postgresql.UUID(as_uuid=True), default=uuid4, server_default=text("gen_random_uuid()"), primary_key=True)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True))
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True))
    test_type: str = Column(String)
    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id"), nullable=False)
    test_description: str = Column(NullIfEmptyString)
    schema_name: str = Column(String)
    table_name: str = Column(NullIfEmptyString)
    column_name: str = Column(NullIfEmptyString)
    skip_errors: int = Column(ZeroIfEmptyInteger)
    baseline_ct: str = Column(NullIfEmptyString)
    baseline_unique_ct: str = Column(NullIfEmptyString)
    baseline_value: str = Column(NullIfEmptyString)
    baseline_value_ct: str = Column(NullIfEmptyString)
    threshold_value: str = Column(NullIfEmptyString)
    baseline_sum: str = Column(NullIfEmptyString)
    baseline_avg: str = Column(NullIfEmptyString)
    baseline_sd: str = Column(NullIfEmptyString)
    lower_tolerance: str = Column(NullIfEmptyString)
    upper_tolerance: str = Column(NullIfEmptyString)
    subset_condition: str = Column(NullIfEmptyString)
    groupby_names: str = Column(NullIfEmptyString)
    having_condition: str = Column(NullIfEmptyString)
    window_date_column: str = Column(NullIfEmptyString)
    window_days: int = Column(ZeroIfEmptyInteger)
    match_schema_name: str = Column(NullIfEmptyString)
    match_table_name: str = Column(NullIfEmptyString)
    match_column_names: str = Column(NullIfEmptyString)
    match_subset_condition: str = Column(NullIfEmptyString)
    match_groupby_names: str = Column(NullIfEmptyString)
    match_having_condition: str = Column(NullIfEmptyString)
    history_calculation: str = Column(NullIfEmptyString)
    history_calculation_upper: str = Column(NullIfEmptyString)
    history_lookback: int = Column(ZeroIfEmptyInteger, default=0)
    custom_query: str = Column(QueryString)
    test_active: bool = Column(YNString, default="Y")
    test_definition_status: str = Column(NullIfEmptyString)
    severity: str = Column(NullIfEmptyString)
    watch_level: str = Column(String, default="WARN")
    check_result: str = Column(String)
    lock_refresh: bool = Column(YNString, default="N", nullable=False)
    last_auto_gen_date: datetime = Column(postgresql.TIMESTAMP)
    profiling_as_of_date: datetime = Column(postgresql.TIMESTAMP)
    last_manual_update: datetime = Column(postgresql.TIMESTAMP)
    export_to_observability: bool = Column(YNString)
    prediction: dict[str, dict[str, float]] | None = Column(postgresql.JSONB)
    flagged: bool = Column(Boolean, default=False, nullable=False)
    external_id: UUID | None = Column(postgresql.UUID(as_uuid=True))
    impact_dimension: str | None = Column(String, nullable=True)
    external_url: str | None = Column(NullIfEmptyString)
    custom_metadata: dict | None = Column(postgresql.JSONB)
    version_id: UUID = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("suite_versions.id", ondelete="CASCADE"),
        nullable=False,
        server_default=FetchedValue(),
    )
    contract_term_id: str | None = Column(String)

    _default_order_by = (
        asc(func.lower(schema_name)),
        asc(func.lower(table_name)),
        asc(func.lower(column_name)),
        asc(test_type),
    )
    _summary_columns = (
        *TestDefinitionSummary.__annotations__.keys(),
        *[key for key in TestTypeSummary.__annotations__.keys() if key not in ("default_test_description", "default_impact_dimension")],
        TestType.test_description.label("default_test_description"),
        TestType.impact_dimension.label("default_impact_dimension"),
    )
    _minimal_columns = TestDefinitionMinimal.__annotations__.keys()
    _update_exclude_columns = (
        id,
        table_groups_id,
        profile_run_id,
        test_type,
        test_suite_id,
        schema_name,
        watch_level,
        check_result,
        last_auto_gen_date,
        profiling_as_of_date,
        prediction,
        external_id,
        version_id,
        contract_term_id,
    )

    @classmethod
    def version_clause(cls):
        """Narrow to the rows belonging to each row's resolved suite version."""
        return cls.version_id == SuiteVersion.resolved_for(cls.test_suite_id)

    @classmethod
    def assert_version_writable(cls, version_id: UUID | str) -> None:
        """Raise when the target version is a contract's frozen version."""
        if SuiteVersion.is_frozen_agreement(version_id):
            raise FrozenVersionError(version_id)

    @classmethod
    def copy_to_version(cls, source_version_id: UUID, target_version_id: UUID) -> dict[UUID, UUID]:
        """Copy every term from one version to another, keeping each term's contract identity.

        Returns a map from each copied term's previous id to its new one.
        """
        session = get_current_session()
        id_map: dict[UUID, UUID] = {}
        for term in session.scalars(
            select(cls).where(cls.version_id == source_version_id)
        ).all():
            copied = cls()
            for column in cls.__table__.columns:
                if column.key != "id":
                    setattr(copied, column.key, getattr(term, column.key))
            copied.id = uuid4()
            copied.version_id = target_version_id
            if copied.last_auto_gen_date is None and copied.external_id is None:
                copied.external_id = uuid4()
            session.add(copied)
            id_map[term.id] = copied.id
        session.flush()
        return id_map

    @classmethod
    def resolve_write_target(cls, test_suite_id: UUID | str) -> tuple[UUID, dict[UUID, UUID]]:
        """The version this suite's next write lands in, opening a draft when there is none.

        Returns the version id and a map from each copied term's previous id to its new one.
        The map is empty when a draft already existed.
        """
        draft = SuiteVersion.draft_for(test_suite_id)
        if draft is not None:
            return draft.id, {}

        draft, source = SuiteVersion.open_draft(test_suite_id)
        return draft.id, cls.copy_to_version(source.id, draft.id) if source else {}

    @classmethod
    def resolve_writable(
        cls, test_suite_id: UUID | str, row_ids: Sequence[UUID | str] = (), *, skip_unwritable: bool = False
    ) -> tuple[UUID, dict[UUID, UUID]]:
        """The version the suite's next write lands in, and each named row's counterpart there.

        Opens a draft when the suite resolves to a contract's frozen version or a named row
        belongs to the version in force. A row of the writable version maps to itself; a row of
        the version in force maps to the draft's copy, matched by contract identity. Rows that
        do not exist are left out of the map.

        Raises ``FrozenVersionError`` for a row of any other frozen version, before a draft is
        opened, and its ``UnmatchedInDraftError`` subclass naming every row of the version in force
        that carries no contract identity to match in an open draft. Raises ``RemovedInDraftError`` naming every row of the version
        in force that the draft no longer holds.

        With ``skip_unwritable``, those rows are left out of the map instead of raising, and no
        draft is opened when every named row was left out for belonging to another frozen version.
        """
        session = get_current_session()
        ids = [UUID(str(row_id)) for row_id in row_ids]
        position = {row_id: index for index, row_id in enumerate(ids)}
        rows = sorted(
            session.execute(select(cls.id, cls.version_id, cls.contract_term_id).where(cls.id.in_(ids))).all()
            if ids
            else [],
            key=lambda row: position[row.id],
        )
        frozen_by_version = {
            version_id: SuiteVersion.is_frozen_agreement(version_id) for version_id in {row.version_id for row in rows}
        }
        frozen_versions = {version_id for version_id, frozen in frozen_by_version.items() if frozen}
        if frozen_versions:
            in_force = SuiteVersion.in_force_for(test_suite_id)
            superseded = [
                row.version_id
                for row in rows
                if row.version_id in frozen_versions and (in_force is None or row.version_id != in_force.id)
            ]
            if superseded and not skip_unwritable:
                raise FrozenVersionError(superseded[0])
            if superseded:
                rows = [row for row in rows if row.version_id not in superseded]
                frozen_versions -= set(superseded)
                if not rows:
                    return session.scalar(select(SuiteVersion.resolved_for(test_suite_id))), {}

        resolved = session.scalar(select(SuiteVersion.resolved_for(test_suite_id)))
        mapping = {row.id: row.id for row in rows if row.version_id not in frozen_versions}
        resolved_frozen = (
            frozen_by_version[resolved] if resolved in frozen_by_version else SuiteVersion.is_frozen_agreement(resolved)
        )
        if not frozen_versions and not resolved_frozen:
            return resolved, mapping

        target, copied = cls.resolve_write_target(test_suite_id)
        frozen_rows = [row for row in rows if row.version_id in frozen_versions]
        if copied:
            mapping.update({row.id: copied[row.id] for row in frozen_rows})
            return target, mapping

        unmatchable = [row for row in frozen_rows if not row.contract_term_id]
        if unmatchable and not skip_unwritable:
            raise UnmatchedInDraftError(unmatchable[0].version_id, target, [row.id for row in unmatchable])
        frozen_rows = [row for row in frozen_rows if row.contract_term_id]
        term_ids = [row.contract_term_id for row in frozen_rows]
        in_draft = (
            {
                draft_row.contract_term_id: draft_row.id
                for draft_row in session.execute(
                    select(cls.id, cls.version_id, cls.contract_term_id).where(
                        cls.version_id == target, cls.contract_term_id.in_(term_ids)
                    )
                ).all()
            }
            if term_ids
            else {}
        )
        removed = [row.id for row in frozen_rows if row.contract_term_id not in in_draft]
        if removed and not skip_unwritable:
            raise RemovedInDraftError(target, removed)
        mapping.update({row.id: in_draft[row.contract_term_id] for row in frozen_rows if row.contract_term_id in in_draft})
        return target, mapping

    def _route_to_writable_version(self) -> None:
        """Move this write onto the contract's draft when the version it would land on is frozen.

        An update is routed by ``resolve_writable`` from the persisted row's own version: a row
        of the version in force becomes the draft's copy of it, opening the draft when there is
        none, so the edit lands on the draft and the frozen version keeps what it had. A row of
        a superseded version raises ``FrozenVersionError`` before any draft is opened, and a row
        the draft has removed raises ``RemovedInDraftError``.

        An insert holding the version in force lands on the draft instead, opening one when
        there is none; one holding any other frozen version is refused.

        Raises ``MissingTestDefinitionError`` when the row being updated no longer exists, since
        nothing can then establish which version the write would land on.
        """
        # Both ids are compared against ones the ORM hands back, never only passed to the
        # database, and a dialog payload delivers them as strings.
        row_id = UUID(str(self.id)) if self.id else None
        if row_id is not None:
            self.version_id, mapping = self.resolve_writable(self.test_suite_id, [row_id])
            if row_id not in mapping:
                raise MissingTestDefinitionError(f"Test definition {self.id} no longer exists.")
            self.id = mapping[row_id]
            return

        version_id = UUID(str(self.version_id)) if self.version_id else None
        if not SuiteVersion.is_frozen_agreement(version_id):
            return

        in_force = SuiteVersion.in_force_for(self.test_suite_id)
        if in_force is None or version_id != in_force.id:
            raise FrozenVersionError(version_id)

        self.version_id, _ = self.resolve_write_target(self.test_suite_id)

    @classmethod
    def delete_where(cls, *clauses: ColumnElement[bool]) -> int:
        """Delete the rows the clauses select, landing on a contract's draft rather than a frozen version.

        A draft copy is spared when a column the clauses name holds a different value on it than on the
        selected row. Returns the number of rows deleted. Raises ``FrozenVersionError`` when the clauses select a
        contract's superseded rows, and ``RemovedInDraftError`` for rows its draft no longer holds.
        """
        cls._assert_no_managed_definitions(*clauses)
        selected = get_current_session().execute(select(cls.id).where(*clauses)).scalars().all()
        id_map = cls._writable_id_map(selected)
        drifted = cls._drifted_copies(id_map, clauses)
        targets = [target for target in dict.fromkeys(id_map.values()) if target not in drifted]
        return super().delete_where(cls.id.in_(targets), cls.version_clause())

    @classmethod
    def _assert_no_managed_definitions(cls, *clauses: ColumnElement[bool]) -> None:
        """Raise if any row matching the clauses belongs to a managed test type."""
        if get_current_session().scalar(
            select(exists().where(*clauses, cls.test_type.in_(MANAGED_TEST_TYPES)))
        ):
            raise ManagedTestDefinitionError

    @classmethod
    def writable_ids(cls, row_ids: Iterable[UUID | str]) -> list[UUID]:
        """The rows a write to the named rows lands on, resolving each row's suite through ``resolve_writable``.

        A row of a regular or monitor suite maps to itself. A row of a contract's frozen version maps to
        its counterpart in the draft, which is opened when there is none.
        """
        return list(dict.fromkeys(cls._writable_id_map(row_ids).values()))

    @classmethod
    def _writable_id_map(cls, row_ids: Iterable[UUID | str]) -> dict[UUID, UUID]:
        """Each named row's id mapped to the id of the row a write to it lands on, as ``writable_ids`` resolves it."""
        ids = [UUID(str(row_id)) for row_id in row_ids]
        if not ids:
            return {}
        ids_by_suite: dict[UUID, list[UUID]] = {}
        for row_id, suite_id in get_current_session().execute(
            select(cls.id, cls.test_suite_id).where(cls.id.in_(ids))
        ).all():
            ids_by_suite.setdefault(suite_id, []).append(row_id)
        writable: dict[UUID, UUID] = {}
        for suite_id, suite_row_ids in ids_by_suite.items():
            writable.update(cls.resolve_writable(suite_id, suite_row_ids)[1])
        return writable

    @classmethod
    def _drifted_copies(cls, id_map: dict[UUID, UUID], clauses: Sequence[ColumnElement[bool]]) -> set[UUID]:
        """The draft copies in ``id_map`` holding a different value than their source row in a column the clauses name."""
        copies = {source: target for source, target in id_map.items() if source != target}
        identity = {cls.id.key, cls.version_id.key}
        columns = {
            element.key: element
            for clause in clauses
            for element in visitors.iterate(clause)
            if isinstance(element, Column) and element.table is cls.__table__ and element.key not in identity
        }
        if not copies or not columns:
            return set()
        values = {
            row[0]: tuple(row[1:])
            for row in get_current_session().execute(
                select(cls.id, *columns.values()).where(cls.id.in_([*copies, *copies.values()]))
            )
        }
        return {target for source, target in copies.items() if values.get(source) != values.get(target)}

    @classmethod
    def _scoped_select(
        cls,
        columns: list[str | InstrumentedAttribute],
        *clauses,
        join_target=None,
        join_clause=None,
        order_by: tuple[str | InstrumentedAttribute] | None = None,
        version_predicate=None,
    ):
        """Build a select over *columns* narrowed to each row's resolved suite version.

        ``version_predicate`` replaces the resolved-version predicate when given.
        """
        if join_target is not None:
            select_columns = [
                getattr(cls, col, None) or getattr(join_target, col) if isinstance(col, str) else col
                for col in columns
            ]
            query = select(*select_columns).join(join_target, join_clause)
        else:
            select_columns = [getattr(cls, col) if isinstance(col, str) else col for col in columns]
            query = select(*select_columns)

        query = query.where(cls.version_clause() if version_predicate is None else version_predicate, *clauses)
        if order_by is not None:
            query = query.order_by(*order_by)
        return query

    @classmethod
    def any_contract_version_clause(cls, suite_types: Sequence[SuiteType]) -> ColumnElement[bool] | None:
        """The version predicate reading a contract's rows in any version, or None to keep the
        resolved-version predicate when ``suite_types`` excludes contracts."""
        from testgen.common.models.test_suite import TestSuite

        if SuiteType.CONTRACT not in suite_types:
            return None
        return or_(cls.version_clause(), TestSuite.suite_type == SuiteType.CONTRACT)

    @classmethod
    def get(cls, identifier: str | UUID) -> TestDefinitionSummary | None:
        if not is_uuid4(identifier):
            return None

        query = cls._scoped_select(
            cls._summary_columns,
            cls.id == identifier,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
        )
        result = get_current_session().execute(query).mappings().first()
        return TestDefinitionSummary(**result) if result else None

    @classmethod
    def get_for_project(
        cls,
        identifier: UUID,
        project_codes: list[str] | None = None,
        *,
        suite_types: Sequence[SuiteType] = (SuiteType.REGULAR,),
    ) -> TestDefinitionSummary | None:
        """Fetch a test definition with project-level access check.

        Returns None if the definition doesn't exist, its suite is not one of ``suite_types``, or the user lacks access.
        When ``suite_types`` includes contracts, a contract's definition is read in any of its versions.
        """
        from testgen.common.models.test_suite import TestSuite

        query = cls._scoped_select(
            cls._summary_columns,
            cls.id == identifier,
            TestSuite.suite_type.in_(suite_types),
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            version_predicate=cls.any_contract_version_clause(suite_types),
        ).join(TestSuite, cls.test_suite_id == TestSuite.id)
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        result = get_current_session().execute(query).mappings().first()
        return TestDefinitionSummary(**result) if result else None

    @classmethod
    def select_where(
        cls,
        *clauses,
        order_by: tuple[str | InstrumentedAttribute] = _default_order_by,
        version_id: UUID | str | None = None,
    ) -> Iterable[TestDefinitionSummary]:
        """Test definitions matching ``clauses``. ``version_id`` reads that suite version instead of the one
        each suite resolves to."""
        query = cls._scoped_select(
            cls._summary_columns,
            *clauses,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            order_by=order_by or cls._default_order_by,
            version_predicate=cls.version_id == version_id if version_id else None,
        )
        results = get_current_session().execute(query).mappings().all()
        return [TestDefinitionSummary(**row) for row in results]

    @classmethod
    def select_minimal_where(
        cls,
        *clauses,
        order_by: tuple[str | InstrumentedAttribute] = _default_order_by,
        version_id: UUID | str | None = None,
    ) -> Iterable[TestDefinitionMinimal]:
        """Test definitions matching ``clauses``, in their minimal form. ``version_id`` reads that suite
        version instead of the one each suite resolves to."""
        query = cls._scoped_select(
            cls._minimal_columns,
            *clauses,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            order_by=order_by or cls._default_order_by,
            version_predicate=cls.version_id == version_id if version_id else None,
        )
        results = get_current_session().execute(query).mappings().all()
        return [TestDefinitionMinimal(**row) for row in results]

    @classmethod
    def list_for_suite(
        cls,
        test_suite_id: UUID,
        project_codes: list[str] | None = None,
        table_name: str | None = None,
        test_type: str | None = None,
        test_active: bool | None = None,
        page: int = 1,
        limit: int = 50,
        *,
        suite_types: Sequence[SuiteType] = (SuiteType.REGULAR,),
        version_id: UUID | None = None,
    ) -> tuple[list[TestDefinitionSummary], int]:
        """Paginated test definitions for a suite, with optional filters.

        ``version_id`` reads that suite version instead of the one the suite resolves to.

        Only suites of ``suite_types`` are read; a suite of another type yields an empty page.
        Project-level access is enforced when ``project_codes`` is set.
        """
        from testgen.common.models.test_suite import TestSuite

        query = cls._scoped_select(
            cls._summary_columns,
            cls.test_suite_id == test_suite_id,
            TestSuite.suite_type.in_(suite_types),
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            version_predicate=cls.version_id == version_id if version_id else None,
        ).join(TestSuite, cls.test_suite_id == TestSuite.id)
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        if table_name:
            query = query.where(cls.table_name == table_name)
        if test_type:
            query = query.where(cls.test_type == test_type)
        if test_active is not None:
            query = query.where(cls.test_active == test_active)
        query = query.order_by(*cls._default_order_by)
        return cls._paginate(query, page=page, limit=limit, data_class=TestDefinitionSummary)

    @classmethod
    def list_for_ids(
        cls,
        test_definition_ids: Iterable[UUID],
        project_codes: list[str] | None = None,
        *,
        suite_types: Sequence[SuiteType] = (SuiteType.REGULAR,),
    ) -> list[TestDefinitionMinimal]:
        """Test definitions for the given ids, in one statement.

        Only suites of ``suite_types`` are read. When ``suite_types`` includes contracts, a
        contract's definition is read in any of its versions. Project-level access is enforced when
        ``project_codes`` is set. An id matching nothing is absent from the result rather
        than raising, so a caller can report the difference itself.
        """
        from testgen.common.models.test_suite import TestSuite

        ids = list(test_definition_ids)
        if not ids:
            return []

        query = cls._scoped_select(
            cls._minimal_columns,
            cls.id.in_(ids),
            TestSuite.suite_type.in_(suite_types),
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            version_predicate=cls.any_contract_version_clause(suite_types),
        ).join(TestSuite, cls.test_suite_id == TestSuite.id)
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        query = query.order_by(*cls._default_order_by)
        results = get_current_session().execute(query).mappings().all()
        return [TestDefinitionMinimal(**row) for row in results]

    @classmethod
    def get_singleton_monitor(
        cls,
        test_suite_id: str | UUID,
        table_name: str,
        test_type: str,
    ) -> "TestDefinition | None":
        """Return the single ``TestDefinition`` row for a singleton monitor
        type (Freshness / Volume / Schema) on a given table. Metric is
        multi-instance and should be looked up by ``id`` instead — this
        helper would silently pick the first match. Returns ``None`` when no
        monitor is configured."""
        session = get_current_session()
        return session.execute(
            select(cls)
            .where(cls.version_clause())
            .where(cls.test_suite_id == test_suite_id)
            .where(cls.table_name == table_name)
            .where(cls.test_type == test_type)
            .limit(1)
        ).scalars().first()

    @classmethod
    def list_monitor_configs_for_table(
        cls,
        test_suite_id: str | UUID,
        table_name: str,
    ) -> list[MonitorConfig]:
        """List configured monitors for a single table within a monitor suite.

        Returns one entry per ``test_definition`` row whose ``test_type`` is one
        of the four monitor types. Typically 3-4 rows per table; Metric_Trend
        contributes one entry per metric, so a table may have more.
        """
        monitor_codes = [m.value for m in MonitorType]
        defs = cls.select_where(
            cls.test_suite_id == test_suite_id,
            cls.table_name == table_name,
            cls.test_type.in_(monitor_codes),
        )
        return [cls._build_monitor_config(td) for td in defs]

    @classmethod
    def _build_monitor_config(cls, td: "TestDefinition") -> MonitorConfig:
        mode, threshold_lower, threshold_upper = cls._derive_threshold_mode(td)
        return MonitorConfig(
            monitor_id=td.id,
            test_type=td.test_type,
            table_name=td.table_name,
            metric_name=td.column_name or None if td.test_type == MonitorType.METRIC.value else None,
            threshold_mode=mode,
            threshold_lower=threshold_lower,
            threshold_upper=threshold_upper,
            custom_query=td.custom_query if td.test_type == MonitorType.METRIC.value else None,
        )

    @classmethod
    def _derive_threshold_mode(
        cls, td: "TestDefinition",
    ) -> tuple[ThresholdMode, str | None, str | None]:
        """``derive_threshold_mode`` for a ``TestDefinition`` instance."""
        return derive_threshold_mode(
            td.test_type, td.history_calculation, td.history_calculation_upper,
            td.lower_tolerance, td.upper_tolerance,
        )

    @classmethod
    def select_page(
        cls,
        *clauses,
        order_by: tuple[str | InstrumentedAttribute] | None = None,
        page: int = 1,
        limit: int = 500,
        version_id: UUID | str | None = None,
    ) -> tuple[list["TestDefinitionSummary"], int]:
        """One page of the test definitions matching ``clauses``, and their total count. ``version_id``
        reads that suite version instead of the one each suite resolves to."""
        query = cls._scoped_select(
            cls._summary_columns,
            *clauses,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            order_by=order_by or cls._default_order_by,
            version_predicate=cls.version_id == version_id if version_id else None,
        )
        return cls._paginate(query, page=page, limit=limit, data_class=TestDefinitionSummary)

    _yn_columns: ClassVar = {"test_active", "lock_refresh"}

    # Fields editable on every test type regardless of param_columns.
    EDITABLE_BASE_FIELDS: ClassVar[frozenset[str]] = frozenset({
        "test_active", "severity", "lock_refresh", "flagged", "test_description",
        "external_url", "custom_metadata",
    })

    def editable_fields(self, test_type: TestType) -> set[str]:
        """Fields a caller may set or change on this test definition under the given test type."""
        fields = self.EDITABLE_BASE_FIELDS | test_type.param_columns
        if test_type.test_scope in COLUMN_NAME_SCOPES:
            fields = fields | {"column_name"}
        # impact_dimension is overridable only for user-defined-semantic scopes
        # (custom-scope = user-authored SQL; referential-scope = comparison-based tests).
        # Other scopes have baked-in dimensions so the override doesn't apply.
        if test_type.test_scope in ("custom", "referential"):
            fields = fields | {"impact_dimension"}
        return fields

    def normalize_value_list(self) -> None:
        """Rewrite ``baseline_value`` as ``stored_value_list`` stores it, for the general type the table
        group's catalog records for the test's column.

        Raises:
            InvalidTestDefinitionFields: As ``stored_value_list`` raises it.
        """
        # data_column imports, through job_execution, models that import this one
        from testgen.common.models.data_column import DataColumnChars

        if self.test_type not in VALUE_LIST_TEST_TYPES or _is_blank(self.baseline_value):
            return
        self.baseline_value = stored_value_list(
            self.test_type,
            self.baseline_value,
            DataColumnChars.general_type_of(self.table_groups_id, self.table_name, self.column_name),
            partial(stores_empty_string, self.table_groups_id),
        )

    def validate(self, test_type: TestType) -> None:
        """Validate the current state against the given test type.

        Raises :class:`InvalidTestDefinitionFields` with every offending field
        and reason — callers see all problems at once.
        """
        if errors := test_definition_errors(test_type, lambda field: getattr(self, field, None)):
            raise InvalidTestDefinitionFields(errors)

    @classmethod
    def set_status_attribute(
        cls,
        status_type: Literal["test_active", "lock_refresh", "flagged"],
        test_definition_ids: list[str | UUID],
        value: bool,
    ) -> list[UUID]:
        """Set a status column on the named rows, landing on a contract's draft rather than a frozen version.

        Returns the ids of the rows whose value changed.
        """
        writable_ids = cls.writable_ids(test_definition_ids)
        if not writable_ids:
            return []

        query = f"""
        WITH selected AS (
            SELECT UNNEST(ARRAY [:test_definition_ids]) AS id
        )
        UPDATE test_definitions
        SET {status_type} = :value
            {", test_definition_status = NULL" if status_type == "test_active" and value else ""}
        FROM test_definitions td
            INNER JOIN selected ON (td.id = selected.id::UUID)
        WHERE td.id = test_definitions.id
            AND td.version_id = {SuiteVersion.resolved_for_sql("td.test_suite_id")}
        RETURNING test_definitions.id, td.{status_type} IS DISTINCT FROM :value AS changed;
        """
        params = {
            "test_definition_ids": [str(row_id) for row_id in writable_ids],
            "value": YNString().process_bind_param(value, None) if status_type in cls._yn_columns else value,
        }

        db_session = get_current_session()
        return [row.id for row in db_session.execute(text(query), params) if row.changed]

    @classmethod
    def _retargeted_schemas(
        cls,
        target_table_group_id: str | UUID,
        target_schema: str,
        qualifies_table_refs: bool,
    ) -> dict[str, ColumnElement]:
        """The schema columns of a definition relocated into a table group, keyed by column name.

        A definition from another table group takes ``target_schema``. Its reference table's schema
        takes it too when it was blank or named the definition's own schema, and always when
        ``qualifies_table_refs`` is false, since the target then reaches every table through one
        schema. A definition already in the target table group keeps both.
        """
        same_group = cls.table_groups_id == target_table_group_id
        no_reference = func.nullif(cls.match_table_name, "").is_(None)
        reference_follows = (
            or_(func.nullif(cls.match_schema_name, "").is_(None), cls.match_schema_name == cls.schema_name)
            if qualifies_table_refs
            else true()
        )
        return {
            "schema_name": case((same_group, cls.schema_name), else_=literal(target_schema)),
            "match_schema_name": case(
                (or_(same_group, no_reference), cls.match_schema_name),
                (reference_follows, literal(target_schema)),
                else_=cls.match_schema_name,
            ),
        }

    @classmethod
    def move(
        cls,
        test_definition_ids: list[str | UUID],
        target_table_group_id: str | UUID,
        target_test_suite_id: str | UUID,
        target_table_name: str | None = None,
        target_column_name: str | None = None,
        *,
        target_schema: str,
        qualifies_table_refs: bool,
    ) -> list[UUID]:
        """Relocate test definitions into a test suite, taking the target table group's schema.

        ``target_schema`` is the target table group's schema, and ``qualifies_table_refs`` whether its
        connection's flavor names a table as ``schema.table``. Returns the ids of the rows moved.
        """
        db_session = get_current_session()
        target_version = db_session.scalar(select(SuiteVersion.resolved_for(target_test_suite_id)))
        cls.assert_version_writable(target_version)
        cls._assert_no_managed_definitions(cls.id.in_([UUID(str(identifier)) for identifier in test_definition_ids]))
        writable_ids = cls.writable_ids(test_definition_ids)
        scoped_ids = db_session.scalars(
            select(cls.id).where(cls.id.in_(writable_ids), cls.version_clause())
        ).all()

        values: dict[str, object] = {
            **cls._retargeted_schemas(target_table_group_id, target_schema, qualifies_table_refs),
            "table_groups_id": target_table_group_id,
            "test_suite_id": target_test_suite_id,
            "version_id": target_version,
            "contract_term_id": None,
        }
        if target_table_name:
            values["table_name"] = target_table_name
        if target_column_name:
            values["column_name"] = target_column_name

        db_session.execute(
            update(cls)
            .where(cls.id.in_(scoped_ids))
            .values(values)
            .execution_options(synchronize_session=False)
        )
        cls.assign_missing_term_ids(target_version)
        return list(scoped_ids)

    @classmethod
    def copy(
        cls,
        test_definition_ids: list[str | UUID],
        target_table_group_id: str | UUID,
        target_test_suite_id: str | UUID,
        target_table_name: str | None = None,
        target_column_name: str | None = None,
        *,
        target_schema: str,
        qualifies_table_refs: bool,
    ) -> list[UUID]:
        """Copy test definitions into a test suite, taking the target table group's schema.

        ``target_schema`` is the target table group's schema, and ``qualifies_table_refs`` whether its
        connection's flavor names a table as ``schema.table``. Returns the ids of the copies.
        """
        db_session = get_current_session()
        target_version = db_session.scalar(select(SuiteVersion.resolved_for(target_test_suite_id)))
        cls.assert_version_writable(target_version)
        cls._assert_no_managed_definitions(cls.id.in_([UUID(str(identifier)) for identifier in test_definition_ids]))

        retargeted = cls._retargeted_schemas(target_table_group_id, target_schema, qualifies_table_refs)

        modified_columns = [
            cls.id,
            cls.table_groups_id,
            cls.profile_run_id,
            cls.test_suite_id,
            cls.last_auto_gen_date,
            cls.version_id,
            cls.contract_term_id,
            cls.external_id,
            cls.schema_name,
            cls.match_schema_name,
        ]

        select_columns = [
            func.gen_random_uuid().label("id"),
            literal(target_table_group_id).label("table_groups_id"),
            case(
                (cls.table_groups_id == target_table_group_id, cls.profile_run_id),
                else_=None,
            ).label("profile_run_id"),
            literal(target_test_suite_id).label("test_suite_id"),
            literal(None).label("last_auto_gen_date"),
            literal(target_version).label("version_id"),
            literal(None).label("contract_term_id"),
            func.gen_random_uuid().label("external_id"),
            retargeted["schema_name"].label("schema_name"),
            retargeted["match_schema_name"].label("match_schema_name"),
        ]

        if target_table_name:
            modified_columns.append(cls.table_name)
            select_columns.append(literal(target_table_name).label("table_name"))

        if target_column_name:
            modified_columns.append(cls.column_name)
            select_columns.append(literal(target_column_name).label("column_name"))

        other_columns = [
            column for column in cls.__table__.columns if column not in modified_columns and column != cls.id
        ]
        select_columns.extend(other_columns)

        query = insert(cls).from_select(
            [*modified_columns, *other_columns],
            select(*select_columns).where(cls.id.in_(test_definition_ids), cls.version_clause()),
        ).returning(cls.id)
        copied_ids = list(db_session.execute(query).scalars())
        # A copy is a new term, so it takes none of the source's contract identity; it still
        # needs one of its own when the target version is a contract's.
        cls.assign_missing_term_ids(target_version)
        return copied_ids

    @classmethod
    def get_source_data_context(
        cls,
        test_definition_id: UUID,
        project_codes: list[str] | None = None,
        *,
        suite_types: Sequence[SuiteType] = (SuiteType.REGULAR,),
    ) -> dict | None:
        """Get the fields needed by the source data service for a given test definition.

        Returns None when the definition is not in one of ``project_codes`` or its suite is not one of
        ``suite_types``. A contract's definition is found in any of its versions.
        """
        if cls.get_for_project(test_definition_id, project_codes, suite_types=suite_types) is None:
            return None

        session = get_current_session()

        sql = """
            SELECT
                d.table_groups_id,
                tt.id AS test_type_id,
                d.id AS test_definition_id,
                d.test_type,
                tt.test_name_short,
                d.schema_name,
                d.table_name,
                d.column_name AS column_names,
                dcc.column_type,
                ts.project_code
            FROM test_definitions d
            INNER JOIN test_types tt ON d.test_type = tt.test_type
            INNER JOIN test_suites ts ON d.test_suite_id = ts.id
            LEFT JOIN data_column_chars dcc
                ON d.table_groups_id = dcc.table_groups_id
                AND d.table_name = dcc.table_name
                AND d.column_name = dcc.column_name
            WHERE d.id = :test_definition_id
        """
        params: dict = {"test_definition_id": str(test_definition_id)}

        if project_codes is not None:
            sql += " AND ts.project_code = ANY(:project_codes)"
            params["project_codes"] = project_codes

        result = session.execute(text(sql), params).first()
        return dict(result._mapping) if result else None

    @classmethod
    def _term_id_candidates(
        cls,
        test_type: str,
        schema_name: str | None,
        table_name: str | None,
        column_name: str | None,
        term_id: UUID | str | None,
    ) -> list[str]:
        """Every contract identity this natural key could take, in preference order.

        The bare ``slugify_term_id`` slug first, then the forms suffixed with a growing prefix
        of ``term_id``'s digest. Only the slug when ``term_id`` is ``None``.
        """
        slug = slugify_term_id(test_type, schema_name, table_name, column_name)
        candidates = [slug]
        if term_id is not None:
            digest = hashlib.sha256(str(term_id).encode()).hexdigest()
            for length in range(_DIGEST_LENGTH, len(digest) + 1):
                kept = slug[: TERM_ID_MAX_LENGTH - length - 1].rstrip("-_")
                candidates.append(f"{kept}-{digest[:length]}")
        return candidates

    @classmethod
    def _mint_against(
        cls,
        taken: set[str],
        test_type: str,
        schema_name: str | None,
        table_name: str | None,
        column_name: str | None,
        term_id: UUID | str | None = None,
    ) -> str:
        """Pick this term's contract identity, treating ``taken`` as the whole set to avoid.

        Returns the bare ``slugify_term_id`` slug when it is free. ``slugify_term_id`` is
        already injective over distinct natural keys, so the only collision possible here is
        two terms sharing an identical natural key -- legal because the natural-key dedup
        indexes are partial on ``last_auto_gen_date``. In that case the slug is disambiguated
        with a digest of this term's own primary key (``term_id``), a function of the term
        rather than of minting order.

        ``slugify_term_id``'s plain and digested forms are not disjoint -- a natural key that
        itself ends in something shaped like a hex digest can already own the exact string a
        suffix would mint -- so every candidate is checked against ``taken`` in turn, never
        assumed free from its shape alone. When a candidate is taken, the next one keeps more
        of the digest (never an ordinal, which would depend on minting order) until a free one
        is found or the digest is exhausted, trimming the slug so the result still fits
        ``TERM_ID_MAX_LENGTH``.

        Raises ``ValueError`` when the digest is exhausted, and when ``term_id`` is ``None``
        and the bare slug is taken: the digest has nothing to hash, and hashing a constant in
        its place would turn every such call into a generator of the same colliding id.
        """
        slug, *suffixed = cls._term_id_candidates(test_type, schema_name, table_name, column_name, term_id)
        if slug not in taken:
            return slug

        if term_id is None:
            raise ValueError(f"minting {slug!r} needs the term's own primary key to disambiguate it")

        for candidate in suffixed:
            if candidate not in taken:
                return candidate

        raise ValueError(f"no free term identity for {slug!r}")

    @classmethod
    def mint_term_id(
        cls,
        version_id: UUID | str,
        test_type: str,
        schema_name: str | None,
        table_name: str | None,
        column_name: str | None,
        term_id: UUID | str | None = None,
    ) -> str:
        """Derive a term's contract identity, disambiguated against what ``version_id`` holds.

        Reads in one query which of the identities this term could take are already held on the
        version, then picks a free one. Raises ``ValueError`` when none is free.
        """
        candidates = cls._term_id_candidates(test_type, schema_name, table_name, column_name, term_id)
        taken = set(
            get_current_session()
            .scalars(
                select(cls.contract_term_id).where(
                    cls.version_id == version_id, cls.contract_term_id.in_(candidates)
                )
            )
            .all()
        )
        return cls._mint_against(taken, test_type, schema_name, table_name, column_name, term_id)

    @classmethod
    def assign_missing_term_ids(cls, version_id: UUID | str) -> int:
        """Mint a contract identity for every term in the version that has none.

        Covers manual terms as well as generated ones -- the natural-key dedup indexes are
        partial on ``last_auto_gen_date``, so a manual term is deduped against nothing and this
        is the only place a duplicate natural key becomes visible as a duplicate. Sweeps in a
        stable order (``test_type``, ``schema_name``, ``table_name``, ``column_name``) so two
        runs over the same data mint the same ids. Returns the number of terms minted.

        The identities the version holds are read once and grown in memory as terms are minted,
        so the sweep costs two queries whatever the number of terms and tells apart two terms
        sharing a natural key within the sweep.

        A version no suite owns -- the placeholder that regular and monitor suites share --
        holds no contract terms, so nothing is minted on it.
        """
        if not SuiteVersion.is_suite_owned(version_id):
            return 0

        session = get_current_session()
        taken = set(
            session.scalars(
                select(cls.contract_term_id).where(
                    cls.version_id == version_id, cls.contract_term_id.is_not(None)
                )
            ).all()
        )
        terms = session.scalars(
            select(cls)
            .where(cls.version_id == version_id, cls.contract_term_id.is_(None))
            .order_by(cls.test_type, cls.schema_name, cls.table_name, cls.column_name)
        ).all()
        for term in terms:
            term.contract_term_id = cls._mint_against(
                taken, term.test_type, term.schema_name, term.table_name, term.column_name, term.id
            )
            taken.add(term.contract_term_id)
        session.flush()
        return len(terms)

    def save(self) -> None:
        if self.id:
            session = get_current_session()
            with session.no_autoflush:
                # A loaded row of a frozen version is dirty with an edit meant for the draft's
                # copy: opening the draft flushes explicitly, and routing changes its key. A row
                # that stays put stays attached, since only the session's flush persists its
                # changes to columns the UPDATE below does not write.
                if inspect(self).persistent and SuiteVersion.is_frozen_agreement(self.version_id):
                    session.expunge(self)
                loaded_id = UUID(str(self.id))
                self._route_to_writable_version()
            columns = [column for column in self.__table__.columns if column not in self._update_exclude_columns]
            values = {column.key: getattr(self, column.key, None) for column in columns}
            if self.id != loaded_id:
                # Routed onto the draft's copy, which may already carry edits of its own: only
                # what this edit changed from the row it was loaded from is written over it.
                loaded = session.execute(select(*columns).where(TestDefinition.id == loaded_id)).one()
                values = {key: value for key, value in values.items() if value != getattr(loaded, key)}
            if SuiteVersion.is_suite_owned(self.version_id):
                values["external_id"] = case(
                    (
                        TestDefinition.last_auto_gen_date.is_(None),
                        func.coalesce(TestDefinition.external_id, func.gen_random_uuid()),
                    ),
                    else_=TestDefinition.external_id,
                )
            if values:
                session.execute(
                    update(TestDefinition)
                    .where(TestDefinition.id == self.id, TestDefinition.version_clause())
                    .values(**values)
                )
        else:
            if self.version_id is None:
                self.version_id = get_current_session().scalar(
                    select(SuiteVersion.resolved_for(self.test_suite_id))
                )
            self._route_to_writable_version()
            # A SQLAlchemy column default is evaluated at flush, not at construction, so the
            # primary key does not exist yet here. An explicit value takes precedence over the
            # column default and the post-flush refresh returns the same value, so nothing
            # downstream shifts.
            self.id = self.id or uuid4()
            if SuiteVersion.is_suite_owned(self.version_id):
                if self.last_auto_gen_date is None and self.external_id is None:
                    self.external_id = uuid4()
                if not self.contract_term_id:
                    self.contract_term_id = self.mint_term_id(
                        self.version_id, self.test_type, self.schema_name, self.table_name, self.column_name, self.id
                    )
            super().save()


class TestDefinitionNote(Base):
    __tablename__ = "test_definition_notes"

    id: UUID = Column(postgresql.UUID(as_uuid=True), default=uuid4, primary_key=True)
    test_definition_id: UUID = Column(
        postgresql.UUID(as_uuid=True), ForeignKey("test_definitions.id", ondelete="CASCADE"), nullable=False
    )
    detail: str = Column(Text, nullable=False)
    created_by: str = Column(String(100), nullable=False)
    created_at: datetime = Column(postgresql.TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: datetime = Column(postgresql.TIMESTAMP)

    @staticmethod
    def _same_term(peer: type[TestDefinition], definition: type[TestDefinition]) -> ColumnElement[bool]:
        """Whether ``peer`` is a version of the same test as ``definition``.

        Rows of one suite sharing a contract term are versions of one test. A row without a term
        matches only itself.
        """
        return (peer.test_suite_id == definition.test_suite_id) & (
            (peer.id == definition.id) | (peer.contract_term_id == definition.contract_term_id)
        )

    @classmethod
    def _storage_row(cls, test_definition_id: str | UUID) -> UUID:
        """The row a note added to the given test definition is stored on.

        The earliest frozen row of its term, so that deleting a draft row never takes a note on a
        test that outlives the draft. The row itself when the term has no frozen row.
        """
        definition = aliased(TestDefinition)
        peer = aliased(TestDefinition)
        stored_on = get_current_session().scalar(
            select(peer.id)
            .join(definition, cls._same_term(peer, definition))
            .join(SuiteVersion, SuiteVersion.id == peer.version_id)
            .where(
                definition.id == test_definition_id,
                SuiteVersion.test_suite_id.is_not(None),
                SuiteVersion.frozen_at.is_not(None),
            )
            .order_by(SuiteVersion.frozen_at, SuiteVersion.version)
            .limit(1)
        )
        return stored_on or UUID(str(test_definition_id))

    @classmethod
    def add_note(cls, test_definition_id: str | UUID, detail: str, username: str) -> "TestDefinitionNote":
        """Insert a note on the given test definition and return the persisted instance.

        A note on a contract's test is stored on the earliest frozen version of that test, whichever
        version it is added from.
        """
        db_session = get_current_session()
        note = cls(
            test_definition_id=cls._storage_row(test_definition_id),
            detail=detail,
            created_by=username,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db_session.add(note)
        db_session.flush()
        return note

    @classmethod
    def update_note(cls, note_id: str | UUID, detail: str) -> None:
        db_session = get_current_session()
        db_session.execute(
            update(cls).where(cls.id == note_id).values(detail=detail, updated_at=datetime.now(UTC).replace(tzinfo=None))
        )

    @classmethod
    def delete_note(cls, note_id: str | UUID) -> None:
        db_session = get_current_session()
        db_session.execute(delete(cls).where(cls.id == note_id))

    @classmethod
    def get_notes_count_by_ids(cls, test_definition_ids: list[str]) -> dict[str, int]:
        """Returns {test_definition_id: count} for the given IDs, counting the notes of every version
        of each test. IDs with no notes are omitted."""
        definition = aliased(TestDefinition)
        peer = aliased(TestDefinition)
        rows = get_current_session().execute(
            select(definition.id, func.count(cls.id))
            .join(peer, cls._same_term(peer, definition))
            .join(cls, cls.test_definition_id == peer.id)
            .where(definition.id.in_([UUID(str(td_id)) for td_id in test_definition_ids]))
            .group_by(definition.id)
        ).all()
        return {str(td_id): count for td_id, count in rows}

    @classmethod
    def count_stored_on(cls, test_definition_ids: Iterable[str | UUID]) -> int:
        """The number of notes stored on the given rows, which are the notes deleting them deletes."""
        return get_current_session().scalar(
            select(func.count(cls.id)).where(
                cls.test_definition_id.in_([UUID(str(td_id)) for td_id in test_definition_ids])
            )
        ) or 0

    @classmethod
    def get_notes(cls, test_definition_id: str | UUID) -> list[dict]:
        """The notes of every version of the given test definition's test, newest first."""
        definition = aliased(TestDefinition)
        peer = aliased(TestDefinition)
        results = (
            get_current_session().execute(
                select(cls)
                .join(peer, peer.id == cls.test_definition_id)
                .join(definition, cls._same_term(peer, definition))
                .where(definition.id == test_definition_id)
                .order_by(cls.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": str(note.id),
                "detail": note.detail,
                "created_by": note.created_by,
                "created_at": note.created_at.isoformat() if note.created_at else None,
                "updated_at": note.updated_at.isoformat() if note.updated_at else None,
            }
            for note in results
        ]
