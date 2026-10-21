import pytest

from testgen.common.flavors import SqlFlavorCode
from testgen.common.models.test_definition import NON_PUBLIC_TEST_TYPES, TestDefinition, TestType
from testgen.common.odcs.quality_rules import (
    RULE_MAPPINGS,
    RuleMapping,
    RuleScope,
    RuleShape,
    drop_generated_metadata,
    is_unverifiable_marker,
    mark_unverifiable,
    project_rule,
    resolve_declarations,
    resolve_rule,
    resolve_unnamed_declarations,
    rule_scope,
)
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND
from testgen.common.odcs.validation import validate_document

pytestmark = pytest.mark.unit

# The test types tier 2 (the exact-equivalence table) resolves an unmarked rule onto.
_TIER_TWO_TARGETS = frozenset({"Required", "Row_Ct", "LOV_Match", "Pattern_Match", "Match_Null_Ct", "Match_Row_Ct"})

_KNOWN = frozenset({"Required", "Row_Ct", "LOV_Match", "Pattern_Match", "Avg_Shift", "Unique", "Missing_Pct", "CUSTOM"})


def _wrap(rule: dict, scope: RuleScope) -> dict:
    """A minimal ODCS document carrying ``rule`` at the node its scope implies -- confirms a
    fixture used to exercise ``resolve_rule`` is itself legal ODCS, not just a shape invented
    to make the resolver's decision table easy to hit."""
    table = {"name": "customers"}
    if scope is RuleScope.COLUMN:
        table["properties"] = [{"name": "email", "quality": [rule]}]
    else:
        table["quality"] = [rule]
    return {
        "version": "1.0.0",
        "apiVersion": ODCS_API_VERSION,
        "kind": ODCS_KIND,
        "id": "contract-1",
        "schema": [table],
    }


def _term(**overrides) -> TestDefinition:
    defaults = {
        "test_type": "Required",
        "contract_term_id": "term-1",
        "column_name": "email",
        "table_name": "customers",
        "schema_name": "public",
        "threshold_value": "3",
        "baseline_ct": "1000",
        "baseline_value_ct": "950",
        "baseline_unique_ct": "900",
    }
    defaults.update(overrides)
    return TestDefinition(**defaults)


def _test_type(test_type_code: str, **overrides) -> TestType:
    defaults = {
        "test_type": test_type_code,
        "dq_dimension": "Validity",
        "test_name_short": "",
        "test_name_long": "",
    }
    defaults.update(overrides)
    return TestType(**defaults)


def _rule_from(mapping: RuleMapping) -> tuple[dict, TestDefinition]:
    """A real ``project_rule`` output for ``mapping``'s test type, and the term it was built
    from -- not a rule assembled by hand from the mapping's own fields, since ``project_rule``
    is what stamps the ``testType`` marker every real TestGen-authored rule carries. Feeding
    that rule back through ``resolve_rule`` is what the round-trip coverage test below
    exercises; the term is returned alongside it so that test can also check ``ResolvedTerm``
    against the term's own stored values, not just its test type.
    """
    argument_value = None
    logical_type = None
    if mapping.test_type == "Constant":
        argument_value, logical_type = "'Y'", "string"
    elif mapping.argument is not None and mapping.argument.name == "missingValues":
        argument_value = '"",N/A'
    elif mapping.argument is not None and mapping.argument.name == "validValues":
        argument_value = "('Y','N')"
    elif mapping.argument is not None and mapping.argument.name == "pattern":
        argument_value = "[A-Z]{3}"
    term = _term(
        test_type=mapping.test_type,
        column_name=None if mapping.scope is RuleScope.TABLE else "email",
        baseline_value=argument_value,
        contract_term_id=f"term-{mapping.test_type}",
    )
    return project_rule(term, _test_type(mapping.test_type), SqlFlavorCode.POSTGRESQL, logical_type=logical_type), term


def _pending_rule(test_type_code: str) -> dict:
    """A real ``project_rule`` output for a routing-deferred type -- the ``text`` rule the
    renderer writes for it, marker and all, rather than one assembled by hand."""
    term = _term(test_type=test_type_code, column_name=None, contract_term_id=f"term-{test_type_code}")
    return project_rule(term, _test_type(test_type_code), SqlFlavorCode.POSTGRESQL)


def _without_marker(rule: dict) -> dict:
    """``rule`` with its ``testType`` marker customProperty removed -- forces resolution
    through tier 2 (the exact-equivalence table) rather than tier 1 (the marker), so a test
    against the stripped rule actually exercises the table instead of short-circuiting past
    it."""
    properties = [
        entry
        for entry in rule.get("customProperties", [])
        if not (isinstance(entry, dict) and entry.get("vendor") == "testgen" and entry.get("property") == "testType")
    ]
    return {**rule, "customProperties": properties}


