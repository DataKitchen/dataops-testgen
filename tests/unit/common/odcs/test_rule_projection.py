import math
import re

import pytest
import yaml

from testgen.common.enums import QualityDimension
from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.odcs import quality_rules
from testgen.common.odcs.quality_rules import (
    CatCondition,
    Operator,
    RuleMapping,
    RuleScope,
    RuleShape,
    odcs_dimension,
    project_rule,
)
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, ServerType
from testgen.common.odcs.validation import validate_document

pytestmark = pytest.mark.unit


def _term(**overrides) -> TestDefinition:
    defaults = {
        "test_type": "Required",
        "contract_term_id": "term-1",
        "column_name": "email",
        "table_name": "customers",
        "schema_name": "public",
        "threshold_value": "0",
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


# A handful of real `cat_test_conditions` rows (postgres, verbatim from the catalogue YAML)
# used to exercise `_build_sql_query`/`_resolved_bound` against actual measure text rather
# than an invented stand-in.
CONDITION_FLAG_CONDITION = CatCondition(
    measure="SUM(CASE WHEN {CUSTOM_QUERY} THEN 1 ELSE 0 END)",
    test_operator=">",
    test_condition="{THRESHOLD_VALUE}",
)
DAILY_RECORD_CT_CONDITION = CatCondition(
    measure="<%DATEDIFF_DAY;MIN({COLUMN_NAME});MAX({COLUMN_NAME})%>+1-COUNT(DISTINCT CAST({COLUMN_NAME} AS DATE))",
    test_operator=">",
    test_condition="{THRESHOLD_VALUE}",
)
FUTURE_DATE_CONDITION = CatCondition(
    measure="SUM(GREATEST(0, SIGN({COLUMN_NAME}::DATE - '{RUN_DATE}'::DATE)))",
    test_operator=">",
    test_condition="{THRESHOLD_VALUE}",
)
RECENCY_CONDITION = CatCondition(
    measure="<%DATEDIFF_DAY;MAX({COLUMN_NAME});'{RUN_DATE}'::DATE%>",
    test_operator=">",
    test_condition="{THRESHOLD_VALUE}",
)
# {COLUMN_TYPE}-carrying measures -- bigquery's Future_Date and sap_hana's Min_Date, the two
# flavors/types the full placeholder audit found needing the profiled column's data type.
FUTURE_DATE_BIGQUERY_CONDITION = CatCondition(
    measure="SUM(IF({COLUMN_NAME} > CAST(CAST('{RUN_DATE}' AS DATETIME) AS {COLUMN_TYPE}), 1, 0))",
    test_operator=">",
    test_condition="{THRESHOLD_VALUE}",
)
MIN_DATE_SAP_HANA_CONDITION = CatCondition(
    measure="SUM(CASE WHEN {COLUMN_NAME} < CAST('{BASELINE_VALUE}' AS {COLUMN_TYPE}) THEN 1 ELSE 0 END)",
    test_operator=">",
    test_condition="{THRESHOLD_VALUE}",
)


def _wrap(rule: dict, scope: RuleScope) -> dict:
    """A minimal ODCS document carrying ``rule`` at the node its scope implies."""
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


def test_a_required_term_projects_a_null_values_library_rule():
    term = _term(test_type="Required", threshold_value="0", contract_term_id="term-required")
    rule = project_rule(term, _test_type("Required", dq_dimension="Completeness"), ServerType.POSTGRES)

    assert rule["type"] == "library"
    assert rule["metric"] == "nullValues"
    assert rule["unit"] == "rows"
    assert rule["mustBeLessOrEqualTo"] == 0
    assert rule["dimension"] == "completeness"
    assert rule["id"] == "term-required"
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_library_rule_names_its_metric_and_never_a_rule_key():
    rule = project_rule(_term(test_type="Required", threshold_value="3"), _test_type("Required"), ServerType.POSTGRES)
    assert "rule" not in rule


def test_a_list_of_values_term_carries_its_values_as_an_argument():
    term = _term(
        test_type="LOV_Match",
        baseline_value="('Y','N')",
        threshold_value="0",
        contract_term_id="term-lov",
    )
    rule = project_rule(term, _test_type("LOV_Match", dq_dimension="Validity"), ServerType.POSTGRES)

    assert rule["type"] == "library"
    assert rule["metric"] == "invalidValues"
    assert rule["arguments"] == {"validValues": "('Y','N')"}
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_pattern_match_term_carries_its_pattern_as_an_argument():
    term = _term(
        test_type="Pattern_Match",
        baseline_value="[A-Z][0-9]{4}",
        threshold_value="0",
        contract_term_id="term-pattern",
    )
    rule = project_rule(term, _test_type("Pattern_Match", dq_dimension="Validity"), ServerType.POSTGRES)

    assert rule["arguments"] == {"pattern": "[A-Z][0-9]{4}"}
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_custom_query_term_projects_a_sql_rule_that_counts():
    term = _term(
        test_type="Condition_Flag",
        column_name="Quantity Consistency",
        custom_query="quantity_ordered <> quantity_shipped",
        threshold_value="0",
        contract_term_id="term-condition",
    )
    rule = project_rule(
        term, _test_type("Condition_Flag", dq_dimension="Validity"), ServerType.POSTGRES, CONDITION_FLAG_CONDITION
    )

    assert rule["type"] == "sql"
    assert rule["query"] == "SELECT SUM(CASE WHEN quantity_ordered <> quantity_shipped THEN 1 ELSE 0 END) FROM {object}"
    assert rule["mustBeLessOrEqualTo"] == 0
    assert not validate_document(_wrap(rule, RuleScope.TABLE))


def test_a_table_scoped_sql_rule_never_carries_the_property_placeholder():
    term = _term(
        test_type="Condition_Flag",
        custom_query="a <> b",
        threshold_value="0",
    )
    rule = project_rule(term, _test_type("Condition_Flag"), ServerType.POSTGRES, CONDITION_FLAG_CONDITION)

    assert "{object}" in rule["query"]
    assert "{property}" not in rule["query"]


def test_a_referential_term_projects_a_custom_rule_with_an_implementation(monkeypatch):
    monkeypatch.setitem(
        quality_rules.RULE_MAPPINGS,
        "Combo_Match",
        RuleMapping(
            test_type="Combo_Match",
            shape=RuleShape.CUSTOM,
            scope=RuleScope.TABLE,
            operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
            dimension=odcs_dimension(QualityDimension.CONSISTENCY),
        ),
    )
    term = _term(
        test_type="Combo_Match",
        column_name=None,
        table_name="orders",
        match_table_name="order_lines",
        match_column_names="order_id",
        threshold_value="0",
        contract_term_id="term-combo",
    )
    rule = project_rule(term, _test_type("Combo_Match", dq_dimension="Consistency"), ServerType.POSTGRES)

    assert rule["type"] == "custom"
    assert rule["engine"] == "testgen"
    assert rule["implementation"]
    assert not validate_document(_wrap(rule, RuleScope.TABLE))


def test_a_custom_rule_carries_no_operator(monkeypatch):
    monkeypatch.setitem(
        quality_rules.RULE_MAPPINGS,
        "Combo_Match",
        RuleMapping(
            test_type="Combo_Match",
            shape=RuleShape.CUSTOM,
            scope=RuleScope.TABLE,
            operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
            dimension=odcs_dimension(QualityDimension.CONSISTENCY),
        ),
    )
    term = _term(test_type="Combo_Match", threshold_value="0")
    rule = project_rule(term, _test_type("Combo_Match"), ServerType.POSTGRES)

    assert not any(operator.value in rule for operator in Operator)


def test_the_originating_test_type_rides_in_custom_properties_under_the_testgen_vendor():
    rule = project_rule(_term(test_type="Required", threshold_value="0"), _test_type("Required"), ServerType.POSTGRES)
    marker = {"property": "testType", "value": "Required", "vendor": "testgen"}
    assert marker in rule["customProperties"]


def test_the_rules_id_is_the_terms_stored_identity():
    term = _term(test_type="Required", threshold_value="0", contract_term_id="a-very-specific-id")
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)
    assert rule["id"] == "a-very-specific-id"


