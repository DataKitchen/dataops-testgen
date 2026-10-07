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

from testgen.common.enums import OdcsDimension, QualityDimension, TestScope
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, SqlFlavorCode
from testgen.common.models.test_definition import (
    ODCS_AUTHORITATIVE_DEFINITION_FIELDS,
    ODCS_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS,
    ODCS_CUSTOM_PROPERTY_FIELDS,
    ODCS_CUSTOM_PROPERTY_REQUIRED_FIELDS,
    ODCS_RULE_METADATA_KEY,
    ODCS_STABLE_ID_PATTERN,
)
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

    Derived from the catalogue by ``rule_scope``. Distinct from ``TestScope``: TestGen's
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
class RuleArgument:
    """One library rule's ``arguments`` entry: the ODCS key, and the term field feeding it.

    The field is named rather than assumed because the two are not the same across rows --
    ``LOV_Match`` and ``Pattern_Match`` carry their predicate in ``baseline_value``, while
    ``Dupe_Rows`` lists its grouping from ``groupby_names``.
    """
    name: str
    term_field: str


@dataclass(frozen=True)
class RuleMapping:
    """One test type's route to an ODCS quality rule.

    ``metric``, ``unit`` and ``argument`` (a ``RuleArgument``) are set only when ``shape`` is ``LIBRARY``; every
    other shape carries ``None`` for all three. ``operator`` is the acceptance operator the
    rendered rule carries: for most rows this is the inversion of the type's stored
    ``test_operator`` (see ``ACCEPTANCE_OPERATOR``), but ``Missing_Pct`` and
    ``Row_Ct_Pct`` carry ``mustBeBetween`` outright -- a converted band around a fixed
    baseline, not an inversion of the stored operator. ``dimension`` is the already-translated
    ODCS dimension (``odcs_dimension`` output), except ``LOV_All``, which carries ``coverage``
    explicitly rather than the ``conformity`` its stored ``Validity`` dimension would translate
    to. ``scope`` is the node the rule renders on; when ``scope_follows_term`` is set the node
    depends on the term, not the type (see ``rule_scope``), and ``scope`` is only the default.
    """
    test_type: str
    shape: RuleShape
    scope: RuleScope
    operator: Operator
    dimension: str
    metric: LibraryMetric | None = None
    unit: str | None = None
    argument: RuleArgument | None = None
    scope_follows_term: bool = False


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


# The seven test types with a direct ODCS library metric. `Missing_Pct` and `Row_Ct_Pct` carry
# `mustBeBetween`. `Missing_Pct`'s threshold is a Cohen's h drift bound, and Cohen's h is
# monotonic in the underlying ratio, so one h-threshold around a fixed baseline maps onto a
# closed interval on that ratio; `Row_Ct_Pct`'s is a plain percent deviation from a baseline
# count. The bounds are computed elsewhere, this table only records that the rendered operator
# is the between one.
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
    "LOV_Match": RuleMapping(
        test_type="LOV_Match",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.VALIDITY),
        metric=LibraryMetric.INVALID_VALUES,
        unit="rows",
        argument=RuleArgument(name="validValues", term_field="baseline_value"),
    ),
    "Pattern_Match": RuleMapping(
        test_type="Pattern_Match",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.VALIDITY),
        metric=LibraryMetric.INVALID_VALUES,
        unit="rows",
        argument=RuleArgument(name="pattern", term_field="baseline_value"),
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
        unit="rows",
    ),
    "Dupe_Rows": RuleMapping(
        test_type="Dupe_Rows",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.TABLE,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.UNIQUENESS),
        metric=LibraryMetric.DUPLICATE_VALUES,
        unit="rows",
        argument=RuleArgument(name="properties", term_field="groupby_names"),
        scope_follows_term=True,
    ),
}

# Routed `sql` rules: the query is projected from `cat_test_conditions.measure`, and the
# operator is the inversion (via `ACCEPTANCE_OPERATOR`) of the type's stored `test_operator`.
# Empty in this tree: `SQL_Metric` is the only type this shape is decided for, and it is not
# in the catalogue yet. `_build_sql_query` and the SQL branch of `project_rule` are kept
# against its arrival.
_SQL_ROWS: dict[str, RuleMapping] = {}

