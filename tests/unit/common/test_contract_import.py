from contextlib import ExitStack
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import yaml

from testgen.common import contract_import
from testgen.common.contract_import import (
    AUTHORED_PHYSICAL_TYPE,
    ContractIdentityError,
    ContractTermReason,
    IncomingTerm,
    _BaselineTerm,
    _custom_metadata,
    _match_physical_types,
    check_identity,
    parse_document,
    plan_changes,
    server_type_warning,
    split_document,
)
from testgen.common.contract_service import InvalidContractDocumentError
from testgen.common.flavors import SqlFlavorCode
from testgen.common.models.test_definition import TestType
from testgen.common.odcs.quality_rules import is_unverifiable_marker
from testgen.common.test_definition_export_import_service import ImportAction

pytestmark = pytest.mark.unit

MODULE = "testgen.common.contract_import"

_PARAMETERS = {
    "Required": "threshold_value",
    "Max_Val": "baseline_value,threshold_value",
    "Unique": "threshold_value",
    "Dupe_Rows": "groupby_names,skip_errors",
    "SQL_Metric": "custom_query,lower_tolerance,upper_tolerance",
    "Row_Ct": "threshold_value",
    "Text_Length_Range": "lower_tolerance,upper_tolerance,threshold_value",
    "Avg_Shift": "baseline_value_ct,baseline_avg,baseline_sd,threshold_value",
    "LOV_Match": "baseline_value,threshold_value",
    "Condition_Flag": "custom_query,threshold_value",
}
_TABLE_SCOPED = {"Dupe_Rows", "SQL_Metric", "Row_Ct", "Schema_Conformance"}
_CUSTOM_SCOPED = {"Condition_Flag"}
_TEST_TYPES = {
    code: TestType(
        test_type=code, default_parm_columns=columns, test_name_short=code.replace("_", " "),
        test_scope="table" if code in _TABLE_SCOPED else "custom" if code in _CUSTOM_SCOPED else "column",
    )
    for code, columns in {**_PARAMETERS, "Schema_Conformance": ""}.items()
}
_DECLARED = {code: columns.split(",") for code, columns in _PARAMETERS.items()}


def _document(**overrides) -> dict:
    document = {
        "apiVersion": "v3.2.0",
        "kind": "DataContract",
        "id": "orders-contract",
        "version": "2.0.0",
        "name": "Orders",
        "status": "active",
        "schema": [
            {
                "name": "orders",
                "quality": [
                    {"id": "orders-rows", "metric": "rowCount", "unit": "rows", "mustBeGreaterOrEqualTo": 1},
                    {"type": "text", "description": "Orders arrive by 6am."},
                ],
                "properties": [
                    {
                        "name": "email",
                        "logicalType": "string",
                        "quality": [
                            {"id": "email-nulls", "metric": "nullValues", "unit": "rows", "mustBeLessOrEqualTo": 0},
                            {"metric": "duplicateValues", "unit": "percent", "mustBeLessOrEqualTo": 1},
                        ],
                    },
                    {"name": "amount", "logicalType": "number", "logicalTypeOptions": {"maximum": 500}},
                ],
            }
        ],
    }
    document.update(overrides)
    return document


def _split(document: dict) -> contract_import.SplitDocument:
    return split_document(document, _TEST_TYPES, flavor=SqlFlavorCode.POSTGRESQL, qualify_tables=True)


# --- parsing ---


def test_a_payload_that_is_not_yaml_is_refused():
    with pytest.raises(InvalidContractDocumentError, match="not valid YAML"):
        parse_document("a: [unclosed")


def test_a_document_that_does_not_validate_is_refused_with_every_problem():
    with pytest.raises(InvalidContractDocumentError) as excinfo:
        parse_document(yaml.safe_dump({"apiVersion": "v3.2.0", "kind": "NotAContract"}))

    assert len(excinfo.value.problems) >= 2


def test_a_document_declaring_v3_1_validates_against_v3_1():
    document = _document(apiVersion="v3.1.0")

    assert parse_document(yaml.safe_dump(document))["apiVersion"] == "v3.1.0"


# --- splitting ---


def test_resolved_rules_become_terms_and_leave_the_document():
    split = _split(_document())

    assert sorted((term.test_type, term.column_name, term.contract_term_id) for term in split.terms) == [
        ("Max_Val", "amount", None),
        ("Required", "email", "email-nulls"),
        ("Row_Ct", None, "orders-rows"),
    ]
    table = split.metadata_document["schema"][0]
    assert [rule["type"] for rule in table["quality"]] == ["text"]
    assert len(table["properties"][0]["quality"]) == 1


def test_a_rule_no_test_type_checks_stays_in_the_document_marked_unverifiable():
    split = _split(_document())

    table = split.metadata_document["schema"][0]
    kept = [*table["quality"], *table["properties"][0]["quality"]]
    assert all(any(is_unverifiable_marker(entry) for entry in rule["customProperties"]) for rule in kept)
    assert split.unverifiable_rules == [
        "orders: rule 2 (text)",
        "orders.email: rule 2 (library duplicateValues in percent, mustBeLessOrEqualTo)",
    ]


def _property(split: contract_import.SplitDocument, name: str) -> dict:
    return next(prop for prop in split.metadata_document["schema"][0]["properties"] if prop["name"] == name)


