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

import dataclasses
import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from testgen.common import query_variables
from testgen.common.clean_sql import format_value_list, parse_value_list, strip_trailing_semicolons
from testgen.common.database.database_service import get_flavor_service
from testgen.common.enums import VALUE_LIST_TEST_TYPES, OdcsDimension, QualityDimension, TestScope
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, SqlFlavorCode
from testgen.common.models.test_definition import (
    NON_PUBLIC_TEST_TYPES,
    ODCS_AUTHORITATIVE_DEFINITION_FIELDS,
    ODCS_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS,
    ODCS_CUSTOM_PROPERTY_FIELDS,
    ODCS_CUSTOM_PROPERTY_REQUIRED_FIELDS,
    ODCS_RULE_METADATA_KEY,
    ODCS_STABLE_ID_PATTERN,
)
from testgen.common.odcs.servers import FLAVOR_TO_SERVER_TYPE
from testgen.common.read_file import replace_templated_functions

if TYPE_CHECKING:
    from testgen.common.models.test_definition import TestDefinition, TestType


LOG = logging.getLogger("testgen")


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
    """One library rule's ``arguments`` entry: the ODCS key, and where its value comes from.

    Exactly one of ``term_field`` and ``fixed`` is set. ``term_field`` names the term field
    feeding the argument, which differs across rows -- ``LOV_Match`` and ``Pattern_Match``
    carry their predicate in ``baseline_value``, while ``Dupe_Rows`` lists its grouping from
    ``groupby_names``. ``fixed`` is the argument itself, for a type whose predicate is part of
    its definition rather than a parameter (``Email_Format``'s pattern, ``US_State``'s list);
    a list is stored as a tuple so the row stays immutable.
    """
    name: str
    term_field: str | None = None
    fixed: str | tuple[str, ...] | None = None


@dataclass(frozen=True)
class RuleMapping:
    """One test type's route to an ODCS quality rule.

    ``metric``, ``unit`` and ``argument`` (a ``RuleArgument``) are set only when ``shape`` is ``LIBRARY``; every
    other shape carries ``None`` for all three. ``operator`` is the acceptance operator the
    rendered rule carries: for most rows this is the inversion of the type's stored
    ``test_operator`` (see ``ACCEPTANCE_OPERATOR``), but ``Missing_Pct`` and
    ``Row_Ct_Pct`` carry ``mustBeBetween`` outright -- a converted band around a fixed
    baseline, not an inversion of the stored operator. ``dimension`` is the already-translated
    ODCS dimension (``odcs_dimension`` output). ``scope`` is the node the rule renders on; when ``scope_follows_term`` is set the node
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
    resolves the row for a term's ``test_type`` and the contract connection's flavor, and passes
    it to ``project_rule`` for an ``SQL``-shape term. ``measure`` and ``test_condition`` are
    the raw, unsubstituted template text -- TestGen's own ``{PLACEHOLDER}`` tokens, not yet
    rewritten into ODCS syntax or literal values; ``test_operator`` is the raw stored
    comparison (``>``, ``<``, ...), inverted into an acceptance operator the same way every
    other row's is (``ACCEPTANCE_OPERATOR``).
    """
    measure: str
    test_operator: str
    test_condition: str


# Fixed predicates of the test types whose library argument is part of their definition. Each
# is the PostgreSQL measure's own check, restated as a pattern or list the engine evaluates the
# same way: a NULL is never counted, and `''` is counted unless the type treats it as valid.
EMAIL_PATTERN = r"^[A-Za-z0-9._'%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
US_ZIP_PATTERN = r"^([0-9]{5}|[0-9]{9}|[0-9]{5}-[0-9]{4})$"
US_ZIP3_PATTERN = r"^[0-9]{3}$"
US_CA_ZIP_PATTERN = r"^([0-9]{5}|[0-9]{9}|[0-9]{5}-[0-9]{4}|[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9])$"
# `US_State` reads `NULLIF(column, '')`, so the empty string is valid there.
US_STATE_VALID_VALUES: tuple[str, ...] = (
    "AL", "AK", "AS", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FM", "FL", "GA", "GU", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MH", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
    "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "MP", "OH", "OK", "OR", "PW", "PA", "PR", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VI", "VA", "WA", "WV", "WI", "WY", "AE", "AP", "AA", "",
)


# Flavor families whose measure for a fixed-predicate type checks something other than its fixed
# predicate -- a LIKE approximation, or a different regex. There the type renders `custom`.
_INEXACT_FAMILIES: dict[str, frozenset[str]] = {
    "Email_Format": frozenset({"bigquery", "mssql"}),
}


def _invalid_values_row(test_type: str, argument: RuleArgument) -> RuleMapping:
    return RuleMapping(
        test_type=test_type,
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.VALIDITY),
        metric=LibraryMetric.INVALID_VALUES,
        unit="rows",
        argument=argument,
    )


# The test types with a direct ODCS library metric. `Missing_Pct` and `Row_Ct_Pct` carry
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
    "Required_No_Placeholder": RuleMapping(
        test_type="Required_No_Placeholder",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
        dimension=odcs_dimension(QualityDimension.COMPLETENESS),
        metric=LibraryMetric.MISSING_VALUES,
        unit="rows",
        argument=RuleArgument(name="missingValues", term_field="baseline_value"),
    ),
    "Email_Format": _invalid_values_row("Email_Format", RuleArgument(name="pattern", fixed=EMAIL_PATTERN)),
    "Valid_US_Zip": _invalid_values_row("Valid_US_Zip", RuleArgument(name="pattern", fixed=US_ZIP_PATTERN)),
    "Valid_US_Zip3": _invalid_values_row("Valid_US_Zip3", RuleArgument(name="pattern", fixed=US_ZIP3_PATTERN)),
    "Valid_US_CA_Zip": _invalid_values_row(
        "Valid_US_CA_Zip", RuleArgument(name="pattern", fixed=US_CA_ZIP_PATTERN),
    ),
    "US_State": _invalid_values_row("US_State", RuleArgument(name="validValues", fixed=US_STATE_VALID_VALUES)),
    # Library only when its baseline is one literal of the property's own type -- see `constant_value`.
    "Constant": _invalid_values_row("Constant", RuleArgument(name="validValues", term_field="baseline_value")),
    "Match_Row_Ct": RuleMapping(
        test_type="Match_Row_Ct",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.TABLE,
        operator=Operator.MUST_BE,
        dimension=odcs_dimension(QualityDimension.CONSISTENCY),
        metric=LibraryMetric.ROW_COUNT,
        unit="rows",
    ),
    "Match_Null_Ct": RuleMapping(
        test_type="Match_Null_Ct",
        shape=RuleShape.LIBRARY,
        scope=RuleScope.COLUMN,
        operator=Operator.MUST_BE,
        dimension=odcs_dimension(QualityDimension.CONSISTENCY),
        metric=LibraryMetric.NULL_VALUES,
        unit="rows",
    ),
}

# Routed `sql` rules. `SQL_Metric` is the only one: its query is the term's own, and its
# operator is whichever `bound_clause` builds from the term's bounds, so the row's `operator`
# names the two-sided case only. A row other than `SQL_Metric` projects its query from
# `cat_test_conditions.measure` (`_build_sql_query`).
_SQL_ROWS: dict[str, RuleMapping] = {
    "SQL_Metric": RuleMapping(
        test_type="SQL_Metric",
        shape=RuleShape.SQL,
        scope=RuleScope.TABLE,
        operator=Operator.MUST_BE_BETWEEN,
        dimension=odcs_dimension(QualityDimension.ACCURACY),
    ),
}

# Every routed test type -- the union `render` and `resolve_rule` both read. Disjoint from
# `NON_PUBLIC_TEST_TYPES`; a type in neither renders `custom`.
RULE_MAPPINGS: dict[str, RuleMapping] = {**_LIBRARY_ROWS, **_SQL_ROWS}

# Test types that come close to an ODCS construct and render `custom` because the construct
# would claim something the test does not check.
# Every type outside this set, `RULE_MAPPINGS`, `DECLARATION_TEST_TYPES` and
# `NON_PUBLIC_TEST_TYPES` renders `custom` for having no ODCS counterpart at all.
NEAR_STANDARD_CUSTOM_TEST_TYPES: frozenset[str] = frozenset({
    # invalidValues with validValues [false] is exact, but would call every TRUE value invalid.
    "Match_True_Ct",
    # Its percent divides by non-null rows; an invalidValues percent divides by all rows.
    "Street_Addr_Pattern",
    # missingValues with [''] also counts NULLs, which this test does not.
    "Match_Zero_Length_Ct",
    # A freshness service level compares seconds with a strict bound, not calendar days, and is
    # contract-level, so it would lose the term's identity and severity.
    "Recency",
    # Its date category accepts a date or a timestamp; an ODCS logicalType names one of them.
    "Match_Column_Type",
    # It also requires every listed value to be present; invalidValues only rejects values outside
    # the list.
    "LOV_All",
    # A minimum is one-sided, so it cannot assert equality with the baseline.
    "Match_Min_Val",
    # A maximum is one-sided, so it cannot assert equality with the baseline.
    "Match_Max_Val",
    # A minLength is per value, so it cannot assert the shortest length equals the baseline.
    "Match_Min_Length",
    # A maxLength is one-sided, so it cannot assert equality with the baseline.
    "Match_Max_Length",
    # ODCS has no column-count assertion.
    "Match_Column_Ct",
    # ODCS relationships are not checked by engines, and treat NULL combinations differently.
    "Combo_Match",
    # Its bound is the run date, which no fixed declared value can express.
    "Future_Date",
    # Its bound moves with the run date, which no fixed declared value can express.
    "Future_Date_1Y",
})