# Every routed test type -- the union `render` and `resolve_rule` both read. Disjoint from
# `EXCLUDED_TEST_TYPES`; a type in neither renders `custom`.
RULE_MAPPINGS: dict[str, RuleMapping] = {**_LIBRARY_ROWS, **_SQL_ROWS}

# Run-history test types: no term is ever authored against them, so no quality rule applies.
# The value is the reason a reviewer would otherwise have to re-derive.
EXCLUDED_TEST_TYPES: dict[str, str] = {
    "Volume_Trend": "run-history type -- monitors row-count drift over time, not a contract-testable state",
    "Freshness_Trend": "run-history type -- monitors update-interval drift over time, not a contract-testable state",
    "Metric_Trend": "run-history type -- monitors an aggregate metric's drift over time, not a contract-testable state",
    "Schema_Drift": "run-history type -- monitors schema changes over time, not a contract-testable state",
}


def rule_shape(test_type: str) -> RuleShape | None:
    """How ``test_type``'s terms render: ``None`` when no rule applies at all.

    Three outcomes, in order. A run-history type (``EXCLUDED_TEST_TYPES``) renders nothing --
    no term is ever authored against one. A type with a ``RULE_MAPPINGS`` row renders that
    row's shape. Everything else renders ``custom``: the fallback carries the test type's own
    parameters, so it needs no per-type entry and a type added to the catalogue later exports
    without a mapping change.

    Never raises. A name outside the catalogue falls through to ``custom`` like any other
    unrouted type -- placement is where an unplaceable term is refused, not here.
    """
    if test_type in EXCLUDED_TEST_TYPES:
        return None
    mapping = RULE_MAPPINGS.get(test_type)
    return mapping.shape if mapping is not None else RuleShape.CUSTOM


_LOV_LITERAL_VALUE = re.compile(r"'((?:[^']|'')*)'")


def lov_values(raw: str) -> list[str]:
    """The individual values inside a stored LOV literal, e.g. ``"('Y','N')"`` -> ``["Y", "N"]``."""
    return [match.replace("''", "'") for match in _LOV_LITERAL_VALUE.findall(raw)]


def _unquote_identifier(name: str) -> str:
    if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        return name[1:-1].replace('""', '"')
    return name


def _groupby_columns(term: "TestDefinition") -> list[str]:
    """``term``'s ``groupby_names`` as individual unquoted column names, empty when it holds none."""
    return [_unquote_identifier(name.strip()) for name in (term.groupby_names or "").split(",") if name.strip()]


def rule_scope(term: "TestDefinition", test_type: "TestType") -> RuleScope:
    """The ODCS node ``term``'s rule attaches to.

    Derived from the catalogue rather than declared per type: a rule hangs on a property
    exactly when the term's ``column_name`` denotes one column (``test_scope: column``) or an
    aggregate over one (``column_name_prompt: Aggregate Expression``). Every other stored
    scope puts something in ``column_name`` that is not a column -- a free-text label, a
    comma-separated list of them, or nothing -- so its rule hangs on the table.

    Types whose mapping sets ``scope_follows_term`` (``Dupe_Rows``) depend on the term instead: a
    grouping of one column attaches to that column, a grouping of several to the table.

    Raises ``ValueError`` for an excluded type, whose terms should not exist.
    """
    if test_type.test_type in EXCLUDED_TEST_TYPES:
        raise ValueError(f"{test_type.test_type!r} renders no quality rule, so it has no node to attach one to.")

    mapping = RULE_MAPPINGS.get(test_type.test_type)
    if mapping is not None and mapping.scope_follows_term:
        return RuleScope.COLUMN if len(_groupby_columns(term)) == 1 else RuleScope.TABLE

    names_one_column = (
        test_type.test_scope == TestScope.COLUMN
        or (test_type.column_name_prompt or "").strip() == "Aggregate Expression"
    )
    return RuleScope.COLUMN if names_one_column else RuleScope.TABLE