def test_a_declaration_that_becomes_a_term_leaves_the_document():
    document = _document()
    document["schema"][0]["properties"][0].update(required=True, unique=False)

    split = _split(document)

    assert "logicalTypeOptions" not in _property(split, "amount")
    assert "required" not in _property(split, "email")
    assert _property(split, "email")["unique"] is False


def test_a_declaration_a_testgen_entry_names_leaves_the_document_with_the_entry():
    document = _document()
    document["schema"][0]["properties"][0].update(required=True, customProperties=[
        {"property": "testgenTerm", "vendor": "testgen",
         "value": {"id": "email-required", "testType": "Required", "declares": ["required"]}},
        {"property": "owner", "value": "ops"},
    ])
    document["schema"][0]["properties"][0]["quality"] = []

    split = _split(document)

    email = _property(split, "email")
    assert "required" not in email
    assert email["customProperties"] == [{"property": "owner", "value": "ops"}]
    assert [(term.test_type, term.contract_term_id) for term in split.terms if term.column_name == "email"] == [
        ("Required", "email-required")
    ]


def test_a_declaration_restating_a_rule_on_its_column_adds_no_second_term():
    document = _document()
    document["schema"][0]["properties"][0]["required"] = True

    split = _split(document)

    assert [(term.test_type, term.contract_term_id) for term in split.terms if term.column_name == "email"] == [
        ("Required", "email-nulls")
    ]
    assert "required" not in _property(split, "email")


def test_a_list_of_values_term_takes_its_columns_enum():
    document = _document()
    document["schema"][0]["properties"].append({
        "name": "status", "logicalType": "string", "enum": [{"value": "Y"}, {"value": "OLD"}],
        "quality": [{"metric": "invalidValues", "unit": "rows", "arguments": {"validValues": ["Y", "N"]},
                     "mustBeLessOrEqualTo": 0}],
    })

    split = _split(document)

    assert "enum" not in _property(split, "status")
    assert [term.test_type for term in split.terms if term.column_name == "status"] == ["LOV_Match"]


def test_a_property_testgen_synthesized_resolves_against_its_subject_and_leaves_the_document():
    document = _document()
    document["schema"][0]["properties"].append({
        "name": "first_name", "semanticType": "measure", "logicalType": "number", "transformLogic": "first name",
        "customProperties": [{"property": "synthesized", "value": True, "vendor": "testgen"}],
        "quality": [
            {"id": "first-nulls", "metric": "nullValues", "unit": "rows", "mustBeLessOrEqualTo": 2},
            {"type": "text", "description": "Names are title case."},
        ],
    })

    split = _split(document)

    assert [prop["name"] for prop in split.metadata_document["schema"][0]["properties"]] == ["email", "amount"]
    term = next(term for term in split.terms if term.contract_term_id == "first-nulls")
    assert term.column_name == "first name"
    assert split.metadata_document["schema"][0]["quality"][-1]["description"] == "Names are title case."


def test_a_declaration_with_no_exact_test_type_is_reported():
    document = _document()
    document["schema"][0]["properties"][0]["unique"] = True

    split = _split(document)

    assert split.unresolved_declarations == ["orders.email: unique"]


def test_an_unverifiable_rule_with_an_empty_unit_is_described_as_written():
    document = _document()
    document["schema"][0]["quality"].append({"metric": "rowCount", "unit": "", "mustBeGreaterThan": 0})

    split = _split(document)

    assert "orders: rule 3 (library rowCount in '', mustBeGreaterThan)" in split.unverifiable_rules


def test_relationships_are_reported_and_kept():
    document = _document()
    document["schema"][0]["properties"][0]["relationships"] = [{"type": "foreignKey", "to": "customers.email"}]
    document["schema"][0]["relationships"] = [
        {"type": "foreignKey", "from": "orders.email", "to": "customers.email"},
    ]

    split = _split(document)

    assert split.unresolved_declarations == ["orders.email: relationships", "orders: relationships"]
    assert split.metadata_document["schema"][0]["relationships"]
    assert split.metadata_document["schema"][0]["properties"][0]["relationships"]


def test_a_quality_list_every_rule_of_which_became_a_term_leaves_the_metadata():
    document = _document()
    document["schema"][0]["quality"] = document["schema"][0]["quality"][:1]
    document["schema"][0]["properties"][0]["quality"] = document["schema"][0]["properties"][0]["quality"][:1]

    split = _split(document)

    table = split.metadata_document["schema"][0]
    assert "quality" not in table
    assert "quality" not in table["properties"][0]


def test_testgen_term_entries_are_dropped_from_the_metadata():
    document = _document()
    document["schema"][0]["properties"][1]["customProperties"] = [{
        "property": "testgenTerm", "vendor": "testgen",
        "value": {"id": "amount-max", "testType": "Max_Val", "declares": ["logicalTypeOptions.maximum"]},
    }]

    split = _split(document)

    assert "customProperties" not in split.metadata_document["schema"][0]["properties"][1]
    assert [term.contract_term_id for term in split.terms if term.test_type == "Max_Val"] == ["amount-max"]