# The property `logicalType` values each declaration is exact for, per test type; `None` admits
# any. A bound compares values of one kind -- and the schema shapes `logicalTypeOptions` by
# `logicalType` -- so a term on a property declaring another type, or none, renders `custom`.
DECLARATION_LOGICAL_TYPES: dict[str, frozenset[str] | None] = {
    "Min_Val": frozenset({"integer", "number"}),
    "Max_Val": frozenset({"integer", "number"}),
    "Min_Date": frozenset({"date", "timestamp"}),
    "Max_Date": frozenset({"date", "timestamp"}),
    "Text_Length_Range": frozenset({"string"}),
    "Unique": None,
    "Required": None,
}
DECLARATION_TEST_TYPES: frozenset[str] = frozenset(DECLARATION_LOGICAL_TYPES)


def _allows_no_exceptions(term: "TestDefinition") -> bool:
    """Whether ``term`` fails on a single offending value: a threshold of 0, which is also what
    execution reads for an unset one."""
    raw = term.threshold_value
    if raw is None or not str(raw).strip():
        return True
    try:
        return float(raw) == 0
    except ValueError:
        return False


def _number_or_none(raw: str | None) -> int | float | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        value = _numeric(str(raw))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _whole_or_none(raw: str | None) -> int | None:
    value = _number_or_none(raw)
    return value if isinstance(value, int) else None


def _date_bound(value: str, logical_type: str | None) -> str:
    """``value`` as a ``date`` property declares it: the date alone when the time is midnight.

    A bound with a time of day keeps it, since dropping the time would move the bound.
    """
    if logical_type != "date":
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None and parsed.time() == datetime.min.time():
        return parsed.date().isoformat()
    return value


def property_declaration(term: "TestDefinition", logical_type: str | None) -> dict[str, Any] | None:
    """The schema-property fields that make exactly ``term``'s claim, or ``None`` when none do.

    A declaration asserts every value of the column, so only a term that fails on a single
    offending value, and tests every record, is one. ``logical_type`` is the property's declared ``logicalType``. A
    ``Text_Length_Range`` term declares whichever of its two bounds it sets. ``Unique`` also
    declares ``required``, because its measure counts every NULL where ``unique`` alone ignores
    them.
    """
    if term.test_type not in DECLARATION_LOGICAL_TYPES or not _allows_no_exceptions(term) or term.subset_condition:
        return None
    allowed = DECLARATION_LOGICAL_TYPES[term.test_type]
    if allowed is not None and logical_type not in allowed:
        return None

    if term.test_type == "Unique":
        return {"unique": True, "required": True}
    if term.test_type == "Required":
        return {"required": True}
    if term.test_type == "Text_Length_Range":
        options = {}
        for key, raw in (("minLength", term.lower_tolerance), ("maxLength", term.upper_tolerance)):
            if raw is None or not str(raw).strip():
                continue
            # A non-whole length bound cannot be declared, and declaring only the other bound would claim
            # less than the term checks.
            if (value := _whole_or_none(raw)) is None:
                return None
            options[key] = value
        return {"logicalTypeOptions": options} if options else None

    # Accepted divergence: the Min_Val/Max_Val measures allow 1e-6 past the baseline, and the
    # declaration does not. A generated baseline is a DOUBLE PRECISION profile value, so on a
    # column holding more significant digits than a double, the engine can fail a value
    # TestGen passes.
    key = "minimum" if term.test_type.startswith("Min_") else "maximum"
    if term.test_type.endswith("_Date"):
        value: Any = _date_bound((term.baseline_value or "").strip(), logical_type) or None
    else:
        value = _number_or_none(term.baseline_value)
    return {"logicalTypeOptions": {key: value}} if value is not None else None


# The `customProperties` entry naming a term rendered as a declaration on the property it sits on.
DECLARATION_MARKER = "testgenTerm"


def _declared_paths(declaration: dict[str, Any]) -> list[str]:
    """The dotted field paths ``declaration`` sets, e.g. ``logicalTypeOptions.maximum``."""
    return [
        f"{key}.{sub_key}" if isinstance(value, dict) else key
        for key, value in declaration.items()
        for sub_key in (value if isinstance(value, dict) else [None])
    ]


def declaration_marker(term: "TestDefinition", test_type: "TestType", declaration: dict[str, Any]) -> dict[str, Any]:
    """The ``customProperties`` entry recording that ``term`` rendered as ``declaration``.

    A declaration has no rule to carry the term's identity, so this entry does: its id, its test
    type, the fields it declares, and the descriptive fields its rule would otherwise have carried.
    """
    if not term.contract_term_id:
        raise ValueError(
            f"{test_type.test_name_short!r} term on {term.table_name}.{term.column_name} has no contract identity, "
            "so its declaration has no id to carry."
        )
    metadata: dict[str, Any] = {"dimension": odcs_dimension(QualityDimension(test_type.dq_dimension))}
    if term.test_description:
        metadata["name"] = term.test_description
    custom_properties = [
        *_apply_reserved_subtree(metadata, term.custom_metadata),
        *_user_custom_properties(term.custom_metadata),
    ]
    if custom_properties:
        metadata["customProperties"] = custom_properties
    return {
        "property": DECLARATION_MARKER,
        "value": {
            "id": term.contract_term_id,
            "testType": term.test_type,
            "declares": _declared_paths(declaration),
            **metadata,
        },
        "vendor": "testgen",
    }


def is_declaration_marker(entry: object) -> bool:
    return isinstance(entry, dict) and entry.get("vendor") == "testgen" and entry.get("property") == DECLARATION_MARKER


_SQL_STRING_LITERAL = re.compile(r"^'((?:[^']|'')*)'$")


def constant_value(term: "TestDefinition", logical_type: str | None) -> str | int | float | bool | None:
    """The one value a ``Constant`` term admits, typed as the property declares it, or ``None``
    when its stored baseline is not a single literal of that type.

    The baseline is stored as a SQL literal. A date is stored as a quoted string too, so a
    property declaring no type, or a date or timestamp, yields ``None``: the value cannot be
    told apart from text, and the engine would compare a string against a date.
    """
    raw = (term.baseline_value or "").strip()
    if logical_type == "string":
        match = _SQL_STRING_LITERAL.match(raw)
        return match.group(1).replace("''", "'") if match else None
    if logical_type in ("integer", "number"):
        return _number_or_none(raw)
    if logical_type == "boolean" and raw.upper() in ("TRUE", "FALSE"):
        return raw.upper() == "TRUE"
    return None


def rule_shape(test_type: str) -> RuleShape | None:
    """How ``test_type``'s terms render: ``None`` when no rule applies at all.

    Three outcomes, in order. A non-public type (``NON_PUBLIC_TEST_TYPES``) renders nothing --
    no term of one is ever authored in a document. A type with a ``RULE_MAPPINGS`` row renders that
    row's shape. Everything else renders ``custom``: the fallback carries the test type's own
    parameters, so it needs no per-type entry and a type added to the catalogue later exports
    without a mapping change.

    Never raises. A name outside the catalogue falls through to ``custom`` like any other
    unrouted type -- placement is where an unplaceable term is refused, not here.
    """
    if test_type in NON_PUBLIC_TEST_TYPES:
        return None
    mapping = RULE_MAPPINGS.get(test_type)
    return mapping.shape if mapping is not None else RuleShape.CUSTOM


# Identifier quote characters across flavors: ANSI double quotes, and BigQuery/Databricks backticks.
_IDENTIFIER_QUOTES = ('"', "`")