def _numeric(raw: str) -> int | float:
    """Parse a stored threshold-shaped string into a plain, JSON-safe number.

    Renders a whole number as ``int`` rather than ``2.0`` -- ODCS operators accept either,
    but the term's own value was typed by a user as a count, not a float.
    """
    value = float(raw)
    return int(value) if value.is_integer() else value


def _required_threshold(term: "TestDefinition") -> str:
    """The term's stored threshold text, or a ``ValueError`` naming the term when it has none.

    Every library-routed test type declares ``threshold_value`` optional, so a term saved with
    it cleared reaches rendering with no bound to compare against.
    """
    raw = term.threshold_value
    if raw is None or not str(raw).strip():
        raise ValueError(
            f"{term.test_type!r} term {term.contract_term_id!r} has no threshold value, "
            "so the bound its rule compares against is undefined."
        )
    return str(raw)


def _cohens_h_band(baseline_ratio: float, h: float) -> tuple[float, float]:
    """The closed ratio interval a Cohen's h bound ``h`` maps onto around ``baseline_ratio``.

    Cohen's h, ``phi(p) = 2*asin(sqrt(p))``, is monotonic in the ratio, so a single
    threshold around a fixed baseline corresponds to exactly one interval on the ratio
    itself: ``[inv(phi(baseline) - h), inv(phi(baseline) + h)]`` where
    ``inv(f) = sin(f/2)**2``.

    ``phi`` maps onto ``[0, pi]``, and ``inv`` is only its inverse on that interval -- past
    ``pi`` it turns back downward, below ``0`` it mirrors -- so the shifted centre is clamped
    before inverting. A bound wide enough to reach either end saturates there: ratio 0 or 1,
    which is what a drift threshold that admits everything should render as.
    """
    center = 2 * math.asin(math.sqrt(baseline_ratio))
    lower = math.sin(max(0.0, center - h) / 2) ** 2
    upper = math.sin(min(math.pi, center + h) / 2) ** 2
    return lower, upper


def _complement_percent_band(lower_ratio: float, upper_ratio: float) -> tuple[float, float]:
    """The percent band on a ratio's complement -- e.g. null percent from populated ratio."""
    return 100 * (1 - upper_ratio), 100 * (1 - lower_ratio)


def _missing_pct_band(term: "TestDefinition") -> tuple[float, float, float, float]:
    """Null-percent band, baseline populated ratio and threshold bound for a ``Missing_Pct`` term."""
    baseline_count = float(term.baseline_ct)
    if baseline_count == 0:
        raise ValueError(
            f"{term.test_type!r} term {term.contract_term_id!r} has a baseline row count of 0, "
            "so its baseline null ratio is undefined."
        )
    baseline_ratio = float(term.baseline_value_ct) / baseline_count
    h = float(_required_threshold(term))
    lower_ratio, upper_ratio = _cohens_h_band(baseline_ratio, h)
    lower, upper = _complement_percent_band(lower_ratio, upper_ratio)
    return lower, upper, baseline_ratio, h


def _row_ct_pct_band(term: "TestDefinition") -> tuple[float, float, float, float]:
    """Row-count band, baseline count and threshold percent for a ``Row_Ct_Pct`` term.

    ``|100*(n-b)/b| <= T`` rearranges to ``n in [b*(1-T/100), b*(1+T/100)]``.
    """
    baseline_count = float(term.baseline_ct)
    if baseline_count == 0:
        raise ValueError(
            f"{term.test_type!r} term {term.contract_term_id!r} has a baseline row count of 0, "
            "so its percent change from baseline is undefined."
        )
    percent = float(_required_threshold(term))
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
        # Normalised, not validated: a member would reach `yaml.safe_dump` as a `StrEnum` and
        # raise, where a value the enum does not hold is reported by schema validation like
        # every other field of this subtree.
        rule["dimension"] = dimension.value if isinstance(dimension, OdcsDimension) else dimension

    tags = reserved.get("tags")
    if tags is not None:
        rule["tags"] = tags

    authoritative_definitions = reserved.get("authoritativeDefinitions")
    if authoritative_definitions is not None:
        rule["authoritativeDefinitions"] = _reconstruct_sealed_entries(
            authoritative_definitions, ODCS_AUTHORITATIVE_DEFINITION_FIELDS, ODCS_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS
        )

    custom_properties = reserved.get("customProperties")
    return _reconstruct_sealed_entries(custom_properties, ODCS_CUSTOM_PROPERTY_FIELDS, ODCS_CUSTOM_PROPERTY_REQUIRED_FIELDS)