def test_reserved_subtree_fields_are_emitted_onto_the_rule():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {
                "name": "Email required",
                "businessImpact": "regulatory",
                "method": "reconciliation",
                "tags": ["finance"],
                "authoritativeDefinitions": [{"url": "https://example.com/policy", "type": "businessDefinition"}],
                "schedule": "0 20 * * *",
            }
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert rule["name"] == "Email required"
    assert rule["businessImpact"] == "regulatory"
    assert rule["method"] == "reconciliation"
    assert rule["tags"] == ["finance"]
    assert rule["authoritativeDefinitions"] == [{"url": "https://example.com/policy", "type": "businessDefinition"}]
    assert rule["schedule"] == "0 20 * * *"
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_an_unrecognised_reserved_subtree_key_is_not_emitted():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={"odcs": {"bogusKey": "nope", "name": "kept"}},
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert "bogusKey" not in rule
    assert rule["name"] == "kept"
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_stray_key_inside_a_reserved_custom_property_is_stripped_not_forwarded():
    # A term saved before the model's writer-side validator rejected this shape, or one
    # arriving through the test-definition import, must not be able to carry a sealed-schema
    # violation into a rendered document and block its contract version's freeze.
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {"customProperties": [{"property": "vendor", "value": "acme", "stray": "z"}]}
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert {"property": "vendor", "value": "acme"} in rule["customProperties"]
    assert not any("stray" in entry for entry in rule["customProperties"])
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_stray_key_inside_a_reserved_authoritative_definition_is_stripped_not_forwarded():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {"authoritativeDefinitions": [
                {"url": "https://example.com/policy", "type": "glossary", "bogus": 1}
            ]}
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert rule["authoritativeDefinitions"] == [{"url": "https://example.com/policy", "type": "glossary"}]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_non_conforming_id_is_stripped_from_a_reserved_custom_property_not_the_whole_entry():
    # CustomProperty.id is a StableId ($ref, pattern ^[^\s.#/\\@!%&^]+$) in the pinned schema.
    # id is never required (property/value are), so an entry with a bad id keeps everything
    # else -- dropping the whole entry over one bad field would lose data the user supplied.
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {"customProperties": [{"property": "vendor", "value": "acme", "id": "has spaces"}]}
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert {"property": "vendor", "value": "acme"} in rule["customProperties"]
    assert not any("id" in entry and entry.get("property") == "vendor" for entry in rule["customProperties"])
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_non_conforming_id_is_stripped_from_a_reserved_authoritative_definition_not_the_whole_entry():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {"authoritativeDefinitions": [
                {"url": "https://example.com/policy", "type": "glossary", "id": "a.b"}
            ]}
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert rule["authoritativeDefinitions"] == [{"url": "https://example.com/policy", "type": "glossary"}]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_conforming_id_survives_untouched_on_both_reserved_entry_shapes():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {
                "customProperties": [{"property": "vendor", "value": "acme", "id": "cp-1"}],
                "authoritativeDefinitions": [
                    {"url": "https://example.com/policy", "type": "glossary", "id": "ad-1"}
                ],
            }
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert {"property": "vendor", "value": "acme", "id": "cp-1"} in rule["customProperties"]
    assert rule["authoritativeDefinitions"] == [
        {"url": "https://example.com/policy", "type": "glossary", "id": "ad-1"}
    ]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_an_incomplete_reserved_entry_is_dropped_rather_than_forwarded_invalid():
    # An entry missing a required field (e.g. from data older than the writer-side check, or
    # from import) would itself fail schema validation if forwarded -- dropped instead.
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {
                "customProperties": [{"property": "only_a_property_no_value"}],
                "authoritativeDefinitions": [{"description": "no url or type"}],
            }
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert not any(entry.get("property") == "only_a_property_no_value" for entry in rule["customProperties"])
    assert rule["authoritativeDefinitions"] == []
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_users_own_metadata_keys_become_rule_custom_properties():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={"team": "finance", "ownerEmail": "data-owner@example.com"},
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert {"property": "team", "value": "finance"} in rule["customProperties"]
    assert {"property": "ownerEmail", "value": "data-owner@example.com"} in rule["customProperties"]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_dimension_in_the_reserved_subtree_overrides_the_test_types_dimension():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={"odcs": {"dimension": "accuracy"}},
    )
    rule = project_rule(term, _test_type("Required", dq_dimension="Completeness"), ServerType.POSTGRES)
    assert rule["dimension"] == "accuracy"