def _unquote_identifier(name: str) -> str:
    for quote in _IDENTIFIER_QUOTES:
        if len(name) >= 2 and name.startswith(quote) and name.endswith(quote):
            return name[1:-1].replace(quote * 2, quote)
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

    Raises ``ValueError`` for a non-public type, which renders no rule.
    """
    if test_type.test_type in NON_PUBLIC_TEST_TYPES:
        raise ValueError(f"{test_type.test_name_short!r} renders no quality rule, so it has no node to attach one to.")

    mapping = RULE_MAPPINGS.get(test_type.test_type)
    if mapping is not None and mapping.scope_follows_term:
        return RuleScope.COLUMN if len(_groupby_columns(term)) == 1 else RuleScope.TABLE

    return RuleScope.COLUMN if names_one_column(test_type) else RuleScope.TABLE


def names_one_column(test_type: "TestType") -> bool:
    """Whether a term of ``test_type`` stores one column, or an aggregate over one, in ``column_name``."""
    return (
        test_type.test_scope == TestScope.COLUMN
        or (test_type.column_name_prompt or "").strip() == "Aggregate Expression"
    )


def _numeric(raw: str) -> int | float:
    """Parse a stored threshold-shaped string into a plain, JSON-safe number.

    Renders a whole number as ``int`` rather than ``2.0`` -- ODCS operators accept either,
    but the term's own value was typed by a user as a count, not a float.
    """
    value = float(raw)
    return int(value) if value.is_integer() else value


class _InexactTerm(Exception):
    """A term whose stored values cannot be stated as its type's exact ODCS construct, so it
    renders ``custom`` instead."""


def _required_number(term: "TestDefinition", field: str) -> int | float:
    """The term's stored ``field`` as a number. Raises ``_InexactTerm`` when it is unset or not a number.

    Every exactly-projected parameter is optional in the catalogue, so a term saved with one
    cleared reaches rendering with nothing to compare against.
    """
    value = _number_or_none(getattr(term, field))
    if value is None:
        raise _InexactTerm(f"{term.test_type!r} term {term.contract_term_id!r} has no numeric {field!r}.")
    return value


def _threshold(term: "TestDefinition") -> int | float:
    """The term's ``threshold_value`` as a number, 0 when unset or empty as test execution reads it.
    Raises ``_InexactTerm`` when it is set to something other than a number."""
    if term.threshold_value in (None, ""):
        return 0
    return _required_number(term, "threshold_value")


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
    baseline_count = float(_required_number(term, "baseline_ct"))
    if baseline_count == 0:
        raise _InexactTerm(f"{term.test_type!r} term {term.contract_term_id!r} has a baseline row count of 0.")
    baseline_ratio = _required_number(term, "baseline_value_ct") / baseline_count
    if not 0 <= baseline_ratio <= 1:
        raise _InexactTerm(
            f"{term.test_type!r} term {term.contract_term_id!r} has a baseline populated ratio of {baseline_ratio}."
        )
    # Not ``_threshold``: a blank bound runs as h >= 0 and fails every run, which no band can express.
    h = float(_required_number(term, "threshold_value"))
    lower_ratio, upper_ratio = _cohens_h_band(baseline_ratio, h)
    lower, upper = _complement_percent_band(lower_ratio, upper_ratio)
    return lower, upper, baseline_ratio, h


def _row_ct_pct_band(term: "TestDefinition") -> tuple[float, float, float, float]:
    """Row-count band, baseline count and threshold percent for a ``Row_Ct_Pct`` term.

    ``|100*(n-b)/b| <= T`` rearranges to ``n in [b*(1-T/100), b*(1+T/100)]``.
    """
    baseline_count = float(_required_number(term, "baseline_ct"))
    if baseline_count == 0:
        raise _InexactTerm(f"{term.test_type!r} term {term.contract_term_id!r} has a baseline row count of 0.")
    percent = float(_threshold(term))
    lower = baseline_count * (1 - percent / 100)
    upper = baseline_count * (1 + percent / 100)
    return lower, upper, baseline_count, percent


# The ``testgen`` properties ``_conversion_properties`` writes onto a rule: baselines and
# thresholds behind a converted band.
CONVERSION_PROPERTIES = frozenset({
    "baselineRatio", "thresholdBound", "baselineCt", "baselineValueCt", "baselineCount", "thresholdPercent",
})


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


def _server_type_markers(flavor: SqlFlavorCode) -> list[dict[str, Any]]:
    """The ``serverType`` property naming the dialect a rule's payload is written in, or none when
    ``flavor`` has no ODCS server type."""
    server_type = FLAVOR_TO_SERVER_TYPE.get(flavor)
    if server_type is None:
        return []
    return [{"property": "serverType", "value": server_type.value, "vendor": "testgen"}]


# Reserved-subtree fields copied onto the rule unchanged when present. `dimension`,
# `tags`, `authoritativeDefinitions` and `customProperties` each need their own handling
# (a translation, a list assignment, a list assignment and a merge respectively), so they
# are not in this tuple -- see `_apply_reserved_subtree`.
_RESERVED_DIRECT_FIELDS: tuple[str, ...] = ("name", "description", "businessImpact", "method", "schedule", "scheduler")

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


def test_type_parameters(test_type: "TestType") -> list[str]:
    """The parameter names ``test_type`` declares, in catalogue order."""
    return [name.strip() for name in (test_type.default_parm_columns or "").split(",") if name.strip()]


def _custom_implementation(term: "TestDefinition", test_type: "TestType") -> dict[str, Any]:
    """``term``'s values for the parameters its test type declares.

    Keyed by the catalogue's own ``default_parm_columns`` rather than a fixed list, so a test
    type added later exports its parameters with no change here. Carries no schema or table, and
    ``column_name`` only for a type whose ``column_name`` is not a column: otherwise the subject is
    the node the rule nests on. Values the term leaves unset are omitted rather than rendered null.
    """
    implementation = {
        name: getattr(term, name)
        for name in test_type_parameters(test_type)
        if name not in ("schema_name", "table_name", "column_name") and getattr(term, name, None) not in (None, "")
    }
    if not names_one_column(test_type) and term.column_name not in (None, ""):
        implementation["column_name"] = term.column_name
    return implementation


def drop_generated_metadata(
    metadata: dict[str, Any], test_type: "TestType", parameters: dict[str, Any], *, custom: bool
) -> dict[str, Any]:
    """``metadata`` resolved from a rule or declaration, without the fields the projection
    writes from the catalog rather than from the term: a ``dimension`` equal to the one
    ``test_type`` renders with, and, on a ``custom`` rule, a ``name`` equal to the catalog's
    own and a ``description`` equal to the one the projection writes for ``parameters``."""
    generated: dict[str, list[Any]] = {"dimension": []}
    if test_type.dq_dimension:
        generated["dimension"].append(odcs_dimension(QualityDimension(test_type.dq_dimension)))
    if (mapping := RULE_MAPPINGS.get(test_type.test_type)) is not None:
        generated["dimension"].append(mapping.dimension)
    if custom:
        generated["name"] = [test_type.test_name_long, test_type.test_name_short, test_type.test_type]
        generated["description"] = [_custom_description(parameters, test_type)]
    return {key: value for key, value in metadata.items() if value not in generated.get(key, ())}


def _normalized(text: str | None) -> str:
    """``text`` with runs of whitespace collapsed to single spaces, empty when unset."""
    return " ".join(text.split()) if text else ""


def _custom_description(parameters: dict[str, Any], test_type: "TestType") -> str:
    """A plain-words statement of what a ``custom`` rule checks.

    Built from the catalog's own prose and the term's ``parameters``: its ``threshold_value``, and
    for a value-list type the values its ``baseline_value`` lists. Other ODCS engines do not run a
    ``custom`` rule, so for a counterparty without TestGen this is the only usable part of it.
    Names no parameter: a reader is told what the check does, not which field carries it. A
    segment the catalogue leaves unset is omitted rather than rendered as ``None``.
    """
    threshold_value = parameters.get("threshold_value")
    segments: list[str] = []
    if statement := _normalized(test_type.test_description):
        segments.append(statement)
    if failure := _normalized(test_type.except_message):
        segments.append(f"Fails: {failure}")
    if test_type.test_type in VALUE_LIST_TEST_TYPES and (values := parse_value_list(parameters.get("baseline_value"))):
        segments.append(f"Expected values: {format_value_list(values)}.")
    if threshold_value not in (None, ""):
        bound = f"Threshold: {threshold_value}"
        if label := _normalized(test_type.threshold_description):
            bound = f"{bound} ({label})"
        segments.append(f"{bound}.")
    return " ".join(segments)


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
    bound = _number_or_none(condition_text)
    if bound is None:
        raise _InexactTerm(f"{term.test_type!r} term {term.contract_term_id!r} has no numeric bound {condition_text!r}.")
    return operator, bound


# TestGen's own placeholder shape -- {ALL_CAPS_WITH_UNDERSCORES} -- versus the two ODCS
# placeholders a query is allowed to still carry once this module is done with it.
_LEFTOVER_PLACEHOLDER = re.compile(r"\{[A-Z_]+\}")
_LEGAL_ODCS_PLACEHOLDERS = frozenset({"{object}", "{property}"})

# Every flavor's measure wraps {RUN_DATE} as a quoted string literal fed to a date-parsing
# cast or function (`'{RUN_DATE}'::DATE`, `TO_DATE('{RUN_DATE}', ...)`, ...). The quoted
# form is replaced as a unit so the result is the bare keyword CURRENT_DATE, not a quoted
# string reading "CURRENT_DATE" that a date cast would then fail to parse.
_RUN_DATE_QUOTED = re.compile(r"'\{RUN_DATE\}'")


def _check_no_leftover_placeholder(query: str, term: "TestDefinition", flavor: SqlFlavorCode) -> None:
    """Raise ``_InexactTerm`` when a TestGen placeholder survives in ``query`` -- no other engine
    could run it."""
    leftover = sorted({token for token in _LEFTOVER_PLACEHOLDER.findall(query) if token not in _LEGAL_ODCS_PLACEHOLDERS})
    if leftover:
        raise _InexactTerm(
            f"{term.test_type!r} on {flavor.value!r} left {leftover} unresolved in its sql query -- "
            "no data was available to substitute it."
        )


def _build_sql_query(
    term: "TestDefinition",
    condition: CatCondition,
    scope: RuleScope,
    flavor: SqlFlavorCode,
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
    Macro calls (``<%FUNC;args%>``) are expanded for the contract connection's flavor by the same
    expander the execution engine uses (``read_file.replace_templated_functions``), not a
    second one.

    Raises ``_InexactTerm`` if anything TestGen-shaped survives substitution -- a leftover
    placeholder would still validate against the schema and then fail at the counterparty.
    """
    measure = condition.measure

    if scope is RuleScope.COLUMN:
        measure = measure.replace("{COLUMN_NAME}", "{property}")

    # A qualified schema/table pattern a measure may use to reference the same table a second
    # time -- it names the same object the rule is attached to, so it collapses onto ODCS's own
    # placeholder too.
    measure = measure.replace('"{SCHEMA_NAME}"."{TABLE_NAME}"', "{object}")
    measure = measure.replace("{SCHEMA_NAME}", "{object}").replace("{TABLE_NAME}", "{object}")

    measure = _RUN_DATE_QUOTED.sub("CURRENT_DATE", measure).replace("{RUN_DATE}", "CURRENT_DATE")

    for token, value in _sql_literal_substitutions(term, column_type).items():
        if value is not None and token in measure:
            measure = measure.replace(token, str(value))

    measure = replace_templated_functions(measure, FLAVOR_CODE_TO_FAMILY[flavor])

    query = f"SELECT {measure} FROM {{object}}"
    _check_no_leftover_placeholder(query, term, flavor)
    return query