def _user_custom_properties(custom_metadata: dict | None) -> list[dict[str, Any]]:
    """The caller's own top-level ``custom_metadata`` keys, promoted onto the rule as
    ``customProperties``. Excludes the reserved ``odcs`` key, which
    ``_apply_reserved_subtree`` handles separately."""
    if not custom_metadata:
        return []
    return [
        {"property": key, "value": value} for key, value in custom_metadata.items() if key != ODCS_RULE_METADATA_KEY
    ]


def _declared_parameters(test_type: "TestType") -> list[str]:
    """The parameter names ``test_type`` declares, in catalogue order."""
    return [name.strip() for name in (test_type.default_parm_columns or "").split(",") if name.strip()]


def _custom_implementation(term: "TestDefinition", test_type: "TestType") -> dict[str, Any]:
    """``term``'s values for the parameters its test type declares.

    Keyed by the catalogue's own ``default_parm_columns`` rather than a fixed list, so a test
    type added later exports its parameters with no change here. Carries no schema, table or
    column: the subject is the node the rule nests on. Values the term leaves unset are
    omitted rather than rendered null.
    """
    return {
        name: getattr(term, name)
        for name in _declared_parameters(test_type)
        if name not in ("schema_name", "table_name", "column_name") and getattr(term, name, None) not in (None, "")
    }


def _normalized(text: str | None) -> str:
    """``text`` with runs of whitespace collapsed to single spaces, empty when unset."""
    return " ".join(text.split()) if text else ""