def test_rules_and_declarations_on_nested_properties_are_kept_and_reported():
    document = _document()
    document["schema"][0]["properties"].append({
        "name": "address", "logicalType": "object",
        "properties": [{
            "name": "city", "logicalType": "string", "required": True,
            "quality": [{"id": "city-nulls", "metric": "nullValues", "unit": "rows", "mustBeLessOrEqualTo": 0}],
        }],
    })
    document["schema"][0]["properties"].append({
        "name": "tags", "logicalType": "array",
        "items": {"logicalType": "string", "logicalTypeOptions": {"maxLength": 20}},
    })

    split = _split(document)

    assert not any(term.column_name in ("address", "tags") for term in split.terms)
    city = split.metadata_document["schema"][0]["properties"][2]["properties"][0]
    assert any(is_unverifiable_marker(entry) for entry in city["quality"][0]["customProperties"])
    assert "orders.address.city: city-nulls" in split.unverifiable_rules
    assert split.unresolved_declarations == [
        "orders.address.city: required", "orders.tags.items: logicalTypeOptions.maxLength",
    ]


def test_a_rules_description_is_kept_as_term_metadata():
    document = _document()
    document["schema"][0]["quality"][0]["description"] = "At least one order a day."

    split = _split(document)

    term = next(term for term in split.terms if term.contract_term_id == "orders-rows")
    assert term.metadata == {"description": "At least one order a day."}


def test_a_rule_naming_a_managed_test_type_is_kept_unverifiable():
    document = _document()
    document["schema"][0]["quality"].append({
        "type": "custom", "engine": "testgen", "implementation": {},
        "customProperties": [{"property": "testType", "value": "Schema_Conformance", "vendor": "testgen"}],
    })

    split = _split(document)

    assert "Schema_Conformance" not in {term.test_type for term in split.terms}
    assert "orders: rule 3 (custom for engine testgen)" in split.unverifiable_rules


def test_a_rule_naming_an_inactive_test_type_is_kept_unverifiable():
    document = _document()
    document["schema"][0]["quality"].append({
        "type": "custom", "engine": "testgen",
        "implementation": {"column_name": "Shipped within order", "custom_query": "qty_shipped > qty"},
        "customProperties": [{"property": "testType", "value": "Condition_Flag", "vendor": "testgen"}],
    })
    inactive = TestType(
        test_type="Condition_Flag", default_parm_columns=_PARAMETERS["Condition_Flag"], test_scope="custom", active="N",
    )

    split = split_document(
        document, {**_TEST_TYPES, "Condition_Flag": inactive}, flavor=SqlFlavorCode.POSTGRESQL, qualify_tables=True
    )

    assert "Condition_Flag" not in {term.test_type for term in split.terms}
    assert "orders: rule 3 (custom for engine testgen)" in split.unverifiable_rules


def test_a_custom_rule_takes_its_column_name_from_its_implementation():
    document = _document()
    document["schema"][0]["quality"].append({
        "type": "custom", "engine": "testgen",
        "implementation": {"column_name": "Shipped within order", "custom_query": "qty_shipped > qty"},
        "customProperties": [{"property": "testType", "value": "Condition_Flag", "vendor": "testgen"}],
    })

    split = _split(document)

    term = next(term for term in split.terms if term.test_type == "Condition_Flag")
    assert term.column_name == "Shipped within order"
    assert term.parameters["custom_query"] == "qty_shipped > qty"


def test_a_column_duplicate_rule_names_its_column_in_the_grouping_not_the_column():
    document = _document()
    document["schema"][0]["properties"][0]["quality"][1]["unit"] = "rows"

    split = _split(document)

    term = next(term for term in split.terms if term.test_type == "Dupe_Rows")
    assert term.column_name is None
    assert term.parameters["groupby_names"] == '"email"'


def test_two_rules_sharing_an_id_are_refused():
    document = _document()
    document["schema"][0]["properties"][0]["quality"][0]["id"] = "orders-rows"

    with pytest.raises(InvalidContractDocumentError, match="orders-rows"):
        _split(document)


def test_the_incoming_document_is_not_mutated():
    document = _document()
    snapshot = yaml.safe_dump(document)

    _split(document)

    assert yaml.safe_dump(document) == snapshot


# --- identity ---


def test_a_document_with_another_contract_id_is_refused_naming_both_ids_and_both_remedies():
    with pytest.raises(ContractIdentityError) as excinfo:
        check_identity({"id": "orders-contract"}, "billing-contract")

    message = str(excinfo.value)
    assert "orders-contract" in message
    assert "billing-contract" in message
    assert "change the document's `id`" in message
    assert "import it as a new contract" in message


@pytest.mark.parametrize("target", [None, {}, {"id": None}])
def test_a_target_with_no_id_adopts_the_incoming_one(target):
    check_identity(target, "orders-contract")


# --- server type ---


def _connection(flavor="postgresql"):
    return MagicMock(sql_flavor_code=flavor, connection_name="warehouse")


@pytest.mark.parametrize("servers", [
    [{"server": "a", "type": "postgres"}],
    [{"server": "a", "type": "postgresql"}],
    [{"server": "a", "type": "custom"}],
    [],
    [{"server": "a", "type": "snowflake"}, {"server": "b", "type": "postgres"}],
])
def test_no_warning_when_the_document_declares_the_connections_server_or_none(servers):
    assert server_type_warning({"servers": servers}, _connection()) is None


def test_a_server_of_another_type_warns():
    warning = server_type_warning({"servers": [{"server": "a", "type": "snowflake"}]}, _connection())

    assert "`snowflake`" in warning
    assert "PostgreSQL" in warning


def test_a_connection_with_no_server_type_is_never_warned_on():
    assert server_type_warning({"servers": [{"server": "a", "type": "snowflake"}]}, _connection("files")) is None