def _sql_metric_query(term: "TestDefinition", flavor: SqlFlavorCode) -> str:
    """A ``SQL_Metric`` term's ``sql`` rule query: the term's own query, which already returns
    the one value its bounds compare against, with each declared variable given its default and
    the table group's schema substituted for ``{DATA_SCHEMA}``.

    Raises ``_InexactTerm`` when the term has no query, or when a TestGen placeholder survives
    substitution.
    """
    query = strip_trailing_semicolons(term.custom_query)
    if not query:
        raise _InexactTerm(f"{term.test_type!r} term {term.contract_term_id!r} has no query.")
    # Before the leftover check, which looks for `{NAME}` and so would pass over a `{NAME:default}`
    # declaration and export it for an engine that cannot resolve it. The declared query survives
    # in queryTemplate, which the caller attaches whenever rendering changed the query.
    query = query_variables.render(query)
    query = query.replace("{DATA_SCHEMA}", term.schema_name)
    _check_no_leftover_placeholder(query, term, flavor)
    return query


def _argument_value(term: "TestDefinition", argument: RuleArgument, logical_type: str | None) -> Any:
    """The value of a library rule's ``argument`` for ``term``, or ``None`` when it renders none.

    ``Dupe_Rows`` names its columns only when it groups on more than one; a single column is
    the node the rule sits on. ``Required_No_Placeholder``'s list may be empty, which leaves a
    plain null check. Every other argument is required, so a value that does not parse raises
    ``_InexactTerm``.
    """
    if argument.fixed is not None:
        return list(argument.fixed) if isinstance(argument.fixed, tuple) else argument.fixed
    if argument.term_field == "groupby_names":
        names = [name.strip() for name in (term.groupby_names or "").split(",") if name.strip()]
        # An unquoted name folds to the flavor's default case when TestGen runs it, so it may not be
        # the column's exact name, which a property name must be.
        if any(_unquote_identifier(name) == name for name in names):
            raise _InexactTerm(f"{term.test_type!r} term {term.contract_term_id!r} groups on an unquoted name.")
        columns = _groupby_columns(term)
        return columns if len(columns) > 1 else None

    raw = getattr(term, argument.term_field)
    if argument.name == "missingValues":
        return parse_value_list(raw) or None

    value: Any
    if term.test_type == "Constant":
        literal = constant_value(term, logical_type)
        value = [literal] if literal is not None else None
    elif argument.name == "validValues":
        value = parse_value_list(raw)
    else:
        value = raw
    if not value:
        raise _InexactTerm(
            f"{term.test_type!r} term {term.contract_term_id!r} has no parseable "
            f"{argument.term_field!r} to render its {argument.name!r} argument."
        )
    return value


