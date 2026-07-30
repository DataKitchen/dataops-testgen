import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import zip_longest
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    ForeignKey,
    String,
    Text,
    TypeDecorator,
    asc,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.expression import case, literal

from testgen.common.enums import MonitorType
from testgen.common.models import Base, get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, YNString, ZeroIfEmptyInteger
from testgen.common.models.entity import Entity, EntityMinimal
from testgen.utils import is_uuid4

TestRunType = Literal["QUERY", "CAT", "METADATA"]
TestScope = Literal["column", "referential", "table", "tablegroup", "custom"]
TestRunStatus = Literal["Running", "Complete", "Error", "Cancelled"]


class Severity(StrEnum):
    FAIL = "Fail"
    WARNING = "Warning"


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
    "Valid_Characters", "Valid_Month", "Valid_US_Zip", "Valid_US_Zip3",
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
    are enumerated and Defined Threshold is the fallthrough.
    """
    if test_scope == "custom":
        return TestCriteria.CUSTOM_CRITERIA
    if test_scope == "referential":
        return TestCriteria.REFERENCE_DATASET
    if algorithm == TestAlgorithm.SET_LOOKUP:
        return TestCriteria.LIST_OF_VALUES
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
    return value is None or value == ""


CUSTOM_METADATA_MAX_KEYS = 50
CUSTOM_METADATA_MAX_BYTES = 10_240


def validate_custom_metadata(value: object) -> str | None:
    """Return an error message if ``value`` is not a valid ``custom_metadata`` payload, else ``None``.

    ``custom_metadata`` must be a JSON object (key-value pairs), bounded in key count and serialized
    size. Shared by every write path — ``TestDefinition.validate`` (UI/CLI/MCP) and the
    ``TestDefinitionExport`` import schema — so the rule has a single definition.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        return "must be a JSON object of key-value pairs"
    if len(value) > CUSTOM_METADATA_MAX_KEYS:
        return f"must have at most {CUSTOM_METADATA_MAX_KEYS} keys"
    if len(json.dumps(value)) > CUSTOM_METADATA_MAX_BYTES:
        return f"must be at most {CUSTOM_METADATA_MAX_BYTES} bytes when serialized as JSON"
    return None


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
    definition are populated. See ``derive_threshold_mode``."""
    PREDICTION = "Prediction Model"
    HISTORICAL = "Historical Calculation"
    STATIC = "Static"
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
    if history_calculation == "PREDICT":
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

    # Unmapped columns: generation_template, result_visualization, result_visualization_params

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


def _required_fields_for(test_type: TestType) -> set[str]:
    """Fields that must be present and non-empty for the given test type.

    - Column-scoped tests implicitly require ``column_name``.
    - Tests that read a physical table implicitly require ``table_name`` — every scope except
      ``tablegroup`` (which spans the whole group) and the ``CUSTOM`` test type (whose
      ``custom_query`` supplies its own FROM clause; the table is only an output label).
    - ``default_parm_required`` is a CSV of ``Y``/``N`` aligned with ``default_parm_columns``;
      positions marked ``Y`` are required.
    """
    required: set[str] = set()
    if test_type.test_scope == "column":
        required.add("column_name")
    if test_type.test_scope != "tablegroup" and test_type.test_type != "CUSTOM":
        required.add("table_name")
    if test_type.default_parm_required and test_type.default_parm_columns:
        flags = [v.strip().upper() for v in test_type.default_parm_required.split(",")]
        columns = [c.strip() for c in test_type.default_parm_columns.split(",")]
        for col, flag in zip(columns, flags, strict=False):
            if flag == "Y":
                required.add(col)
    return required


class TestDefinition(Entity):
    __tablename__ = "test_definitions"

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
    test_mode: str = Column(String)
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
        test_mode,
        watch_level,
        check_result,
        last_auto_gen_date,
        profiling_as_of_date,
        prediction,
        external_id,
    )

    @classmethod
    def get(cls, identifier: str | UUID) -> TestDefinitionSummary | None:
        if not is_uuid4(identifier):
            return None

        result = cls._get_columns(
            identifier,
            cls._summary_columns,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
        )
        return TestDefinitionSummary(**result) if result else None

    @classmethod
    def get_for_project(
        cls, identifier: UUID, project_codes: list[str] | None = None,
    ) -> TestDefinitionSummary | None:
        """Fetch a test definition with project-level access check.

        Returns None if the definition doesn't exist, belongs to a monitor suite, or the user lacks access.
        """
        from testgen.common.models.test_suite import TestSuite

        select_columns = [
            getattr(cls, col, None) or getattr(TestType, col) if isinstance(col, str) else col
            for col in cls._summary_columns
        ]
        query = (
            select(*select_columns)
            .join(TestType, cls.test_type == TestType.test_type)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(cls.id == identifier, TestSuite.is_monitor.isnot(True))
        )
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        result = get_current_session().execute(query).mappings().first()
        return TestDefinitionSummary(**result) if result else None

    @classmethod
    def select_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TestDefinitionSummary]:
        results = cls._select_columns_where(
            cls._summary_columns,
            *clauses,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            order_by=order_by,
        )
        return [TestDefinitionSummary(**row) for row in results]

    @classmethod
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TestDefinitionMinimal]:
        results = cls._select_columns_where(
            cls._minimal_columns,
            *clauses,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            order_by=order_by,
        )
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
    ) -> tuple[list[TestDefinitionSummary], int]:
        """Paginated test definitions for a suite, with optional filters.

        Monitor suites are always filtered out — callers requesting a monitor suite get an empty page.
        Project-level access is enforced when ``project_codes`` is set.
        """
        from testgen.common.models.test_suite import TestSuite

        select_columns = [
            getattr(cls, col, None) or getattr(TestType, col) if isinstance(col, str) else col
            for col in cls._summary_columns
        ]
        query = (
            select(*select_columns)
            .join(TestType, cls.test_type == TestType.test_type)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(cls.test_suite_id == test_suite_id, TestSuite.is_monitor.isnot(True))
        )
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
    ) -> tuple[list["TestDefinitionSummary"], int]:
        select_columns = [
            getattr(cls, col, None) or getattr(TestType, col) if isinstance(col, str) else col
            for col in cls._summary_columns
        ]
        query = (
            select(*select_columns)
            .join(TestType, cls.test_type == TestType.test_type)
            .where(*clauses)
            .order_by(*(order_by or cls._default_order_by))
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
        # column_name is meaningful for column-scoped tests (the column under test),
        # custom-scoped tests (a "Test Focus" label), and referential tests (the aggregate
        # expression or categorical column list under test). Table-scoped tests don't use it.
        if test_type.test_scope in ("column", "custom", "referential"):
            fields = fields | {"column_name"}
        # impact_dimension is overridable only for user-defined-semantic scopes
        # (custom-scope = user-authored SQL; referential-scope = comparison-based tests).
        # Other scopes have baked-in dimensions so the override doesn't apply.
        if test_type.test_scope in ("custom", "referential"):
            fields = fields | {"impact_dimension"}
        return fields

    def validate(self, test_type: TestType) -> None:
        """Validate the current state against the given test type.

        Raises :class:`InvalidTestDefinitionFields` with every offending field
        and reason — callers see all problems at once.
        """
        errors: dict[str, str] = {}

        if self.severity:
            try:
                Severity(self.severity)
            except ValueError:
                errors["severity"] = (
                    f"must be `{Severity.FAIL.value}` or `{Severity.WARNING.value}` "
                    f"(got `{self.severity}`)"
                )

        # column_name applies to column-scoped tests (the column under test),
        # custom-scoped tests (a "Test Focus" label), and referential tests (the aggregate
        # expression or categorical column list under test). Table-scoped tests don't use it.
        if test_type.test_scope not in ("column", "custom", "referential") and not _is_blank(self.column_name):
            errors["column_name"] = (
                f"test type `{test_type.test_type}` has scope `{test_type.test_scope}`; "
                f"column_name does not apply to this scope"
            )

        if not _is_blank(self.custom_query) and "custom_query" not in test_type.param_columns:
            errors["custom_query"] = (
                f"test type `{test_type.test_type}` does not accept a custom query"
            )

        metadata_error = validate_custom_metadata(self.custom_metadata)
        if metadata_error:
            errors["custom_metadata"] = metadata_error

        for required in _required_fields_for(test_type):
            if _is_blank(getattr(self, required, None)):
                errors[required] = f"required for test type `{test_type.test_type}`"

        if errors:
            raise InvalidTestDefinitionFields(errors)

    @classmethod
    def set_status_attribute(
        cls,
        status_type: Literal["test_active", "lock_refresh", "flagged"],
        test_definition_ids: list[str | UUID],
        value: bool,
    ) -> None:
        query = f"""
        WITH selected AS (
            SELECT UNNEST(ARRAY [:test_definition_ids]) AS id
        )
        UPDATE test_definitions
        SET {status_type} = :value
            {", test_definition_status = NULL" if status_type == "test_active" and value else ""}
        FROM test_definitions td
            INNER JOIN selected ON (td.id = selected.id::UUID)
        WHERE td.id = test_definitions.id;
        """
        params = {
            "test_definition_ids": test_definition_ids,
            "value": YNString().process_bind_param(value, None) if status_type in cls._yn_columns else value,
        }

        db_session = get_current_session()
        db_session.execute(text(query), params)

    @classmethod
    def move(
        cls,
        test_definition_ids: list[str | UUID],
        target_table_group_id: str | UUID,
        target_test_suite_id: str | UUID,
        target_table_name: str | None = None,
        target_column_name: str | None = None,
    ) -> None:
        query = f"""
        WITH selected AS (
            SELECT UNNEST(ARRAY [:test_definition_ids]) AS id
        )
        UPDATE test_definitions
        SET
            {"table_name = :target_table_name," if target_table_name else ""}
            {"column_name = :target_column_name," if target_column_name else ""}
            table_groups_id = :target_table_group,
            test_suite_id = :target_test_suite
        FROM test_definitions td
            INNER JOIN selected ON (td.id = selected.id::UUID)
        WHERE td.id = test_definitions.id;
        """
        params = {
            "test_definition_ids": test_definition_ids,
            "target_table_group": target_table_group_id,
            "target_test_suite": target_test_suite_id,
            "target_table_name": target_table_name,
            "target_column_name": target_column_name,
        }

        db_session = get_current_session()
        db_session.execute(text(query), params)

    @classmethod
    def copy(
        cls,
        test_definition_ids: list[str | UUID],
        target_table_group_id: str | UUID,
        target_test_suite_id: str | UUID,
        target_table_name: str | None = None,
        target_column_name: str | None = None,
    ) -> None:
        modified_columns = [cls.id, cls.table_groups_id, cls.profile_run_id, cls.test_suite_id, cls.last_auto_gen_date]

        select_columns = [
            func.gen_random_uuid().label("id"),
            literal(target_table_group_id).label("table_groups_id"),
            case(
                (cls.table_groups_id == target_table_group_id, cls.profile_run_id),
                else_=None,
            ).label("profile_run_id"),
            literal(target_test_suite_id).label("test_suite_id"),
            literal(None).label("last_auto_gen_date"),
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
            [*modified_columns, *other_columns], select(*select_columns).where(cls.id.in_(test_definition_ids))
        )
        db_session = get_current_session()
        db_session.execute(query)

    @classmethod
    def get_source_data_context(cls, test_definition_id: UUID, project_codes: list[str] | None = None) -> dict | None:
        """Get the fields needed by the source data service for a given test definition."""
        session = get_current_session()

        sql = """
            SELECT
                d.table_groups_id,
                tt.id AS test_type_id,
                d.id AS test_definition_id,
                d.test_type,
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
                AND d.schema_name = dcc.schema_name
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

    def save(self) -> None:
        if self.id:
            values = {
                column.key: getattr(self, column.key, None)
                for column in self.__table__.columns
                if column not in self._update_exclude_columns
            }
            query = update(TestDefinition).where(TestDefinition.id == self.id).values(**values)
            db_session = get_current_session()
            db_session.execute(query)
        else:
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

    @classmethod
    def add_note(cls, test_definition_id: str | UUID, detail: str, username: str) -> "TestDefinitionNote":
        """Insert a note and return the persisted instance with ``id`` and ``created_at`` populated."""
        db_session = get_current_session()
        note = cls(
            test_definition_id=test_definition_id,
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
        """Returns {test_definition_id: count} for all given IDs."""
        db_session = get_current_session()
        rows = db_session.execute(
            text("""
                SELECT test_definition_id::VARCHAR, COUNT(*) as cnt
                FROM test_definition_notes
                WHERE test_definition_id = ANY(:ids)
                GROUP BY test_definition_id
            """),
            {"ids": [UUID(td_id) for td_id in test_definition_ids]},
        ).all()
        return {str(row[0]): row[1] for row in rows}

    @classmethod
    def get_notes(cls, test_definition_id: str | UUID) -> list[dict]:
        db_session = get_current_session()
        results = (
            db_session.execute(
                select(cls).where(cls.test_definition_id == test_definition_id).order_by(cls.created_at.desc())
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