def test_a_pending_decision_term_projects_as_an_unverifiable_text_rule():
    term = _term(
        test_type="Combo_Match",
        column_name=None,
        table_name="orders",
        threshold_value=None,
        contract_term_id="term-pending",
        test_description="",
    )
    test_type = _test_type(
        "Combo_Match",
        dq_dimension="Consistency",
        test_name_short="Combo Match",
        test_name_long="Combination values found in reference set",
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)

    assert rule["type"] == "text"
    assert rule["name"] == "Combination values found in reference set"
    assert rule["description"] == "Carried unverified: routing for this test type is not yet decided."
    assert rule["dimension"] == "consistency"
    assert rule["id"] == "term-pending"
    assert {"property": "testType", "value": "Combo_Match", "vendor": "testgen"} in rule["customProperties"]
    assert {"property": "verifiable", "value": False, "vendor": "testgen"} in rule["customProperties"]
    assert not validate_document(_wrap(rule, RuleScope.TABLE))


def test_a_pending_decision_term_does_not_raise_and_does_not_return_none():
    for test_type_code in quality_rules.PENDING_DECISION:
        term = _term(test_type=test_type_code, column_name=None, threshold_value=None)
        rule = project_rule(term, _test_type(test_type_code, dq_dimension="Validity"), ServerType.POSTGRES)
        assert rule is not None
        assert rule["type"] == "text"