def _custom_check(
    term: "TestDefinition", test_type: "TestType", flavor: SqlFlavorCode
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The fields of ``term``'s ``custom`` rule, and the ``testgen`` system properties it carries."""
    rule = {
        "type": RuleShape.CUSTOM.value,
        "engine": "testgen",
        "name": term.test_description or test_type.test_name_long or test_type.test_name_short or term.test_type,
        "description": _custom_description(
            {"threshold_value": term.threshold_value, "baseline_value": term.baseline_value}, test_type
        ),
        "implementation": _custom_implementation(term, test_type),
    }
    return rule, _server_type_markers(flavor)


def _exact_check(
    term: "TestDefinition",
    flavor: SqlFlavorCode,
    mapping: RuleMapping,
    condition: CatCondition | None,
    column_type: str | None,
    logical_type: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The check fields of ``term``'s rule in its mapped shape, and the ``testgen`` system
    properties that recover the term from it.

    Raises ``_InexactTerm`` when the term's stored values cannot be stated in that shape.
    """
    rule: dict[str, Any] = {"type": mapping.shape.value}
    system_properties: list[dict[str, Any]] = []

    if mapping.shape is RuleShape.LIBRARY:
        if mapping.metric is None:
            # Every LIBRARY row carries a metric -- test_rule_mapping_coverage.py's
            # test_a_library_row_carries_a_metric_and_a_scope_and_nothing_else_does enforces it.
            raise ValueError(f"Term {term.contract_term_id!r} is mapped as a library rule but carries no metric.")
        rule["metric"] = mapping.metric.value
        if mapping.unit is not None:
            rule["unit"] = mapping.unit
        if mapping.argument is not None:
            value = _argument_value(term, mapping.argument, logical_type)
            if value:
                rule["arguments"] = {mapping.argument.name: value}

        if term.test_type == "Missing_Pct":
            lower, upper, baseline_ratio, h = _missing_pct_band(term)
            rule.update(bound_clause(lower, upper))
            system_properties += _conversion_properties(baseline_ratio, h)
            # The ratio alone does not give back the two counts it was computed from.
            system_properties += _conversion_properties(
                _numeric(term.baseline_ct), _numeric(term.baseline_value_ct),
                baseline_property="baselineCt", bound_property="baselineValueCt",
            )
        elif term.test_type == "Row_Ct_Pct":
            lower, upper, baseline_count, percent = _row_ct_pct_band(term)
            rule.update(bound_clause(lower, upper))
            system_properties += _conversion_properties(
                baseline_count, percent, baseline_property="baselineCount", bound_property="thresholdPercent"
            )
        elif term.test_type == "Dupe_Rows":
            rule[mapping.operator.value] = term.skip_errors or 0
        elif term.test_type == "Match_Null_Ct":
            rule[mapping.operator.value] = _required_number(term, "baseline_ct")
        else:
            rule[mapping.operator.value] = _threshold(term)

    elif term.test_type == "SQL_Metric":
        rule["query"] = _sql_metric_query(term, flavor)
        if rule["query"] != term.custom_query:
            # The query as written is kept to export it back: the rendered one names the schema
            # and drops a trailing semicolon.
            system_properties.append({"property": "queryTemplate", "value": term.custom_query, "vendor": "testgen"})
        bound = bound_clause(_number_or_none(term.lower_tolerance), _number_or_none(term.upper_tolerance))
        if not bound:
            raise _InexactTerm(f"{term.test_type!r} term {term.contract_term_id!r} sets neither a minimum nor a maximum.")
        rule.update(bound)
        system_properties.extend(_server_type_markers(flavor))

    else:
        if condition is None:
            raise ValueError(
                f"project_rule needs a resolved CatCondition to render term {term.contract_term_id!r}'s sql rule."
            )
        rule["query"] = _build_sql_query(term, condition, mapping.scope, flavor, column_type)
        operator, bound = _resolved_bound(condition, term, column_type)
        rule[operator.value] = bound
        system_properties.extend(_server_type_markers(flavor))

    return rule, system_properties


def project_rule(
    term: "TestDefinition",
    test_type: "TestType",
    flavor: SqlFlavorCode,
    condition: CatCondition | None = None,
    column_type: str | None = None,
    logical_type: str | None = None,
) -> dict[str, Any]:
    """Project one contract term into one ODCS quality-rule object.

    ``term`` supplies the stored values a rule is built from -- threshold, baseline
    statistics, custom query, contract identity, and the reserved
    ``custom_metadata['odcs']`` subtree. ``test_type`` supplies the catalogue context a
    ``custom`` rule reads -- its declared parameters, prose, display name and TestGen
    dimension. ``flavor`` is the contract connection's flavor: the dialect a ``sql`` or
    ``custom`` rule's payload is written in, carried onto the rule as its ODCS server type
    when the flavor has one. ``condition`` is the resolved ``cat_test_conditions`` row for
    ``term.test_type`` and that flavor -- required for (and only for) an
    ``SQL``-shape term; this module has no database access, so the caller (the contract
    renderer, which holds a session) resolves it and passes it in. ``column_type`` is the
    profiled column's data type (``DataColumnChars.column_type``) -- needed only by the
    handful of ``SQL``-shape measures whose declared flavor casts a baseline value to it
    (bigquery/sap_hana); every other term ignores it, and it may be left ``None``.
    ``logical_type`` is the ``logicalType`` the term's column property declares; a ``Constant``
    term renders ``custom`` unless its baseline is one literal of that type (``constant_value``).
    A routed term renders ``custom`` whenever its stored values cannot be stated in its
    mapped shape -- a cleared threshold or bound, a baseline count of 0, an unparseable
    argument, a placeholder no other engine could substitute, or a record subset condition.
    The result is plain JSON-safe data -- ``dict``, ``list``, ``str``, ``int``, ``float`` and
    ``bool`` only -- so it serializes with ``yaml.safe_dump`` and validates against the
    pinned ODCS schema.
    """
    shape = rule_shape(term.test_type)
    if shape is None:
        raise ValueError(
            f"{test_type.test_name_short!r} renders no quality rule, so {term.contract_term_id!r} should not exist."
        )
    mapping = RULE_MAPPINGS.get(term.test_type)
    if FLAVOR_CODE_TO_FAMILY[flavor] in _INEXACT_FAMILIES.get(term.test_type, frozenset()):
        mapping = None
    if term.subset_condition:
        # No other shape can state a subset: a library or sql rule would check the whole table
        mapping = None

    check = None
    if mapping is not None and mapping.shape is not RuleShape.CUSTOM:
        try:
            check = _exact_check(term, flavor, mapping, condition, column_type, logical_type)
        except _InexactTerm as reason:
            LOG.info(f"{reason} Rendering it as a custom rule.")
            mapping = None
    rule, system_properties = check or _custom_check(term, test_type, flavor)

    if not term.contract_term_id:
        raise ValueError(
            f"{test_type.test_name_short!r} term on {term.schema_name}.{term.table_name}"
            f"{'.' + term.column_name if term.column_name else ''} has no contract identity, "
            "so its rule has no id to carry."
        )
    rule["id"] = term.contract_term_id
    rule["dimension"] = (
        mapping.dimension if mapping is not None
        else odcs_dimension(QualityDimension(test_type.dq_dimension))
    )
    if term.test_description and "name" not in rule:
        rule["name"] = term.test_description

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
#      operator can express the same bound. Every row here is `unit: rows`, the ODCS default:
#      `nullValues` onto `Required` (or `Match_Null_Ct` for an exact count above zero); `rowCount`
#      onto `Row_Ct` (or `Match_Row_Ct` for an exact count); and `invalidValues` (carrying exactly
#      one of `arguments.validValues` / `arguments.pattern`) onto `LOV_Match` / `Pattern_Match`. A bound
#      on a count is restated onto the target's operator when, the count being a non-negative
#      integer, both state the same check (`_count_ceiling`, `_resolve_row_count`).
#      `duplicateValues` still has no tier-2 row: `Unique`'s measure counts NULLs as
#      duplicates (no threshold conversion makes it match), so there is nothing to resolve
#      onto regardless of which node the rule sits on. `Dupe_Rows` is a library row, but it is
#      reachable through its marker (tier 1) alone.
#   3. Everything else declines (`None`): any `unit: percent` (no TestGen type computes a
#      plain proportion), an unrecognised unit (never defaulted to `rows`), `missingValues`,
#      an operator TestGen cannot state, a `text`/`sql`/`custom` rule, a metric on a scope its
#      target test type does not have, or an `invalidValues` rule with neither or both of its
#      two recognised arguments.

# The `testgen` customProperties a rule carries so its term is recoverable from the rule alone:
# the baseline ratio/count, baseline counts and threshold bound a converted band was computed
# from, and the query a `SQL_Metric` term was written with before its schema was substituted.
_CONVERSION_PROPERTY_NAMES = frozenset({
    "baselineRatio", "baselineCount", "thresholdBound", "thresholdPercent", "baselineCt", "baselineValueCt",
    "queryTemplate",
})


@dataclass(frozen=True)
class ResolvedTerm:
    """One incoming ODCS quality rule, resolved onto the TestGen test type that verifies it.

    ``thresholds`` is the rule's own acceptance-operator key(s) and value(s) -- ``{"mustBeLessOrEqualTo": 0}``,
    for instance -- read directly off the rule, or re-expressed onto the target's own operator where the
    incoming bound is strict but the target's measure is integral (see ``_resolve_row_count``). For
    ``Missing_Pct``/``Row_Ct_Pct`` this is the *rendered* band, not the term's own threshold --
    see ``conversion``. ``arguments`` is the rule's ``arguments`` mapping when the target test type has one
    (``LOV_Match``, ``Pattern_Match``), otherwise empty. ``conversion`` is the rule's
    ``testgen`` system properties named in ``_CONVERSION_PROPERTY_NAMES``, read back by name --
    non-empty only for a marked ``Missing_Pct``/``Row_Ct_Pct``/``SQL_Metric`` rule.

    ``parameters`` is what a caller stores on the term: its values for the parameters the test
    type declares, as ``test_definitions`` holds them. ``contract_term_id`` is the rule's ``id``.
    ``metadata`` is the rule's descriptive fields -- everything but its check, its id and the
    ``testgen`` system properties.
    """
    test_type: str
    thresholds: dict[str, Any]
    arguments: dict[str, Any]
    conversion: dict[str, Any]
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)
    contract_term_id: str | None = None
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


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


def rename_argument_columns(rule: dict[str, Any], names: Mapping[str, str]) -> dict[str, Any]:
    """``rule`` with each column its ``arguments.properties`` lists renamed through ``names``.

    A column ``names`` does not hold keeps its name. Returns ``rule`` itself when nothing is renamed,
    and a copy otherwise.
    """
    arguments = rule.get("arguments")
    columns = arguments.get("properties") if isinstance(arguments, dict) else None
    if not isinstance(columns, list):
        return rule
    renamed = [names.get(column, column) if isinstance(column, str) else column for column in columns]
    if renamed == columns:
        return rule
    return {**rule, "arguments": {**arguments, "properties": renamed}}


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


def _count_ceiling(operator: Operator, value: Any) -> tuple[Operator, Any] | None:
    """An upper bound on a row count restated as ``mustBeLessOrEqualTo``, or None for any other bound.

    A row count is a non-negative integer, so ``mustBe: 0`` states the same check as
    ``mustBeLessOrEqualTo: 0``, and ``mustBeLessThan: N`` the same as ``mustBeLessOrEqualTo: N - 1``.
    """
    if operator is Operator.MUST_BE_LESS_OR_EQUAL_TO:
        return operator, value
    if operator is Operator.MUST_BE and _is_integral(value) and value == 0:
        return Operator.MUST_BE_LESS_OR_EQUAL_TO, 0
    if operator is Operator.MUST_BE_LESS_THAN and _is_integral(value) and value >= 1:
        return Operator.MUST_BE_LESS_OR_EQUAL_TO, int(value) - 1
    return None


def _resolve_null_values(operator: Operator, value: Any, scope: RuleScope) -> tuple[str, dict, dict] | None:
    """``Required`` for an upper bound on the null count (see ``_count_ceiling``), ``Match_Null_Ct`` for an
    exact count above zero, else None."""
    if operator is Operator.MUST_BE and _is_integral(value) and value > 0:
        mapping = _LIBRARY_ROWS["Match_Null_Ct"]
        return ("Match_Null_Ct", {operator.value: value}, {}) if scope is mapping.scope else None
    mapping = _LIBRARY_ROWS["Required"]
    ceiling = _count_ceiling(operator, value)
    if scope is not mapping.scope or ceiling is None or ceiling[0] is not mapping.operator:
        return None
    return "Required", {ceiling[0].value: ceiling[1]}, {}


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
    if operator is Operator.MUST_BE and _is_integral(value):
        return "Match_Row_Ct", {operator.value: value}, {}
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
    ceiling = _count_ceiling(operator, value)
    if scope is not mapping.scope or ceiling is None or ceiling[0] is not mapping.operator:
        return None
    return target, {ceiling[0].value: ceiling[1]}, dict(arguments)


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
    was rendered), names a non-public type, claims more than one operator at once, or disagrees
    with its own routed shape.

    A custom-routed type must carry no operator: its bound is one of its parameters, never an
    operator on the rule. So must a routed type's rule rendered ``custom``, as one is when its
    term's values cannot be stated in the mapped shape. An ``sql`` type carries exactly one operator, which
    its own bounds decide. A library type must agree with its ``RULE_MAPPINGS`` row's scope,
    operator and (for a ``validValues``/``pattern`` row) argument shape; an optional argument such as
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

    if shape is RuleShape.CUSTOM or rule.get("type") == RuleShape.CUSTOM.value:
        if marker_operator is not None:
            return None
        return marker

    mapping = RULE_MAPPINGS[marker]
    if mapping.shape is RuleShape.SQL:
        if marker_operator not in _BOUND_OPERATORS:
            return None
        between = rule[marker_operator.value] if marker_operator is Operator.MUST_BE_BETWEEN else None
        if between is not None and not (isinstance(between, list) and len(between) == 2):
            return None
        return marker
    if scope is not mapping.scope and not mapping.scope_follows_term:
        return None
    if marker_operator is None or not _operator_matches(marker_operator, mapping.operator):
        return None
    if mapping.argument is not None and not _argument_is_well_formed(rule, marker, mapping.argument):
        return None
    return marker


# The operators `bound_clause` writes, and so the only ones a `SQL_Metric` rule can carry.
_BOUND_OPERATORS = frozenset({
    Operator.MUST_BE, Operator.MUST_BE_BETWEEN, Operator.MUST_BE_GREATER_OR_EQUAL_TO, Operator.MUST_BE_LESS_OR_EQUAL_TO,
})


def _argument_is_well_formed(rule: dict[str, Any], marker: str, argument: RuleArgument) -> bool:
    """Whether ``rule`` carries ``argument`` in the shape its type's projection writes.

    A fixed argument must be the type's own predicate: a rule whose pattern or list was edited
    checks something else. A ``Constant`` list holds exactly one value, and a ``missingValues``
    list, which may be absent, holds no NULL.
    """
    if argument.name in _INVALID_VALUES_ARGUMENT_KEYS:
        arguments = _unambiguous_argument(rule)
        if arguments is None or argument.name not in arguments:
            return False
        value = arguments[argument.name]
        if argument.fixed is not None:
            return value == (list(argument.fixed) if isinstance(argument.fixed, tuple) else argument.fixed)
        if argument.name == "validValues":
            return isinstance(value, list) and (len(value) == 1 if marker == "Constant" else bool(value)) and (
                None not in value
            )
        return isinstance(value, str)
    if argument.name == "missingValues":
        value = _arguments_from_rule(rule).get("missingValues")
        return value is None or (isinstance(value, list) and None not in value)
    return True


def _is_testgen_implementation(
    rule: dict[str, Any], test_type: str, declared_parameters: Mapping[str, frozenset[str]] | None
) -> bool:
    """Whether a ``custom`` rule is one TestGen's engine wrote, with parameters ``test_type`` takes."""
    implementation = rule.get("implementation")
    if rule.get("engine") != "testgen" or not isinstance(implementation, dict):
        return False
    if declared_parameters is None:
        return True
    return set(implementation) - {"column_name"} <= declared_parameters.get(test_type, frozenset())


def _resolve_duplicate_values(
    rule: dict[str, Any], operator: Operator, value: Any, scope: RuleScope, subject: str | None
) -> tuple[str, dict, dict] | None:
    """``duplicateValues`` in rows resolves to ``Dupe_Rows``, which counts the keys occurring more
    than once -- never to ``Unique``, which also counts every NULL.

    A column rule groups on its own column; a table rule groups on its listed ``properties``,
    and one listing none declines. ``Dupe_Rows`` renders ``mustBeLessOrEqualTo``; a strict
    ``mustBeLessThan`` on a whole count re-expresses as ``<= N - 1`` and ``mustBe 0`` as
    ``<= 0``, since a count is never negative.
    """
    arguments = _arguments_from_rule(rule)
    if set(arguments) - {"properties"}:
        return None
    properties = arguments.get("properties")
    if scope is RuleScope.COLUMN:
        if not subject or properties not in (None, [subject]):
            return None
        arguments = {}
    elif not (isinstance(properties, list) and properties and all(isinstance(item, str) for item in properties)):
        return None

    expected = _LIBRARY_ROWS["Dupe_Rows"].operator
    if operator is expected and _is_integral(value) and value >= 0:
        bound = int(value)
    elif operator is Operator.MUST_BE_LESS_THAN and _is_integral(value) and value >= 1:
        bound = int(value) - 1
    elif operator is Operator.MUST_BE and value == 0 and not isinstance(value, bool):
        bound = 0
    else:
        return None
    return "Dupe_Rows", {expected.value: bound}, arguments


def _quoted_identifier(name: str, flavor: SqlFlavorCode) -> str:
    quote = get_flavor_service(FLAVOR_CODE_TO_FAMILY[flavor]).quote_character
    return quote + name.replace(quote, quote * 2) + quote


def _resolve_sql_metric(
    rule: dict[str, Any],
    subject: str | None,
    table_name: str | None,
    flavor: SqlFlavorCode,
    conversion: dict[str, Any],
    qualify_tables: bool,
) -> ResolvedTerm | None:
    """An unmarked ``sql`` rule as a ``SQL_Metric`` term: its query, which returns the one value
    its bound compares, and that bound. A strict or negated operator, which ``SQL_Metric``'s
    inclusive tolerances cannot state, declines.

    ``{object}`` becomes the table, qualified by ``{DATA_SCHEMA}`` when ``qualify_tables`` is set,
    and ``{property}`` the column, each quoted as the flavor quotes identifiers; a placeholder with
    nothing to substitute declines. ``${object}`` and ``${property}`` are read as the same placeholders.
    """
    query = rule.get("query")
    operator, value = _sole_operator(rule)
    if not isinstance(query, str) or not query.strip() or operator not in _BOUND_OPERATORS:
        return None
    if operator is Operator.MUST_BE_BETWEEN:
        if not (isinstance(value, list) and len(value) == 2 and all(_is_number(item) for item in value)):
            return None
    elif not _is_number(value):
        return None
    query = query.replace("${object}", "{object}").replace("${property}", "{property}")
    if "{object}" in query:
        if not table_name:
            return None
        table = _quoted_identifier(table_name, flavor)
        query = query.replace("{object}", f"{{DATA_SCHEMA}}.{table}" if qualify_tables else table)
    if "{property}" in query:
        if not subject:
            return None
        query = query.replace("{property}", _quoted_identifier(subject, flavor))
    thresholds = {operator.value: value}
    return ResolvedTerm(
        test_type="SQL_Metric",
        thresholds=thresholds,
        arguments={},
        conversion=conversion,
        parameters={"custom_query": query, **_bounds_from(thresholds)},
        contract_term_id=rule.get("id"),
        metadata=_rule_metadata_from(rule),
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def resolve_rule(
    rule: dict[str, Any],
    scope: RuleScope,
    known_test_types: frozenset[str],
    subject: str | None = None,
    *,
    flavor: SqlFlavorCode,
    table_name: str | None = None,
    qualify_tables: bool = True,
    declared_parameters: Mapping[str, frozenset[str]] | None = None,
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
    guessed, so most incoming shapes -- any ``percent`` unit, an unrecognised unit,
    ``missingValues``, an operator TestGen cannot state, a ``text``/``sql``/``custom`` rule --
    decline rather than resolve. A rule without ``unit`` counts in rows and a rule without ``type``
    is ``library``, both ODCS defaults.

    Two shapes resolve without a marker beyond that table. A row-based ``duplicateValues`` rule
    resolves to ``Dupe_Rows`` grouped on the column it nests under, or on the table rule's
    listed ``properties``. A single-value ``sql`` rule resolves to ``SQL_Metric``, with ODCS's
    ``{object}`` and ``{property}`` placeholders replaced by ``table_name`` and ``subject``.

    ``subject`` is the name of the property the rule sits on, for a column rule; a single-column
    ``Dupe_Rows`` names its grouping by its node alone. ``table_name`` is the schema object the
    rule sits under; ``qualify_tables`` is whether SQL on the connection names a table by its
    schema. ``flavor`` is the flavor of the connection the resolved term runs against;
    identifiers are quoted with its quote character.

    A ``custom`` rule resolves only when ``engine`` is ``testgen`` and its ``implementation`` is
    an object. ``declared_parameters`` maps a test type to the parameter names it takes; when
    given, a ``custom`` rule whose ``implementation`` holds any other name declines.
    """
    conversion = _conversion_properties_from_rule(rule)

    marker = _marker_test_type(rule)
    if marker is not None:
        resolved_marker = _resolve_marker(rule, marker, scope, known_test_types)
        if resolved_marker is None:
            return None
        if rule.get("type") == RuleShape.CUSTOM.value and not _is_testgen_implementation(
            rule, resolved_marker, declared_parameters
        ):
            return None
        return _resolved(
            rule, resolved_marker, _thresholds_from_rule(rule), _arguments_from_rule(rule), conversion, subject,
            flavor,
        )

    if rule.get("type") == RuleShape.SQL.value:
        return _resolve_sql_metric(rule, subject, table_name, flavor, conversion, qualify_tables)

    if rule.get("unit", "rows") != "rows" or rule.get("type", RuleShape.LIBRARY.value) != RuleShape.LIBRARY.value:
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
    elif metric == LibraryMetric.DUPLICATE_VALUES.value:
        result = _resolve_duplicate_values(rule, operator, value, scope, subject)
    if result is None:
        return None

    test_type, thresholds, arguments = result
    return _resolved(rule, test_type, thresholds, arguments, conversion, subject, flavor)


def _resolved(
    rule: dict[str, Any],
    test_type: str,
    thresholds: dict[str, Any],
    arguments: dict[str, Any],
    conversion: dict[str, Any],
    subject: str | None,
    flavor: SqlFlavorCode,
) -> ResolvedTerm:
    return ResolvedTerm(
        test_type=test_type,
        thresholds=thresholds,
        arguments=arguments,
        conversion=conversion,
        parameters=_rule_parameters(rule, test_type, thresholds, arguments, conversion, subject, flavor),
        contract_term_id=rule.get("id"),
        metadata=_rule_metadata_from(rule),
    )


# A rule's keys that carry its check rather than describe it.
_CHECK_KEYS = frozenset({
    "id", "type", "engine", "implementation", "metric", "unit", "arguments", "query", "customProperties",
    *(op.value for op in Operator),
})


def _rule_metadata_from(rule: dict[str, Any]) -> dict[str, Any]:
    """``rule``'s descriptive fields: every key but its check and its id, plus the
    ``customProperties`` entries no ``testgen`` system property put there."""
    metadata = {key: value for key, value in rule.items() if key not in _CHECK_KEYS}
    custom_properties = [
        entry for entry in rule.get("customProperties") or []
        if not (isinstance(entry, dict) and entry.get("vendor") == "testgen")
    ]
    if custom_properties:
        metadata["customProperties"] = custom_properties
    return metadata


def _stored(value: Any) -> str:
    """``value`` as ``test_definitions`` stores a parameter: text, with a whole number written
    without a decimal point."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _pipe_list_parameters(threshold_value: Any) -> dict[str, str]:
    """``baseline_value`` and ``threshold_value`` for a ``LOV_All`` implementation that carries its
    values as one quoted, pipe-delimited ``threshold_value``, e.g. ``'A|it''s'``; none for any other."""
    text = str(threshold_value or "").strip()
    if len(text) < 2 or not (text.startswith("'") and text.endswith("'")):
        return {}
    values = text[1:-1].replace("''", "'").split("|")
    return {"baseline_value": format_value_list(values), "threshold_value": "0"}


def _constant_literal(value: Any) -> str:
    """The stored ``Constant`` baseline for ``value`` -- the inverse of ``constant_value``."""
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return _stored(value)


def _bounds_from(thresholds: dict[str, Any]) -> dict[str, str]:
    """``lower_tolerance``/``upper_tolerance`` for a rule built by ``bound_clause``."""
    if Operator.MUST_BE_BETWEEN.value in thresholds:
        lower, upper = thresholds[Operator.MUST_BE_BETWEEN.value]
        return {"lower_tolerance": _stored(lower), "upper_tolerance": _stored(upper)}
    if Operator.MUST_BE.value in thresholds:
        value = _stored(thresholds[Operator.MUST_BE.value])
        return {"lower_tolerance": value, "upper_tolerance": value}
    if Operator.MUST_BE_GREATER_OR_EQUAL_TO.value in thresholds:
        return {"lower_tolerance": _stored(thresholds[Operator.MUST_BE_GREATER_OR_EQUAL_TO.value])}
    if Operator.MUST_BE_LESS_OR_EQUAL_TO.value in thresholds:
        return {"upper_tolerance": _stored(thresholds[Operator.MUST_BE_LESS_OR_EQUAL_TO.value])}
    return {}


def _rule_parameters(
    rule: dict[str, Any],
    test_type: str,
    thresholds: dict[str, Any],
    arguments: dict[str, Any],
    conversion: dict[str, Any],
    subject: str | None,
    flavor: SqlFlavorCode,
) -> dict[str, Any]:
    """The term parameters ``rule`` was projected from -- the inverse of ``project_rule``.

    A ``custom`` rule carries them in its ``implementation``. Every other rule carries them in its
    bound, its arguments and its ``testgen`` conversion properties, as the type's own projection
    put them there.
    """
    if rule.get("type") == RuleShape.CUSTOM.value:
        parameters = dict(rule.get("implementation") or {})
        if test_type == "LOV_All" and not parameters.get("baseline_value"):
            parameters.update(_pipe_list_parameters(parameters.get("threshold_value")))
        return parameters

    bound = next(iter(thresholds.values()), None)
    if test_type == "SQL_Metric":
        return {"custom_query": conversion.get("queryTemplate", rule.get("query")), **_bounds_from(thresholds)}
    if test_type in ("Missing_Pct", "Row_Ct_Pct"):
        # A document may carry the ratio without the baseline counts; only the properties present are read.
        sources = (
            {"baseline_ct": "baselineCt", "baseline_value_ct": "baselineValueCt", "threshold_value": "thresholdBound"}
            if test_type == "Missing_Pct"
            else {"baseline_ct": "baselineCount", "threshold_value": "thresholdPercent"}
        )
        return {name: _stored(conversion[source]) for name, source in sources.items() if source in conversion}
    if test_type == "Dupe_Rows":
        # Quoted as generation stores them: a property name is the column's exact name.
        columns = arguments.get("properties") or ([subject] if subject else [])
        quote = get_flavor_service(FLAVOR_CODE_TO_FAMILY[flavor]).quote_character
        grouping = ", ".join(quote + str(column).replace(quote, quote * 2) + quote for column in columns)
        return {"groupby_names": grouping, "skip_errors": bound} if columns else {"skip_errors": bound}
    if test_type == "Match_Null_Ct":
        return {"baseline_ct": _stored(bound)}

    parameters = {"threshold_value": _stored(bound)}
    if test_type == "LOV_Match":
        parameters["baseline_value"] = format_value_list([_stored(value) for value in arguments.get("validValues") or []])
    elif test_type == "Pattern_Match":
        parameters["baseline_value"] = arguments.get("pattern")
    elif test_type == "Required_No_Placeholder" and arguments.get("missingValues"):
        parameters["baseline_value"] = format_value_list([_stored(value) for value in arguments["missingValues"]])
    elif test_type == "Constant":
        parameters["baseline_value"] = _constant_literal((arguments.get("validValues") or [None])[0])
    return parameters


# The fields each declaration type's marker must name -- Text_Length_Range names one or both.
_DECLARATION_PATHS: dict[str, frozenset[str]] = {
    "Min_Val": frozenset({"logicalTypeOptions.minimum"}),
    "Min_Date": frozenset({"logicalTypeOptions.minimum"}),
    "Max_Val": frozenset({"logicalTypeOptions.maximum"}),
    "Max_Date": frozenset({"logicalTypeOptions.maximum"}),
    "Text_Length_Range": frozenset({"logicalTypeOptions.minLength", "logicalTypeOptions.maxLength"}),
    "Unique": frozenset({"unique", "required"}),
    "Required": frozenset({"required"}),
}

_MARKER_IDENTITY_KEYS = frozenset({"id", "testType", "declares"})


def _field_at(prop: dict[str, Any], path: str) -> Any:
    node: Any = prop
    for key in path.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _declaration_parameters(test_type: str, declared: dict[str, Any]) -> dict[str, Any] | None:
    """The term parameters a declaration was projected from -- the inverse of
    ``property_declaration`` -- or ``None`` when the declared values are not ones it writes."""
    parameters: dict[str, Any] = {"threshold_value": "0"}
    if test_type in ("Unique", "Required"):
        return parameters if all(value is True for value in declared.values()) else None
    if test_type == "Text_Length_Range":
        for path, key in (
            ("logicalTypeOptions.minLength", "lower_tolerance"),
            ("logicalTypeOptions.maxLength", "upper_tolerance"),
        ):
            if path in declared:
                if not _is_integral(declared[path]):
                    return None
                parameters[key] = _stored(declared[path])
        return parameters
    (value,) = declared.values()
    if isinstance(value, date):
        # An unquoted date in YAML loads as a date, not as the string the projection wrote.
        value = value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    parameters["baseline_value"] = _stored(value)
    return parameters


def resolve_declarations(prop: dict[str, Any], known_test_types: frozenset[str]) -> list[ResolvedTerm]:
    """The terms rendered as declarations on the schema property ``prop``.

    Read from the property's ``testgenTerm`` entries (``declaration_marker``), each naming its
    term's id, test type and declared fields; the declared values are read from the property
    itself. An entry naming a type that is not a declaration type or not in
    ``known_test_types``, a field its type does not declare, or a field the property does not
    carry, resolves to nothing. A declaration no entry names -- one the stored metadata
    carries, or another tool wrote -- also resolves to nothing here.
    """
    return [
        term
        for entry in prop.get("customProperties") or []
        if (term := _resolve_declaration_marker(prop, entry, known_test_types)) is not None
    ]


def _resolve_declaration_marker(
    prop: dict[str, Any], entry: object, known_test_types: frozenset[str]
) -> ResolvedTerm | None:
    """The term the ``testgenTerm`` entry ``entry`` on ``prop`` names, or ``None`` when it is not
    one or does not resolve."""
    if not is_declaration_marker(entry) or not isinstance(entry.get("value"), dict):
        return None
    value = entry["value"]
    test_type, term_id, paths = value.get("testType"), value.get("id"), value.get("declares")
    if (
        not isinstance(test_type, str)
        or not isinstance(paths, list)
        or not all(isinstance(path, str) for path in paths)
        or test_type not in _DECLARATION_PATHS
        or test_type not in known_test_types
        or not isinstance(term_id, str)
        or not isinstance(paths, list)
        or not paths
        or not set(paths) <= _DECLARATION_PATHS[test_type]
        or (test_type != "Text_Length_Range" and set(paths) != _DECLARATION_PATHS[test_type])
    ):
        return None
    declared = {path: _field_at(prop, path) for path in paths}
    if any(declared_value is None for declared_value in declared.values()):
        return None
    parameters = _declaration_parameters(test_type, declared)
    if parameters is None:
        return None
    return ResolvedTerm(
        test_type=test_type,
        thresholds={},
        arguments={},
        conversion={},
        parameters=parameters,
        contract_term_id=term_id,
        metadata={key: item for key, item in value.items() if key not in _MARKER_IDENTITY_KEYS},
    )


# `logicalTypeOptions` keys that constrain a value. A declared one that no test type checks
# exactly is reported as unresolved; the remaining keys (`timezone`, embedding settings, ...)
# describe the value rather than constrain it.
_CONSTRAINT_OPTIONS = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength",
    "pattern", "format", "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties",
})

# The bound each `logicalType` declares exactly, and the test type that checks it.
_UNNAMED_BOUNDS: dict[str, dict[str, str]] = {
    "integer": {"minimum": "Min_Val", "maximum": "Max_Val"},
    "number": {"minimum": "Min_Val", "maximum": "Max_Val"},
    "date": {"minimum": "Min_Date", "maximum": "Max_Date"},
    "timestamp": {"minimum": "Min_Date", "maximum": "Max_Date"},
}


@dataclass(frozen=True)
class UnnamedDeclarations:
    """The terms a property's unnamed declarations resolve to, the declared paths none does, the
    declared paths a term owns: those a resolving ``testgenTerm`` entry names or an unnamed
    declaration resolved from, and the paths each term's test type resolved from."""

    terms: list[ResolvedTerm]
    unresolved: list[str]
    owned: list[str]
    declares: dict[str, list[str]]


def resolve_unnamed_declarations(prop: dict[str, Any], known_test_types: frozenset[str]) -> UnnamedDeclarations:
    """The terms checking the declarations on ``prop`` that no resolving ``testgenTerm`` entry names.

    Each resolves at a threshold of 0, since a declaration asserts every value of the column,
    and carries no term id. ``minimum`` and ``maximum`` resolve to ``Min_Val``/``Max_Val`` on an
    integer or number property and ``Min_Date``/``Max_Date`` on a date or timestamp property;
    ``minLength`` and ``maxLength`` on a string property resolve together to ``Text_Length_Range``;
    ``unique`` with ``required`` resolves to ``Unique`` and ``required`` alone to ``Required``.
    Every other declared constraint -- ``unique`` alone, an exclusive bound, a pattern or format,
    a bound on another logical type, or a value that is not one the test type stores -- is listed
    in ``unresolved`` and resolves to nothing. ``owned`` lists every declared path a term checks:
    those a resolving ``testgenTerm`` entry names and those resolved here.
    """
    named = {
        path
        for entry in prop.get("customProperties") or []
        if _resolve_declaration_marker(prop, entry, known_test_types) is not None
        for path in entry["value"]["declares"]
    }

    logical_type = prop.get("logicalType")
    options = prop.get("logicalTypeOptions") if isinstance(prop.get("logicalTypeOptions"), dict) else {}
    declared = {
        f"logicalTypeOptions.{key}": value
        for key, value in options.items()
        if key in _CONSTRAINT_OPTIONS and value is not None
    }
    for flag in ("unique", "required"):
        if prop.get(flag) is True:
            declared[flag] = True
    pending = {path: value for path, value in declared.items() if path not in named}

    terms: list[ResolvedTerm] = []
    owned = set(named)
    declares: dict[str, list[str]] = {}

    def take(test_type: str, paths: list[str]) -> None:
        if test_type not in known_test_types:
            return
        parameters = _declaration_parameters(test_type, {path: pending[path] for path in paths})
        if test_type in ("Min_Val", "Max_Val") and not all(_is_number(pending[path]) for path in paths):
            parameters = None
        if test_type in ("Min_Date", "Max_Date") and not all(isinstance(pending[path], date | str) for path in paths):
            parameters = None
        if parameters is None:
            return
        terms.append(ResolvedTerm(
            test_type=test_type, thresholds={}, arguments={}, conversion={}, parameters=parameters,
        ))
        declares[test_type] = paths
        for path in paths:
            del pending[path]
            owned.add(path)

    for option, test_type in _UNNAMED_BOUNDS.get(logical_type, {}).items():
        path = f"logicalTypeOptions.{option}"
        if path in pending:
            take(test_type, [path])
    if logical_type == "string":
        if length_paths := [
            path for path in ("logicalTypeOptions.minLength", "logicalTypeOptions.maxLength") if path in pending
        ]:
            take("Text_Length_Range", length_paths)
    if "unique" in pending and "required" in pending:
        take("Unique", ["unique", "required"])
    elif "required" in pending and "unique" not in named:
        take("Required", ["required"])

    return UnnamedDeclarations(terms=terms, unresolved=sorted(pending), owned=sorted(owned), declares=declares)


# The `testgen` property marking a quality rule this engine cannot check: it stays in the
# contract's document, and nothing runs it.
_UNVERIFIABLE_MARKER = {"property": "verifiable", "value": False, "vendor": "testgen"}


def mark_unverifiable(rule: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``rule`` carrying the ``testgen`` unverifiable marker once."""
    marked = dict(rule)
    entries = [entry for entry in rule.get("customProperties") or [] if not is_unverifiable_marker(entry)]
    marked["customProperties"] = [*entries, dict(_UNVERIFIABLE_MARKER)]
    return marked


def is_unverifiable_marker(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("vendor") == "testgen"
        and entry.get("property") == _UNVERIFIABLE_MARKER["property"]
    )


# The `testgen` property marking a schema property the renderer made up to carry a column-scoped
# rule whose subject (an expression, or a column the document does not declare) has no property.
_SYNTHESIZED_MARKER = {"property": "synthesized", "value": True, "vendor": "testgen"}


def synthesized_marker() -> dict[str, Any]:
    return dict(_SYNTHESIZED_MARKER)


def is_synthesized_property(prop: dict[str, Any]) -> bool:
    return any(
        isinstance(entry, dict)
        and entry.get("vendor") == "testgen"
        and entry.get("property") == _SYNTHESIZED_MARKER["property"]
        for entry in prop.get("customProperties") or []
    )


def drop_field(node: dict[str, Any], path: list[str]) -> None:
    """Remove the field at ``path`` under ``node``, and a parent object it leaves empty."""
    if len(path) == 1:
        node.pop(path[0], None)
        return
    child = node.get(path[0])
    if isinstance(child, dict):
        drop_field(child, path[1:])
        if not child:
            del node[path[0]]
