import pytest

from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.odcs.quality_rules import (
    EXCLUDED_TEST_TYPES,
    RULE_MAPPINGS,
    RuleMapping,
    RuleScope,
    RuleShape,
    project_rule,
    resolve_rule,
)
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, ServerType
from testgen.common.odcs.validation import validate_document

pytestmark = pytest.mark.unit


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
    if mapping.argument == "validValues":
        argument_value = "('Y','N')"
    elif mapping.argument == "pattern":
        argument_value = "[A-Z]{3}"
    term = _term(
        test_type=mapping.test_type,
        column_name=None if mapping.scope is RuleScope.TABLE else "email",
        baseline_value=argument_value,
        contract_term_id=f"term-{mapping.test_type}",
    )
    return project_rule(term, _test_type(mapping.test_type), ServerType.POSTGRES), term


def _pending_rule(test_type_code: str) -> dict:
    """A real ``project_rule`` output for a routing-deferred type -- the ``text`` rule the
    renderer writes for it, marker and all, rather than one assembled by hand."""
    term = _term(test_type=test_type_code, column_name=None, contract_term_id=f"term-{test_type_code}")
    return project_rule(term, _test_type(test_type_code), ServerType.POSTGRES)


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
    resolved = resolve_rule(rule, scope=RuleScope.COLUMN)
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
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


def test_a_marker_whose_bound_does_not_match_its_types_own_operator_resolves_to_unverifiable():
    # Required only ever renders mustBeLessOrEqualTo -- a marker claiming Required alongside
    # a different operator is not this type's own shape, even though the marker names it.
    rule = {
        "metric": "nullValues",
        "unit": "rows",
        "mustBeBetween": [1, 2],
        "customProperties": [{"property": "testType", "value": "Required", "vendor": "testgen"}],
    }
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


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
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


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
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


def test_a_routed_types_marker_resolves_on_its_own_node_and_declines_on_the_other():
    # The marker says which type, not where the rule is allowed to sit. Required is
    # COLUMN-scoped, so the same projected rule presented as a table-node rule is not this
    # type's own shape -- tier 1 refuses it exactly as tier 2 refuses a metric on the wrong
    # scope.
    rule, _ = _rule_from(RULE_MAPPINGS["Required"])
    resolved = resolve_rule(rule, scope=RuleScope.COLUMN)
    assert resolved is not None
    assert resolved.test_type == "Required"
    assert resolve_rule(rule, scope=RuleScope.TABLE) is None


def test_a_marker_for_a_pending_type_on_the_node_it_does_not_declare_resolves_to_unverifiable():
    # CUSTOM declares TABLE: its column_name is a free-text focus label, so TestGen never
    # renders it on a column node. A marker claiming it there is no more this type's own
    # shape than a wrong operator would be.
    rule = _pending_rule("CUSTOM")
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


def test_a_marker_for_a_pending_type_on_its_declared_node_resolves():
    # The other half of the check above -- the scope is what tier 1 refuses, not the fact
    # that the type's rule shape is still undecided.
    rule = _pending_rule("CUSTOM")
    resolved = resolve_rule(rule, scope=RuleScope.TABLE)
    assert resolved is not None
    assert resolved.test_type == "CUSTOM"


def test_a_marker_naming_an_excluded_type_declines_and_does_not_raise():
    """An ``EXCLUDED_TEST_TYPES`` member is in the catalogue, so a marker naming one passes
    the membership check and reaches the scope lookup with nothing declared. Resolution
    answers a rule it cannot place by declining it: an incoming document is a counterparty's,
    and failing the import over one is not this path's to do. (``declared_scope`` raises on
    the same input, for the rendering path, where such a term is our own inconsistency.)
    """
    for test_type_code in EXCLUDED_TEST_TYPES:
        rule = {
            "type": "text",
            "customProperties": [{"property": "testType", "value": test_type_code, "vendor": "testgen"}],
        }
        assert resolve_rule(rule, scope=RuleScope.TABLE) is None
        assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


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
    resolved = resolve_rule(rule, scope=RuleScope.COLUMN)
    assert resolved is not None
    assert resolved.conversion == {"baselineRatio": 0.95, "thresholdBound": 3.0}


def test_a_rule_with_no_conversion_properties_surfaces_an_empty_conversion():
    rule = {"metric": "nullValues", "unit": "rows", "mustBeLessOrEqualTo": 5}
    resolved = resolve_rule(rule, scope=RuleScope.COLUMN)
    assert resolved is not None
    assert resolved.conversion == {}


def test_a_null_values_rule_in_rows_resolves_to_required():
    rule = {"metric": "nullValues", "unit": "rows", "mustBeLessOrEqualTo": 5}
    resolved = resolve_rule(rule, scope=RuleScope.COLUMN)
    assert resolved is not None
    assert resolved.test_type == "Required"
    assert resolved.thresholds == {"mustBeLessOrEqualTo": 5}
    assert resolved.arguments == {}


def test_a_null_values_rule_in_percent_is_declined_not_defaulted_to_missing_pct():
    # This is the mirror of the brief's own framing: no TestGen type computes a plain
    # proportion, so nullValues/percent has no equivalent at all. Resolving it onto
    # Missing_Pct would assert a Cohen's h drift bound the contract never stated.
    rule = {"metric": "nullValues", "unit": "percent", "mustBeBetween": [1, 2]}
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