def test_no_enum_member_reaches_the_rendered_rule():
    rule = project_rule(_term(test_type="Required", threshold_value="0"), _test_type("Required"), ServerType.POSTGRES)
    assert type(rule["type"]) is str
    assert type(rule["metric"]) is str
    assert type(rule["dimension"]) is str
    # The real keys project_rule wrote -- not a hardcoded literal, which would be
    # tautologically true regardless of what the function emitted. Catches e.g.
    # `rule[Operator.MUST_BE_LESS_OR_EQUAL_TO] = value` (the enum member itself, not
    # `.value`): its type is `Operator`, not `str`, even though it compares equal to the
    # right string as a `StrEnum`.
    assert all(type(key) is str for key in rule)
    # The one mechanism that actually raises on a leaked enum member: neither `jsonschema`
    # nor a dict-equality assertion would catch it (a `StrEnum` member passes
    # `isinstance(x, str)` and compares equal to its string value), but `yaml.safe_dump`
    # raises `RepresenterError` on an unregistered type.
    yaml.safe_dump(rule)


def test_library_sql_and_custom_rules_carry_their_shapes_required_companion(monkeypatch):
    library_rule = project_rule(
        _term(test_type="Required", threshold_value="0"), _test_type("Required"), ServerType.POSTGRES
    )
    assert "metric" in library_rule

    sql_rule = project_rule(
        _term(test_type="Condition_Flag", custom_query="a <> b", threshold_value="0"),
        _test_type("Condition_Flag"),
        ServerType.POSTGRES,
        CONDITION_FLAG_CONDITION,
    )
    assert "query" in sql_rule

    monkeypatch.setitem(
        quality_rules.RULE_MAPPINGS,
        "Combo_Match",
        RuleMapping(
            test_type="Combo_Match",
            shape=RuleShape.CUSTOM,
            scope=RuleScope.TABLE,
            operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
            dimension=odcs_dimension(QualityDimension.CONSISTENCY),
        ),
    )
    custom_rule = project_rule(
        _term(test_type="Combo_Match", threshold_value="0"), _test_type("Combo_Match"), ServerType.POSTGRES
    )
    assert "engine" in custom_rule
    assert "implementation" in custom_rule


