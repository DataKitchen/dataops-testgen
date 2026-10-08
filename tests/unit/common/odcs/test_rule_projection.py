import math
import re

import pytest
import yaml

from testgen.common.enums import OdcsDimension, QualityDimension
from testgen.common.models import test_definition
from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.odcs import quality_rules
from testgen.common.odcs.quality_rules import (
    CatCondition,
    Operator,
    RuleMapping,
    RuleScope,
    RuleShape,
    _cohens_h_band,
    _groupby_columns,
    odcs_dimension,
    project_rule,
    rule_scope,
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
        "default_parm_columns": None,
        "test_description": None,
        "except_message": None,
        "threshold_description": None,
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


def _route_to_sql(monkeypatch, test_type: str, scope: RuleScope = RuleScope.COLUMN) -> None:
    """Route ``test_type`` to the sql shape for one test, as a catalogue row would."""
    monkeypatch.setitem(
        quality_rules.RULE_MAPPINGS,
        test_type,
        RuleMapping(
            test_type=test_type,
            shape=RuleShape.SQL,
            scope=scope,
            operator=Operator.MUST_BE_LESS_OR_EQUAL_TO,
            dimension=odcs_dimension(QualityDimension.VALIDITY),
        ),
    )


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
    assert rule["arguments"] == {"validValues": ["Y", "N"]}
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


def test_a_custom_query_term_projects_a_sql_rule_that_counts(monkeypatch):
    _route_to_sql(monkeypatch, "Condition_Flag", RuleScope.TABLE)
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


def test_a_table_scoped_sql_rule_never_carries_the_property_placeholder(monkeypatch):
    _route_to_sql(monkeypatch, "Condition_Flag", RuleScope.TABLE)
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
    test_type = _test_type(
        "Combo_Match", dq_dimension="Consistency", default_parm_columns="match_table_name,match_column_names"
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)

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


def test_the_reader_and_the_save_time_validator_share_one_list_of_sealed_fields():
    assert quality_rules.ODCS_CUSTOM_PROPERTY_FIELDS is test_definition.ODCS_CUSTOM_PROPERTY_FIELDS
    assert quality_rules.ODCS_CUSTOM_PROPERTY_REQUIRED_FIELDS is test_definition.ODCS_CUSTOM_PROPERTY_REQUIRED_FIELDS
    assert quality_rules.ODCS_AUTHORITATIVE_DEFINITION_FIELDS is test_definition.ODCS_AUTHORITATIVE_DEFINITION_FIELDS
    assert (
        quality_rules.ODCS_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS
        is test_definition.ODCS_AUTHORITATIVE_DEFINITION_REQUIRED_FIELDS
    )


def test_a_reserved_entry_is_rebuilt_in_the_schemas_key_order_whatever_order_it_was_stored_in():
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={
            "odcs": {
                "customProperties": [{"vendor": "v", "description": "d", "value": "acme", "property": "p", "id": "c"}],
                "authoritativeDefinitions": [
                    {"description": "d", "type": "glossary", "url": "https://example.com/policy", "id": "a"}
                ],
            }
        },
    )
    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    custom_property = next(entry for entry in rule["customProperties"] if entry.get("property") == "p")
    assert list(custom_property) == ["id", "property", "value", "description", "vendor"]
    assert list(rule["authoritativeDefinitions"][0]) == ["id", "url", "type", "description"]


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


def test_a_dimension_the_enum_does_not_hold_is_reported_not_raised():
    """Every other field of the reserved subtree tolerates a value the current writer would
    refuse -- a row predating the save-time validator, or one written straight to the database --
    and lets schema validation report it. Raising instead aborts the whole render, hiding every
    other problem the document has and naming no term."""
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={"odcs": {"dimension": "Nonsense"}},
    )

    rule = project_rule(term, _test_type("Required", dq_dimension="Completeness"), ServerType.POSTGRES)

    assert rule["dimension"] == "Nonsense"
    problems = validate_document(_wrap(rule, RuleScope.COLUMN))
    assert any("dimension" in problem and "Nonsense" in problem for problem in problems)


