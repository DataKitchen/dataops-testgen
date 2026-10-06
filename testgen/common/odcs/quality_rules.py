"""Pure functions for building ODCS quality-rule fragments from TestGen's CAT test catalogue.

No database access: everything here operates on plain values so it can be exercised without
a session and reused by every caller that projects a quality rule. ``project_rule`` type-hints
against the ORM ``TestDefinition``/``TestType`` classes for readability, but only under
``TYPE_CHECKING`` -- at runtime it reads them by attribute access alone, so a duck-typed
stand-in works exactly as well as the real model. It imports one plain constant,
``ODCS_RULE_METADATA_KEY``, from ``common.models.test_definition``, not an ORM class. A
``sql``-shape rule's ``cat_test_conditions`` row is resolved by the caller (which has a
session) and passed in as a ``CatCondition`` -- this module reads the YAML-backed,
file-only ``templated_functions.yaml`` catalogue (via ``read_file.replace_templated_functions``)
to expand its macros, which is file access, not database access.
"""

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import yaml

from testgen.common.enums import OdcsDimension, QualityDimension
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, SqlFlavorCode
from testgen.common.models.test_definition import ODCS_RULE_METADATA_KEY, ODCS_STABLE_ID_PATTERN
from testgen.common.odcs.servers import FLAVOR_TO_SERVER_TYPE, ServerType
from testgen.common.read_file import replace_templated_functions

if TYPE_CHECKING:
    from testgen.common.models.test_definition import TestDefinition, TestType


class Operator(StrEnum):
    """The ``$defs.DataQualityOperators`` enum from the pinned ODCS JSON schema.

    Values are the schema's own eight branch names -- the quality-rule object is sealed with
    ``unevaluatedProperties: false``, so an unrecognized key here invalidates the whole rule.
    """
    MUST_BE = "mustBe"
    MUST_NOT_BE = "mustNotBe"
    MUST_BE_GREATER_THAN = "mustBeGreaterThan"
    MUST_BE_GREATER_OR_EQUAL_TO = "mustBeGreaterOrEqualTo"
    MUST_BE_LESS_THAN = "mustBeLessThan"
    MUST_BE_LESS_OR_EQUAL_TO = "mustBeLessOrEqualTo"
    MUST_BE_BETWEEN = "mustBeBetween"
    MUST_NOT_BE_BETWEEN = "mustNotBeBetween"


# A TestGen `test_operator` states when a CAT test fails; an ODCS rule states when the data is
# acceptable, so each value here is the negation of its key. Covers the six operators the test
# type catalogue's `cat_test_conditions` uses today.
ACCEPTANCE_OPERATOR: dict[str, Operator] = {
    ">": Operator.MUST_BE_LESS_OR_EQUAL_TO,
    "<": Operator.MUST_BE_GREATER_OR_EQUAL_TO,
    ">=": Operator.MUST_BE_LESS_THAN,
    "NOT BETWEEN": Operator.MUST_BE_BETWEEN,
    "<>": Operator.MUST_BE,
    "!=": Operator.MUST_BE,
}

# TestGen dimensions with no like-named ODCS counterpart. Every other QualityDimension passes
# through lower-cased in `odcs_dimension`.
_DIMENSION_TRANSLATION: dict[QualityDimension, OdcsDimension] = {
    QualityDimension.RECENCY: OdcsDimension.TIMELINESS,
    QualityDimension.VALIDITY: OdcsDimension.CONFORMITY,
}


def bound_clause(lower: Any, upper: Any) -> dict[str, Any]:
    """Build the ODCS quality-rule fragment for an acceptable range.

    ``lower`` and ``upper`` are the acceptable bounds, either of which may be ``None``. Two
    distinct bounds render ``mustBeBetween``; equal bounds render ``mustBe`` instead, since
    ``mustBeBetween`` requires two unique items. A single bound renders the matching one-sided
    operator, and no bounds render an empty dict. The result never carries more than one
    operator key -- this is the single place that decides which one operator applies. The key
    is a plain ``str`` (``Operator.value``), not the enum member: the result is document data
    bound for YAML and JSON, and ``yaml.safe_dump`` cannot represent an enum member.
    """
    if lower is not None and upper is not None:
        if lower == upper:
            return {Operator.MUST_BE.value: lower}
        return {Operator.MUST_BE_BETWEEN.value: [lower, upper]}
    if lower is not None:
        return {Operator.MUST_BE_GREATER_OR_EQUAL_TO.value: lower}
    if upper is not None:
        return {Operator.MUST_BE_LESS_OR_EQUAL_TO.value: upper}
    return {}


def odcs_dimension(quality_dimension: QualityDimension) -> str:
    """Translate a TestGen ``QualityDimension`` into its ODCS ``OdcsDimension`` value.

    ``Recency`` and ``Validity`` map onto ``timeliness`` and ``conformity``, the ODCS terms
    with no like-named TestGen counterpart; every other dimension passes through lower-cased.
    The return is a plain ``str`` (``OdcsDimension.value``), not the enum member: the result is
    document data bound for YAML and JSON, and ``yaml.safe_dump`` cannot represent an enum
    member.
    """
    translated = _DIMENSION_TRANSLATION.get(quality_dimension)
    resolved = translated if translated is not None else OdcsDimension(quality_dimension.value.lower())
    return resolved.value


class RuleShape(StrEnum):
    """How a routed test type's quality rule is built.

    ``LIBRARY`` renders one of the schema's five ``metric`` values. ``SQL`` renders a
    ``query`` built from the test type's ``cat_test_conditions.measure``. ``CUSTOM`` renders
    an ``engine``/``implementation`` block for a check no other ODCS engine can run.
    """
    LIBRARY = "library"
    SQL = "sql"
    CUSTOM = "custom"


class RuleScope(StrEnum):
    """The ODCS node a test type's rule attaches to.

    Declared by every test type a term can be authored against -- ``RULE_MAPPINGS`` for a
    routed one, ``PENDING_DECISION`` for one whose rule shape is still undecided -- and read
    through ``declared_scope``. Distinct from ``TestScope``: TestGen's
    ``test_types.test_scope`` has five stored values, an ODCS document has only two places a
    rule can nest.
    """
    COLUMN = "column"
    TABLE = "table"


class LibraryMetric(StrEnum):
    """The ``$defs.DataQuality.properties.metric`` enum from the pinned ODCS JSON schema."""
    NULL_VALUES = "nullValues"
    MISSING_VALUES = "missingValues"
    INVALID_VALUES = "invalidValues"
    DUPLICATE_VALUES = "duplicateValues"
    ROW_COUNT = "rowCount"