def test_a_sql_rule_carries_which_server_dialect_it_was_written_for():
    term = _term(test_type="Condition_Flag", custom_query="a <> b", threshold_value="0")
    rule = project_rule(term, _test_type("Condition_Flag"), ServerType.SNOWFLAKE, CONDITION_FLAG_CONDITION)
    assert {"property": "serverType", "value": "snowflake", "vendor": "testgen"} in rule["customProperties"]


def test_a_library_rule_never_carries_a_server_dialect_marker():
    rule = project_rule(_term(test_type="Required", threshold_value="0"), _test_type("Required"), ServerType.POSTGRES)
    assert not any(entry["property"] == "serverType" for entry in rule["customProperties"])


# --- General sql-shape query building: macros, {RUN_DATE}, and no leftover placeholder ----


def test_a_macro_carrying_measure_is_expanded_for_the_declared_flavor_and_leaves_no_macro():
    # Daily_Record_Ct's postgres measure: a <%DATEDIFF_DAY;...;...%> macro call and no
    # {RUN_DATE} -- exercises macro expansion in isolation.
    term = _term(
        test_type="Daily_Record_Ct",
        column_name="order_date",
        threshold_value="0",
        contract_term_id="term-daily",
    )
    rule = project_rule(
        term, _test_type("Daily_Record_Ct", dq_dimension="Completeness"), ServerType.POSTGRES,
        DAILY_RECORD_CT_CONDITION,
    )

    assert rule["type"] == "sql"
    assert "<%" not in rule["query"] and "%>" not in rule["query"]
    assert "DATEDIFF_DAY" not in rule["query"]
    assert "{property}" in rule["query"]
    assert "{COLUMN_NAME}" not in rule["query"]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_run_date_carrying_measure_uses_current_date_not_a_frozen_export_date():
    # Future_Date's postgres measure carries '{RUN_DATE}'::DATE and no macro -- exercises
    # the RUN_DATE substitution in isolation. The rule must read CURRENT_DATE (evaluated
    # whenever the counterparty next checks it), never a date literal frozen at export time.
    term = _term(
        test_type="Future_Date",
        column_name="ship_date",
        threshold_value="0",
        contract_term_id="term-future-date",
    )
    rule = project_rule(
        term, _test_type("Future_Date", dq_dimension="Timeliness"), ServerType.POSTGRES, FUTURE_DATE_CONDITION
    )

    assert "CURRENT_DATE" in rule["query"]
    assert "{RUN_DATE}" not in rule["query"]
    assert "'CURRENT_DATE'" not in rule["query"]  # must be the bare keyword, not a quoted string
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_measure_combining_a_macro_and_run_date_resolves_both():
    # Recency's postgres measure: <%DATEDIFF_DAY;MAX(...);'{RUN_DATE}'::DATE%> -- both
    # substitutions have to compose, in the right order (placeholders resolved before the
    # macro is expanded, matching execute_tests_query.py's own replace_params-then-macro order).
    term = _term(test_type="Recency", column_name="last_seen", threshold_value="0", contract_term_id="term-recency")
    rule = project_rule(
        term, _test_type("Recency", dq_dimension="Timeliness"), ServerType.POSTGRES, RECENCY_CONDITION
    )

    assert "<%" not in rule["query"]
    assert "CURRENT_DATE" in rule["query"]
    assert "{property}" in rule["query"]
    for leftover in ("{RUN_DATE}", "{COLUMN_NAME}", "{THRESHOLD_VALUE}"):
        assert leftover not in rule["query"]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_no_testgen_placeholder_survives_into_a_sql_query_across_several_real_measures():
    # A leftover {BASELINE_AVG}-shaped placeholder would still validate against the schema
    # and only fail once a counterparty tries to run it -- exactly the failure this task
    # guards against, so assert its absence directly rather than trusting the shape alone.
    cases = [
        ("Condition_Flag", CONDITION_FLAG_CONDITION, {"custom_query": "a <> b"}),
        ("Daily_Record_Ct", DAILY_RECORD_CT_CONDITION, {"column_name": "d"}),
        ("Future_Date", FUTURE_DATE_CONDITION, {"column_name": "d"}),
        ("Recency", RECENCY_CONDITION, {"column_name": "d"}),
    ]
    for test_type_code, condition, extra in cases:
        term = _term(test_type=test_type_code, threshold_value="0", **extra)
        rule = project_rule(term, _test_type(test_type_code), ServerType.POSTGRES, condition)
        leftover = re.findall(r"\{[A-Z_]+\}", rule["query"])
        assert not leftover, (test_type_code, rule["query"], leftover)