# --- reconciliation ---


def _incoming(test_type="Required", column="email", term_id=None, **parameters) -> IncomingTerm:
    return IncomingTerm(
        test_type=test_type, table_name="orders", column_name=column,
        parameters=parameters or {"threshold_value": "0"}, contract_term_id=term_id, metadata={},
    )


def _baseline(test_type="Required", column="email", term_id=None, **values) -> _BaselineTerm:
    return _BaselineTerm(
        id=uuid4(), test_type=test_type, schema_name="public", table_name="orders", column_name=column,
        contract_term_id=term_id, values=values or {"threshold_value": "0"},
    )


def _plan(incoming, baseline):
    return plan_changes(incoming, baseline, schema_name="public", declared_parameters=_DECLARED)


def test_a_term_missing_a_required_field_is_named_by_its_rule_id():
    changes = _plan([
        _incoming("Condition_Flag", column=None, term_id="rule-a", custom_query="qty < 0", threshold_value="0"),
        _incoming("Condition_Flag", column="Valid", term_id="rule-b", custom_query="qty > 9", threshold_value="0"),
    ], [])

    problems = contract_import._invalid_terms(changes, _TEST_TYPES, "public")

    assert problems == ["orders rule rule-a (Condition Flag): column_name required for test type `Condition Flag`"]


def test_a_rule_whose_column_changed_updates_its_term_rather_than_replacing_it():
    existing = _baseline(column="email", term_id="email-nulls")

    changes = _plan([_incoming(column="contact_email", term_id="email-nulls")], [existing])

    assert [(change.action, change.reason, change.target_id) for change in changes] == [
        (ImportAction.update, ContractTermReason.MATCHED_BY_ID, existing.id)
    ]


def test_a_rule_with_no_id_matches_by_test_type_table_and_column():
    existing = _baseline(term_id="minted-id", threshold_value="0")

    changes = _plan([_incoming(threshold_value="5")], [existing])

    assert [(change.action, change.reason, change.contract_term_id) for change in changes] == [
        (ImportAction.update, ContractTermReason.MATCHED_BY_KEY, "minted-id")
    ]


def test_an_identical_term_is_unchanged():
    changes = _plan([_incoming(term_id="email-nulls")], [_baseline(term_id="email-nulls")])

    assert [(change.action, change.reason) for change in changes] == [(ImportAction.skip, ContractTermReason.UNCHANGED)]


@pytest.mark.parametrize(
    ("stored", "incoming", "same"),
    [
        ("2022-02-11 00:00:00", "2022-02-11", True),
        ("2022-02-11T00:00:00.000", "2022-02-11", True),
        ("2022-02-11 08:30:00", "2022-02-11", False),
    ],
)
def test_a_timestamp_at_midnight_compares_as_its_date(stored, incoming, same):
    assert (contract_import._comparable(stored) == contract_import._comparable(incoming)) is same


@pytest.mark.parametrize(
    ("stored", "incoming", "same"),
    [
        ("0.0", "0", True),
        ("-12.000", "-12", True),
        ("2.5", "2", False),
        ("0.50", "0.5", True),
        ("007", "7", False),
    ],
)
def test_a_decimal_compares_without_trailing_zeros(stored, incoming, same):
    assert (contract_import._comparable(stored) == contract_import._comparable(incoming)) is same


@pytest.mark.parametrize(
    ("test_type", "parameter", "same"),
    [
        ("Pattern_Match", "baseline_value", False),
        ("Required_No_Placeholder", "baseline_value", False),
        ("Max_Val", "baseline_value", True),
        ("Pattern_Match", "threshold_value", True),
    ],
)
def test_a_text_parameter_that_reads_as_a_decimal_compares_as_written(test_type, parameter, same):
    declared = {"Pattern_Match": ["baseline_value", "threshold_value"], "Required_No_Placeholder": ["baseline_value"]}

    stored = contract_import._parameter_values(test_type, {parameter: "1.50"}, {**_DECLARED, **declared})
    incoming = contract_import._parameter_values(test_type, {parameter: "1.5"}, {**_DECLARED, **declared})

    assert (stored[parameter] == incoming[parameter]) is same


@pytest.mark.parametrize(("stored", "incoming", "same"), [("'1.50'", "'1.5'", False), ("1.50", "1.5", True)])
def test_a_constant_compares_as_written_when_text_and_as_a_number_otherwise(stored, incoming, same):
    # A text constant is stored as a quoted literal; a bare literal is a number the export writes as one
    declared = {**_DECLARED, "Constant": ["baseline_value"]}

    stored_values = contract_import._parameter_values("Constant", {"baseline_value": stored}, declared)
    incoming_values = contract_import._parameter_values("Constant", {"baseline_value": incoming}, declared)

    assert (stored_values == incoming_values) is same


@pytest.mark.parametrize("stored", [None, ""])
def test_a_blank_threshold_compares_as_the_0_it_runs_as(stored):
    changes = _plan(
        [_incoming(term_id="email-nulls", threshold_value="0")],
        [_baseline(term_id="email-nulls", threshold_value=stored)],
    )

    assert [(change.action, change.reason) for change in changes] == [(ImportAction.skip, ContractTermReason.UNCHANGED)]