def test_a_dimension_stored_as_an_enum_member_is_normalised_to_its_value():
    """``yaml.safe_dump`` raises ``RepresenterError`` on a ``StrEnum`` member, so a member
    reaching the rule would fail at serialization rather than validation."""
    term = _term(
        test_type="Required",
        threshold_value="0",
        custom_metadata={"odcs": {"dimension": OdcsDimension.ACCURACY}},
    )

    rule = project_rule(term, _test_type("Required"), ServerType.POSTGRES)

    assert type(rule["dimension"]) is str
    assert rule["dimension"] == "accuracy"


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
    _route_to_sql(monkeypatch, "Condition_Flag", RuleScope.TABLE)
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
        _term(test_type="Combo_Match", threshold_value="0"),
        _test_type("Combo_Match", default_parm_columns="threshold_value"),
        ServerType.POSTGRES,
    )
    assert "engine" in custom_rule
    assert "implementation" in custom_rule


def test_a_sql_rule_carries_which_server_dialect_it_was_written_for(monkeypatch):
    _route_to_sql(monkeypatch, "Condition_Flag", RuleScope.TABLE)
    term = _term(test_type="Condition_Flag", custom_query="a <> b", threshold_value="0")
    rule = project_rule(term, _test_type("Condition_Flag"), ServerType.SNOWFLAKE, CONDITION_FLAG_CONDITION)
    assert {"property": "serverType", "value": "snowflake", "vendor": "testgen"} in rule["customProperties"]


def test_a_library_rule_never_carries_a_server_dialect_marker():
    rule = project_rule(_term(test_type="Required", threshold_value="0"), _test_type("Required"), ServerType.POSTGRES)
    assert not any(entry["property"] == "serverType" for entry in rule["customProperties"])


# --- General sql-shape query building: macros, {RUN_DATE}, and no leftover placeholder ----


def test_a_macro_carrying_measure_is_expanded_for_the_declared_flavor_and_leaves_no_macro(monkeypatch):
    _route_to_sql(monkeypatch, "Daily_Record_Ct")
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


def test_a_run_date_carrying_measure_uses_current_date_not_a_frozen_export_date(monkeypatch):
    _route_to_sql(monkeypatch, "Future_Date")
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


def test_a_measure_combining_a_macro_and_run_date_resolves_both(monkeypatch):
    _route_to_sql(monkeypatch, "Recency")
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


def test_no_testgen_placeholder_survives_into_a_sql_query_across_several_real_measures(monkeypatch):
    _route_to_sql(monkeypatch, "Condition_Flag")
    _route_to_sql(monkeypatch, "Daily_Record_Ct")
    _route_to_sql(monkeypatch, "Future_Date")
    _route_to_sql(monkeypatch, "Recency")
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


def test_a_column_type_carrying_measure_renders_custom_without_one_and_builds_with_one(monkeypatch):
    _route_to_sql(monkeypatch, "Future_Date")
    # bigquery's Future_Date measure needs {COLUMN_TYPE} (the profiled column's data type,
    # DataColumnChars.column_type) -- not reachable from term/test_type alone. Without it,
    # project_rule renders custom rather than ship a query no engine can run; with it, the
    # query builds and validates.
    term = _term(test_type="Future_Date", column_name="ship_date", threshold_value="0")
    test_type = _test_type("Future_Date", dq_dimension="Timeliness")

    assert project_rule(term, test_type, ServerType.BIGQUERY, FUTURE_DATE_BIGQUERY_CONDITION)["type"] == "custom"

    rule = project_rule(term, test_type, ServerType.BIGQUERY, FUTURE_DATE_BIGQUERY_CONDITION, column_type="DATETIME")
    assert "{COLUMN_TYPE}" not in rule["query"]
    assert "DATETIME" in rule["query"]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_a_column_type_carrying_measure_on_its_second_flavor_also_builds_with_one(monkeypatch):
    _route_to_sql(monkeypatch, "Min_Date")
    # Min_Date is the type the full audit found needing {COLUMN_TYPE} on *two* flavors
    # (bigquery and sap_hana) -- exercise the sap_hana side specifically.
    term = _term(
        test_type="Min_Date", column_name="ship_date", baseline_value="2020-01-01", threshold_value="0"
    )
    test_type = _test_type("Min_Date", dq_dimension="Validity")

    assert project_rule(term, test_type, ServerType.HANA, MIN_DATE_SAP_HANA_CONDITION)["type"] == "custom"

    rule = project_rule(term, test_type, ServerType.HANA, MIN_DATE_SAP_HANA_CONDITION, column_type="DATE")
    assert "{COLUMN_TYPE}" not in rule["query"]
    assert "CAST('2020-01-01' AS DATE)" in rule["query"]
    assert not validate_document(_wrap(rule, RuleScope.COLUMN))