@dataclass(frozen=True)
class RuleMapping:
    """One test type's route to an ODCS quality rule.

    ``metric``, ``unit`` and ``argument`` are set only when ``shape`` is ``LIBRARY``; every
    other shape carries ``None`` for all three. ``operator`` is the acceptance operator the
    rendered rule carries: for most rows this is the inversion of the type's stored
    ``test_operator`` (see ``ACCEPTANCE_OPERATOR``), but ``Missing_Pct``, ``Unique_Pct`` and
    ``Row_Ct_Pct`` carry ``mustBeBetween`` outright -- a converted band around a fixed
    baseline, not an inversion of the stored operator. ``dimension`` is the already-translated
    ODCS dimension (``odcs_dimension`` output), except ``LOV_All``, which carries ``coverage``
    explicitly rather than the ``conformity`` its stored ``Validity`` dimension would translate
    to.
    """
    test_type: str
    shape: RuleShape
    scope: RuleScope
    operator: Operator
    dimension: str
    metric: LibraryMetric | None = None
    unit: str | None = None
    argument: str | None = None


@dataclass(frozen=True)
class CatCondition:
    """One resolved ``cat_test_conditions`` row -- a test type's check, for one SQL flavor.

    This module has no database access, so a caller with a session (the contract renderer)
    resolves the row for a term's ``test_type`` and the declared server's flavor, and passes
    it to ``project_rule`` for an ``SQL``-shape term. ``measure`` and ``test_condition`` are
    the raw, unsubstituted template text -- TestGen's own ``{PLACEHOLDER}`` tokens, not yet
    rewritten into ODCS syntax or literal values; ``test_operator`` is the raw stored
    comparison (``>``, ``<``, ...), inverted into an acceptance operator the same way every
    other row's is (``ACCEPTANCE_OPERATOR``).
    """
    measure: str
    test_operator: str
    test_condition: str


# The nine test types with a direct ODCS library metric. `Missing_Pct`, `Unique_Pct` and
# `Row_Ct_Pct` carry `mustBeBetween`: each threshold is a Cohen's h drift bound, and Cohen's h
# is monotonic in the underlying ratio, so one h-threshold around a fixed baseline maps onto a
# closed interval on that ratio -- the interval's bounds are computed elsewhere, this table
# only records that the rendered operator is the between one.
_LIBRARY_ROWS: dict[str, RuleMapping] = {
    "Required": RuleMapping(
        test_type="Required",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
        metric=LibraryMetric.NULL_VALUES,
        unit="rows",
    ),
    "Missing_Pct": RuleMapping(
        test_type="Missing_Pct",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_BETWEEN,
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
        metric=LibraryMetric.NULL_VALUES,
        unit="percent",
    ),
    "Unique_Pct": RuleMapping(
        test_type="Unique_Pct",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_BETWEEN,
        dimension=odcs_dimension(QualityDimension.UNIQUENESS),
        metric=LibraryMetric.DUPLICATE_VALUES,
        unit="percent",
    ),
    "LOV_Match": RuleMapping(
        test_type="LOV_Match",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.VALIDITY),
        metric=LibraryMetric.INVALID_VALUES,
        unit="rows",
        argument="validValues",
    ),
    "Pattern_Match": RuleMapping(
        test_type="Pattern_Match",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.VALIDITY),
        metric=LibraryMetric.INVALID_VALUES,
        unit="rows",
        argument="pattern",
    ),
    "Row_Ct": RuleMapping(
        test_type="Row_Ct",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.TABLE,
        operator=Operator.MUST_BE_GREATER_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
        metric=LibraryMetric.ROW_COUNT,
        unit="rows",
    ),
    "Row_Ct_Pct": RuleMapping(
        test_type="Row_Ct_Pct",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.TABLE,
        operator=Operator.MUST_BE_BETWEEN,
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
        metric=LibraryMetric.ROW_COUNT,
        unit="percent",
    ),
}