def test_the_testgen_marker_is_honoured_before_the_table():
    # Unit "percent" would decline under the table on its own -- no TestGen type computes a
    # plain proportion -- but the marker is the round-trip case and resolves regardless.
    rule = {
        "metric": "nullValues",
        "unit": "percent",
        "mustBeBetween": [1, 2],
        "customProperties": [{"property": "testType", "value": "Missing_Pct", "vendor": "testgen"}],
    }
    resolved = resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "Missing_Pct"
    assert resolved.thresholds == {"mustBeBetween": [1, 2]}
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_marker_naming_an_unknown_test_type_resolves_to_unverifiable():
    # test_type is a primary key with a foreign key from test_results -- a stale marker from
    # a renamed or removed type must not resolve silently.
    rule = {
        "metric": "nullValues",
        "unit": "rows",
        "mustBeLessOrEqualTo": 5,
        "customProperties": [{"property": "testType", "value": "Not_A_Real_Test_Type", "vendor": "testgen"}],
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_marker_whose_bound_does_not_match_its_types_own_operator_resolves_to_unverifiable():
    # Required only ever renders mustBeLessOrEqualTo -- a marker claiming Required alongside
    # a different operator is not this type's own shape, even though the marker names it.
    rule = {
        "metric": "nullValues",
        "unit": "rows",
        "mustBeBetween": [1, 2],
        "customProperties": [{"property": "testType", "value": "Required", "vendor": "testgen"}],
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_marker_carrying_two_operators_at_once_resolves_to_unverifiable():
    # Tier 1 must be at least as strict as tier 2 about rule well-formedness: the marker says
    # which type, not that the rest of the rule is a coherent single claim.
    rule = {
        "metric": "nullValues",
        "unit": "rows",
        "mustBeLessOrEqualTo": 5,
        "mustBeBetween": [1, 2],
        "customProperties": [{"property": "testType", "value": "Required", "vendor": "testgen"}],
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_marker_carrying_both_valid_values_and_a_pattern_resolves_to_unverifiable():
    # LOV_Match's mapping declares the `validValues` argument -- a marker naming it alongside
    # a rule that (like tier 2's own equivalent case) cannot tell validValues from pattern
    # must not resolve just because the marker names a type.
    rule = {
        "metric": "invalidValues",
        "unit": "rows",
        "mustBeLessOrEqualTo": 0,
        "arguments": {"validValues": ["Y", "N"], "pattern": "[A-Z]"},
        "customProperties": [{"property": "testType", "value": "LOV_Match", "vendor": "testgen"}],
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_routed_types_marker_resolves_on_its_own_node_and_declines_on_the_other():
    # The marker says which type, not where the rule is allowed to sit. Required is
    # COLUMN-scoped, so the same projected rule presented as a table-node rule is not this
    # type's own shape -- tier 1 refuses it exactly as tier 2 refuses a metric on the wrong
    # scope.
    rule, _ = _rule_from(RULE_MAPPINGS["Required"])
    resolved = resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "Required"
    assert resolve_rule(rule, RuleScope.TABLE, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_marker_for_a_custom_routed_type_resolves_on_its_declared_node():
    rule = _pending_rule("CUSTOM")
    resolved = resolve_rule(rule, RuleScope.TABLE, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "CUSTOM"


def test_a_marker_naming_a_non_public_type_declines_and_does_not_raise():
    """A ``NON_PUBLIC_TEST_TYPES`` member is in the catalogue, so a marker naming one passes
    the membership check and reaches the scope lookup with nothing declared. Resolution
    answers a rule it cannot place by declining it: an incoming document is a counterparty's,
    and failing the import over one is not this path's to do. (``rule_scope`` raises on
    the same input, for the rendering path, where such a term is our own inconsistency.)
    """
    known = NON_PUBLIC_TEST_TYPES
    for test_type_code in NON_PUBLIC_TEST_TYPES:
        rule = {
            "type": "text",
            "customProperties": [{"property": "testType", "value": test_type_code, "vendor": "testgen"}],
        }
        assert resolve_rule(rule, RuleScope.TABLE, known, flavor=SqlFlavorCode.POSTGRESQL) is None
        assert resolve_rule(rule, RuleScope.COLUMN, known, flavor=SqlFlavorCode.POSTGRESQL) is None


@pytest.mark.parametrize(
    ("test_type", "scope", "overrides"),
    [
        ("Row_Ct_Pct", RuleScope.TABLE, {"baseline_ct": "100", "threshold_value": "0", "column_name": None}),
        ("Missing_Pct", RuleScope.COLUMN, {"baseline_ct": "100", "baseline_value_ct": "95", "threshold_value": "0"}),
    ],
)
def test_a_collapsed_band_resolves_back_to_the_type_that_rendered_it(test_type, scope, overrides):
    """A band whose bounds coincide renders ``mustBe``, because ``mustBeBetween`` requires two
    unique items. It is still a rule TestGen projected, so declining it would break the round
    trip on exactly the terms that allow no drift at all."""
    term = _term(test_type=test_type, **overrides)
    rule = project_rule(term, _test_type(test_type), SqlFlavorCode.POSTGRESQL)
    assert "mustBe" in rule, "bound_clause no longer collapses equal bounds; this case is moot"

    resolved = resolve_rule(rule, scope, _KNOWN | {test_type}, flavor=SqlFlavorCode.POSTGRESQL)

    assert resolved is not None, f"a projected {test_type} rule was declined by the resolver"
    assert resolved.test_type == test_type


def test_a_marker_carrying_a_conversion_band_surfaces_it_for_reconstruction():
    # _conversion_properties' own docstring says these exist so the term is recoverable
    # exactly from the rendered rule alone -- resolve_rule must actually read them back, not
    # just carry the rendered (lossy) band forward in thresholds.
    rule = {
        "metric": "nullValues",
        "unit": "percent",
        "mustBeBetween": [91.47, 97.63],
        "customProperties": [
            {"property": "testType", "value": "Missing_Pct", "vendor": "testgen"},
            {"property": "baselineRatio", "value": 0.95, "vendor": "testgen"},
            {"property": "thresholdBound", "value": 3.0, "vendor": "testgen"},
        ],
    }
    resolved = resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.conversion == {"baselineRatio": 0.95, "thresholdBound": 3.0}


def test_a_rule_with_no_conversion_properties_surfaces_an_empty_conversion():
    rule = {"metric": "nullValues", "unit": "rows", "mustBeLessOrEqualTo": 5}
    resolved = resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.conversion == {}


def test_a_null_values_rule_in_rows_resolves_to_required():
    rule = {"metric": "nullValues", "unit": "rows", "mustBeLessOrEqualTo": 5}
    resolved = resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "Required"
    assert resolved.thresholds == {"mustBeLessOrEqualTo": 5}
    assert resolved.arguments == {}


def test_a_null_values_rule_in_percent_is_declined_not_defaulted_to_missing_pct():
    # This is the mirror of the brief's own framing: no TestGen type computes a plain
    # proportion, so nullValues/percent has no equivalent at all. Resolving it onto
    # Missing_Pct would assert a Cohen's h drift bound the contract never stated.
    rule = {"metric": "nullValues", "unit": "percent", "mustBeBetween": [1, 2]}
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_an_unrecognised_unit_resolves_to_unverifiable_and_is_not_defaulted_to_rows():
    assert resolve_rule({"metric": "nullValues", "unit": "percentage", "mustBe": 0}, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


@pytest.mark.parametrize("rule, scope, known, expected", [
    ({"metric": "nullValues", "mustBe": 0}, RuleScope.COLUMN, _KNOWN, "Required"),
    ({"metric": "rowCount", "mustBeGreaterThan": 100}, RuleScope.TABLE, _KNOWN, "Row_Ct"),
    ({"metric": "invalidValues", "arguments": {"validValues": ["A", "B"]}, "mustBe": 0}, RuleScope.COLUMN, _KNOWN, "LOV_Match"),
    (
        {"metric": "duplicateValues", "arguments": {"properties": ["order_id"]}, "mustBe": 0},
        RuleScope.TABLE, frozenset({"Dupe_Rows"}), "Dupe_Rows",
    ),
])
def test_a_rule_without_a_unit_counts_rows(rule, scope, known, expected):
    resolved = resolve_rule(rule, scope, known, "email", flavor=SqlFlavorCode.POSTGRESQL, table_name="customers")

    assert resolved is not None
    assert resolved.test_type == expected


def test_a_row_based_duplicate_values_rule_resolves_by_scope():
    # Neither destination is implemented -- Unique is deliberately held back (its measure
    # counts NULLs as duplicates) and Dupe_Rows has no decided threshold shape -- so a
    # duplicateValues/rows rule declines on both nodes rather than a (metric, unit) key
    # picking one of the two test types and being wrong for the other.
    rule = {"metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0}
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None
    assert resolve_rule(rule, RuleScope.TABLE, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_rule_carrying_both_valid_values_and_a_pattern_resolves_to_unverifiable():
    rule = {
        "metric": "invalidValues",
        "unit": "rows",
        "mustBeLessOrEqualTo": 0,
        "arguments": {"validValues": ["Y", "N"], "pattern": "[A-Z]"},
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_an_invalid_values_rule_with_an_unrecognised_argument_resolves_to_unverifiable():
    # A recognised argument (validValues) is present alongside the stray one -- if only the
    # stray key were there, the rule would already decline via "neither argument present",
    # never exercising the unrecognised-argument branch this test is for.
    rule = {
        "metric": "invalidValues",
        "unit": "rows",
        "mustBeLessOrEqualTo": 0,
        "arguments": {"validValues": ["Y", "N"], "somethingElse": True},
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_metric_on_the_wrong_scope_resolves_to_unverifiable():
    # rowCount on a column node validates against the schema and means nothing -- Row_Ct is
    # a table-scoped test type, so a caller that knows the rule sits on a column node must
    # not get a resolution back.
    rule = {"metric": "rowCount", "unit": "rows", "mustBeGreaterOrEqualTo": 100}
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None
    resolved = resolve_rule(rule, RuleScope.TABLE, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "Row_Ct"


def test_the_operator_is_part_of_the_key():
    # mustNotBe: 0 and mustBeGreaterThan: 0 are not upper bounds on the null count, so neither resolves
    # onto Required.
    base = {"metric": "nullValues", "unit": "rows"}
    assert resolve_rule({**base, "mustNotBe": 0}, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None
    assert resolve_rule(
        {**base, "mustBeGreaterThan": 0}, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL
    ) is None
    assert resolve_rule({**base, "mustBeLessOrEqualTo": 0}, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is not None


@pytest.mark.parametrize(
    ("rule", "test_type", "thresholds"),
    [
        ({"metric": "nullValues", "mustBe": 0}, "Required", {"mustBeLessOrEqualTo": 0}),
        ({"metric": "nullValues", "mustBeLessThan": 5}, "Required", {"mustBeLessOrEqualTo": 4}),
        ({"metric": "nullValues", "mustBe": 3}, "Match_Null_Ct", {"mustBe": 3}),
        (
            {"metric": "invalidValues", "arguments": {"validValues": ["a", "b"]}, "mustBe": 0},
            "LOV_Match", {"mustBeLessOrEqualTo": 0},
        ),
        (
            {"metric": "invalidValues", "arguments": {"pattern": "^[0-9]+$"}, "mustBeLessThan": 1},
            "Pattern_Match", {"mustBeLessOrEqualTo": 0},
        ),
    ],
)
def test_a_bound_on_a_column_count_resolves_onto_the_test_that_states_the_same_check(rule, test_type, thresholds):
    known = _KNOWN | {"Match_Null_Ct"}
    resolved = resolve_rule(
        {**rule, "unit": "rows"}, RuleScope.COLUMN, known, "email", flavor=SqlFlavorCode.POSTGRESQL
    )

    assert (resolved.test_type, resolved.thresholds) == (test_type, thresholds)


def test_an_exact_row_count_resolves_onto_match_row_count():
    rule = {"metric": "rowCount", "unit": "rows", "mustBe": 500}
    resolved = resolve_rule(rule, RuleScope.TABLE, _KNOWN | {"Match_Row_Ct"}, flavor=SqlFlavorCode.POSTGRESQL)

    assert (resolved.test_type, resolved.thresholds) == ("Match_Row_Ct", {"mustBe": 500})


def test_a_strict_row_count_bound_is_reexpressed_as_the_next_integer():
    # rowCount counts rows -- always integral -- so re-expressing a strict lower bound as
    # the inclusive one is sound (unlike doing the same over a float-valued measure).
    rule = {"metric": "rowCount", "unit": "rows", "mustBeGreaterThan": 100}
    resolved = resolve_rule(rule, RuleScope.TABLE, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "Row_Ct"
    assert resolved.thresholds == {"mustBeGreaterOrEqualTo": 101}


def test_a_text_rule_always_resolves_to_unverifiable():
    rule = {"type": "text", "description": "Some free text quality expectation."}
    assert resolve_rule(rule, RuleScope.TABLE, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_custom_rule_always_resolves_to_unverifiable():
    rule = {"type": "custom", "engine": "soda", "implementation": "checks for tables:\n  - name: x"}
    assert resolve_rule(rule, RuleScope.TABLE, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def _testgen_custom_rule(**overrides) -> dict:
    rule = {
        "type": "custom", "engine": "testgen", "implementation": {"threshold_value": "2"},
        "customProperties": [{"property": "testType", "value": "Avg_Shift", "vendor": "testgen"}],
    }
    rule.update(overrides)
    return rule


def test_a_custom_rule_for_another_engine_with_a_testgen_marker_is_unverifiable():
    rule = _testgen_custom_rule(engine="soda")
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, "email", flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_testgen_custom_rule_with_a_parameter_its_type_does_not_take_is_unverifiable():
    rule = _testgen_custom_rule(implementation={"threshold_value": "2", "custom_query": "SELECT 1"})
    declared = {"Avg_Shift": frozenset({"threshold_value", "baseline_avg"})}

    assert resolve_rule(
        rule, RuleScope.COLUMN, _KNOWN, "email", flavor=SqlFlavorCode.POSTGRESQL, declared_parameters=declared
    ) is None


def test_a_testgen_custom_rule_with_its_types_parameters_resolves():
    declared = {"Avg_Shift": frozenset({"threshold_value", "baseline_avg"})}

    resolved = resolve_rule(
        _testgen_custom_rule(), RuleScope.COLUMN, _KNOWN, "email",
        flavor=SqlFlavorCode.POSTGRESQL, declared_parameters=declared,
    )

    assert resolved.test_type == "Avg_Shift"
    assert resolved.parameters == {"threshold_value": "2"}


def test_a_custom_rules_catalog_name_is_dropped_but_a_users_name_is_kept():
    test_type = _test_type("Avg_Shift", test_name_short="Average Shift", test_name_long="Column mean shift")

    assert drop_generated_metadata({"name": "Column mean shift", "tags": ["a"]}, test_type, {}, custom=True) == {
        "tags": ["a"]
    }
    assert drop_generated_metadata({"name": "Mean of order totals"}, test_type, {}, custom=True) == {
        "name": "Mean of order totals"
    }
    assert drop_generated_metadata({"name": "Column mean shift"}, test_type, {}, custom=False) == {
        "name": "Column mean shift"
    }


def test_a_custom_rules_generated_description_is_dropped_but_a_users_description_is_kept():
    test_type = _test_type(
        "Avg_Shift", test_description="Checks the mean.", threshold_description="standard deviations"
    )
    rule = project_rule(_term(test_type="Avg_Shift", threshold_value="2"), test_type, SqlFlavorCode.POSTGRESQL)
    generated = {"description": rule["description"]}

    assert drop_generated_metadata(generated, test_type, {"threshold_value": "2"}, custom=True) == {}
    assert drop_generated_metadata(
        {"description": "Spend per order stays stable."}, test_type, {"threshold_value": "2"}, custom=True
    ) == {"description": "Spend per order stays stable."}


def test_the_dimension_a_test_type_renders_with_is_dropped_but_another_is_kept():
    test_type = _test_type("Required", dq_dimension="Completeness")

    assert drop_generated_metadata({"dimension": "completeness"}, test_type, {}, custom=False) == {}
    assert drop_generated_metadata({"dimension": "accuracy"}, test_type, {}, custom=False) == {"dimension": "accuracy"}


@pytest.mark.parametrize(("rule", "groupby"), [
    ({"metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0}, '"email"'),
    ({"metric": "duplicateValues", "unit": "rows", "mustBeLessThan": 3}, '"email"'),
    ({"metric": "duplicateValues", "unit": "rows", "mustBe": 0}, '"email"'),
])
def test_a_column_duplicate_values_rule_groups_dupe_rows_on_its_column(rule, groupby):
    resolved = resolve_rule(rule, RuleScope.COLUMN, frozenset({"Dupe_Rows"}), "email", flavor=SqlFlavorCode.POSTGRESQL)

    assert resolved.test_type == "Dupe_Rows"
    assert resolved.parameters["groupby_names"] == groupby
    assert resolved.thresholds.keys() == {"mustBeLessOrEqualTo"}


def test_a_column_duplicate_values_rule_never_resolves_to_unique():
    rule = {"metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0}
    resolved = resolve_rule(rule, RuleScope.COLUMN, _KNOWN | {"Dupe_Rows"}, "email", flavor=SqlFlavorCode.POSTGRESQL)

    assert resolved.test_type == "Dupe_Rows"


def test_a_table_duplicate_values_rule_groups_on_its_listed_properties():
    rule = {
        "metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0,
        "arguments": {"properties": ["order_id", "line_no"]},
    }
    resolved = resolve_rule(rule, RuleScope.TABLE, frozenset({"Dupe_Rows"}), flavor=SqlFlavorCode.POSTGRESQL)

    assert resolved.parameters["groupby_names"] == '"order_id", "line_no"'


@pytest.mark.parametrize("rule", [
    {"metric": "duplicateValues", "unit": "percent", "mustBeLessOrEqualTo": 0},
    {"metric": "duplicateValues", "unit": "rows", "mustBeGreaterThan": 0},
    {"metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0.5},
])
def test_a_column_duplicate_values_rule_with_no_exact_test_type_is_unverifiable(rule):
    resolved = resolve_rule(rule, RuleScope.COLUMN, frozenset({"Dupe_Rows"}), "email", flavor=SqlFlavorCode.POSTGRESQL)

    assert resolved is None


def test_a_table_duplicate_values_rule_listing_no_properties_is_unverifiable():
    rule = {"metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0}
    assert resolve_rule(rule, RuleScope.TABLE, frozenset({"Dupe_Rows"}), flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_single_value_sql_rule_resolves_to_sql_metric_with_its_placeholders_substituted():
    rule = {
        "id": "orders-total", "type": "sql", "query": "SELECT SUM({property}) FROM {object}",
        "mustBeBetween": [0, 1000], "name": "Order total",
    }

    resolved = resolve_rule(
        rule, RuleScope.COLUMN, frozenset(), "amount", flavor=SqlFlavorCode.POSTGRESQL, table_name="orders"
    )

    assert resolved.test_type == "SQL_Metric"
    assert resolved.parameters == {
        "custom_query": 'SELECT SUM("amount") FROM {DATA_SCHEMA}."orders"',
        "lower_tolerance": "0",
        "upper_tolerance": "1000",
    }
    assert resolved.contract_term_id == "orders-total"
    assert resolved.metadata == {"name": "Order total"}


def test_a_sql_rule_reads_dollar_placeholders_as_its_placeholders():
    rule = {"type": "sql", "query": "SELECT SUM(${property}) FROM ${object}", "mustBeBetween": [0, 1000]}

    resolved = resolve_rule(
        rule, RuleScope.COLUMN, frozenset(), "amount", flavor=SqlFlavorCode.POSTGRESQL, table_name="orders"
    )

    assert resolved.parameters["custom_query"] == 'SELECT SUM("amount") FROM {DATA_SCHEMA}."orders"'


def test_a_sql_rule_quotes_identifiers_the_way_its_flavor_does():
    rule = {"type": "sql", "query": "SELECT COUNT(*) FROM {object}", "mustBeGreaterOrEqualTo": 1}

    resolved = resolve_rule(rule, RuleScope.TABLE, frozenset(), flavor=SqlFlavorCode.BIGQUERY, table_name="orders")

    assert resolved.parameters == {
        "custom_query": "SELECT COUNT(*) FROM {DATA_SCHEMA}.`orders`", "lower_tolerance": "1",
    }


@pytest.mark.parametrize("rule", [
    {"type": "sql", "query": "SELECT COUNT(*) FROM {object}", "mustBeGreaterThan": 0},
    {"type": "sql", "query": "SELECT COUNT(*) FROM {object}", "mustNotBe": 0},
    {"type": "sql", "query": "SELECT COUNT(*) FROM t"},
    {"type": "sql", "query": "SELECT MAX({property}) FROM t", "mustBe": 1},
])
def test_a_sql_rule_sql_metric_cannot_state_is_unverifiable(rule):
    assert resolve_rule(rule, RuleScope.TABLE, frozenset(), flavor=SqlFlavorCode.POSTGRESQL, table_name="t") is None


def _prop(**fields) -> dict:
    return {"name": "c", **fields}


@pytest.mark.parametrize(("prop", "expected"), [
    (
        _prop(logicalType="integer", logicalTypeOptions={"maximum": 100}),
        [("Max_Val", {"threshold_value": "0", "baseline_value": "100"})],
    ),
    (
        _prop(logicalType="date", logicalTypeOptions={"minimum": "2020-01-01"}),
        [("Min_Date", {"threshold_value": "0", "baseline_value": "2020-01-01"})],
    ),
    (
        _prop(logicalType="string", logicalTypeOptions={"minLength": 2, "maxLength": 10}),
        [("Text_Length_Range", {"threshold_value": "0", "lower_tolerance": "2", "upper_tolerance": "10"})],
    ),
    (_prop(logicalType="string", unique=True, required=True), [("Unique", {"threshold_value": "0"})]),
    (_prop(logicalType="string", required=True), [("Required", {"threshold_value": "0"})]),
])
def test_an_unnamed_declaration_resolves_to_the_test_type_checking_exactly_it(prop, expected):
    known = frozenset({"Max_Val", "Min_Date", "Text_Length_Range", "Unique", "Required"})

    result = resolve_unnamed_declarations(prop, known)

    assert [(term.test_type, term.parameters) for term in result.terms] == expected
    assert all(term.contract_term_id is None for term in result.terms)
    assert result.unresolved == []


@pytest.mark.parametrize(("prop", "unresolved"), [
    (_prop(logicalType="string", unique=True), ["unique"]),
    (_prop(logicalType="integer", logicalTypeOptions={"exclusiveMaximum": 5}), ["logicalTypeOptions.exclusiveMaximum"]),
    (_prop(logicalType="string", logicalTypeOptions={"pattern": "^a"}), ["logicalTypeOptions.pattern"]),
    (_prop(logicalType="string", logicalTypeOptions={"maximum": 5}), ["logicalTypeOptions.maximum"]),
    (_prop(logicalType="integer", logicalTypeOptions={"maximum": "high"}), ["logicalTypeOptions.maximum"]),
])
def test_a_declaration_with_no_exact_test_type_is_reported_and_creates_no_term(prop, unresolved):
    known = frozenset({"Max_Val", "Unique", "Required"})

    result = resolve_unnamed_declarations(prop, known)

    assert result.terms == []
    assert result.unresolved == unresolved


def test_a_declaration_a_testgen_entry_names_is_left_to_that_entry():
    prop = _prop(
        logicalType="integer", logicalTypeOptions={"maximum": 100, "minimum": 1},
        customProperties=[{
            "property": "testgenTerm", "vendor": "testgen",
            "value": {"id": "c-max", "testType": "Max_Val", "declares": ["logicalTypeOptions.maximum"]},
        }],
    )

    result = resolve_unnamed_declarations(prop, frozenset({"Max_Val", "Min_Val"}))

    assert [term.test_type for term in result.terms] == ["Min_Val"]


@pytest.mark.parametrize(("prop", "expected_terms", "unresolved"), [
    (
        _prop(logicalType="string", unique=False, required=True, customProperties=[{
            "property": "testgenTerm", "vendor": "testgen",
            "value": {"id": "c-unique", "testType": "Unique", "declares": ["unique", "required"]},
        }]),
        ["Required"],
        [],
    ),
    (
        _prop(logicalType="string", logicalTypeOptions={"minLength": 1.5}, customProperties=[{
            "property": "testgenTerm", "vendor": "testgen",
            "value": {"id": "c-len", "testType": "Text_Length_Range", "declares": ["logicalTypeOptions.minLength"]},
        }]),
        [],
        ["logicalTypeOptions.minLength"],
    ),
])
def test_a_declaration_whose_entry_no_longer_resolves_is_resolved_unnamed(prop, expected_terms, unresolved):
    result = resolve_unnamed_declarations(prop, frozenset({"Unique", "Required", "Text_Length_Range"}))

    assert [term.test_type for term in result.terms] == expected_terms
    assert result.unresolved == unresolved


@pytest.mark.parametrize("value", [
    {"id": "c-unique", "testType": ["Unique"], "declares": ["unique", "required"]},
    {"id": "c-unique", "testType": "Unique", "declares": [["unique"], "required"]},
], ids=["list_test_type", "list_path"])
def test_a_malformed_testgen_entry_resolves_to_nothing(value):
    prop = _prop(logicalType="string", unique=True, required=True, customProperties=[
        {"property": "testgenTerm", "vendor": "testgen", "value": value},
    ])

    assert resolve_declarations(prop, frozenset({"Unique"})) == []
    assert [term.test_type for term in resolve_unnamed_declarations(prop, frozenset({"Unique"})).terms] == ["Unique"]


def test_marking_a_rule_unverifiable_is_idempotent():
    rule = {"type": "text", "customProperties": [{"property": "owner", "value": "x"}]}

    marked = mark_unverifiable(mark_unverifiable(rule))

    assert [entry for entry in marked["customProperties"] if is_unverifiable_marker(entry)] == [
        {"property": "verifiable", "value": False, "vendor": "testgen"}
    ]
    assert {"property": "owner", "value": "x"} in marked["customProperties"]
    assert "customProperties" in rule and len(rule["customProperties"]) == 1


def test_every_library_mapping_resolves_back_to_the_test_type_it_came_from():
    for test_type, mapping in RULE_MAPPINGS.items():
        if mapping.shape is not RuleShape.LIBRARY:
            continue

        rule, term = _rule_from(mapping)
        assert not validate_document(_wrap(rule, mapping.scope))

        # With the marker: every library mapping round-trips through tier 1 -- this alone
        # says nothing about tier 2 (the exact-equivalence table), since the marker resolves
        # before the table is ever consulted.
        resolved = resolve_rule(rule, mapping.scope, frozenset(RULE_MAPPINGS), flavor=SqlFlavorCode.POSTGRESQL)
        assert resolved is not None, f"{test_type} did not resolve from its own projected rule"
        assert resolved.test_type == test_type

        # ResolvedTerm must carry enough to reconstruct the term's own threshold, not just
        # identify its type. Mappings that state a single bound render the term's own threshold
        # directly into `thresholds`; the `mustBeBetween` mappings render a converted band instead, so
        # the term's own threshold_value must still be recoverable from `conversion` -- this
        # is what `_conversion_properties` is emitted for in the first place.
        if mapping.operator.value != "mustBeBetween":
            assert resolved.thresholds == {mapping.operator.value: rule[mapping.operator.value]}
            assert resolved.conversion == {}
        else:
            assert float(term.threshold_value) in resolved.conversion.values()

        # With the marker stripped: only the table can resolve it now. The table's own targets
        # resolve back to themselves. Every other library type either declines or resolves to
        # the table target checking the same predicate -- an unmarked email pattern is a
        # Pattern_Match, an unmarked list of valid values a LOV_Match -- since nothing left in
        # the rule says which of the two wrote it.
        stripped = resolve_rule(_without_marker(rule), mapping.scope, frozenset(RULE_MAPPINGS), flavor=SqlFlavorCode.POSTGRESQL)
        if test_type in _TIER_TWO_TARGETS:
            assert stripped is not None, f"{test_type} did not resolve via the table once its marker was stripped"
            assert stripped.test_type == test_type
        else:
            assert stripped is None or stripped.test_type in _TIER_TWO_TARGETS, (
                f"{test_type} resolved with no marker to {stripped.test_type}, which the table does not name"
            )


def test_a_marker_naming_a_custom_routed_type_resolves():
    """The types that render `custom` have no RULE_MAPPINGS row. Their marker is still
    the lossless round-trip of a rule this renderer wrote.
    """
    rule = {
        "type": "custom", "engine": "testgen", "implementation": {"threshold_value": "2"},
        "customProperties": [{"property": "testType", "value": "Avg_Shift", "vendor": "testgen"}],
    }
    resolved = resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "Avg_Shift"
    assert resolved.parameters == {"threshold_value": "2"}


@pytest.mark.parametrize("implementation", [None, "threshold_value: 2", ["2"]])
def test_a_custom_rule_whose_implementation_is_not_an_object_is_declined(implementation):
    """Its parameters cannot be read, so it is kept unverifiable rather than resolved with none."""
    rule = {
        "type": "custom", "engine": "testgen",
        "customProperties": [{"property": "testType", "value": "Avg_Shift", "vendor": "testgen"}],
        **({"implementation": implementation} if implementation is not None else {}),
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_custom_rule_claiming_a_comparison_operator_is_declined():
    """A custom rule's bound is one of its parameters, never an operator on the rule."""
    rule = {
        "type": "custom", "engine": "testgen", "mustBeLessOrEqualTo": 0,
        "customProperties": [{"property": "testType", "value": "Avg_Shift", "vendor": "testgen"}],
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_marker_naming_a_type_the_caller_does_not_know_is_declined():
    rule = {
        "type": "custom", "engine": "testgen",
        "customProperties": [{"property": "testType", "value": "Renamed_Away", "vendor": "testgen"}],
    }
    assert resolve_rule(rule, RuleScope.COLUMN, _KNOWN, flavor=SqlFlavorCode.POSTGRESQL) is None


def test_a_dupe_rows_rule_resolves_on_either_node():
    """Its node follows the term's grouping, so both nodes are legal for the type."""
    rule = {
        "type": "library", "metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0,
        "customProperties": [{"property": "testType", "value": "Dupe_Rows", "vendor": "testgen"}],
    }
    for scope in (RuleScope.COLUMN, RuleScope.TABLE):
        resolved = resolve_rule(rule, scope, frozenset({"Dupe_Rows"}), flavor=SqlFlavorCode.POSTGRESQL)
        assert resolved is not None
        assert resolved.test_type == "Dupe_Rows"


@pytest.mark.parametrize("groupby_names", ['"order_id"', '"order_id","customer_id"'])
def test_a_dupe_rows_rule_round_trips_on_the_scope_it_renders_to(groupby_names):
    term = _term(test_type="Dupe_Rows", column_name=None, groupby_names=groupby_names, contract_term_id="term-d")
    test_type = _test_type("Dupe_Rows")
    scope = rule_scope(term, test_type)
    rule = project_rule(term, test_type, SqlFlavorCode.POSTGRESQL)
    resolved = resolve_rule(rule, scope, frozenset({"Dupe_Rows"}), flavor=SqlFlavorCode.POSTGRESQL)
    assert resolved is not None
    assert resolved.test_type == "Dupe_Rows"


def test_a_non_term_dependent_library_type_still_declines_on_the_wrong_node():
    rule, _ = _rule_from(RULE_MAPPINGS["Required"])
    assert resolve_rule(rule, RuleScope.TABLE, frozenset({"Required"}), flavor=SqlFlavorCode.POSTGRESQL) is None


@pytest.mark.parametrize(
    ("flavor", "groupby_names", "subject"),
    [
        (SqlFlavorCode.POSTGRESQL, '"order_id", "line_no"', None),
        (SqlFlavorCode.BIGQUERY, "`order_id`, `line_no`", None),
        (SqlFlavorCode.DATABRICKS, "`order_id`, `line_no`", None),
        (SqlFlavorCode.BIGQUERY, "`order_id`", "order_id"),
    ],
)
def test_a_dupe_rows_grouping_round_trips_in_its_flavors_quoting(flavor, groupby_names, subject):
    term = _term(test_type="Dupe_Rows", column_name=None, groupby_names=groupby_names, contract_term_id="term-d")
    test_type = _test_type("Dupe_Rows")
    scope = rule_scope(term, test_type)
    rule = project_rule(term, test_type, flavor)
    if subject is None:
        assert rule["arguments"]["properties"] == ["order_id", "line_no"]

    resolved = resolve_rule(rule, scope, frozenset({"Dupe_Rows"}), subject, flavor=flavor)

    assert resolved is not None
    assert resolved.parameters["groupby_names"] == groupby_names


@pytest.mark.parametrize(
    ("test_type", "fields"),
    [
        ("Required", {"threshold_value": "many"}),
        ("Row_Ct_Pct", {"baseline_ct": "0", "threshold_value": "10"}),
        ("Match_Null_Ct", {"baseline_ct": None}),
        ("SQL_Metric", {"column_name": None, "custom_query": "SELECT COUNT(*) FROM {DATA_SCHEMA}.orders"}),
    ],
)
def test_a_term_rendered_custom_for_its_values_resolves_back_to_its_type(test_type, fields):
    term = _term(test_type=test_type, **fields)
    catalogue_type = _test_type(test_type, default_parm_columns="threshold_value,baseline_ct,custom_query")
    rule = project_rule(term, catalogue_type, SqlFlavorCode.POSTGRESQL)
    assert rule["type"] == "custom"

    resolved = resolve_rule(
        rule, rule_scope(term, catalogue_type), frozenset({test_type}), flavor=SqlFlavorCode.POSTGRESQL
    )

    assert resolved is not None
    assert resolved.test_type == test_type
    assert resolved.parameters == rule["implementation"]