def test_project_rule_requires_a_condition_for_an_sql_shape_term(monkeypatch):
    _route_to_sql(monkeypatch, "Condition_Flag", RuleScope.TABLE)
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


def test_cohens_h_band_saturates_instead_of_folding_past_the_domain():
    """phi(p) = 2*asin(sqrt(p)) has range [0, pi]. Outside it, sin(f/2)**2 is no longer
    phi's inverse -- past pi it turns back downward -- so an unclamped upper bound returns a
    ratio lower than the baseline and the rendered band excludes data the test accepts.
    """
    lower, upper = _cohens_h_band(0.96, 2.0)
    assert upper == pytest.approx(1.0)
    assert lower == pytest.approx(0.13045, abs=1e-4)


def test_cohens_h_band_saturates_at_the_low_end_too():
    lower, upper = _cohens_h_band(0.0, 2.0)
    assert lower == pytest.approx(0.0)
    assert upper == pytest.approx(0.70807, abs=1e-4)


def test_a_missing_pct_term_whose_band_saturates_renders_a_range_not_an_equality():
    """An all-null column at baseline ratio 0 collapsed to `mustBe` before the clamp,
    because both band ends landed on the same folded value.
    """
    term = _term(test_type="Missing_Pct", baseline_ct="50", baseline_value_ct="0", threshold_value="2.0")
    rule = project_rule(term, _test_type("Missing_Pct", dq_dimension="Completeness"), ServerType.POSTGRES)
    assert "mustBe" not in rule
    assert rule["mustBeBetween"] == [pytest.approx(29.19, abs=0.01), pytest.approx(100.0)]


def test_a_term_with_no_contract_identity_is_refused_by_name():
    """Rendering it instead emits ``id: null``, which the pinned schema rejects by JSON path --
    so the freeze fails naming a node position rather than the term that has no identity."""
    term = _term(contract_term_id=None)
    with pytest.raises(ValueError, match="customers"):
        project_rule(term, _test_type("Required"), ServerType.POSTGRES)


@pytest.mark.parametrize(
    ("test_type", "fields"),
    [
        ("Required", {"threshold_value": None}),
        ("Required", {"threshold_value": ""}),
        ("Required", {"threshold_value": "   "}),
        ("Required", {"threshold_value": "many"}),
        ("Missing_Pct", {"baseline_ct": "50", "baseline_value_ct": "40", "threshold_value": None}),
        ("Missing_Pct", {"baseline_ct": "0", "baseline_value_ct": "0", "threshold_value": "2.0"}),
        ("Missing_Pct", {"baseline_ct": None, "baseline_value_ct": "40", "threshold_value": "2.0"}),
        ("Missing_Pct", {"baseline_ct": "50", "baseline_value_ct": "60", "threshold_value": "0.5"}),
        ("Missing_Pct", {"baseline_ct": "-5", "baseline_value_ct": "1", "threshold_value": "0.5"}),
        ("Row_Ct_Pct", {"baseline_ct": "50", "threshold_value": None}),
        ("Row_Ct_Pct", {"baseline_ct": "0", "threshold_value": "10"}),
        ("LOV_Match", {"baseline_value": "Val1,Val2", "threshold_value": "0"}),
        ("Pattern_Match", {"baseline_value": "", "threshold_value": "0"}),
        ("Match_Null_Ct", {"baseline_ct": None}),
        ("Match_Row_Ct", {"threshold_value": None}),
        ("Dupe_Rows", {"groupby_names": "order_id"}),
        ("Dupe_Rows", {"groupby_names": '"order_id", line_no'}),
        ("SQL_Metric", {"column_name": None, "custom_query": "SELECT 1"}),
        ("SQL_Metric", {"column_name": None, "upper_tolerance": "1", "custom_query": "SELECT {RUN_DATE}"}),
        ("SQL_Metric", {"column_name": None, "upper_tolerance": "1", "custom_query": None}),
    ],
)
def test_a_term_whose_values_cannot_be_stated_exactly_renders_custom(test_type, fields):
    """TestGen still runs such a term -- a cleared bound reads as NULL and passes -- so the
    contract carries it as a ``custom`` rule rather than failing the freeze or export."""
    term = _term(test_type=test_type, **fields)
    rule = project_rule(term, _test_type(test_type), ServerType.POSTGRES)
    assert rule["type"] == "custom"
    assert "metric" not in rule
    assert "query" not in rule
    assert not [key for key in rule if key.startswith("must")]
    assert not validate_document(_wrap(rule, rule_scope(term, _test_type(test_type))))