def _custom_description(term: "TestDefinition", test_type: "TestType") -> str:
    """A plain-words statement of what a ``custom`` rule checks.

    Built from the catalogue's own prose and the term's threshold. Other ODCS engines do not
    run a ``custom`` rule, so for a counterparty without TestGen this is the only usable part
    of it. Names no parameter: a reader is told what the check does, not which field carries
    it. A segment the catalogue leaves unset is omitted rather than rendered as ``None``.
    """
    segments: list[str] = []
    if statement := _normalized(test_type.test_description):
        segments.append(statement)
    if failure := _normalized(test_type.except_message):
        segments.append(f"Fails: {failure}")
    if term.threshold_value not in (None, ""):
        bound = f"Threshold: {term.threshold_value}"
        if label := _normalized(test_type.threshold_description):
            bound = f"{bound} ({label})"
        segments.append(f"{bound}.")
    return " ".join(segments)


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
    ``custom`` rule reads -- its declared parameters, prose, display name and TestGen
    dimension. ``server_type`` names the dialect a
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
    """
    shape = rule_shape(term.test_type)
    if shape is None:
        raise ValueError(
            f"{term.test_type!r} renders no quality rule, so {term.contract_term_id!r} should not exist."
        )
    mapping = RULE_MAPPINGS.get(term.test_type)

    rule: dict[str, Any] = {"type": shape.value}
    system_properties: list[dict[str, Any]] = []

    if mapping is None or shape is RuleShape.CUSTOM:
        rule["engine"] = "testgen"
        rule["name"] = (
            term.test_description or test_type.test_name_long
            or test_type.test_name_short or term.test_type
        )
        rule["description"] = _custom_description(term, test_type)
        rule["implementation"] = _custom_implementation(term, test_type)
        system_properties.append(_server_type_marker(server_type))

    elif shape is RuleShape.LIBRARY:
        if mapping.metric is None:
            # Every LIBRARY row carries a metric -- test_rule_mapping_coverage.py's
            # test_a_library_row_carries_a_metric_and_a_scope_and_nothing_else_does enforces it.
            raise ValueError(f"{term.test_type!r} is mapped as a library rule but carries no metric.")
        rule["metric"] = mapping.metric.value
        if mapping.unit is not None:
            rule["unit"] = mapping.unit
        if mapping.argument is not None:
            value: Any
            if mapping.argument.term_field == "groupby_names":
                columns = _groupby_columns(term)
                value = columns if len(columns) > 1 else None
            else:
                value = getattr(term, mapping.argument.term_field)
                if value and mapping.argument.name == "validValues":
                    value = lov_values(value)
            if mapping.argument.term_field != "groupby_names" and not value:
                raise ValueError(
                    f"{term.test_type!r} term {term.contract_term_id!r} has no parseable "
                    f"{mapping.argument.term_field!r} to render its {mapping.argument.name!r} argument."
                )
            if value:
                rule["arguments"] = {mapping.argument.name: value}

        if term.test_type == "Missing_Pct":
            lower, upper, baseline_ratio, h = _missing_pct_band(term)
            rule.update(bound_clause(lower, upper))
            system_properties += _conversion_properties(baseline_ratio, h)
        elif term.test_type == "Row_Ct_Pct":
            lower, upper, baseline_count, percent = _row_ct_pct_band(term)
            rule.update(bound_clause(lower, upper))
            system_properties += _conversion_properties(
                baseline_count, percent, baseline_property="baselineCount", bound_property="thresholdPercent"
            )
        elif term.test_type == "Dupe_Rows":
            rule[mapping.operator.value] = term.skip_errors or 0
        else:
            rule[mapping.operator.value] = _numeric(_required_threshold(term))

    elif shape is RuleShape.SQL:
        if condition is None:
            raise ValueError(
                f"project_rule needs a resolved CatCondition to render {term.test_type!r}'s sql rule."
            )
        rule["query"] = _build_sql_query(term, condition, mapping.scope, server_type, column_type)
        operator, bound = _resolved_bound(condition, term, column_type)
        rule[operator.value] = bound
        system_properties.append(_server_type_marker(server_type))

    if not term.contract_term_id:
        raise ValueError(
            f"{term.test_type!r} term on {term.schema_name}.{term.table_name}"
            f"{'.' + term.column_name if term.column_name else ''} has no contract identity, "
            "so its rule has no id to carry."
        )
    rule["id"] = term.contract_term_id
    rule["dimension"] = (
        mapping.dimension if mapping is not None
        else odcs_dimension(QualityDimension(test_type.dq_dimension))
    )

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
#      `duplicateValues` still has no tier-2 row: `Unique`'s measure counts NULLs as
#      duplicates (no threshold conversion makes it match), so there is nothing to resolve
#      onto regardless of which node the rule sits on. `Dupe_Rows` is a library row, but it is
#      reachable through its marker (tier 1) alone.
#   3. Everything else declines (`None`): any `unit: percent` (no TestGen type computes a
#      plain proportion), an unrecognised unit (never defaulted to `rows`), `missingValues`,
#      an operator TestGen cannot state, a `text`/`sql`/`custom` rule, a metric on a scope its
#      target test type does not have, or an `invalidValues` rule with neither or both of its
#      two recognised arguments.

# The `_conversion_properties` entries a percent-shape term's rule carries -- the baseline
# ratio/count and the threshold bound the rendered band was computed from. Reading them back
# is what makes `Missing_Pct`/`Row_Ct_Pct` recoverable from `ResolvedTerm` alone;
# without it, a caller would have to re-parse `customProperties` itself -- a second reader of
# the same data that could disagree with this one.
_CONVERSION_PROPERTY_NAMES = frozenset({"baselineRatio", "baselineCount", "thresholdBound", "thresholdPercent"})


@dataclass(frozen=True)
class ResolvedTerm:
    """One incoming ODCS quality rule, resolved onto the TestGen test type that verifies it.

    ``thresholds`` is the rule's own acceptance-operator key(s) and value(s) -- ``{"mustBeLessOrEqualTo": 0}``,
    for instance -- read directly off the rule, or re-expressed onto the target's own operator where the
    incoming bound is strict but the target's measure is integral (see ``_resolve_row_count``). For
    ``Missing_Pct``/``Row_Ct_Pct`` this is the *rendered* band, not the term's own threshold --
    see ``conversion``. ``arguments`` is the rule's ``arguments`` mapping when the target test type has one
    (``LOV_Match``, ``Pattern_Match``), otherwise empty. ``conversion`` is the rule's own
    ``_conversion_properties`` entries (``baselineRatio``/``baselineCount`` and
    ``thresholdBound``/``thresholdPercent``), read back by name -- non-empty only for a marked
    ``Missing_Pct``/``Row_Ct_Pct`` rule, and it is what lets a caller recover that term's own
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


