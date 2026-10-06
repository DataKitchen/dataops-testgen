import copy
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.odcs import render
from testgen.common.odcs.quality_rules import CatCondition
from testgen.common.odcs.render import OrphanedTermError, render_document
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND
from testgen.common.odcs.validation import validate_document
from tests.unit.sql_assertions import conjuncts, emitted_statements, equality_conjunct, scopes_to_a_version

pytestmark = pytest.mark.unit


def _version(**overrides) -> SuiteVersion:
    defaults = {
        "id": uuid4(),
        "test_suite_id": uuid4(),
        "version": 1,
        "metadata_document": {
            "apiVersion": ODCS_API_VERSION,
            "kind": ODCS_KIND,
            "id": "contract-1",
            "version": "1.0.0",
            "schema": [],
        },
        "odcs_api_version": ODCS_API_VERSION,
    }
    defaults.update(overrides)
    return SuiteVersion(**defaults)


def _term(**overrides) -> TestDefinition:
    defaults = {
        "test_type": "Required",
        "contract_term_id": "term-1",
        "schema_name": "public",
        "table_name": "orders",
        "column_name": "amount",
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


def _table_group() -> TableGroup:
    return TableGroup(id=uuid4(), connection_id=1)


def _all_rules(document: dict) -> list[dict]:
    """Every rule dict in the document, wherever it is attached -- table level or column
    level -- flattened into one list."""
    rules = []
    for table in document.get("schema", []):
        rules.extend(table.get("quality", []))
        for prop in table.get("properties", []):
            rules.extend(prop.get("quality", []))
    return rules


def _property_named(document: dict, name: str) -> dict:
    for table in document.get("schema", []):
        for prop in table.get("properties", []):
            if prop.get("name") == name:
                return prop
    raise AssertionError(f"no property named {name!r} in the rendered document")


def _patched(*, terms, test_types, flavor="postgresql", conditions=None, column_types=None):
    return (
        patch.object(render, "_terms_for_version", return_value=terms),
        patch.object(render, "_test_types_for", return_value=test_types),
        patch.object(render, "_table_group_for", return_value=_table_group()),
        patch.object(render, "_flavor_for", return_value=flavor),
        patch.object(render, "_conditions_for", return_value=conditions or {}),
        patch.object(render, "_column_types_for", return_value=column_types or {}),
    )


def _render_with(*, terms, test_types, **kwargs):
    version = kwargs.pop("version", None) or _version()
    patchers = _patched(terms=terms, test_types=test_types, **kwargs)
    with patchers[0], patchers[1], patchers[2], patchers[3], patchers[4], patchers[5]:
        return render_document(version)


def test_a_table_level_term_lands_on_the_table_node():
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(test_type="Row_Ct", column_name=None, table_name="orders", threshold_value="10", contract_term_id="term-row-ct")
    test_types = {"Row_Ct": _test_type("Row_Ct", test_scope="table", dq_dimension="Completeness")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    table = rendered["schema"][0]
    assert table.get("properties", []) == []
    assert [rule["id"] for rule in table["quality"]] == ["term-row-ct"]


def test_a_column_level_term_lands_on_its_column_node():
    version = _version(
        metadata_document={"schema": [{"name": "orders", "properties": [{"name": "amount"}]}]}
    )
    term = _term(test_type="Required", column_name="amount", table_name="orders", threshold_value="0", contract_term_id="term-required")
    test_types = {"Required": _test_type("Required", test_scope="column", dq_dimension="Completeness")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    table = rendered["schema"][0]
    assert table.get("quality", []) == []
    assert len(table["properties"]) == 1
    assert [rule["id"] for rule in table["properties"][0]["quality"]] == ["term-required"]


def test_rules_are_never_a_root_key():
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(test_type="Row_Ct", column_name=None, table_name="orders", threshold_value="10", contract_term_id="term-row-ct")
    test_types = {"Row_Ct": _test_type("Row_Ct", test_scope="table", dq_dimension="Completeness")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    assert "quality" not in rendered


def test_a_term_whose_subject_is_an_expression_lands_under_a_measure_property():
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(
        test_type="Avg_Shift",
        column_name="SUM(total_amount)",
        table_name="orders",
        threshold_value="5",
        contract_term_id="term-avg-shift",
    )
    test_types = {"Avg_Shift": _test_type("Avg_Shift", test_scope="column", dq_dimension="Consistency")}
    condition = CatCondition(measure="AVG({COLUMN_NAME})", test_operator=">=", test_condition="{THRESHOLD_VALUE}")

    rendered = _render_with(
        version=version, terms=[term], test_types=test_types, conditions={"Avg_Shift": condition}
    )

    prop = _property_named(rendered, "SUM_total_amount")
    assert prop["semanticType"] == "measure"
    assert prop["logicalType"] == "number"
    assert prop["transformLogic"] == "SUM(total_amount)"
    assert [rule["id"] for rule in prop["quality"]] == ["term-avg-shift"]


def test_a_table_scoped_term_with_a_column_name_still_lands_on_the_table_node():
    # Condition_Flag is TABLE-scoped in RULE_MAPPINGS, but its column_name_prompt ("Test
    # Focus") means a term ordinarily carries a free-text label there -- not a real column --
    # to distinguish several Condition_Flag terms on the same table. Placement must follow the
    # mapping's own scope, not this column_name, or the common case fabricates a property
    # representing no real column.
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(
        test_type="Condition_Flag", column_name="Quantity Consistency", table_name="orders",
        threshold_value="0", custom_query="quantity_ordered <> quantity_shipped",
        contract_term_id="term-condition-flag",
    )
    test_types = {"Condition_Flag": _test_type("Condition_Flag", test_scope="custom", dq_dimension="Validity")}
    condition = CatCondition(
        measure="SUM(CASE WHEN {CUSTOM_QUERY} THEN 1 ELSE 0 END)",
        test_operator=">", test_condition="{THRESHOLD_VALUE}",
    )

    rendered = _render_with(
        version=version, terms=[term], test_types=test_types, conditions={"Condition_Flag": condition}
    )

    table = rendered["schema"][0]
    assert table.get("properties", []) == []
    assert [rule["id"] for rule in table["quality"]] == ["term-condition-flag"]


def test_a_routing_deferred_term_whose_column_name_is_a_label_lands_on_the_table_node():
    # CUSTOM's column_name_prompt is "Test Focus" -- the same free-text label Condition_Flag
    # carries. Condition_Flag is placed correctly because it has a RULE_MAPPINGS row declaring
    # TABLE; CUSTOM has none, so it needs its own declared scope to reach the same node.
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(
        test_type="CUSTOM", column_name="Order Total Matches Detail", table_name="orders",
        custom_query="SELECT 1", contract_term_id="term-custom",
    )
    test_types = {"CUSTOM": _test_type("CUSTOM", test_scope="custom", dq_dimension="Accuracy")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    table = rendered["schema"][0]
    assert table.get("properties", []) == []
    assert [rule["id"] for rule in table["quality"]] == ["term-custom"]


def test_a_routing_deferred_term_whose_column_name_is_a_column_list_lands_on_the_table_node():
    # Combo_Match's column_name_prompt is "Categorical Column List" -- one *or more* columns,
    # comma-separated. A list is neither a column nor an expression, so there is no property
    # for the rule to hang on, and slugifying it would mint one named after the whole list.
    version = _version(
        metadata_document={
            "schema": [{"name": "customers", "properties": [{"name": "city"}, {"name": "state"}]}]
        }
    )
    term = _term(
        test_type="Combo_Match", column_name="city,state", table_name="customers",
        match_schema_name="reference", match_table_name="regions", contract_term_id="term-combo",
    )
    test_types = {"Combo_Match": _test_type("Combo_Match", test_scope="referential", dq_dimension="Validity")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    table = rendered["schema"][0]
    assert [rule["id"] for rule in table["quality"]] == ["term-combo"]
    assert [prop["name"] for prop in table["properties"]] == ["city", "state"]
    assert all("quality" not in prop for prop in table["properties"])


def test_a_routing_deferred_column_scoped_term_with_no_column_name_is_refused():
    # Unique is COLUMN-scoped and pending. Before pending types declared a scope, this term
    # fell to the column_name heuristic and landed on the table; now it reaches the same
    # refusal a routed column-scoped term with no column_name gets.
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(test_type="Unique", column_name=None, table_name="orders", contract_term_id="term-unique")
    test_types = {"Unique": _test_type("Unique", test_scope="column", dq_dimension="Uniqueness")}

    with pytest.raises(OrphanedTermError, match="column-scoped but carries no column_name"):
        _render_with(version=version, terms=[term], test_types=test_types)


def test_two_terms_sharing_an_unmatched_subject_reuse_the_same_synthesized_property():
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    condition = CatCondition(measure="AVG({COLUMN_NAME})", test_operator=">=", test_condition="{THRESHOLD_VALUE}")
    terms = [
        _term(
            test_type="Avg_Shift", column_name="SUM(total_amount)", table_name="orders",
            threshold_value="5", contract_term_id="term-avg-shift-1",
        ),
        _term(
            test_type="Avg_Shift", column_name="SUM(total_amount)", table_name="orders",
            threshold_value="7", contract_term_id="term-avg-shift-2",
        ),
    ]
    test_types = {"Avg_Shift": _test_type("Avg_Shift", test_scope="column", dq_dimension="Consistency")}

    rendered = _render_with(
        version=version, terms=terms, test_types=test_types, conditions={"Avg_Shift": condition}
    )

    table = rendered["schema"][0]
    assert len(table["properties"]) == 1
    prop = table["properties"][0]
    assert prop["name"] == "SUM_total_amount"
    assert [rule["id"] for rule in prop["quality"]] == ["term-avg-shift-1", "term-avg-shift-2"]


def test_a_declared_column_named_like_a_slug_does_not_capture_an_unmatched_subjects_rule():
    # "SUM_total_amount" is declared as an ordinary real column here -- it is not something
    # this renderer synthesized. A term whose expression subject slugifies to that same name
    # must still get its own synthesized property; the declared column is a coincidence, not a
    # stand-in for the term's subject, and its quality must stay untouched.
    version = _version(
        metadata_document={"schema": [{"name": "orders", "properties": [{"name": "SUM_total_amount"}]}]}
    )
    term = _term(
        test_type="Avg_Shift", column_name="SUM(total_amount)", table_name="orders",
        threshold_value="5", contract_term_id="term-avg-shift",
    )
    test_types = {"Avg_Shift": _test_type("Avg_Shift", test_scope="column", dq_dimension="Consistency")}
    condition = CatCondition(measure="AVG({COLUMN_NAME})", test_operator=">=", test_condition="{THRESHOLD_VALUE}")

    rendered = _render_with(
        version=version, terms=[term], test_types=test_types, conditions={"Avg_Shift": condition}
    )

    table = rendered["schema"][0]
    assert len(table["properties"]) == 2
    declared_column = next(prop for prop in table["properties"] if "transformLogic" not in prop)
    assert "quality" not in declared_column
    synthesized_property = next(prop for prop in table["properties"] if prop.get("transformLogic") == "SUM(total_amount)")
    assert [rule["id"] for rule in synthesized_property["quality"]] == ["term-avg-shift"]


def test_the_rendered_rule_count_equals_the_term_count():
    # Two pre-existing retained rules -- one on the table, one on a column -- prove the count
    # asserted below is a *delta* over what the document already carried, not a recount of
    # whatever the renderer happens to have produced.
    retained_table_rule = {
        "id": "retained-table-rule", "type": "text",
        "customProperties": [{"property": "verifiable", "value": False, "vendor": "testgen"}],
    }
    retained_column_rule = {
        "id": "retained-column-rule", "type": "text",
        "customProperties": [{"property": "verifiable", "value": False, "vendor": "testgen"}],
    }
    version = _version(
        metadata_document={
            "schema": [
                {
                    "name": "orders",
                    "quality": [retained_table_rule],
                    "properties": [{"name": "amount", "quality": [retained_column_rule]}],
                }
            ]
        }
    )
    terms = [
        _term(test_type="Row_Ct", column_name=None, table_name="orders", threshold_value="10", contract_term_id="term-row-ct"),
        _term(test_type="Required", column_name="amount", table_name="orders", threshold_value="0", contract_term_id="term-required"),
        _term(
            test_type="Avg_Shift", column_name="SUM(total_amount)", table_name="orders",
            threshold_value="5", contract_term_id="term-avg-shift",
        ),
        _term(test_type="Unique", column_name="amount", table_name="orders", contract_term_id="term-unique"),
    ]
    test_types = {
        "Row_Ct": _test_type("Row_Ct", test_scope="table", dq_dimension="Completeness"),
        "Required": _test_type("Required", test_scope="column", dq_dimension="Completeness"),
        "Avg_Shift": _test_type("Avg_Shift", test_scope="column", dq_dimension="Consistency"),
        "Unique": _test_type("Unique", test_scope="column", dq_dimension="Uniqueness"),
    }
    condition = CatCondition(measure="AVG({COLUMN_NAME})", test_operator=">=", test_condition="{THRESHOLD_VALUE}")

    rendered = _render_with(
        version=version, terms=terms, test_types=test_types, conditions={"Avg_Shift": condition}
    )

    assert len(_all_rules(rendered)) == 2 + len(terms)
    rendered_ids = {rule["id"] for rule in _all_rules(rendered)}
    assert {term.contract_term_id for term in terms} <= rendered_ids
    assert {"retained-table-rule", "retained-column-rule"} <= rendered_ids


def test_a_retained_unverifiable_rule_survives_the_merge():
    retained_rule = {
        "id": "retained-table-rule", "type": "text",
        "customProperties": [{"property": "verifiable", "value": False, "vendor": "testgen"}],
    }
    version = _version(metadata_document={"schema": [{"name": "orders", "quality": [retained_rule]}]})
    term = _term(test_type="Row_Ct", column_name=None, table_name="orders", threshold_value="10", contract_term_id="term-row-ct")
    test_types = {"Row_Ct": _test_type("Row_Ct", test_scope="table", dq_dimension="Completeness")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    table = rendered["schema"][0]
    assert len(table["quality"]) == 2
    assert table["quality"][0] == retained_rule


def test_a_list_of_values_term_declares_the_columns_enum_as_well_as_its_rule():
    version = _version(
        metadata_document={"schema": [{"name": "orders", "properties": [{"name": "status"}]}]}
    )
    term = _term(
        test_type="LOV_Match", column_name="status", table_name="orders",
        baseline_value="('Y','N')", threshold_value="0", contract_term_id="term-lov",
    )
    test_types = {"LOV_Match": _test_type("LOV_Match", test_scope="column", dq_dimension="Validity")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    prop = _property_named(rendered, "status")
    assert prop["enum"] == [{"value": "Y"}, {"value": "N"}]
    assert [rule["id"] for rule in prop["quality"]] == ["term-lov"]


def test_an_already_declared_enum_is_not_overwritten():
    version = _version(
        metadata_document={
            "schema": [
                {
                    "name": "orders",
                    "properties": [{"name": "status", "enum": [{"value": "PRE_EXISTING"}]}],
                }
            ]
        }
    )
    term = _term(
        test_type="LOV_Match", column_name="status", table_name="orders",
        baseline_value="('Y','N')", threshold_value="0", contract_term_id="term-lov",
    )
    test_types = {"LOV_Match": _test_type("LOV_Match", test_scope="column", dq_dimension="Validity")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    prop = _property_named(rendered, "status")
    assert prop["enum"] == [{"value": "PRE_EXISTING"}]
    assert [rule["id"] for rule in prop["quality"]] == ["term-lov"]


def test_a_term_whose_table_is_not_declared_raises_rather_than_being_dropped():
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(test_type="Row_Ct", column_name=None, table_name="missing_table", threshold_value="10", contract_term_id="term-orphan")
    test_types = {"Row_Ct": _test_type("Row_Ct", test_scope="table", dq_dimension="Completeness")}

    patchers = _patched(terms=[term], test_types=test_types)
    with patchers[0], patchers[1], patchers[2], patchers[3], patchers[4], patchers[5]:
        with pytest.raises(OrphanedTermError):
            render_document(version)


def test_a_column_scoped_term_with_no_column_name_raises_rather_than_landing_on_the_table():
    # Alpha_Trunc is sql-shape and COLUMN-scoped, so project_rule's query carries `{property}`.
    # Generation always sets column_name for a column-scoped type, so a term missing it here
    # only arrives through the test-definition import or a hand-authored row -- but landing it
    # on the table node would carry a `{property}` placeholder nothing there can resolve.
    version = _version(metadata_document={"schema": [{"name": "orders"}]})
    term = _term(
        test_type="Alpha_Trunc", column_name=None, table_name="orders",
        threshold_value="5", contract_term_id="term-alpha-trunc",
    )
    test_types = {"Alpha_Trunc": _test_type("Alpha_Trunc", test_scope="column", dq_dimension="Validity")}

    patchers = _patched(terms=[term], test_types=test_types)
    with patchers[0], patchers[1], patchers[2], patchers[3], patchers[4], patchers[5]:
        with pytest.raises(OrphanedTermError):
            render_document(version)


def test_the_required_root_keys_are_filled_when_the_document_lacks_them():
    version = _version(metadata_document={}, odcs_api_version=None, version=3)

    rendered = _render_with(version=version, terms=[], test_types={})

    assert {"apiVersion", "kind", "id", "version"} <= set(rendered)
    assert rendered["kind"] == ODCS_KIND
    assert rendered["id"] == str(version.test_suite_id)
    assert rendered["version"] == "3.0.0"
    assert rendered["apiVersion"] == ODCS_API_VERSION


def test_an_authored_root_value_is_not_overwritten():
    version = _version(
        metadata_document={"kind": "SomethingElse", "apiVersion": "v9.9.9"}, odcs_api_version=ODCS_API_VERSION
    )

    rendered = _render_with(version=version, terms=[], test_types={})

    assert rendered["kind"] == "SomethingElse"
    assert rendered["apiVersion"] == "v9.9.9"


def test_rendering_does_not_mutate_the_stored_document():
    version = _version(
        metadata_document={"schema": [{"name": "orders", "properties": [{"name": "amount"}]}]}
    )
    before = copy.deepcopy(version.metadata_document)
    term = _term(test_type="Required", column_name="amount", table_name="orders", threshold_value="0", contract_term_id="term-required")
    test_types = {"Required": _test_type("Required", test_scope="column", dq_dimension="Completeness")}

    rendered = _render_with(version=version, terms=[term], test_types=test_types)

    assert version.metadata_document == before
    assert rendered != version.metadata_document


def test_terms_are_read_by_the_named_version_not_the_resolved_one():
    session = MagicMock()
    session.scalars.return_value = []
    version = _version(metadata_document={"schema": []})

    with patch.object(render, "get_current_session", return_value=session):
        render_document(version)

    statement = emitted_statements(session)[0]
    assert not scopes_to_a_version(statement)
    assert any(
        equality_conjunct(term, "version_id", "test_definitions", version.id)
        for term in conjuncts(statement.whereclause)
    )


def test_a_rendered_document_with_several_tables_and_both_rule_scopes_validates():
    # The definition-of-done shape: several tables, a table-level and a column-level rule, an
    # expression subject, a retained unverifiable rule already in the stored document, and user
    # keys in a term's custom_metadata -- rendered and validated in strict mode together, since
    # that combination is what would have caught each of them landing wrong on its own.
    retained_rule = {
        "id": "retained-table-rule", "type": "text",
        "customProperties": [{"property": "verifiable", "value": False, "vendor": "testgen"}],
    }
    version = _version(
        metadata_document={
            "schema": [
                {
                    "name": "orders",
                    "quality": [retained_rule],
                    "properties": [{"name": "amount"}, {"name": "status"}],
                },
                {"name": "customers", "properties": [{"name": "email"}]},
            ]
        }
    )
    terms = [
        _term(test_type="Row_Ct", column_name=None, table_name="orders", threshold_value="10", contract_term_id="term-row-ct"),
        _term(
            test_type="LOV_Match", column_name="status", table_name="orders",
            baseline_value="('Y','N')", threshold_value="0", contract_term_id="term-lov",
        ),
        _term(
            test_type="Avg_Shift", column_name="SUM(total_amount)", table_name="orders",
            threshold_value="5", contract_term_id="term-avg-shift",
            custom_metadata={"team": "data-eng"},
        ),
        _term(test_type="Required", column_name="email", table_name="customers", threshold_value="0", contract_term_id="term-required"),
        _term(test_type="Unique", column_name="email", table_name="customers", contract_term_id="term-pending"),
    ]
    test_types = {
        "Row_Ct": _test_type("Row_Ct", test_scope="table", dq_dimension="Completeness"),
        "LOV_Match": _test_type("LOV_Match", test_scope="column", dq_dimension="Validity"),
        "Avg_Shift": _test_type("Avg_Shift", test_scope="column", dq_dimension="Consistency"),
        "Required": _test_type("Required", test_scope="column", dq_dimension="Completeness"),
        "Unique": _test_type("Unique", test_scope="column", dq_dimension="Uniqueness"),
    }
    condition = CatCondition(measure="AVG({COLUMN_NAME})", test_operator=">=", test_condition="{THRESHOLD_VALUE}")

    rendered = _render_with(
        version=version, terms=terms, test_types=test_types, conditions={"Avg_Shift": condition}
    )

    assert validate_document(rendered, version.odcs_api_version) == []
    assert rendered["schema"][0]["quality"][0] == retained_rule
    prop = _property_named(rendered, "SUM_total_amount")
    rule = prop["quality"][0]
    assert {"property": "team", "value": "data-eng"} in rule["customProperties"]