def test_unique_pct_renders_as_a_custom_rule():
    term = _term(test_type="Unique_Pct", baseline_value_ct="100", baseline_unique_ct="90", threshold_value="0.5")
    rule = project_rule(term, _test_type("Unique_Pct", dq_dimension="Uniqueness"), ServerType.POSTGRES)
    assert rule["type"] == "custom"
    assert "metric" not in rule


def test_dupe_rows_on_one_column_renders_a_column_scoped_duplicate_values_rule():
    term = _term(test_type="Dupe_Rows", groupby_names='"order_id"')
    test_type = _test_type("Dupe_Rows", dq_dimension="Uniqueness", test_scope="table")
    assert rule_scope(term, test_type) is RuleScope.COLUMN
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["metric"] == "duplicateValues"
    assert rule["unit"] == "rows"
    assert rule["mustBeLessOrEqualTo"] == 0
    assert "arguments" not in rule


def test_dupe_rows_bound_is_the_terms_skip_errors():
    term = _term(test_type="Dupe_Rows", groupby_names='"order_id"', skip_errors=5)
    test_type = _test_type("Dupe_Rows", dq_dimension="Uniqueness", test_scope="table")
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["mustBeLessOrEqualTo"] == 5


def test_dupe_rows_on_several_columns_renders_a_table_scoped_rule_listing_them():
    term = _term(test_type="Dupe_Rows", groupby_names='"order_id", "line_no"')
    test_type = _test_type("Dupe_Rows", dq_dimension="Uniqueness", test_scope="table")
    assert rule_scope(term, test_type) is RuleScope.TABLE
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["arguments"] == {"properties": ["order_id", "line_no"]}


def test_dupe_rows_with_no_grouping_attaches_to_the_table_and_lists_nothing():
    term = _term(test_type="Dupe_Rows", groupby_names=None)
    test_type = _test_type("Dupe_Rows", dq_dimension="Uniqueness", test_scope="table")
    assert rule_scope(term, test_type) is RuleScope.TABLE
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert "arguments" not in rule


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