def test_an_unrecognised_unit_resolves_to_unverifiable_and_is_not_defaulted_to_rows():
    assert resolve_rule({"metric": "nullValues", "unit": "percentage", "mustBe": 0}, scope=RuleScope.COLUMN) is None


def test_a_row_based_duplicate_values_rule_resolves_by_scope():
    # Neither destination is implemented -- Unique is deliberately held back (its measure
    # counts NULLs as duplicates) and Dupe_Rows has no decided threshold shape -- so a
    # duplicateValues/rows rule declines on both nodes rather than a (metric, unit) key
    # picking one of the two test types and being wrong for the other.
    rule = {"metric": "duplicateValues", "unit": "rows", "mustBeLessOrEqualTo": 0}
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None
    assert resolve_rule(rule, scope=RuleScope.TABLE) is None


def test_a_rule_carrying_both_valid_values_and_a_pattern_resolves_to_unverifiable():
    rule = {
        "metric": "invalidValues",
        "unit": "rows",
        "mustBeLessOrEqualTo": 0,
        "arguments": {"validValues": ["Y", "N"], "pattern": "[A-Z]"},
    }
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


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
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None


def test_a_metric_on_the_wrong_scope_resolves_to_unverifiable():
    # rowCount on a column node validates against the schema and means nothing -- Row_Ct is
    # a table-scoped test type, so a caller that knows the rule sits on a column node must
    # not get a resolution back.
    rule = {"metric": "rowCount", "unit": "rows", "mustBeGreaterOrEqualTo": 100}
    assert resolve_rule(rule, scope=RuleScope.COLUMN) is None
    resolved = resolve_rule(rule, scope=RuleScope.TABLE)
    assert resolved is not None
    assert resolved.test_type == "Row_Ct"


def test_the_operator_is_part_of_the_key():
    # mustBe: 0, mustBeLessThan: 5, mustNotBe: 0 are three different claims from
    # mustBeLessOrEqualTo: 0 -- none of them is Required's exact shape, even though some
    # would coincide with it at this particular value.
    base = {"metric": "nullValues", "unit": "rows"}
    assert resolve_rule({**base, "mustBe": 0}, scope=RuleScope.COLUMN) is None
    assert resolve_rule({**base, "mustBeLessThan": 5}, scope=RuleScope.COLUMN) is None
    assert resolve_rule({**base, "mustNotBe": 0}, scope=RuleScope.COLUMN) is None
    assert resolve_rule({**base, "mustBeLessOrEqualTo": 0}, scope=RuleScope.COLUMN) is not None


def test_a_strict_row_count_bound_is_reexpressed_as_the_next_integer():
    # rowCount counts rows -- always integral -- so re-expressing a strict lower bound as
    # the inclusive one is sound (unlike doing the same over a float-valued measure).
    rule = {"metric": "rowCount", "unit": "rows", "mustBeGreaterThan": 100}
    resolved = resolve_rule(rule, scope=RuleScope.TABLE)
    assert resolved is not None
    assert resolved.test_type == "Row_Ct"
    assert resolved.thresholds == {"mustBeGreaterOrEqualTo": 101}


def test_a_text_rule_always_resolves_to_unverifiable():
    rule = {"type": "text", "description": "Some free text quality expectation."}
    assert resolve_rule(rule, scope=RuleScope.TABLE) is None


def test_a_custom_rule_always_resolves_to_unverifiable():
    rule = {"type": "custom", "engine": "soda", "implementation": "checks for tables:\n  - name: x"}
    assert resolve_rule(rule, scope=RuleScope.TABLE) is None


def test_every_library_mapping_resolves_back_to_the_test_type_it_came_from():
    for test_type, mapping in RULE_MAPPINGS.items():
        if mapping.shape is not RuleShape.LIBRARY:
            continue

        rule, term = _rule_from(mapping)
        assert not validate_document(_wrap(rule, mapping.scope))

        # With the marker: every library mapping round-trips through tier 1 -- this alone
        # says nothing about tier 2 (the exact-equivalence table), since the marker resolves
        # before the table is ever consulted.
        resolved = resolve_rule(rule, scope=mapping.scope)
        assert resolved is not None, f"{test_type} did not resolve from its own projected rule"
        assert resolved.test_type == test_type

        # ResolvedTerm must carry enough to reconstruct the term's own threshold, not just
        # identify its type. `unit: rows` mappings render the term's own threshold directly
        # into `thresholds`; the percent mappings render a converted band there instead, so
        # the term's own threshold_value must still be recoverable from `conversion` -- this
        # is what `_conversion_properties` is emitted for in the first place.
        if mapping.unit == "rows":
            assert list(resolved.thresholds.values()) == [int(term.threshold_value)]
            assert resolved.conversion == {}
        else:
            assert float(term.threshold_value) in resolved.conversion.values()

        # With the marker stripped: only the table can resolve it now. Partitioned on the
        # mapping's own `unit` -- not a hardcoded name list -- so a mapping added later lands
        # on the right side automatically: `unit: rows` is the table's exact-equivalence
        # shape and must still resolve to the same test type via the table alone; any other
        # unit (the percent rows) has no table entry and must decline, exactly as it does
        # under `resolve_rule` directly.
        stripped = resolve_rule(_without_marker(rule), scope=mapping.scope)
        if mapping.unit == "rows":
            assert stripped is not None, f"{test_type} did not resolve via the table once its marker was stripped"
            assert stripped.test_type == test_type
        else:
            assert stripped is None, f"{test_type} resolved with no marker and no table row for its unit"