def test_a_term_the_document_omits_is_deleted():
    absent = _baseline(test_type="Unique", term_id="email-unique")

    changes = _plan([_incoming(term_id="email-nulls")], [_baseline(term_id="email-nulls"), absent])

    assert [(change.action, change.reason, change.target_id) for change in changes][-1] == (
        ImportAction.delete, ContractTermReason.ABSENT, absent.id,
    )


def test_a_muted_term_the_document_omits_is_left_alone():
    muted = _BaselineTerm(**{**_baseline(test_type="Unique", term_id="email-unique").__dict__, "active": False})

    changes = _plan([_incoming(term_id="email-nulls")], [_baseline(term_id="email-nulls"), muted])

    assert [(change.action, change.contract_term_id) for change in changes] == [(ImportAction.skip, "email-nulls")]


def test_a_muted_term_the_document_states_is_matched_not_duplicated():
    muted = _BaselineTerm(**{**_baseline(term_id="email-nulls").__dict__, "active": False})

    changes = _plan([_incoming(term_id="email-nulls")], [muted])

    assert [(change.action, change.target_id) for change in changes] == [(ImportAction.skip, muted.id)]


@pytest.mark.parametrize("muted_threshold", ["0", "5"], ids=["same-parameters", "other-parameters"])
def test_a_key_match_prefers_the_active_term_to_its_muted_twin(muted_threshold):
    muted = _BaselineTerm(**{**_baseline(threshold_value=muted_threshold).__dict__, "active": False})
    active = _baseline(threshold_value="1")

    changes = _plan([_incoming(threshold_value="0")], [muted, active])

    assert [(change.action, change.target_id) for change in changes] == [(ImportAction.update, active.id)]


@pytest.mark.parametrize(
    ("stored", "incoming", "same"),
    [
        ("(1,2,3)", "('1','2','3')", True),
        ("('Y', 'N')", "('Y','N')", True),
        ("( 'Y' ,'N' )", "('Y','N')", True),
        ("('Y','N')", "('N','Y')", False),
        ("('Y','N')", "('Y','N','U')", False),
    ],
)
def test_a_list_of_values_compares_by_its_values(stored, incoming, same):
    changes = _plan(
        [_incoming("LOV_Match", term_id="flag-lov", baseline_value=incoming, threshold_value="0")],
        [_baseline("LOV_Match", term_id="flag-lov", baseline_value=stored, threshold_value="0")],
    )

    assert (changes[0].action is ImportAction.skip) is same


def test_an_id_match_wins_over_another_terms_key_match():
    existing = _baseline(term_id="kept-id")

    changes = _plan([_incoming(term_id="new-id"), _incoming(term_id="kept-id")], [existing])

    assert [(change.action, change.contract_term_id) for change in changes] == [
        (ImportAction.create, "new-id"), (ImportAction.skip, "kept-id"),
    ]


def _sql_metric(query: str) -> IncomingTerm:
    return _incoming(test_type="SQL_Metric", column=None, custom_query=query, lower_tolerance="0")


def _sql_metric_baseline(query: str) -> _BaselineTerm:
    return _baseline(test_type="SQL_Metric", column=None, term_id=f"minted-{query}", custom_query=query, lower_tolerance="0")


def test_terms_sharing_a_key_pair_with_the_term_of_equal_parameters_whatever_their_order():
    first, second = _sql_metric_baseline("a"), _sql_metric_baseline("b")

    changes = _plan([_sql_metric("a"), _sql_metric("b")], [second, first])

    assert [(change.action, change.target_id) for change in changes] == [
        (ImportAction.skip, first.id), (ImportAction.skip, second.id),
    ]


def test_dropping_one_of_two_terms_sharing_a_key_deletes_that_one():
    first, second = _sql_metric_baseline("a"), _sql_metric_baseline("b")

    changes = _plan([_sql_metric("b")], [first, second])

    assert [(change.action, change.target_id) for change in changes] == [
        (ImportAction.skip, second.id), (ImportAction.delete, first.id),
    ]


def test_a_changed_term_sharing_a_key_takes_the_term_no_equal_one_claims():
    first, second = _sql_metric_baseline("a"), _sql_metric_baseline("b")

    changes = _plan([_sql_metric("a2"), _sql_metric("b")], [first, second])

    assert [(change.action, change.target_id) for change in changes] == [
        (ImportAction.update, first.id), (ImportAction.skip, second.id),
    ]


def test_a_new_rule_is_created():
    changes = _plan([_incoming(test_type="Unique", term_id="email-unique")], [])

    assert [(change.action, change.reason) for change in changes] == [(ImportAction.create, ContractTermReason.NEW)]


def test_a_terms_own_metadata_keys_restated_by_the_document_stay_top_level():
    metadata = {"tags": ["a"], "customProperties": [{"property": "owner", "value": "ops"}, {"property": "x", "value": 1}]}

    stored = _custom_metadata(metadata, {"owner": "ops", "retired": "yes", "odcs": {"tags": ["old"]}})

    assert stored == {"owner": "ops", "odcs": {"tags": ["a"], "customProperties": [{"property": "x", "value": 1}]}}


def test_a_changed_metadata_value_moves_under_the_odcs_key():
    stored = _custom_metadata({"customProperties": [{"property": "owner", "value": "finance"}]}, {"owner": "ops"})

    assert stored == {"odcs": {"customProperties": [{"property": "owner", "value": "finance"}]}}