# Every other routed test type: `sql`, projected from `cat_test_conditions.measure`. The
# operator is the inversion (via `ACCEPTANCE_OPERATOR`) of the type's stored `test_operator`.
# `Condition_Flag` is the one `custom`-scope row here. Its measure is
# `SUM(CASE WHEN {CUSTOM_QUERY} THEN 1 ELSE 0 END)` -- it references `{CUSTOM_QUERY}` and never
# `{COLUMN_NAME}`, and its `column_name_prompt` ("Test Focus") is a free-text label, not
# necessarily a real column. The rule needs no column node, and ODCS's `{property}` placeholder
# is only defined on a column-node rule, so `TABLE` is the correct attachment here, not a
# fallback.
_SQL_ROWS: dict[str, RuleMapping] = {
    "Alpha_Trunc": RuleMapping(
        test_type="Alpha_Trunc",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR["<"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Avg_Shift": RuleMapping(
        test_type="Avg_Shift",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">="],
        dimension=odcs_dimension(QualityDimension.CONSISTENCY),
    ),
    "Constant": RuleMapping(
        test_type="Constant",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Daily_Record_Ct": RuleMapping(
        test_type="Daily_Record_Ct",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
    ),
    "Dec_Trunc": RuleMapping(
        test_type="Dec_Trunc",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR["<"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Distinct_Date_Ct": RuleMapping(
        test_type="Distinct_Date_Ct",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR["<"],
        dimension=odcs_dimension(QualityDimension.TIMELINESS),
    ),
    "Distinct_Value_Ct": RuleMapping(
        test_type="Distinct_Value_Ct",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR["<>"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Email_Format": RuleMapping(
        test_type="Email_Format",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Future_Date": RuleMapping(
        test_type="Future_Date",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.TIMELINESS),
    ),
    "Future_Date_1Y": RuleMapping(
        test_type="Future_Date_1Y",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.TIMELINESS),
    ),
    "Incr_Avg_Shift": RuleMapping(
        test_type="Incr_Avg_Shift",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">="],
        dimension=odcs_dimension(QualityDimension.ACCURACY),
    ),
    "LOV_All": RuleMapping(
        test_type="LOV_All",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR["<>"],
        dimension=OdcsDimension.COVERAGE.value,
    ),
    "Min_Date": RuleMapping(
        test_type="Min_Date",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Min_Val": RuleMapping(
        test_type="Min_Val",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Monthly_Rec_Ct": RuleMapping(
        test_type="Monthly_Rec_Ct",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
    ),
    "Outlier_Pct_Above": RuleMapping(
        test_type="Outlier_Pct_Above",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.ACCURACY),
    ),
    "Outlier_Pct_Below": RuleMapping(
        test_type="Outlier_Pct_Below",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.ACCURACY),
    ),
    "Recency": RuleMapping(
        test_type="Recency",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.TIMELINESS),
    ),
    "Street_Addr_Pattern": RuleMapping(
        test_type="Street_Addr_Pattern",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR["<"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "US_State": RuleMapping(
        test_type="US_State",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Valid_Characters": RuleMapping(
        test_type="Valid_Characters",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Valid_Month": RuleMapping(
        test_type="Valid_Month",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Valid_US_Zip": RuleMapping(
        test_type="Valid_US_Zip",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Valid_US_Zip3": RuleMapping(
        test_type="Valid_US_Zip3",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
    "Variability_Decrease": RuleMapping(
        test_type="Variability_Decrease",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR["<"],
        dimension=odcs_dimension(QualityDimension.ACCURACY),
    ),
    "Variability_Increase": RuleMapping(
        test_type="Variability_Increase",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.ACCURACY),
    ),
    "Weekly_Rec_Ct": RuleMapping(
        test_type="Weekly_Rec_Ct",
        shape=RuleShape.SQL,
        scope=RuleScope.COLUMN,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
    ),
    "Condition_Flag": RuleMapping(
        test_type="Condition_Flag",
        shape=RuleShape.SQL,
        scope=RuleScope.TABLE,
        operator=ACCEPTANCE_OPERATOR[">"],
        dimension=odcs_dimension(QualityDimension.VALIDITY),
    ),
}

# Every routed test type -- the union `render` and `resolve_rule` both read. Disjoint from
# `EXCLUDED_TEST_TYPES` and `PENDING_DECISION`; `test_rule_mapping_coverage.py` enforces the
# union of the three against the test type catalogue.
RULE_MAPPINGS: dict[str, RuleMapping] = {**_LIBRARY_ROWS, **_SQL_ROWS}

# Run-history test types: no term is ever authored against them, so no quality rule applies.
# The value is the reason a reviewer would otherwise have to re-derive.
EXCLUDED_TEST_TYPES: dict[str, str] = {
    "Volume_Trend": "run-history type -- monitors row-count drift over time, not a contract-testable state",
    "Freshness_Trend": "run-history type -- monitors update-interval drift over time, not a contract-testable state",
    "Metric_Trend": "run-history type -- monitors an aggregate metric's drift over time, not a contract-testable state",
    "Schema_Drift": "run-history type -- monitors schema changes over time, not a contract-testable state",
}

@dataclass(frozen=True)
class PendingRouting:
    """One test type whose ODCS rule shape is undecided, and where its rule hangs meanwhile.

    ``reason`` is the open question a shape decision has to answer. ``scope`` does not wait on
    that answer: which node a rule attaches to is a separate question, settled from the
    catalogue's own ``column_name_prompt`` -- what the field holds, and whether that is a
    column at all.
    """
    scope: RuleScope
    reason: str


# Test types the team has deferred a routing decision on. Each carries the open question
# rather than a guess -- routing one of these before the question is answered would render a
# rule that is either wrong (see the null-counting and implicit-bound cases) or a coin flip
# between two valid ODCS shapes (see the no-scalar-measure case). `test_rule_mapping_coverage.py`
# carries one `xfail(strict=True)` test per entry so a routing lands as a marker removal, not a
# silent addition.
#
# Each row's `scope` is read off the catalogue, which already says what the term's
# `column_name` holds: COLUMN where it names one column (`test_scope: column` -- `Unique`) or
# an aggregate over one (`column_name_prompt: Aggregate Expression` -- the four
# `Aggregate_*` types, whose expression is exactly what a synthesized measure property is
# for), and TABLE everywhere else, because everything else puts something in `column_name`
# that is not a column: a comma-separated list of them (`Categorical Column List` -- the
# `Combo_Match` family), a free-text label distinguishing two terms on the same table
# (`Test Focus` -- `CUSTOM`, the same field `Condition_Flag` carries), or nothing at all
# (`Dupe_Rows`, `Table_Freshness`). `test_rule_mapping_coverage.py` re-derives this from the
# catalogue rather than restating it, so a new type whose declaration disagrees fails there.
PENDING_DECISION: dict[str, PendingRouting] = {
    "Unique": PendingRouting(
        scope=RuleScope.COLUMN,
        reason="its measure counts NULLs as duplicates, so no threshold conversion maps it onto duplicateValues",
    ),
    "Dupe_Rows": PendingRouting(
        scope=RuleScope.TABLE,
        reason="no threshold parameter -- the bound is implicit, and what the rendered rule's operator and "
        "value should be is undecided",
    ),
    "Table_Freshness": PendingRouting(
        scope=RuleScope.TABLE,
        reason="no scalar measure and no numeric threshold -- its bound is a fingerprint comparison, "
        "so what the rendered rule should assert is undecided",
    ),
    "Aggregate_Balance": PendingRouting(
        scope=RuleScope.COLUMN,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "Aggregate_Balance_Percent": PendingRouting(
        scope=RuleScope.COLUMN,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "Aggregate_Balance_Range": PendingRouting(
        scope=RuleScope.COLUMN,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "Aggregate_Minimum": PendingRouting(
        scope=RuleScope.COLUMN,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "Combo_Match": PendingRouting(
        scope=RuleScope.TABLE,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "Distribution_Shift": PendingRouting(
        scope=RuleScope.TABLE,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "Timeframe_Combo_Gain": PendingRouting(
        scope=RuleScope.TABLE,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "Timeframe_Combo_Match": PendingRouting(
        scope=RuleScope.TABLE,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
    "CUSTOM": PendingRouting(
        scope=RuleScope.TABLE,
        reason="no scalar cat_test_conditions measure -- sql (wrapped join) vs custom is undecided",
    ),
}


# Every test type that declares where its rule hangs, from both sources in one lookup. The
# two paths that read it want opposite things from a type declaring nothing -- rendering our
# own term raises, resolving a counterparty's rule declines -- so each handles the miss
# itself rather than sharing one answer.
_DECLARED_SCOPES: dict[str, RuleScope] = {
    **{test_type: mapping.scope for test_type, mapping in RULE_MAPPINGS.items()},
    **{test_type: routing.scope for test_type, routing in PENDING_DECISION.items()},
}


def declared_scope(test_type: str) -> RuleScope:
    """The ODCS node ``test_type``'s rule attaches to.

    Read from the type's own declaration -- its ``RULE_MAPPINGS`` row, or its
    ``PENDING_DECISION`` row while its shape is undecided. Raises ``ValueError`` for a type
    that declares neither, rather than falling back to whether a term happens to carry a
    ``column_name``: that field is a free-text label on some types and a list of columns on
    others, so inferring placement from it lands a rule on a property representing no column.

    For the rendering path, where a term stored against such a type is our own inconsistency.
    A caller reading an incoming document must not use this -- see ``_resolve_marker``.
    """
    scope = _DECLARED_SCOPES.get(test_type)
    if scope is None:
        raise ValueError(f"{test_type!r} declares no rule scope, so its rule has no node to attach to.")
    return scope


def _numeric(raw: str) -> int | float:
    """Parse a stored threshold-shaped string into a plain, JSON-safe number.

    Renders a whole number as ``int`` rather than ``2.0`` -- ODCS operators accept either,
    but the term's own value was typed by a user as a count, not a float.
    """
    value = float(raw)
    return int(value) if value.is_integer() else value


def _cohens_h_band(baseline_ratio: float, h: float) -> tuple[float, float]:
    """The closed ratio interval a Cohen's h bound ``h`` maps onto around ``baseline_ratio``.

    Cohen's h, ``phi(p) = 2*asin(sqrt(p))``, is monotonic in the ratio, so a single
    threshold around a fixed baseline corresponds to exactly one interval on the ratio
    itself: ``[inv(phi(baseline) - h), inv(phi(baseline) + h)]`` where
    ``inv(f) = sin(f/2)**2``.
    """
    center = 2 * math.asin(math.sqrt(baseline_ratio))
    lower = math.sin((center - h) / 2) ** 2
    upper = math.sin((center + h) / 2) ** 2
    return lower, upper


def _complement_percent_band(lower_ratio: float, upper_ratio: float) -> tuple[float, float]:
    """The percent band on a ratio's complement -- e.g. null percent from populated ratio."""
    return 100 * (1 - upper_ratio), 100 * (1 - lower_ratio)


def _missing_pct_band(term: "TestDefinition") -> tuple[float, float, float, float]:
    """Null-percent band, baseline populated ratio and threshold bound for a ``Missing_Pct`` term."""
    baseline_ratio = float(term.baseline_value_ct) / float(term.baseline_ct)
    h = float(term.threshold_value)
    lower_ratio, upper_ratio = _cohens_h_band(baseline_ratio, h)
    lower, upper = _complement_percent_band(lower_ratio, upper_ratio)
    return lower, upper, baseline_ratio, h


def _unique_pct_band(term: "TestDefinition") -> tuple[float, float, float, float]:
    """Duplicate-percent band, baseline distinct ratio and threshold bound for a ``Unique_Pct`` term."""
    baseline_ratio = float(term.baseline_unique_ct) / float(term.baseline_value_ct)
    h = float(term.threshold_value)
    lower_ratio, upper_ratio = _cohens_h_band(baseline_ratio, h)
    lower, upper = _complement_percent_band(lower_ratio, upper_ratio)
    return lower, upper, baseline_ratio, h


def _row_ct_pct_band(term: "TestDefinition") -> tuple[float, float, float, float]:
    """Row-count band, baseline count and threshold percent for a ``Row_Ct_Pct`` term.

    ``|100*(n-b)/b| <= T`` rearranges to ``n in [b*(1-T/100), b*(1+T/100)]``.
    """
    baseline_count = float(term.baseline_ct)
    percent = float(term.threshold_value)
    lower = baseline_count * (1 - percent / 100)
    upper = baseline_count * (1 + percent / 100)
    return lower, upper, baseline_count, percent


def _conversion_properties(
    baseline: float, bound: float, *, baseline_property: str = "baselineRatio", bound_property: str = "thresholdBound"
) -> list[dict[str, Any]]:
    """The originals behind a converted band, carried under the ``testgen`` vendor so the
    term is recoverable exactly from the rendered rule alone."""
    return [
        {"property": baseline_property, "value": baseline, "vendor": "testgen"},
        {"property": bound_property, "value": bound, "vendor": "testgen"},
    ]


def _test_type_marker(test_type_code: str) -> dict[str, Any]:
    return {"property": "testType", "value": test_type_code, "vendor": "testgen"}


def _server_type_marker(server_type: ServerType) -> dict[str, Any]:
    return {"property": "serverType", "value": server_type.value, "vendor": "testgen"}


# Reserved-subtree fields copied onto the rule unchanged when present. `dimension`,
# `tags`, `authoritativeDefinitions` and `customProperties` each need their own handling
# (a translation, a list assignment, a list assignment and a merge respectively), so they
# are not in this tuple -- see `_apply_reserved_subtree`.
_RESERVED_DIRECT_FIELDS: tuple[str, ...] = ("name", "businessImpact", "method", "schedule", "scheduler")

# The pinned ODCS schema's `CustomProperty`/`AuthoritativeDefinitions` item objects are
# sealed (`additionalProperties: false`), and their `id` (when present) is a `StableId`,
# constrained to `ODCS_STABLE_ID_PATTERN`. The model's save-time validator
# (`test_definition.py::_validate_odcs_rule_metadata`) rejects a stray key or a malformed
# `id` inside one going forward, but a row saved before that check existed, or one arriving
# through the test-definition import, is not guaranteed to satisfy it -- so this reader
# reconstructs each entry from only its recognised fields rather than forwarding the stored
# dict verbatim, and drops a non-conforming `id` from the rebuilt entry rather than the
# entry itself. An entry missing one of its required fields (`id` is never one of them) is
# dropped rather than forwarded incomplete; all three are the same "tolerate history, don't
# propagate a shape the writer would now refuse, keep everything else the user supplied"
# move.
_CUSTOM_PROPERTY_FIELDS: tuple[str, ...] = ("id", "property", "value", "description", "vendor")
_CUSTOM_PROPERTY_REQUIRED_FIELDS = frozenset({"property", "value"})
_AUTHORITATIVE_DEFINITION_FIELDS: tuple[str, ...] = ("id", "url", "type", "description")
_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS = frozenset({"url", "type"})


def _reconstruct_sealed_entries(
    items: object, fields: tuple[str, ...], required: frozenset[str]
) -> list[dict[str, Any]]:
    """Rebuild each item in ``items`` from only its recognised ``fields``, dropping any item
    that is missing one of its ``required`` fields entirely.

    A present ``id`` that is not a string matching ``ODCS_STABLE_ID_PATTERN`` is dropped from
    the rebuilt entry rather than the whole entry -- ``id`` is never one of ``required``
    (only ``property``/``value`` or ``url``/``type`` are), so an entry with everything else
    intact stays valid and its user-supplied data is not discarded over one bad field.
    """
    if not isinstance(items, list):
        return []
    rebuilt = []
    for entry in items:
        if isinstance(entry, dict) and required <= entry.keys():
            built = {field: entry[field] for field in fields if field in entry}
            entry_id = built.get("id")
            if entry_id is not None and not (isinstance(entry_id, str) and ODCS_STABLE_ID_PATTERN.match(entry_id)):
                del built["id"]
            rebuilt.append(built)
    return rebuilt


def _apply_reserved_subtree(rule: dict[str, Any], custom_metadata: dict | None) -> list[dict[str, Any]]:
    """Copy the reserved ``custom_metadata['odcs']`` subtree's recognised fields onto ``rule``.

    Mutates ``rule`` in place for the direct-copy fields and the dimension override, and
    returns the subtree's own ``customProperties`` entries for the caller to merge in
    alongside the term's other customProperties. An unrecognised key at the subtree's own
    top level is not copied -- a document written by a newer TestGen stays readable by an
    older one. ``customProperties`` and ``authoritativeDefinitions`` entries are rebuilt
    field-by-field (``_reconstruct_sealed_entries``) rather than forwarded verbatim: their
    item shape is sealed in the schema, so an unrecognised key inside one is not tolerated
    the same way -- it would validate at save and then break the version's freeze.
    """
    reserved = (custom_metadata or {}).get(ODCS_RULE_METADATA_KEY) if custom_metadata else None
    if not isinstance(reserved, dict):
        return []

    for field in _RESERVED_DIRECT_FIELDS:
        value = reserved.get(field)
        if value is not None:
            rule[field] = value

    dimension = reserved.get("dimension")
    if dimension is not None:
        rule["dimension"] = OdcsDimension(dimension).value

    tags = reserved.get("tags")
    if tags is not None:
        rule["tags"] = tags

    authoritative_definitions = reserved.get("authoritativeDefinitions")
    if authoritative_definitions is not None:
        rule["authoritativeDefinitions"] = _reconstruct_sealed_entries(
            authoritative_definitions, _AUTHORITATIVE_DEFINITION_FIELDS, _AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS
        )

    custom_properties = reserved.get("customProperties")
    return _reconstruct_sealed_entries(custom_properties, _CUSTOM_PROPERTY_FIELDS, _CUSTOM_PROPERTY_REQUIRED_FIELDS)


def _user_custom_properties(custom_metadata: dict | None) -> list[dict[str, Any]]:
    """The caller's own top-level ``custom_metadata`` keys, promoted onto the rule as
    ``customProperties``. Excludes the reserved ``odcs`` key, which
    ``_apply_reserved_subtree`` handles separately."""
    if not custom_metadata:
        return []
    return [
        {"property": key, "value": value} for key, value in custom_metadata.items() if key != ODCS_RULE_METADATA_KEY
    ]


# The term fields a `custom` rule's `implementation` carries -- the parameters that define
# what the term checks, dumped as YAML rather than synthesized into a query no other ODCS
# engine could run anyway (see `RuleShape.CUSTOM` on `RuleMapping`).
_CUSTOM_IMPLEMENTATION_FIELDS: tuple[str, ...] = (
    "schema_name", "table_name", "column_name",
    "baseline_ct", "baseline_unique_ct", "baseline_value", "baseline_value_ct",
    "threshold_value", "baseline_sum", "baseline_avg", "baseline_sd",
    "lower_tolerance", "upper_tolerance",
    "subset_condition", "groupby_names", "having_condition",
    "window_date_column", "window_days",
    "match_schema_name", "match_table_name", "match_column_names",
    "match_subset_condition", "match_groupby_names", "match_having_condition",
    "custom_query",
)


def _custom_implementation(term: "TestDefinition") -> str:
    """A YAML dump of ``term``'s own non-empty parameters -- the payload a ``custom`` rule carries."""
    parameters = {
        field: getattr(term, field) for field in _CUSTOM_IMPLEMENTATION_FIELDS if getattr(term, field) not in (None, "")
    }
    return yaml.safe_dump(parameters, sort_keys=True)


# Server -> flavor is not injective (azure_mssql and mssql both serve ServerType.SQLSERVER),
# but every flavor sharing a server type also shares a `FLAVOR_CODE_TO_FAMILY` family, so
# which one this picks does not matter -- it is the family that selects the measure dialect.
_SERVER_TYPE_TO_FLAVOR: dict[ServerType, SqlFlavorCode] = {
    server: flavor for flavor, server in FLAVOR_TO_SERVER_TYPE.items()
}


def _flavor_family_for(server_type: ServerType) -> str:
    """The ``cat_test_conditions``/``templated_functions.yaml`` flavor family a ``ServerType``
    resolves to -- the same family key the test type catalogue's ``sql_flavor`` uses."""
    flavor = _SERVER_TYPE_TO_FLAVOR.get(server_type)
    if flavor is None:
        raise ValueError(f"{server_type!r} has no SqlFlavorCode mapping to resolve a measure dialect from.")
    return FLAVOR_CODE_TO_FAMILY[flavor.value]


def _sql_literal_substitutions(term: "TestDefinition", column_type: str | None) -> dict[str, Any]:
    """TestGen placeholders a resolved measure/condition may carry, mapped to the term's own
    literal values. These are frozen into the query at export time -- unlike ``{object}``,
    ``{property}`` and ``CURRENT_DATE``, nothing on the counterparty's side resolves them, so
    leaving one of these unsubstituted would ship a query no engine can run.

    ``column_type`` is the profiled column's data type (``DataColumnChars.column_type``) --
    the caller's to supply, since this module has no database access. It is ``None`` unless
    the caller passed one; a measure that needs ``{COLUMN_TYPE}`` and gets none is caught by
    ``_build_sql_query``'s leftover-placeholder check rather than silently stringified.
    """
    return {
        "{THRESHOLD_VALUE}": term.threshold_value,
        "{BASELINE_CT}": term.baseline_ct,
        "{BASELINE_UNIQUE_CT}": term.baseline_unique_ct,
        "{BASELINE_VALUE}": term.baseline_value,
        "{BASELINE_VALUE_CT}": term.baseline_value_ct,
        "{BASELINE_SUM}": term.baseline_sum,
        "{BASELINE_AVG}": term.baseline_avg,
        "{BASELINE_SD}": term.baseline_sd,
        "{LOWER_TOLERANCE}": term.lower_tolerance,
        "{UPPER_TOLERANCE}": term.upper_tolerance,
        "{SUBSET_CONDITION}": term.subset_condition or "1=1",
        "{CUSTOM_QUERY}": term.custom_query,
        "{COLUMN_TYPE}": column_type,
    }


def _resolved_bound(
    condition: CatCondition, term: "TestDefinition", column_type: str | None
) -> tuple[Operator, int | float]:
    """The acceptance operator and its numeric bound for an ``sql`` rule.

    Read from the resolved condition's own ``test_operator``/``test_condition`` -- not
    assumed from the type -- so a row whose stored condition differs from the rest of its
    type's rows is still rendered faithfully.
    """
    operator = ACCEPTANCE_OPERATOR[condition.test_operator]
    condition_text = condition.test_condition
    for token, value in _sql_literal_substitutions(term, column_type).items():
        if value is not None and token in condition_text:
            condition_text = condition_text.replace(token, str(value))
    return operator, _numeric(condition_text)


# TestGen's own placeholder shape -- {ALL_CAPS_WITH_UNDERSCORES} -- versus the two ODCS
# placeholders a query is allowed to still carry once this module is done with it.
_LEFTOVER_PLACEHOLDER = re.compile(r"\{[A-Z_]+\}")
_LEGAL_ODCS_PLACEHOLDERS = frozenset({"{object}", "{property}"})

# Every flavor's measure wraps {RUN_DATE} as a quoted string literal fed to a date-parsing
# cast or function (`'{RUN_DATE}'::DATE`, `TO_DATE('{RUN_DATE}', ...)`, ...). The quoted
# form is replaced as a unit so the result is the bare keyword CURRENT_DATE, not a quoted
# string reading "CURRENT_DATE" that a date cast would then fail to parse.
_RUN_DATE_QUOTED = re.compile(r"'\{RUN_DATE\}'")


def _build_sql_query(
    term: "TestDefinition",
    condition: CatCondition,
    scope: RuleScope,
    server_type: ServerType,
    column_type: str | None,
) -> str:
    """The ``sql`` rule's ``query``: the resolved condition's own measure, rewritten so it
    means the same check to any ODCS-compliant engine as it does inside TestGen.

    TestGen's own ``{PLACEHOLDER}`` tokens are not ODCS syntax and must not reach the
    document: ``{COLUMN_NAME}`` becomes ODCS's own ``{property}`` (only on a column-scoped
    rule -- R15), the table becomes ``{object}``, ``{RUN_DATE}`` becomes the ANSI
    ``CURRENT_DATE`` (never a date frozen at export time -- the rule must mean the same
    thing whenever the counterparty next checks it), and every other placeholder is replaced
    with the term's own literal value -- ``{COLUMN_TYPE}`` (bigquery/sap_hana's cast target
    for a handful of types) with ``column_type``, the caller-supplied profiled column type.
    Macro calls (``<%FUNC;args%>``) are expanded for the declared server's flavor by the same
    expander the execution engine uses (``read_file.replace_templated_functions``), not a
    second one.

    Raises ``ValueError`` naming the type, the server and the exact leftover token(s) if
    anything TestGen-shaped survives substitution -- a leftover placeholder would still
    validate against the schema and then fail at the counterparty, which is the failure this
    whole task exists to prevent.
    """
    measure = condition.measure

    if scope is RuleScope.COLUMN:
        measure = measure.replace("{COLUMN_NAME}", "{property}")

    # A qualified schema/table pattern some flavors' measures use to reference the same
    # table a second time (e.g. LOV_All's mssql/sap_hana inner subquery) -- it names the
    # same object the rule is attached to, so it collapses onto ODCS's own placeholder too.
    measure = measure.replace('"{SCHEMA_NAME}"."{TABLE_NAME}"', "{object}")
    measure = measure.replace("{SCHEMA_NAME}", "{object}").replace("{TABLE_NAME}", "{object}")

    measure = _RUN_DATE_QUOTED.sub("CURRENT_DATE", measure).replace("{RUN_DATE}", "CURRENT_DATE")

    for token, value in _sql_literal_substitutions(term, column_type).items():
        if value is not None and token in measure:
            measure = measure.replace(token, str(value))

    measure = replace_templated_functions(measure, _flavor_family_for(server_type))

    query = f"SELECT {measure} FROM {{object}}"
    leftover = sorted({token for token in _LEFTOVER_PLACEHOLDER.findall(query) if token not in _LEGAL_ODCS_PLACEHOLDERS})
    if leftover:
        raise ValueError(
            f"{term.test_type!r} on {server_type.value!r} left {leftover} unresolved in its sql query -- "
            "no data was available to substitute it."
        )
    return query


def _project_pending_rule(term: "TestDefinition", test_type: "TestType") -> dict[str, Any]:
    """The ``text`` rule a routing-deferred (``PENDING_DECISION``) test type projects.

    Nothing is dropped: a term whose type has no confirmed routing still lands in the
    document, carrying its type and an explicit ``verifiable: false`` marker, so a later
    routing decision replaces this rule with a real one rather than resurrecting a term
    that silent exclusion had already lost.
    """
    name = term.test_description or test_type.test_name_long or test_type.test_name_short or term.test_type
    rule: dict[str, Any] = {
        "type": "text",
        "name": name,
        "description": "Carried unverified: routing for this test type is not yet decided.",
        "dimension": odcs_dimension(QualityDimension(test_type.dq_dimension)),
        "id": term.contract_term_id,
    }

    reserved_properties = _apply_reserved_subtree(rule, term.custom_metadata)
    user_properties = _user_custom_properties(term.custom_metadata)
    rule["customProperties"] = [
        *reserved_properties,
        *user_properties,
        _test_type_marker(term.test_type),
        {"property": "verifiable", "value": False, "vendor": "testgen"},
    ]
    return rule


def project_rule(
    term: "TestDefinition",
    test_type: "TestType",
    server_type: ServerType,
    condition: CatCondition | None = None,
    column_type: str | None = None,
) -> dict[str, Any]:
    """Project one contract term into one ODCS quality-rule object.

    ``term`` supplies the stored values a rule is built from -- threshold, baseline
    statistics, custom query, contract identity, and the reserved
    ``custom_metadata['odcs']`` subtree. ``test_type`` supplies the catalogue context a
    routing-deferred term needs (its display name and TestGen dimension) when
    ``term.test_type`` has no row in ``RULE_MAPPINGS``. ``server_type`` names the dialect a
    ``sql`` or ``custom`` rule's payload is written in, carried onto the rule so it stays
    recoverable. ``condition`` is the resolved ``cat_test_conditions`` row for
    ``term.test_type`` and the declared server's flavor -- required for (and only for) an
    ``SQL``-shape term; this module has no database access, so the caller (the contract
    renderer, which holds a session) resolves it and passes it in. ``column_type`` is the
    profiled column's data type (``DataColumnChars.column_type``) -- needed only by the
    handful of ``SQL``-shape measures whose declared flavor casts a baseline value to it
    (bigquery/sap_hana); every other term ignores it, and it may be left ``None``. The
    result is plain JSON-safe data -- ``dict``, ``list``, ``str``, ``int``, ``float`` and
    ``bool`` only -- so it serializes with ``yaml.safe_dump`` and validates against the
    pinned ODCS schema.

    A test type with no row in ``RULE_MAPPINGS`` -- one of ``PENDING_DECISION`` -- projects
    as a ``text`` rule rather than raising or returning ``None``; see
    ``_project_pending_rule``.
    """
    mapping = RULE_MAPPINGS.get(term.test_type)
    if mapping is None:
        return _project_pending_rule(term, test_type)

    rule: dict[str, Any] = {"type": mapping.shape.value}
    system_properties: list[dict[str, Any]] = []

    if mapping.shape is RuleShape.LIBRARY:
        if mapping.metric is None:
            # Every LIBRARY row carries a metric -- test_rule_mapping_coverage.py's
            # test_a_library_row_carries_a_metric_and_a_scope_and_nothing_else_does enforces it.
            raise ValueError(f"{term.test_type!r} is mapped as a library rule but carries no metric.")
        rule["metric"] = mapping.metric.value
        if mapping.unit is not None:
            rule["unit"] = mapping.unit
        if mapping.argument is not None:
            rule["arguments"] = {mapping.argument: term.baseline_value}

        if term.test_type == "Missing_Pct":
            lower, upper, baseline_ratio, h = _missing_pct_band(term)
            rule.update(bound_clause(lower, upper))
            system_properties += _conversion_properties(baseline_ratio, h)
        elif term.test_type == "Unique_Pct":
            lower, upper, baseline_ratio, h = _unique_pct_band(term)
            rule.update(bound_clause(lower, upper))
            system_properties += _conversion_properties(baseline_ratio, h)
        elif term.test_type == "Row_Ct_Pct":
            lower, upper, baseline_count, percent = _row_ct_pct_band(term)
            rule.update(bound_clause(lower, upper))
            # The stored threshold is a percent of baseline, but the converted band is a row
            # count, not a percent -- the rendered unit follows the band, not the source.
            rule["unit"] = "rows"
            system_properties += _conversion_properties(
                baseline_count, percent, baseline_property="baselineCount", bound_property="thresholdPercent"
            )
        else:
            rule[mapping.operator.value] = _numeric(term.threshold_value)

    elif mapping.shape is RuleShape.SQL:
        if condition is None:
            raise ValueError(
                f"project_rule needs a resolved CatCondition to render {term.test_type!r}'s sql rule."
            )
        rule["query"] = _build_sql_query(term, condition, mapping.scope, server_type, column_type)
        operator, value = _resolved_bound(condition, term, column_type)
        rule[operator.value] = value
        system_properties.append(_server_type_marker(server_type))

    elif mapping.shape is RuleShape.CUSTOM:
        rule["engine"] = "testgen"
        rule["implementation"] = _custom_implementation(term)
        system_properties.append(_server_type_marker(server_type))

    rule["id"] = term.contract_term_id
    rule["dimension"] = mapping.dimension

    reserved_properties = _apply_reserved_subtree(rule, term.custom_metadata)
    user_properties = _user_custom_properties(term.custom_metadata)
    rule["customProperties"] = [
        *reserved_properties,
        *user_properties,
        *system_properties,
        _test_type_marker(term.test_type),
    ]
    return rule


# --- Resolution: an incoming ODCS rule back onto the TestGen test type that verifies it ----
#
# Not the projection table reversed. Projection must say something about every term;
# resolution may decline, and for most incoming shapes should. Three tiers, tried in order,
# each one final once it fires:
#
#   1. Our own marker (`customProperties` under `vendor: testgen`, `property: testType`) --
#      exact and lossless, since it is the round-trip of what `project_rule` always stamps.
#      The marker names *which* test type, not that the rest of the rule is coherent, so it
#      is checked against the catalogue and, when the named type has a `RULE_MAPPINGS` row,
#      against that row's own scope and operator -- the same well-formedness tier 2 already
#      enforces, so tier 1 cannot be looser than tier 2 about what a rule is allowed to claim.
#   2. Exact equivalence -- only where a TestGen type computes the same quantity and its
#      operator can express the same bound. Every row here is `unit: rows`: `nullValues` onto
#      `Required`, `rowCount` onto `Row_Ct`, and `invalidValues` (carrying exactly one of
#      `arguments.validValues` / `arguments.pattern`) onto `LOV_Match` / `Pattern_Match`.
#      `duplicateValues` has no row: `Unique`'s measure counts NULLs as duplicates (no
#      threshold conversion makes it match), and `Dupe_Rows` has no decided threshold shape --
#      both are `PENDING_DECISION`, not `RULE_MAPPINGS` rows, so there is nothing to resolve
#      onto regardless of which node the rule sits on.
#   3. Everything else declines (`None`): any `unit: percent` (no TestGen type computes a
#      plain proportion), an unrecognised unit (never defaulted to `rows`), `missingValues`,
#      an operator TestGen cannot state, a `text`/`sql`/`custom` rule, a metric on a scope its
#      target test type does not have, or an `invalidValues` rule with neither or both of its
#      two recognised arguments.

# Every test type name `resolve_rule` will accept from a marker -- the same union
# `test_rule_mapping_coverage.py` asserts equals the full test type catalogue. A marker
# naming anything else (a typo, or a type renamed since the rule was rendered -- test_type is
# a primary key with a foreign key from test_results, so a rename is a real hazard here) is
# rejected rather than trusted.
_KNOWN_TEST_TYPES: frozenset[str] = (
    frozenset(RULE_MAPPINGS) | frozenset(EXCLUDED_TEST_TYPES) | frozenset(PENDING_DECISION)
)

# The `_conversion_properties` entries a percent-shape term's rule carries -- the baseline
# ratio/count and the threshold bound the rendered band was computed from. Reading them back
# is what makes `Missing_Pct`/`Unique_Pct`/`Row_Ct_Pct` recoverable from `ResolvedTerm` alone;
# without it, a caller would have to re-parse `customProperties` itself -- a second reader of
# the same data that could disagree with this one.
_CONVERSION_PROPERTY_NAMES = frozenset({"baselineRatio", "baselineCount", "thresholdBound", "thresholdPercent"})


@dataclass(frozen=True)
class ResolvedTerm:
    """One incoming ODCS quality rule, resolved onto the TestGen test type that verifies it.

    ``thresholds`` is the rule's own acceptance-operator key(s) and value(s) -- ``{"mustBeLessOrEqualTo": 0}``,
    for instance -- read directly off the rule, or re-expressed onto the target's own operator where the
    incoming bound is strict but the target's measure is integral (see ``_resolve_row_count``). For
    ``Missing_Pct``/``Unique_Pct``/``Row_Ct_Pct`` this is the *rendered* band, not the term's own threshold --
    see ``conversion``. ``arguments`` is the rule's ``arguments`` mapping when the target test type has one
    (``LOV_Match``, ``Pattern_Match``), otherwise empty. ``conversion`` is the rule's own
    ``_conversion_properties`` entries (``baselineRatio``/``baselineCount`` and
    ``thresholdBound``/``thresholdPercent``), read back by name -- non-empty only for a marked
    ``Missing_Pct``/``Unique_Pct``/``Row_Ct_Pct`` rule, and it is what lets a caller recover that term's own
    ``threshold_value`` without re-parsing the rule's ``customProperties`` itself.
    """
    test_type: str
    thresholds: dict[str, Any]
    arguments: dict[str, Any]
    conversion: dict[str, Any]


def _marker_test_type(rule: dict[str, Any]) -> str | None:
    """The ``testType`` value from the rule's own ``vendor: testgen`` marker, if present."""
    for entry in rule.get("customProperties") or []:
        if isinstance(entry, dict) and entry.get("vendor") == "testgen" and entry.get("property") == "testType":
            value = entry.get("value")
            if isinstance(value, str) and value:
                return value
    return None


def _thresholds_from_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {op.value: rule[op.value] for op in Operator if op.value in rule}


def _arguments_from_rule(rule: dict[str, Any]) -> dict[str, Any]:
    arguments = rule.get("arguments")
    return dict(arguments) if isinstance(arguments, dict) else {}


def _conversion_properties_from_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        entry["property"]: entry["value"]
        for entry in rule.get("customProperties") or []
        if isinstance(entry, dict)
        and entry.get("vendor") == "testgen"
        and entry.get("property") in _CONVERSION_PROPERTY_NAMES
    }


def _operators_present(rule: dict[str, Any]) -> list[Operator]:
    return [op for op in Operator if op.value in rule]


def _sole_operator(rule: dict[str, Any]) -> tuple[Operator, Any] | tuple[None, None]:
    """The rule's one acceptance-operator key and its value, or ``(None, None)`` when the
    rule carries zero or more than one -- the pinned schema's own ``oneOf`` allows only one,
    so anything else is not a rule this resolver can read a bound from."""
    present = _operators_present(rule)
    return (present[0], rule[present[0].value]) if len(present) == 1 else (None, None)


def _is_integral(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()


def _resolve_null_values(operator: Operator, value: Any, scope: RuleScope) -> tuple[str, dict, dict] | None:
    mapping = _LIBRARY_ROWS["Required"]
    if scope is not mapping.scope or operator is not mapping.operator:
        return None
    return "Required", {operator.value: value}, {}


def _resolve_row_count(operator: Operator, value: Any, scope: RuleScope) -> tuple[str, dict, dict] | None:
    """``rowCount``'s one target, ``Row_Ct``, plus the one strictness re-expression this
    resolver allows: ``Row_Ct`` renders ``mustBeGreaterOrEqualTo``, so an incoming strict
    ``mustBeGreaterThan`` is not its exact shape. Re-expressing ``> N`` as ``>= N + 1`` is
    sound because a row count is always integral -- guarded by ``_is_integral`` so a
    non-whole value is left to decline rather than silently rounded.
    """
    mapping = _LIBRARY_ROWS["Row_Ct"]
    if scope is not mapping.scope:
        return None
    if operator is mapping.operator:
        return "Row_Ct", {operator.value: value}, {}
    if operator is Operator.MUST_BE_GREATER_THAN and _is_integral(value):
        reexpressed = int(value) + 1
        return "Row_Ct", {Operator.MUST_BE_GREATER_OR_EQUAL_TO.value: reexpressed}, {}
    return None



# The two recognised invalidValues arguments -- mutually exclusive alternates for the same
# metric, one per target test type (`LOV_Match`'s `validValues`, `Pattern_Match`'s `pattern`).
_INVALID_VALUES_ARGUMENT_KEYS = frozenset({"validValues", "pattern"})


def _unambiguous_argument(rule: dict[str, Any]) -> dict[str, Any] | None:
    """The rule's ``arguments`` mapping, once checked for exactly one recognised
    ``invalidValues`` argument and nothing else -- or ``None`` to decline a rule carrying
    neither ``validValues`` nor ``pattern``, both at once, or any other key alongside one of
    them. Shared by tier 2 (``_resolve_invalid_values``) and the marker path
    (``_resolve_marker``) so the two cannot drift on what counts as an ambiguous argument
    shape.
    """
    arguments = rule.get("arguments")
    if not isinstance(arguments, dict):
        return None
    has_valid_values = "validValues" in arguments
    has_pattern = "pattern" in arguments
    if has_valid_values == has_pattern or set(arguments) - _INVALID_VALUES_ARGUMENT_KEYS:
        return None
    return arguments


def _resolve_invalid_values(
    rule: dict[str, Any], operator: Operator, value: Any, scope: RuleScope
) -> tuple[str, dict, dict] | None:
    """``invalidValues``'s two targets, disambiguated by which argument the rule carries."""
    arguments = _unambiguous_argument(rule)
    if arguments is None:
        return None
    target = "LOV_Match" if "validValues" in arguments else "Pattern_Match"
    mapping = _LIBRARY_ROWS[target]
    if scope is not mapping.scope or operator is not mapping.operator:
        return None
    return target, {operator.value: value}, dict(arguments)


def _resolve_marker(rule: dict[str, Any], marker: str, scope: RuleScope) -> str | None:
    """The marker's test type, once checked for coherence -- or ``None`` to decline a marker
    that names an unknown/renamed type, sits on a node its type does not declare, claims more
    than one operator at once, or disagrees with its own ``RULE_MAPPINGS`` row's operator or
    (for ``LOV_Match``/``Pattern_Match``) argument shape. Beyond scope, a type with no
    ``RULE_MAPPINGS`` row (``PENDING_DECISION``) declares no shape, operator or argument to
    check it against.

    The scope check covers every type that declares one, routed and ``PENDING_DECISION``
    alike. A marker naming a type that declares none -- one of ``EXCLUDED_TEST_TYPES``, which
    is in the catalogue and so passes the membership check above -- is declined here, not
    raised on: an incoming document is untrusted input, and this path answers a rule it cannot
    place by declining it rather than by failing the import. ``declared_scope`` raises on the
    same input, which is what the rendering path wants and why this does not call it.

    Tier 1 (the marker) is the only tier that can identify a type tier 2 (the
    exact-equivalence table) cannot -- that is its entire reason to exist -- but it must never
    be *looser* than tier 2 about whether the rest of the rule is well-formed. Every coherence
    check tier 2 applies to a rule it can reach, this applies too, on the marked type's own
    declared shape, so a marker cannot carry a rule tier 2 would have refused.
    """
    if marker not in _KNOWN_TEST_TYPES:
        return None
    marker_scope = _DECLARED_SCOPES.get(marker)
    if marker_scope is None or scope is not marker_scope:
        return None
    present_operators = _operators_present(rule)
    if len(present_operators) > 1:
        return None
    marker_operator = present_operators[0] if present_operators else None

    mapping = RULE_MAPPINGS.get(marker)
    if mapping is not None:
        if mapping.shape is RuleShape.CUSTOM:
            if marker_operator is not None:
                return None
        elif marker_operator is None or marker_operator is not mapping.operator:
            return None
        if mapping.argument is not None:
            arguments = _unambiguous_argument(rule)
            if arguments is None or mapping.argument not in arguments:
                return None
    return marker


def resolve_rule(rule: dict[str, Any], scope: RuleScope) -> ResolvedTerm | None:
    """Resolve one incoming ODCS quality-rule object onto the TestGen test type that verifies
    exactly the claim it makes, or ``None`` when no TestGen type does.

    ``scope`` is the ODCS node the rule sits on (``column`` or ``table``) -- required, since it
    is not encoded in the rule object itself (the pinned schema has no scope-bearing field on
    a quality rule): a caller walking a document tree always knows the node it is standing on,
    and every routed metric's target has a fixed scope ODCS would otherwise let it sit on the
    wrong node of and still validate.

    A rule carrying the ``testType`` marker under the ``testgen`` vendor (see
    ``_test_type_marker``) resolves to that test type once the marker itself checks out (see
    ``_resolve_marker``) -- this is the lossless round-trip of a rule TestGen itself projected.
    Every other rule is checked against a small, fixed table of exact equivalences: nothing is
    guessed and nothing is defaulted, so most incoming shapes -- any ``percent`` unit, an
    unrecognised unit, ``missingValues``, an operator TestGen cannot state, a ``text``/``sql``/
    ``custom`` rule -- decline rather than resolve.
    """
    conversion = _conversion_properties_from_rule(rule)

    marker = _marker_test_type(rule)
    if marker is not None:
        resolved_marker = _resolve_marker(rule, marker, scope)
        if resolved_marker is None:
            return None
        return ResolvedTerm(
            test_type=resolved_marker,
            thresholds=_thresholds_from_rule(rule),
            arguments=_arguments_from_rule(rule),
            conversion=conversion,
        )

    if rule.get("unit") != "rows":
        return None

    operator, value = _sole_operator(rule)
    if operator is None:
        return None

    metric = rule.get("metric")
    result = None
    if metric == LibraryMetric.NULL_VALUES.value:
        result = _resolve_null_values(operator, value, scope)
    elif metric == LibraryMetric.ROW_COUNT.value:
        result = _resolve_row_count(operator, value, scope)
    elif metric == LibraryMetric.INVALID_VALUES.value:
        result = _resolve_invalid_values(rule, operator, value, scope)
    if result is None:
        return None

    test_type, thresholds, arguments = result
    return ResolvedTerm(test_type=test_type, thresholds=thresholds, arguments=arguments, conversion=conversion)