def test_a_column_type_carrying_measure_raises_without_one_and_builds_with_one():
    # bigquery's Future_Date measure needs {COLUMN_TYPE} (the profiled column's data type,
    # DataColumnChars.column_type) -- not reachable from term/test_type alone. Without it,
    # project_rule must raise rather than ship a query no engine can run; with it (the
    # caller's to supply, same move as `condition` in fix round 1), it builds and validates.
    term = _term(test_type="Future_Date", column_name="ship_date", threshold_value="0")
    test_type = _test_type("Future_Date", dq_dimension="Timeliness")

    with pytest.raises(ValueError, match=r"\{COLUMN_TYPE\}"):
        project_rule(term, test_type, ServerType.BIGQUERY, FUTURE_DATE_BIGQUERY_CONDITION)

    rule = project_rule(term, test_type, ServerType.BIGQUERY, FUTURE_DATE_BIGQUERY_CONDITION, column_type="DATETIME")
    assert "{COLUMN_TYPE}" not in rule["query"]
    assert "DATETIME" in rule["query"]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_column_type_carrying_measure_on_its_second_flavor_also_builds_with_one():
    # Min_Date is the type the full audit found needing {COLUMN_TYPE} on *two* flavors
    # (bigquery and sap_hana) -- exercise the sap_hana side specifically.
    term = _term(
        test_type="Min_Date", column_name="ship_date", baseline_value="2020-01-01", threshold_value="0"
    )
    test_type = _test_type("Min_Date", dq_dimension="Validity")

    with pytest.raises(ValueError, match=r"\{COLUMN_TYPE\}"):
        project_rule(term, test_type, ServerType.HANA, MIN_DATE_SAP_HANA_CONDITION)

    rule = project_rule(term, test_type, ServerType.HANA, MIN_DATE_SAP_HANA_CONDITION, column_type="DATE")
    assert "{COLUMN_TYPE}" not in rule["query"]
    assert "CAST('2020-01-01' AS DATE)" in rule["query"]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_project_rule_requires_a_condition_for_an_sql_shape_term():
    term = _term(test_type="Condition_Flag", custom_query="a <> b", threshold_value="0")
    with pytest.raises(ValueError, match="CatCondition"):
        project_rule(term, _test_type("Condition_Flag"), ServerType.POSTGRES)


# --- Percentage-type threshold conversion: tested by agreement, not by shape --------------


def _phi(ratio: float) -> float:
    return 2 * math.asin(math.sqrt(ratio))


def _cohens_h_term_pass(baseline_ratio: float, h: float, observed_ratio: float) -> bool:
    """Mirrors the CAT measure/operator directly from the YAML catalogue, independent of
    ``project_rule``: ``measure = ABS(phi(baseline) - phi(observed))``, fails when
    ``measure >= threshold``."""
    measure = abs(_phi(baseline_ratio) - _phi(observed_ratio))
    return measure < h