def test_a_term_whose_own_keys_round_trip_is_unchanged():
    existing = _baseline(term_id="email-nulls")
    existing = _BaselineTerm(**{**existing.__dict__, "custom_metadata": {"owner": "ops"}})
    incoming = IncomingTerm(
        test_type="Required", table_name="orders", column_name="email", parameters={"threshold_value": "0"},
        contract_term_id="email-nulls", metadata={"customProperties": [{"property": "owner", "value": "ops"}]},
    )

    changes = _plan([incoming], [existing])

    assert [change.action for change in changes] == [ImportAction.skip]


# --- physical types ---


def _with_catalog(document: dict, recorded: dict[str, str], family: str = "postgresql") -> dict:
    columns = [MagicMock(column_name=name, db_data_type=data_type) for name, data_type in recorded.items()]
    with patch(f"{MODULE}.contract_document.catalog_columns", return_value=columns):
        _match_physical_types(document, MagicMock(id=uuid4()), family)
    return document


def _typed(**physical_types) -> dict:
    return {"schema": [{"name": "orders", "properties": [
        {"name": name, "physicalType": physical_type} for name, physical_type in physical_types.items()
    ]}]}


def test_an_equivalent_physical_type_takes_the_catalogs_spelling_and_keeps_the_authors():
    document = _with_catalog(_typed(email="VARCHAR(255)"), {"email": "character varying(255)"})

    prop = document["schema"][0]["properties"][0]
    assert prop["physicalType"] == "character varying(255)"
    assert {"property": AUTHORED_PHYSICAL_TYPE, "value": "VARCHAR(255)", "vendor": "testgen"} in prop[
        "customProperties"
    ]


def test_a_physical_type_that_cannot_be_compared_is_set_aside_for_the_logical_type():
    document = _with_catalog(_typed(email="varchar(255)"), {"email": "varchar"})

    prop = document["schema"][0]["properties"][0]
    assert "physicalType" not in prop
    assert prop["customProperties"][0]["value"] == "varchar(255)"


def test_a_different_physical_type_is_left_for_conformance_to_report():
    document = _with_catalog(_typed(amount="integer"), {"amount": "bigint"})

    assert document["schema"][0]["properties"][0] == {"name": "amount", "physicalType": "integer"}


def test_a_column_the_catalog_does_not_hold_is_left_as_written():
    document = _with_catalog(_typed(email="VARCHAR(255)"), {})

    assert document["schema"][0]["properties"][0] == {"name": "email", "physicalType": "VARCHAR(255)"}


# --- preview and apply ---


def _db_stubs(stack: ExitStack, *, draft=None, baseline=(), id_holder=None):
    session = MagicMock()
    stack.enter_context(patch(f"{MODULE}.contract_holding_id", return_value=id_holder))
    stack.enter_context(patch(f"{MODULE}.get_current_session", return_value=session))
    stack.enter_context(patch(f"{MODULE}.all_test_types", return_value=_TEST_TYPES))
    stack.enter_context(patch(f"{MODULE}._baseline_terms", return_value=list(baseline)))
    stack.enter_context(patch(f"{MODULE}.table_group_qualifies_table_refs", return_value=True))
    stack.enter_context(patch(f"{MODULE}.contract_document.catalog_table_names", return_value=["orders"]))
    stack.enter_context(patch(f"{MODULE}.SuiteVersion.draft_for", return_value=draft))
    stack.enter_context(patch(f"{MODULE}.SuiteVersion.in_force_for", return_value=None))
    return session


def test_a_preview_persists_nothing():
    draft = MagicMock(metadata_document={"id": "orders-contract"})
    with ExitStack() as stack:
        session = _db_stubs(stack, draft=draft, baseline=[_baseline(test_type="Unique", term_id="email-unique")])
        write_target = stack.enter_context(patch(f"{MODULE}.resolve_write_target"))
        conformance = stack.enter_context(patch(f"{MODULE}.reconcile_contract_conformance"))

        plan = contract_import.prepare_import(
            yaml.safe_dump(_document()), MagicMock(table_group_schema="public"), _connection(), MagicMock()
        )

    assert plan.count(ImportAction.delete) == 1
    assert plan.count(ImportAction.create) == 3
    session.commit.assert_not_called()
    session.add.assert_not_called()
    session.execute.assert_not_called()
    write_target.assert_not_called()
    conformance.assert_not_called()


def _long_table_name(document: dict) -> None:
    document["schema"][0]["name"] = "o" * 101


def _long_maximum(document: dict) -> None:
    document["schema"][0]["properties"][1]["logicalTypeOptions"]["maximum"] = 10**1000


@pytest.mark.parametrize(("edit", "problem"), [
    (_long_table_name, "table_name must be at most 100 characters"),
    (_long_maximum, "orders.amount (Max Val): baseline_value must be at most 1000 characters"),
])
def test_a_term_a_test_definition_cannot_store_is_refused_in_preview(edit, problem):
    document = _document()
    edit(document)
    with ExitStack() as stack, pytest.raises(InvalidContractDocumentError) as excinfo:
        _db_stubs(stack)
        contract_import.prepare_import(
            yaml.safe_dump(document), MagicMock(table_group_schema="public"), _connection(), None
        )

    assert any(problem in reported for reported in excinfo.value.problems)


def test_a_preview_onto_a_contract_with_another_id_is_refused():
    draft = MagicMock(metadata_document={"id": "billing-contract"})
    with ExitStack() as stack, pytest.raises(ContractIdentityError):
        _db_stubs(stack, draft=draft)
        contract_import.prepare_import(
            yaml.safe_dump(_document()), MagicMock(table_group_schema="public"), _connection(), MagicMock()
        )