def _operator_matches(marker_operator: Operator, expected: Operator) -> bool:
    """Whether a rule's operator is the one its mapping renders.

    ``mustBe`` also satisfies a ``mustBeBetween`` mapping: ``bound_clause`` collapses a band
    whose bounds coincide, since ``mustBeBetween`` requires two unique items. Declining that
    would reject a rule TestGen itself projected, on exactly the terms that allow no drift.
    """
    if marker_operator is expected:
        return True
    return expected is Operator.MUST_BE_BETWEEN and marker_operator is Operator.MUST_BE


def _resolve_marker(
    rule: dict[str, Any], marker: str, scope: RuleScope, known_test_types: frozenset[str]
) -> str | None:
    """The marker's test type, once checked for coherence -- or ``None`` to decline a marker
    that names a type absent from ``known_test_types`` (a typo, or a type renamed since the rule
    was rendered), names an excluded type, claims more than one operator at once, or disagrees
    with its own routed shape.

    A custom-routed type must carry no operator: its bound is one of its parameters, never an
    operator on the rule. A library type must agree with its ``RULE_MAPPINGS`` row's scope,
    operator and (for ``LOV_Match``/``Pattern_Match``) argument shape; an optional argument such as
    ``Dupe_Rows``'s column list is not required. An incoming document is
    untrusted input, so a rule this cannot place is declined rather than raised on.

    Tier 1 (the marker) is the only tier that can identify a type tier 2 (the
    exact-equivalence table) cannot -- that is its entire reason to exist -- but it must never
    be *looser* than tier 2 about whether the rest of the rule is well-formed.
    """
    if marker not in known_test_types:
        return None
    shape = rule_shape(marker)
    if shape is None:
        return None

    present_operators = _operators_present(rule)
    if len(present_operators) > 1:
        return None
    marker_operator = present_operators[0] if present_operators else None

    if shape is RuleShape.CUSTOM:
        if marker_operator is not None:
            return None
        return marker

    mapping = RULE_MAPPINGS[marker]
    if scope is not mapping.scope and not mapping.scope_follows_term:
        return None
    if marker_operator is None or not _operator_matches(marker_operator, mapping.operator):
        return None
    if mapping.argument is not None and mapping.argument.name in _INVALID_VALUES_ARGUMENT_KEYS:
        arguments = _unambiguous_argument(rule)
        if arguments is None or mapping.argument.name not in arguments:
            return None
    return marker


def resolve_rule(
    rule: dict[str, Any], scope: RuleScope, known_test_types: frozenset[str]
) -> ResolvedTerm | None:
    """Resolve one incoming ODCS quality-rule object onto the TestGen test type that verifies
    exactly the claim it makes, or ``None`` when no TestGen type does.

    ``scope`` is the ODCS node the rule sits on (``column`` or ``table``) -- required, since it
    is not encoded in the rule object itself (the pinned schema has no scope-bearing field on
    a quality rule): a caller walking a document tree always knows the node it is standing on,
    and every routed metric's target has a fixed scope ODCS would otherwise let it sit on the
    wrong node of and still validate. ``known_test_types`` is the test type catalogue's names, supplied
    by the caller so this module stays database-free; a marker naming anything else is declined.

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
        resolved_marker = _resolve_marker(rule, marker, scope, known_test_types)
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