def test_missing_pct_conversion_agrees_with_the_term_across_a_spread_of_populated_ratios():
    baseline_ct, baseline_value_ct, h = 1000, 950, 0.03
    term = _term(
        test_type="Missing_Pct",
        column_name="email",
        baseline_ct=str(baseline_ct),
        baseline_value_ct=str(baseline_value_ct),
        threshold_value=str(h),
        contract_term_id="term-missing-pct",
    )
    rule = project_rule(term, _test_type("Missing_Pct", dq_dimension="Completeness"), ServerType.POSTGRES)
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))

    lower, upper = rule["mustBeBetween"]
    baseline_ratio = baseline_value_ct / baseline_ct

    saw_pass = saw_fail = False
    for observed_ratio in (0.90, 0.942, 0.944, 0.95, 0.955, 0.957, 0.99):
        term_pass = _cohens_h_term_pass(baseline_ratio, h, observed_ratio)
        null_pct = 100 * (1 - observed_ratio)
        rendered_pass = lower <= null_pct <= upper
        assert term_pass == rendered_pass, (observed_ratio, term_pass, rendered_pass)
        saw_pass = saw_pass or term_pass
        saw_fail = saw_fail or not term_pass
    assert saw_pass and saw_fail

    # The stable-column case: a naive copy of the threshold (treating the Cohen's h bound as
    # if it were itself a null-percent cap) disagrees with both the term and the conversion.
    stable_null_pct = 100 * (1 - baseline_ratio)
    assert _cohens_h_term_pass(baseline_ratio, h, baseline_ratio) is True
    assert lower <= stable_null_pct <= upper
    assert not (stable_null_pct <= h)


def test_unique_pct_conversion_agrees_with_the_term_across_a_spread_of_distinct_ratios():
    baseline_value_ct, baseline_unique_ct, h = 1000, 950, 0.03
    term = _term(
        test_type="Unique_Pct",
        column_name="email",
        baseline_value_ct=str(baseline_value_ct),
        baseline_unique_ct=str(baseline_unique_ct),
        threshold_value=str(h),
        contract_term_id="term-unique-pct",
    )
    rule = project_rule(term, _test_type("Unique_Pct", dq_dimension="Uniqueness"), ServerType.POSTGRES)
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))
    assert rule["metric"] == "duplicateValues"

    lower, upper = rule["mustBeBetween"]
    baseline_ratio = baseline_unique_ct / baseline_value_ct

    saw_pass = saw_fail = False
    for observed_ratio in (0.90, 0.942, 0.944, 0.95, 0.955, 0.957, 0.99):
        term_pass = _cohens_h_term_pass(baseline_ratio, h, observed_ratio)
        duplicate_pct = 100 * (1 - observed_ratio)
        rendered_pass = lower <= duplicate_pct <= upper
        assert term_pass == rendered_pass, (observed_ratio, term_pass, rendered_pass)
        saw_pass = saw_pass or term_pass
        saw_fail = saw_fail or not term_pass
    assert saw_pass and saw_fail


def test_row_ct_pct_conversion_agrees_with_the_term_across_a_spread_of_row_counts():
    baseline_ct, percent = 1000, 5
    term = _term(
        test_type="Row_Ct_Pct",
        column_name=None,
        baseline_ct=str(baseline_ct),
        threshold_value=str(percent),
        contract_term_id="term-row-ct-pct",
    )
    rule = project_rule(term, _test_type("Row_Ct_Pct", dq_dimension="Completeness"), ServerType.POSTGRES)
    assert not validate_document(_wrap(rule, RuleScope.TABLE))
    assert rule["metric"] == "rowCount"
    assert rule["unit"] == "rows"

    lower, upper = rule["mustBeBetween"]

    saw_pass = saw_fail = False
    for observed_count in (800, 949, 950, 1000, 1050, 1051, 1200):
        measure = abs(100 * (observed_count - baseline_ct) / baseline_ct)
        term_pass = measure <= percent
        rendered_pass = lower <= observed_count <= upper
        assert term_pass == rendered_pass, (observed_count, term_pass, rendered_pass)
        saw_pass = saw_pass or term_pass
        saw_fail = saw_fail or not term_pass
    assert saw_pass and saw_fail

    # A naive copy of the threshold (treating the percent bound as a row-count cap) disagrees:
    # the baseline count itself obviously passes, but a raw `rowCount <= percent` check would not.
    assert lower <= baseline_ct <= upper
    assert not (baseline_ct <= percent)