def test_applying_writes_the_draft_then_commits_then_reconciles_conformance():
    calls = []
    with ExitStack() as stack:
        session = _db_stubs(stack)
        version = MagicMock(version=3)
        draft_id = uuid4()
        stack.enter_context(patch(f"{MODULE}.resolve_write_target", return_value=(draft_id, {})))
        stack.enter_context(patch(f"{MODULE}.SuiteVersion.get", return_value=version))
        stack.enter_context(patch(f"{MODULE}.contract_document.catalog_columns", return_value=[]))
        stack.enter_context(patch(f"{MODULE}.apply_test_definition_flavor_rules"))
        stack.enter_context(patch(f"{MODULE}.TestDefinition.assign_missing_term_ids"))
        session.commit.side_effect = lambda: calls.append("commit")
        stack.enter_context(
            patch(f"{MODULE}.reconcile_contract_conformance", side_effect=lambda _: calls.append("conformance"))
        )
        table_group = MagicMock(table_group_schema="public")
        plan = contract_import.prepare_import(
            yaml.safe_dump(_document(apiVersion="v3.1.0")), table_group, _connection(), None
        )

        result = contract_import.apply_import(plan, MagicMock(), table_group, SqlFlavorCode.POSTGRESQL)

    assert result == contract_import.AppliedImport(version_id=draft_id, conformance_failed=False)
    assert calls == ["commit", "conformance"]
    assert version.metadata_document["apiVersion"] == "v3.2.0"
    assert version.metadata_document["version"] == "3.0.0"
    assert version.metadata_document["id"] == "orders-contract"
    added = [call.args[0] for call in session.add.call_args_list]
    assert sorted(term.test_type for term in added) == ["Max_Val", "Required", "Row_Ct"]
    assert all(term.version_id == draft_id for term in added)
    assert next(term for term in added if term.test_type == "Max_Val").baseline_value == "500"


def test_a_new_contract_whose_id_another_contract_in_the_table_group_has_is_refused():
    holder = MagicMock(id=uuid4(), test_suite="Orders")
    with ExitStack() as stack, pytest.raises(contract_import.ContractIdTakenError) as excinfo:
        _db_stubs(stack, id_holder=holder)
        contract_import.prepare_import(
            yaml.safe_dump(_document()), MagicMock(table_group_schema="public"), _connection(), None
        )

    assert excinfo.value.problems == [
        f"$.id: contract `Orders` (`{holder.id}`) in this table group already has the contract `id` "
        "`orders-contract`. To update that contract, import the document into it. To create a separate "
        "contract, change the document's `id`."
    ]


def _apply_stubs(stack: ExitStack, session: MagicMock, draft_id) -> None:
    stack.enter_context(patch(f"{MODULE}.resolve_write_target", return_value=(draft_id, {})))
    stack.enter_context(patch(f"{MODULE}.SuiteVersion.get", return_value=MagicMock(version=2)))
    stack.enter_context(patch(f"{MODULE}.contract_document.catalog_columns", return_value=[]))
    stack.enter_context(patch(f"{MODULE}.apply_test_definition_flavor_rules"))
    stack.enter_context(patch(f"{MODULE}.TestDefinition.assign_missing_term_ids"))


def test_a_conformance_failure_after_the_import_is_saved_is_reported_not_raised():
    with ExitStack() as stack:
        session = _db_stubs(stack)
        _apply_stubs(stack, session, uuid4())
        stack.enter_context(patch(f"{MODULE}.reconcile_contract_conformance", side_effect=RuntimeError("boom")))
        table_group = MagicMock(table_group_schema="public")
        plan = contract_import.prepare_import(yaml.safe_dump(_document()), table_group, _connection(), None)

        result = contract_import.apply_import(plan, MagicMock(), table_group, SqlFlavorCode.POSTGRESQL)

    assert result.conformance_failed is True
    session.commit.assert_called_once()


def test_an_update_clears_the_previous_types_parameters_and_locks_the_term():
    existing = _baseline(test_type="SQL_Metric", column=None, term_id="amount-check", custom_query="SELECT 1")
    change = _plan(
        [_incoming(test_type="Max_Val", column="amount", term_id="amount-check", baseline_value="500",
                   threshold_value="0")],
        [existing],
    )[0]
    with ExitStack() as stack:
        session = _db_stubs(stack)
        _apply_stubs(stack, session, uuid4())
        stack.enter_context(patch(f"{MODULE}.reconcile_contract_conformance"))
        plan = contract_import.ContractImportPlan(
            document_id="x", document_name="x", metadata_document={}, changes=[change],
            unverifiable_rules=[], unresolved_declarations=[],
        )

        contract_import.apply_import(plan, MagicMock(), MagicMock(table_group_schema="public"), SqlFlavorCode.POSTGRESQL)

    values = session.execute.call_args_list[-1].args[0].compile().params
    assert values["custom_query"] is None
    assert values["baseline_value"] == "500"
    assert values["test_type"] == "Max_Val"
    assert values["lock_refresh"] in (True, "Y")