def test_a_custom_rule_carries_parameters_the_test_type_declares_and_nothing_else():
    term = _term(
        test_type="Avg_Shift", baseline_value_ct="4821", baseline_avg="142.7",
        baseline_sd="31.2", threshold_value="0.5", schema_name="sales", table_name="orders",
        column_name="amount",
    )
    test_type = _test_type(
        "Avg_Shift", dq_dimension="Consistency",
        default_parm_columns="baseline_value_ct,baseline_avg,baseline_sd,threshold_value",
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["type"] == "custom"
    assert rule["engine"] == "testgen"
    assert rule["implementation"] == {
        "baseline_value_ct": "4821", "baseline_avg": "142.7",
        "baseline_sd": "31.2", "threshold_value": "0.5",
    }


def test_a_custom_rule_implementation_omits_the_subject():
    """The subject is where the rule nests, so schema/table/column never ride in the payload."""
    term = _term(
        test_type="Avg_Shift", threshold_value="0.5",
        schema_name="sales", table_name="orders", column_name="amount",
    )
    test_type = _test_type(
        "Avg_Shift", dq_dimension="Consistency",
        default_parm_columns="schema_name,table_name,column_name,threshold_value",
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert set(rule["implementation"]) & {"schema_name", "table_name", "column_name"} == set()


def test_a_custom_rule_carries_no_comparison_operator():
    term = _term(test_type="Avg_Shift", threshold_value="0.5")
    test_type = _test_type("Avg_Shift", dq_dimension="Consistency", default_parm_columns="threshold_value")
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert not [key for key in rule if key.startswith("mustBe")]


def test_a_custom_query_term_carries_its_query_as_a_parameter():
    term = _term(test_type="CUSTOM", custom_query="SELECT * FROM t WHERE x < 0")
    test_type = _test_type("CUSTOM", dq_dimension="Accuracy", default_parm_columns="custom_query,match_column_names")
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["type"] == "custom"
    assert rule["implementation"]["custom_query"] == "SELECT * FROM t WHERE x < 0"


def test_a_custom_rule_description_states_the_check_and_the_threshold():
    term = _term(test_type="Avg_Shift", threshold_value="0.5")
    test_type = _test_type(
        "Avg_Shift", dq_dimension="Consistency", default_parm_columns="threshold_value",
        test_description="Tests for statistically significant shift in mean value for column "
        "from average calculated at baseline.",
        except_message="Standardized difference between averages is over the selected threshold level.",
        threshold_description="Standardized Difference Measure",
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["description"] == (
        "Tests for statistically significant shift in mean value for column from average "
        "calculated at baseline. Fails: Standardized difference between averages is over the "
        "selected threshold level. Threshold: 0.5 (Standardized Difference Measure)."
    )
    assert "threshold_value" not in rule["description"]


def test_a_description_omits_the_threshold_clause_when_the_term_has_none():
    term = _term(test_type="Combo_Match", threshold_value=None)
    test_type = _test_type(
        "Combo_Match", dq_dimension="Consistency", default_parm_columns="subset_condition",
        test_description="Tests for the presence of one or a set of column values in reference dataset.",
        except_message="Column value combinations are not found in reference table values.",
        threshold_description="Expected count of non-matching value combinations",
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["description"].endswith("not found in reference table values.")
    assert "Threshold:" not in rule["description"]


def test_a_description_omits_catalogue_segments_that_are_absent():
    """A NULL catalogue field must not reach a counterparty as the string "None"."""
    term = _term(test_type="Avg_Shift", threshold_value="0.5")
    test_type = _test_type(
        "Avg_Shift", dq_dimension="Consistency", default_parm_columns="threshold_value",
        test_description=None, except_message=None, threshold_description=None,
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert "None" not in rule["description"]


def test_a_non_numeric_threshold_renders_as_stored():
    """LOV_All stores a pipe-delimited list, not a number."""
    term = _term(test_type="LOV_All", threshold_value="'Val1|Val2'")
    test_type = _test_type(
        "LOV_All", dq_dimension="Validity", default_parm_columns="threshold_value",
        test_description="Tests that column values match pipe-delimited list of expected values.",
        except_message="Column values do not exactly match expected list of values.",
        threshold_description="Sorted list of all distinct expected values",
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert "Threshold: 'Val1|Val2'" in rule["description"]


def test_a_type_declaring_no_parameters_still_renders_an_empty_implementation():
    """The schema requires `implementation` on a custom rule; an empty object is valid."""
    term = _term(test_type="Table_Freshness")
    test_type = _test_type("Table_Freshness", dq_dimension="Timeliness", default_parm_columns=None)
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["implementation"] == {}


@pytest.mark.parametrize(
    ("test_type", "operator"),
    [
        ("Required", "mustBeLessOrEqualTo"),
        ("LOV_Match", "mustBeLessOrEqualTo"),
        ("Pattern_Match", "mustBeLessOrEqualTo"),
        ("Row_Ct", "mustBeGreaterOrEqualTo"),
    ],
)
def test_a_single_bound_library_term_renders_its_own_threshold(test_type, operator):
    baseline_value = "('x')" if test_type == "LOV_Match" else "x"
    term = _term(
        test_type=test_type, baseline_value=baseline_value, threshold_value="4217", contract_term_id="term-threshold"
    )
    rule = project_rule(term, _test_type(test_type), ServerType.POSTGRES)
    assert rule[operator] == 4217


def test_a_list_of_values_term_unescapes_a_quote_inside_a_value():
    term = _term(test_type="LOV_Match", baseline_value="('it''s','N')", threshold_value="0")
    rule = project_rule(term, _test_type("LOV_Match", dq_dimension="Validity"), ServerType.POSTGRES)

    assert rule["arguments"] == {"validValues": ["it's", "N"]}


def test_a_pattern_term_keeps_its_pattern_as_a_string():
    term = _term(test_type="Pattern_Match", baseline_value="[A-Z][0-9]{4}", threshold_value="0")
    rule = project_rule(term, _test_type("Pattern_Match", dq_dimension="Validity"), ServerType.POSTGRES)

    assert rule["arguments"] == {"pattern": "[A-Z][0-9]{4}"}


def test_groupby_columns_strips_identifier_quoting_for_one_column():
    assert _groupby_columns(_term(groupby_names='"id"')) == ["id"]


def test_groupby_columns_strips_identifier_quoting_for_several_columns():
    assert _groupby_columns(_term(groupby_names='"id", "status",code')) == ["id", "status", "code"]


def test_groupby_columns_collapses_escaped_quotes():
    assert _groupby_columns(_term(groupby_names='"a""b"')) == ['a"b']


def test_a_dupe_rows_term_with_quoted_groupby_names_renders_unquoted_properties():
    term = _term(test_type="Dupe_Rows", column_name=None, groupby_names='"id", "status"', threshold_value="0")
    rule = project_rule(term, _test_type("Dupe_Rows", dq_dimension="Uniqueness"), ServerType.POSTGRES)

    assert rule["arguments"] == {"properties": ["id", "status"]}


@pytest.mark.parametrize(("lower", "upper", "operators"), [
    ("1", "10", {"mustBeBetween": [1, 10]}),
    ("5", "5", {"mustBe": 5}),
    ("", "10", {"mustBeLessOrEqualTo": 10}),
    ("2.5", None, {"mustBeGreaterOrEqualTo": 2.5}),
])
def test_sql_metric_renders_its_own_query_against_its_own_bounds(lower, upper, operators):
    term = _term(
        test_type="SQL_Metric", column_name=None, schema_name="sales", lower_tolerance=lower, upper_tolerance=upper,
        custom_query="SELECT COUNT(*) AS late FROM {DATA_SCHEMA}.orders WHERE shipped IS NULL;\n",
    )

    rule = project_rule(term, _test_type("SQL_Metric", dq_dimension="Accuracy"), ServerType.POSTGRES)

    assert rule["type"] == "sql"
    assert rule["query"] == "SELECT COUNT(*) AS late FROM sales.orders WHERE shipped IS NULL"
    assert {key: value for key, value in rule.items() if key.startswith("must")} == operators
    assert rule["dimension"] == "accuracy"


def test_match_null_ct_must_equal_its_baseline_count():
    term = _term(test_type="Match_Null_Ct", baseline_ct="12")
    rule = project_rule(term, _test_type("Match_Null_Ct"), ServerType.POSTGRES)
    assert (rule["metric"], rule["unit"], rule["mustBe"]) == ("nullValues", "rows", 12)


def test_match_row_ct_must_equal_its_threshold():
    term = _term(test_type="Match_Row_Ct", column_name=None, threshold_value="600")
    rule = project_rule(term, _test_type("Match_Row_Ct"), ServerType.POSTGRES)
    assert (rule["metric"], rule["mustBe"]) == ("rowCount", 600)


@pytest.mark.parametrize(("baseline", "arguments"), [
    ('"",N/A,"a,b"', {"arguments": {"missingValues": ["", "N/A", "a,b"]}}),
    ("", {}),
])
def test_required_no_placeholder_lists_its_placeholders_as_missing_values(baseline, arguments):
    term = _term(test_type="Required_No_Placeholder", baseline_value=baseline, threshold_value="2")
    rule = project_rule(term, _test_type("Required_No_Placeholder"), ServerType.POSTGRES)
    assert rule["metric"] == "missingValues"
    assert {key: rule[key] for key in ("arguments",) if key in rule} == arguments
    assert rule["mustBeLessOrEqualTo"] == 2


@pytest.mark.parametrize(("test_type", "argument"), [
    ("Email_Format", {"pattern": quality_rules.EMAIL_PATTERN}),
    ("Valid_US_Zip", {"pattern": quality_rules.US_ZIP_PATTERN}),
    ("Valid_US_Zip3", {"pattern": quality_rules.US_ZIP3_PATTERN}),
    ("US_State", {"validValues": list(quality_rules.US_STATE_VALID_VALUES)}),
])
def test_a_fixed_predicate_type_renders_its_own_predicate(test_type, argument):
    rule = project_rule(_term(test_type=test_type, threshold_value="3"), _test_type(test_type), ServerType.POSTGRES)
    assert (rule["metric"], rule["arguments"], rule["mustBeLessOrEqualTo"]) == ("invalidValues", argument, 3)


@pytest.mark.parametrize(("server_type", "shape"), [
    (ServerType.POSTGRES, "library"), (ServerType.SNOWFLAKE, "library"),
    (ServerType.SQLSERVER, "custom"), (ServerType.BIGQUERY, "custom"),
])
def test_email_format_is_a_pattern_rule_only_where_its_measure_checks_that_pattern(server_type, shape):
    rule = project_rule(_term(test_type="Email_Format"), _test_type("Email_Format"), server_type)
    assert rule["type"] == shape