def test_created_and_unchanged_terms_are_locked_too():
    existing = _baseline(term_id="email-nulls")
    changes = _plan([_incoming(term_id="email-nulls"), _incoming(test_type="Unique", term_id="email-unique")], [existing])
    with ExitStack() as stack:
        session = _db_stubs(stack)
        _apply_stubs(stack, session, uuid4())
        stack.enter_context(patch(f"{MODULE}.reconcile_contract_conformance"))
        plan = contract_import.ContractImportPlan(
            document_id="x", document_name="x", metadata_document={}, changes=changes,
            unverifiable_rules=[], unresolved_declarations=[],
        )

        contract_import.apply_import(plan, MagicMock(), MagicMock(table_group_schema="public"), SqlFlavorCode.POSTGRESQL)

    (lock,) = (call.args[0] for call in session.execute.call_args_list if "lock_refresh" in str(call.args[0]))
    params = lock.compile().params
    assert params["lock_refresh"] in (True, "Y")
    assert existing.id in params["id_1"]
    (created,) = (call.args[0] for call in session.add.call_args_list)
    assert created.test_type == "Unique"
    assert created.lock_refresh is True


@pytest.mark.parametrize(("qualifies", "expected"), [(False, "public"), (True, "vendor_schema")])
def test_an_update_settles_the_reference_schema_as_a_create_would(qualifies, expected):
    existing = _baseline(test_type="Aggregate_Balance", column="amount", term_id="balance")
    incoming = IncomingTerm(
        test_type="Aggregate_Balance", table_name="orders", column_name="amount",
        parameters={"match_table_name": "invoices", "match_schema_name": "vendor_schema", "match_column_names": "total"},
        contract_term_id="balance", metadata={},
    )
    test_types = {
        **_TEST_TYPES,
        "Aggregate_Balance": TestType(
            test_type="Aggregate_Balance", test_scope="column",
            default_parm_columns="match_schema_name,match_table_name,match_column_names",
        ),
    }
    change = plan_changes(
        [incoming], [existing], schema_name="public",
        declared_parameters={code: (t.default_parm_columns or "").split(",") for code, t in test_types.items()},
    )[0]
    with ExitStack() as stack:
        session = _db_stubs(stack)
        stack.enter_context(patch(f"{MODULE}.all_test_types", return_value=test_types))
        stack.enter_context(patch(f"{MODULE}.table_group_qualifies_table_refs", return_value=qualifies))
        stack.enter_context(patch(f"{MODULE}.resolve_write_target", return_value=(uuid4(), {})))
        stack.enter_context(patch(f"{MODULE}.SuiteVersion.get", return_value=MagicMock(version=2)))
        stack.enter_context(patch(f"{MODULE}.contract_document.catalog_columns", return_value=[]))
        stack.enter_context(patch(f"{MODULE}.TestDefinition.assign_missing_term_ids"))
        stack.enter_context(patch(f"{MODULE}.reconcile_contract_conformance"))
        plan = contract_import.ContractImportPlan(
            document_id="x", document_name="x", metadata_document={}, changes=[change],
            unverifiable_rules=[], unresolved_declarations=[],
        )

        contract_import.apply_import(plan, MagicMock(), MagicMock(table_group_schema="public"), SqlFlavorCode.POSTGRESQL)

    values = session.execute.call_args_list[-1].args[0].compile().params
    assert values["match_schema_name"] == expected



# --- physical names ---


def _physically_named() -> dict:
    document = _document()
    table = document["schema"][0]
    table["physicalName"] = "tbl_orders"
    table["properties"][0]["physicalName"] = "email_addr"
    return document


def test_terms_name_the_physical_table_and_column_and_the_document_keeps_its_logical_names():
    split = _split(_physically_named())

    assert sorted((term.test_type, term.table_name, term.column_name) for term in split.terms) == [
        ("Max_Val", "tbl_orders", "amount"),
        ("Required", "tbl_orders", "email_addr"),
        ("Row_Ct", "tbl_orders", None),
    ]
    table = split.metadata_document["schema"][0]
    assert (table["name"], table["physicalName"]) == ("orders", "tbl_orders")
    assert (table["properties"][0]["name"], table["properties"][0]["physicalName"]) == ("email", "email_addr")


def test_a_physical_type_is_compared_with_the_catalog_type_of_the_physical_column():
    document = {"schema": [{"name": "orders", "physicalName": "tbl_orders", "properties": [
        {"name": "email", "physicalName": "email_addr", "physicalType": "VARCHAR(255)"},
    ]}]}
    columns = [MagicMock(column_name="email_addr", db_data_type="character varying(255)")]
    with patch(f"{MODULE}.contract_document.catalog_columns", return_value=columns) as catalog_columns:
        _match_physical_types(document, MagicMock(id=uuid4()), "postgresql")

    assert catalog_columns.call_args.args[1] == "tbl_orders"
    assert document["schema"][0]["properties"][0]["physicalType"] == "character varying(255)"


@pytest.mark.parametrize(("physical_name", "not_in_catalog"), [("orders", []), ("tbl_orders", ["tbl_orders"])])
def test_the_preview_looks_the_physical_table_up_in_the_catalog(physical_name, not_in_catalog):
    document = _document()
    document["schema"][0].update(name="orders_logical", physicalName=physical_name)
    with ExitStack() as stack:
        _db_stubs(stack)
        plan = contract_import.prepare_import(
            yaml.safe_dump(document), MagicMock(table_group_schema="public"), _connection(), None
        )

    assert plan.tables_not_in_catalog == not_in_catalog
