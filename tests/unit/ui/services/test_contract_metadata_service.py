from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.commands.test_generation import ContractGenerationResult
from testgen.common.contract_service import (
    CheckableRuleError,
    InvalidContractDocumentError,
    OwnedFieldError,
    SavedMetadata,
)
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinitionMinimal
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.quality_rules import mark_unverifiable
from testgen.ui.services import contract_metadata_service as service

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 8, 1, tzinfo=UTC)

DOCUMENT_TEXT = """\
apiVersion: v3.2.0
kind: DataContract
id: 2a91b0d4
name: orders_contract
servers:
- server: main
  type: snowflake
  account: 5
schema:
- name: orders
  properties:
  - name: order_id
    logicalType: integer
  - name: amount
    logicalType: decimalish
- name: customers
  quality:
  - type: sql
    query: SELECT 1
"""


def _suite() -> TestSuite:
    return TestSuite(id=uuid4(), test_suite="orders_contract", table_groups_id=uuid4())


def _document(*tables: str) -> dict:
    return {"apiVersion": "v3.2.0", "kind": "DataContract", "schema": [{"name": name} for name in tables]}


def _tab(document: dict, catalog: list[str], editable: bool = True, rendered=None, definitions=()) -> dict:
    version = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN, metadata_document=document)
    with (
        patch.object(service, "catalog_table_names", return_value=catalog),
        patch.object(service.TableGroup, "get", return_value=TableGroup(table_groups_name="sales_tables")),
        patch.object(service.contract_service, "document_status", return_value="active"),
        patch.object(service, "render_document", side_effect=lambda *_args, **_kwargs: rendered or document),
        patch.object(service.TestDefinition, "select_minimal_where", return_value=definitions),
    ):
        return service.metadata_tab(_suite(), version, editable)


def test_the_tab_lists_the_declared_tables_in_document_order():
    tab = _tab(_document("orders", "customers"), ["customers", "orders", "returns"])

    assert tab["tables"] == [
        {"name": "orders", "unverifiable": False},
        {"name": "customers", "unverifiable": False},
    ]
    assert tab["table_options"] == ["customers", "orders", "returns"]
    assert tab["unverifiable_message"] is None


def test_a_declared_table_the_group_does_not_hold_is_unverifiable_and_still_an_option():
    tab = _tab(_document("orders", "shipments"), ["orders"])

    assert tab["tables"][1] == {"name": "shipments", "unverifiable": True}
    assert tab["table_options"] == ["orders", "shipments"]
    assert tab["unverifiable_message"] == (
        "shipments is declared but is not in the table group sales_tables, so it cannot be verified."
    )


def test_several_unverifiable_tables_are_named_together():
    tab = _tab(_document("a", "b", "c"), [])

    assert tab["unverifiable_message"] == (
        "a, b, and c are declared but are not in the table group sales_tables, so they cannot be verified."
    )


def test_the_tab_shows_the_metadata_document_as_yaml():
    document = _document("orders")

    tab = _tab(document, ["orders"])

    assert tab["document"] == service.serialize_document(document)
    assert tab["document"] == _tab(document, ["orders"])["document"]


def test_each_rule_marked_unverifiable_gets_an_info_marker_on_its_line():
    document = {
        "schema": [
            {
                "name": "orders",
                "quality": [mark_unverifiable({"type": "sql", "query": "SELECT 1"})],
                "properties": [
                    {"name": "id", "quality": [{"type": "library", "metric": "nullValues"}]},
                    {"name": "card", "quality": [mark_unverifiable({"id": "card_pattern", "type": "library"})]},
                ],
            },
        ],
    }

    tab = _tab(document, ["orders"])

    lines = tab["document"].splitlines()
    marked = sorted(lines[marker["line"] - 1].strip() for marker in tab["unverifiable_markers"])
    assert marked == ["- customProperties:", "- id: card_pattern"]
    assert all(
        marker["severity"] == "info" and marker["message"] == service.UNVERIFIABLE_RULE
        for marker in tab["unverifiable_markers"]
    )


def test_a_document_without_marked_rules_has_no_info_markers():
    assert _tab(_document("orders"), ["orders"])["unverifiable_markers"] == []


def test_the_tab_passes_through_whether_the_version_is_editable():
    assert _tab(_document(), [], editable=False)["editable"] is False


def test_a_version_without_a_document_shows_an_empty_one():
    version = SuiteVersion(id=uuid4(), version=1, metadata_document=None)
    with (
        patch.object(service, "catalog_table_names", return_value=[]),
        patch.object(service.TableGroup, "get", return_value=TableGroup(table_groups_name="g")),
        patch.object(service, "render_document", return_value={}),
        patch.object(service.TestDefinition, "select_minimal_where", return_value=[]),
    ):
        tab = service.metadata_tab(_suite(), version, True)

    assert tab["tables"] == []
    assert tab["document"] == service.serialize_document({})


def test_the_overview_shows_the_contracts_name_status_and_description():
    document = {
        "name": "stored_name", "domain": "sales", "tenant": "emea", "tags": ["finance", "tier-1"],
        "description": {"purpose": "Orders placed online.", "usage": "Weekly reporting.", "limitations": "No refunds."},
    }

    assert _tab(document, [])["overview"] == {
        "name": "orders_contract", "status": "active", "domain": "sales", "tenant": "emea",
        "tags": ["finance", "tier-1"], "purpose": "Orders placed online.", "usage": "Weekly reporting.",
        "limitations": "No refunds.",
    }


def test_an_empty_overview_shows_no_values():
    assert _tab({}, [])["overview"] == {
        "name": "orders_contract", "status": "active", "domain": None, "tenant": None, "tags": [],
        "purpose": None, "usage": None, "limitations": None,
    }


STORED_FOR_OVERVIEW = {
    "apiVersion": "v3.2.0", "kind": "DataContract", "name": "orders_contract", "domain": "old", "tenant": "emea",
    "tags": ["a"], "team": {"name": "Platform"},
    "description": {"purpose": "Old", "usage": "Kept?", "authoritativeDefinitions": [{"type": "x", "url": "https://x"}]},
}


def _save_section(section, values: dict, stored: dict, side_effect=None):
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), version=4, metadata_document=stored)
    saved = SavedMetadata(
        version_id=draft.id, unverifiable_rules=[], unresolved_declarations=[], untested_declarations=[],
        overridden_declarations=[], unchecked_paths=[], problems=[],
    )
    with (
        patch.object(service.SuiteVersion, "draft_for", return_value=draft),
        patch.object(service.SuiteVersion, "get", return_value=draft),
        patch.object(service.contract_service, "save_metadata_document", return_value=saved, side_effect=side_effect) as save,
    ):
        result = service.save_section(suite, section, values)
    return result, save


def _save_overview(values: dict, stored: dict | None = None, side_effect=None):
    return _save_section(service.MetadataSection.OVERVIEW, values, stored or STORED_FOR_OVERVIEW, side_effect)


OVERVIEW_VALUES = {
    "domain": "sales", "tenant": "", "tags": ["x", " ", "x", "y"], "purpose": "New", "usage": "  ", "limitations": "L",
}


def test_saving_the_overview_replaces_only_its_fields():
    _, save = _save_overview(OVERVIEW_VALUES)

    document = save.call_args.args[1]
    assert document == {
        "apiVersion": "v3.2.0", "kind": "DataContract", "name": "orders_contract", "domain": "sales",
        "tags": ["x", "y"], "team": {"name": "Platform"},
        "description": {"purpose": "New", "limitations": "L", "authoritativeDefinitions": [{"type": "x", "url": "https://x"}]},
    }


def test_saving_the_overview_does_not_modify_the_stored_document():
    stored = {"domain": "old", "description": {"purpose": "Old"}}

    _save_overview(OVERVIEW_VALUES, stored=stored)

    assert stored == {"domain": "old", "description": {"purpose": "Old"}}


def test_clearing_every_description_field_removes_the_description():
    values = {"domain": "", "tenant": "", "tags": [], "purpose": "", "usage": "", "limitations": ""}

    _, save = _save_overview(values, stored={"name": "orders_contract", "description": {"purpose": "Old"}, "tags": ["a"]})

    assert save.call_args.args[1] == {"name": "orders_contract"}


def test_saving_the_overview_names_the_draft():
    result, _ = _save_overview(OVERVIEW_VALUES)

    assert result == {
        "success": True, "message": "Overview saved to v4 draft.", "problems": [], "markers": [], "version": 4,
        "warnings": [],
    }


def test_a_refused_overview_save_reports_the_problems():
    error = OwnedFieldError(["$.domain: something is wrong"])

    result, _ = _save_overview(OVERVIEW_VALUES, side_effect=error)

    assert result == {
        "success": False, "message": "No changes saved.", "problems": ["domain: something is wrong"], "markers": [],
    }


def test_the_tab_lists_each_server_entry_with_its_type_first_and_its_fields_labeled():
    document = {
        "servers": [
            {"server": "main", "account": "acme", "warehouse": "wh", "type": "snowflake", "port": 443},
            {"server": "replica", "type": "oracle", "serviceName": "ORCL", "endpointUrl": "https://x"},
        ],
    }

    assert _tab(document, [])["servers"] == [
        {"name": "main", "fields": [
            {"label": "Type", "value": "snowflake"},
            {"label": "Account", "value": "acme"},
            {"label": "Warehouse", "value": "wh"},
            {"label": "Port", "value": 443},
        ]},
        {"name": "replica", "fields": [
            {"label": "Type", "value": "oracle"},
            {"label": "Service name", "value": "ORCL"},
            {"label": "Endpoint URL", "value": "https://x"},
        ]},
    ]


def test_a_server_field_holding_a_list_or_mapping_is_left_to_the_yaml():
    document = {"servers": [{"server": "main", "type": "custom", "customProperties": [{"property": "a"}]}]}

    assert _tab(document, [])["servers"] == [{"name": "main", "fields": [{"label": "Type", "value": "custom"}]}]


def test_a_document_without_servers_lists_none():
    assert _tab(_document("orders"), ["orders"])["servers"] == []


def test_the_rules_testgen_cannot_check_are_listed_where_they_sit_with_their_type():
    document = {
        "schema": [
            {
                "name": "orders",
                "quality": [mark_unverifiable({"type": "text", "description": "Orders are never backdated."})],
                "properties": [
                    {"name": "id", "quality": [{"type": "library", "metric": "nullValues"}]},
                    {"name": "card", "quality": [
                        mark_unverifiable({"name": "card_check", "type": "library", "metric": "luhn"}),
                        mark_unverifiable({"type": "custom", "engine": "soda"}),
                    ]},
                ],
            },
        ],
    }

    tab = _tab(document, ["orders"])

    assert tab["unverifiable_rules"] == [
        {"location": "orders", "type": "text", "description": "Orders are never backdated."},
        {"location": "orders.card", "type": "luhn", "description": "card_check"},
        {"location": "orders.card", "type": "custom", "description": None},
    ]
    assert tab["unverifiable_rules_info"] == (
        "These rules are kept in the contract, but TestGen cannot check them. Edit them as YAML."
    )


def test_a_document_without_marked_rules_lists_no_rules_testgen_cannot_check():
    document = {"schema": [{"name": "orders", "quality": [{"type": "library", "metric": "rowCount"}]}]}

    assert _tab(document, ["orders"])["unverifiable_rules"] == []


@pytest.mark.parametrize(("path", "line"), [
    ("$", 1),
    ("$.apiVersion", 1),
    ("$.servers[0].account", 8),
    ("$.servers[0]", 6),
    ("$.schema[0].properties[1].logicalType", 15),
    ("$.schema[1].quality[0]", 18),
    # A path the text does not reach is marked at the deepest node it does
    ("$.schema[1].quality[5].query", 17),
    ("$.slaProperties", 1),
])
def test_a_problem_is_marked_on_the_line_its_path_names(path, line):
    assert service.problem_markers(DOCUMENT_TEXT, [f"{path}: something is wrong"]) == [
        {"line": line, "message": f"{path.removeprefix('$.')}: something is wrong"},
    ]


def test_a_problem_without_a_path_is_marked_on_the_first_line():
    assert service.problem_markers(DOCUMENT_TEXT, ["The terms cannot be rendered."]) == [
        {"line": 1, "message": "The terms cannot be rendered."},
    ]


def _save(text: str, side_effect=None, saved=None):
    suite = _suite()
    saved = saved or SavedMetadata(
        version_id=uuid4(), unverifiable_rules=[], unresolved_declarations=[], untested_declarations=[],
        overridden_declarations=[], unchecked_paths=[], problems=[],
    )
    with (
        patch.object(service.contract_service, "save_metadata_document", return_value=saved, side_effect=side_effect) as save,
        patch.object(service.SuiteVersion, "get", return_value=SuiteVersion(id=saved.version_id, version=4)),
    ):
        result = service.save_document(suite, text)
    return result, save, suite


def test_saving_stores_the_parsed_document_and_names_the_draft():
    result, save, suite = _save(DOCUMENT_TEXT)

    assert result == {
        "success": True,
        "message": "Contract document saved to v4 draft.",
        "problems": [],
        "markers": [],
        "version": 4,
        "warnings": [],
    }
    document = save.call_args.args[1]
    assert save.call_args.args[0] is suite
    assert document["schema"][1]["name"] == "customers"


def test_saving_reports_rules_stored_as_unverifiable_and_problems_left():
    saved = SavedMetadata(
        version_id=uuid4(), unverifiable_rules=["customers: rule 1", "orders: rule 2"], unresolved_declarations=[],
        untested_declarations=[], overridden_declarations=[], unchecked_paths=[], problems=["$.servers[0].account: 5 is not of type 'string'"],
    )

    result, _, _ = _save(DOCUMENT_TEXT, saved=saved)

    assert result["message"] == (
        "Contract document saved to v4 draft. 2 rules no test type checks were stored as unverifiable. "
        "The document still has 1 problem, and the draft cannot be frozen until it is fixed."
    )


def test_one_unverifiable_rule_and_several_problems_read_in_the_singular_and_plural():
    saved = SavedMetadata(
        version_id=uuid4(), unverifiable_rules=["customers: rule 1"], unresolved_declarations=[],
        untested_declarations=[], overridden_declarations=[], unchecked_paths=[], problems=["$.a: x", "$.b: y"],
    )

    result, _, _ = _save(DOCUMENT_TEXT, saved=saved)

    assert "1 rule no test type checks was stored as unverifiable." in result["message"]
    assert "The document still has 2 problems, and the draft cannot be frozen until they are fixed." in result["message"]


def test_text_that_is_not_yaml_is_refused_on_its_line():
    result, save, _ = _save("name: orders\nschema: [\n  - a\n")

    save.assert_not_called()
    assert result["success"] is False
    assert result["message"] == "No changes saved. The document is not valid YAML:"
    assert len(result["markers"]) == 1
    assert result["markers"][0]["line"] == 3
    assert result["problems"] == [result["markers"][0]["message"]]


@pytest.mark.parametrize("text", ["", "- a\n- b\n", "just text\n"])
def test_text_that_is_not_a_mapping_is_refused(text):
    result, save, _ = _save(text)

    save.assert_not_called()
    assert result == {
        "success": False,
        "message": "No changes saved. The document must be a YAML mapping of fields, such as `name: orders`.",
        "problems": [],
        "markers": [],
    }


@pytest.mark.parametrize(("error", "message"), [
    (
        CheckableRuleError(["$.schema[1].quality[0]: customers: rule 1 is checked by the Custom Test test type."]),
        "No changes saved. TestGen checks these rules, so add each one as a test on the Quality Rules tab:",
    ),
    (OwnedFieldError(["$.id: `id` cannot be changed. It is `2a91b0d4`."]), "No changes saved."),
    (
        InvalidContractDocumentError(["$.servers[0].account: 5 is not of type 'string'"]),
        "No changes saved. The document would not be valid ODCS:",
    ),
])
def test_a_refused_document_marks_each_problem_on_its_line(error, message):
    result, _, _ = _save(DOCUMENT_TEXT, side_effect=error)

    assert result["success"] is False
    assert result["message"] == message
    assert result["problems"] == [problem.removeprefix("$.") for problem in error.problems]
    assert result["markers"] == service.problem_markers(DOCUMENT_TEXT, error.problems)


def test_any_other_refusal_is_its_message():
    result, _, _ = _save(DOCUMENT_TEXT, side_effect=ValueError("This contract has no version to write to."))

    assert result == {
        "success": False, "message": "This contract has no version to write to.", "problems": [], "markers": [],
    }


def _versions(draft_document: dict | None, active_document: dict | None = None):
    return (
        patch.object(
            service.SuiteVersion, "draft_for",
            return_value=SuiteVersion(id=uuid4(), version=4, metadata_document=draft_document)
            if draft_document is not None else None,
        ),
        patch.object(
            service.SuiteVersion, "in_force_for",
            return_value=SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN, metadata_document=active_document)
            if active_document is not None else None,
        ),
    )


def _remove_dialog(selected: list[str], terms: int, draft_document=None, active_document=None):
    draft, active = _versions(draft_document, active_document)
    with draft, active, patch.object(service.contract_service, "term_count", return_value=terms) as count:
        return service.remove_tables_dialog(_suite(), selected), count


def test_removing_a_table_names_its_terms_first():
    dialog, count = _remove_dialog(["orders"], 23, draft_document=_document("orders", "order_lines"))

    assert dialog == {
        "question": "Remove order_lines from the contract orders_contract?",
        "warning": "Its descriptor and its 23 terms will be deleted from the draft.",
    }
    clause = count.call_args.args[1]
    assert clause.right.value == ["order_lines"]


def test_removing_several_tables_names_them_together():
    dialog, _ = _remove_dialog(["orders"], 1, draft_document=_document("orders", "order_lines", "returns"))

    assert dialog == {
        "question": "Remove order_lines and returns from the contract orders_contract?",
        "warning": "Their descriptors and their 1 term will be deleted from the draft.",
    }


def test_removing_a_table_without_terms_names_only_its_descriptor():
    dialog, _ = _remove_dialog(["orders"], 0, draft_document=_document("orders", "returns"))

    assert dialog["warning"] == "Its descriptor will be deleted from the draft."


def test_without_a_draft_the_active_versions_tables_are_compared():
    dialog, count = _remove_dialog(["orders"], 5, active_document=_document("orders", "returns"))

    assert dialog["question"] == "Remove returns from the contract orders_contract?"
    assert count.call_args.args[0] is not None


def test_keeping_every_declared_table_needs_no_confirmation():
    dialog, count = _remove_dialog(["orders", "new"], 5, draft_document=_document("orders"))

    assert dialog is None
    count.assert_not_called()


def _generation(term_count: int, tables: list[str], not_profiled: list[str] | None = None) -> ContractGenerationResult:
    return ContractGenerationResult(
        term_count=term_count, tables_declared=tables, tables_not_in_catalog=[], tables_not_profiled=not_profiled or [],
    )


def _save_tables(selected, declared, generations=(), removed_terms=0, side_effect=None, with_session=False):
    suite = _suite()
    draft, active = _versions(_document(*declared))
    with (
        draft,
        active,
        patch.object(
            service.contract_service, "remove_table", return_value={"terms_removed": removed_terms},
            side_effect=side_effect,
        ) as remove,
        patch.object(service.contract_service, "add_table", side_effect=list(generations)) as add,
        patch.object(service, "get_current_session") as session,
    ):
        result = service.save_tables(suite, selected)
    if with_session:
        return result, remove, add, session.return_value
    return result, remove, add, suite


def test_saving_tables_removes_dropped_ones_and_adds_new_ones():
    result, remove, add, suite = _save_tables(
        ["orders", "shipments"], ["orders", "order_lines"], [_generation(12, ["shipments"])], removed_terms=23,
    )

    remove.assert_called_once_with(suite, "order_lines")
    add.assert_called_once_with(suite, "shipments")
    assert result == {
        "success": True,
        "message": "Removed order_lines and its 23 terms. shipments now holds 12 quality tests.",
        "version": 4,
    }


def test_adding_several_tables_reports_their_quality_tests_together():
    result, _, _, _ = _save_tables(
        ["orders", "a", "b"], ["orders"], [_generation(1, ["a"]), _generation(4, ["b"])],
    )

    assert result["message"] == "a and b now hold 5 quality tests."


def test_a_table_added_without_profiling_says_no_quality_tests_were_generated():
    result, _, _, _ = _save_tables(
        ["orders", "a", "b"], ["orders"], [_generation(0, ["a"], ["a"]), _generation(3, ["b"])],
    )

    assert result["message"] == (
        "b now holds 3 quality tests. No quality tests were generated for a, which has not been profiled."
    )


def test_several_tables_added_without_profiling_read_in_the_plural():
    result, _, _, _ = _save_tables(
        ["a", "b"], [], [_generation(0, ["a"], ["a"]), _generation(0, ["b"], ["b"])],
    )

    assert result["message"] == "No quality tests were generated for a and b, which have not been profiled."


def test_removing_tables_without_terms_names_only_the_tables():
    result, _, _, _ = _save_tables(["orders"], ["orders", "a", "b"])

    assert result["message"] == "Removed a and b."


def test_removing_several_tables_counts_their_terms_together():
    result, _, _, _ = _save_tables(["orders"], ["orders", "a", "b"], removed_terms=1)

    assert result["message"] == "Removed a and b, and their 2 terms."


def test_saving_an_unchanged_selection_changes_nothing():
    result, remove, add, _ = _save_tables(["orders"], ["orders"])

    remove.assert_not_called()
    add.assert_not_called()
    assert result == {"success": True, "message": "No tables changed.", "version": None}


def test_a_refused_table_change_is_its_message():
    result, _, _, _ = _save_tables(["orders"], ["orders", "a"], side_effect=ValueError("Not a contract."))

    assert result == {"success": False, "message": "Not a contract."}


def test_a_failed_table_keeps_the_tables_before_it_and_says_what_was_applied():
    result, _, add, session = _save_tables(
        ["orders", "a", "b"], ["orders", "gone"], [_generation(2, ["a"]), RuntimeError("connection lost")],
        removed_terms=3, with_session=True,
    )

    assert add.call_count == 2
    assert session.commit.call_count == 2
    session.rollback.assert_called_once()
    assert result == {
        "success": False,
        "message": "Removed gone and its 3 terms. a now holds 2 quality tests. Something went wrong while adding b.",
    }


def test_a_failed_removal_rolls_back_and_names_the_removal():
    result, _, add, session = _save_tables(
        ["orders"], ["orders", "a", "b"], side_effect=RuntimeError("connection lost"), with_session=True,
    )

    add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_called_once()
    assert result == {"success": False, "message": "Something went wrong while removing a and b."}


MEMBER = {"id": "m1", "username": "ana@acme.com", "name": "Ana Ruiz", "role": "owner", "dateIn": "2025-01-10",
          "customProperties": [{"property": "slack", "value": "@ana"}]}
STORED_TEAM = {
    "name": "orders_contract",
    "team": {"id": "t1", "name": "Order Data", "tags": ["core"], "members": [
        MEMBER, {"username": "li@acme.com", "name": "Li Wei", "role": "data steward"},
    ]},
}


def test_the_team_shows_its_name_description_and_members_in_order():
    team = _tab(STORED_TEAM, [])["team"]

    assert team == {
        "name": "Order Data", "description": None, "deprecated_form": False, "members": [
            {"index": 0, "username": "ana@acme.com", "name": "Ana Ruiz", "role": "owner", "dateIn": "2025-01-10",
             "dateOut": None},
            {"index": 1, "username": "li@acme.com", "name": "Li Wei", "role": "data steward", "dateIn": None,
             "dateOut": None},
        ],
    }


def test_a_team_in_the_deprecated_array_form_shows_its_members():
    team = _tab({"team": [{"username": "ana@acme.com"}]}, [])["team"]

    assert team["deprecated_form"] is True
    assert team["name"] is None
    assert [member["username"] for member in team["members"]] == ["ana@acme.com"]


def test_a_document_without_a_team_shows_no_members():
    assert _tab({}, [])["team"] == {"name": None, "description": None, "deprecated_form": False, "members": []}


def _member(index, username, **fields):
    return {"index": index, "username": username, "name": "", "role": "", "dateIn": "", "dateOut": "", **fields}


def _saved_team(values, stored=STORED_TEAM):
    _, save = _save_section(service.MetadataSection.TEAM, values, stored)
    return save.call_args.args[1]


def test_saving_the_team_keeps_the_fields_the_form_does_not_show_on_each_member():
    values = {"name": "Order Data", "description": "", "members": [
        _member(0, "ana@acme.com", name="Ana Ruiz-Gil", role="owner", dateIn="2025-01-10"),
    ]}

    member, = _saved_team(values)["team"]["members"]

    assert member == {**MEMBER, "name": "Ana Ruiz-Gil"}


def test_saving_the_team_removes_the_members_left_out_and_keeps_the_forms_order():
    values = {"name": "Order Data", "members": [
        _member(None, "sam@acme.com", role="analyst"),
        _member(0, "ana@acme.com", name="Ana Ruiz", role="owner", dateIn="2025-01-10"),
    ]}

    members = _saved_team(values)["team"]["members"]

    assert [member["username"] for member in members] == ["sam@acme.com", "ana@acme.com"]
    assert members[0] == {"username": "sam@acme.com", "role": "analyst"}


def test_a_cleared_member_field_is_removed():
    values = {"name": "Order Data", "members": [_member(1, "li@acme.com", name="Li Wei")]}

    assert _saved_team(values)["team"]["members"] == [{"username": "li@acme.com", "name": "Li Wei"}]


def test_saving_the_team_keeps_its_own_fields_the_form_does_not_show():
    values = {"name": "Orders", "description": "Owns the pipeline.", "members": []}

    assert _saved_team(values)["team"] == {
        "id": "t1", "name": "Orders", "description": "Owns the pipeline.", "tags": ["core"],
    }


def test_a_team_in_the_deprecated_array_form_is_saved_in_the_object_form():
    stored = {"team": [{"username": "ana@acme.com", "id": "m1"}]}
    values = {"name": "Orders", "members": [_member(0, "ana@acme.com")]}

    assert _saved_team(values, stored)["team"] == {"name": "Orders", "members": [{"username": "ana@acme.com", "id": "m1"}]}


def test_an_emptied_team_is_removed():
    stored = {"name": "orders_contract", "team": {"name": "Orders", "members": [{"username": "ana@acme.com"}]}}

    assert _saved_team({"name": "", "description": "", "members": []}, stored) == {"name": "orders_contract"}


def test_saving_the_team_names_the_draft():
    result, _ = _save_section(service.MetadataSection.TEAM, {"name": "Orders", "members": []}, STORED_TEAM)

    assert result["message"] == "Team saved to v4 draft."


STORED_LISTS = {
    "roles": [{"id": "r1", "role": "sales_reader", "access": "read", "firstLevelApprovers": "ana@acme.com"}],
    "support": [{"channel": "#ebike-data", "tool": "slack", "url": "https://acme.slack.com/C222",
                 "invitationUrl": "https://acme.slack.com/join"}],
    "slaProperties": [
        {"property": "latency", "value": 2, "unit": "h", "scheduler": "cron", "schedule": "0 20 * * *"},
        {"property": "availability", "value": "99.5", "unit": "%"},
    ],
}


def test_the_roles_support_and_service_levels_show_their_rows():
    tab = _tab(STORED_LISTS, [])

    assert tab["roles"] == [{
        "index": 0, "role": "sales_reader", "access": "read", "description": None,
        "firstLevelApprovers": "ana@acme.com", "secondLevelApprovers": None,
    }]
    assert tab["support"] == [{
        "index": 0, "channel": "#ebike-data", "tool": "slack", "scope": None, "url": "https://acme.slack.com/C222",
        "description": None,
    }]
    assert [row["value"] for row in tab["service_levels"]] == ["2", "99.5"]
    assert tab["service_levels"][0] == {
        "index": 0, "property": "latency", "value": "2", "unit": "h", "element": None, "driver": None,
        "description": None,
    }
    assert tab["service_levels_info"] == "Service levels are declared in the contract. TestGen does not check them."


def test_a_document_without_roles_support_or_service_levels_shows_no_rows():
    tab = _tab({}, [])

    assert (tab["roles"], tab["support"], tab["service_levels"]) == ([], [], [])


def _saved_list(section, rows, stored=STORED_LISTS):
    _, save = _save_section(section, {"rows": rows}, stored)
    return save.call_args.args[1]


def test_saving_the_roles_keeps_the_fields_the_form_does_not_show():
    rows = [{"index": 0, "role": "sales_reader", "access": "write", "firstLevelApprovers": "ana@acme.com"},
            {"index": None, "role": "auditor", "access": "read"}]

    assert _saved_list(service.MetadataSection.ROLES, rows)["roles"] == [
        {"id": "r1", "role": "sales_reader", "access": "write", "firstLevelApprovers": "ana@acme.com"},
        {"role": "auditor", "access": "read"},
    ]


def test_saving_the_support_channels_keeps_the_fields_the_form_does_not_show():
    rows = [{"index": 0, "channel": "#ebike-data", "tool": "slack", "scope": "issues", "url": "https://acme.slack.com/C222"}]

    assert _saved_list(service.MetadataSection.SUPPORT, rows)["support"] == [{
        "channel": "#ebike-data", "tool": "slack", "scope": "issues", "url": "https://acme.slack.com/C222",
        "invitationUrl": "https://acme.slack.com/join",
    }]


def test_an_unchanged_service_level_value_keeps_its_stored_type():
    rows = [{"index": 0, "property": "latency", "value": "2", "unit": "h"},
            {"index": 1, "property": "availability", "value": "99.5", "unit": "%"}]

    levels = _saved_list(service.MetadataSection.SERVICE_LEVELS, rows)["slaProperties"]

    assert [level["value"] for level in levels] == [2, "99.5"]
    assert levels[0] == {"property": "latency", "value": 2, "unit": "h", "scheduler": "cron", "schedule": "0 20 * * *"}


@pytest.mark.parametrize(("text", "value"), [("4", 4), ("0.5", 0.5), ("7 years", "7 years"), ("1e3", "1e3")])
def test_a_changed_service_level_value_is_a_number_when_it_reads_as_one(text, value):
    rows = [{"index": 0, "property": "latency", "value": text}]

    assert _saved_list(service.MetadataSection.SERVICE_LEVELS, rows)["slaProperties"][0]["value"] == value


def test_removing_every_row_removes_the_section():
    stored = {"name": "orders_contract", **STORED_LISTS}

    document = _saved_list(service.MetadataSection.SUPPORT, [], stored)

    assert "support" not in document
    assert document["roles"] == STORED_LISTS["roles"]


@pytest.mark.parametrize(("section", "label"), [
    (service.MetadataSection.ROLES, "Roles"),
    (service.MetadataSection.SUPPORT, "Support"),
    (service.MetadataSection.SERVICE_LEVELS, "Service Levels"),
])
def test_saving_a_list_section_names_the_draft(section, label):
    result, _ = _save_section(section, {"rows": []}, STORED_LISTS)

    assert result["message"] == f"{label} saved to v4 draft."


SCHEMA_DOCUMENT = {"schema": [{
    "name": "orders", "description": "One row per order.", "dataGranularityDescription": "Order", "logicalType": "object",
    "properties": [
        {"name": "order_id", "logicalType": "integer", "physicalType": "INT", "primaryKey": True, "primaryKeyPosition": 1},
        {"name": "ship_date", "logicalType": "date", "physicalType": "DATE", "classification": "internal",
         "criticalDataElement": True, "description": "Date the order left.", "examples": ["2026-03-01", "2026-03-04"],
         "unique": True, "required": False},
    ],
}]}


def _marker(term_id, test_type, *paths):
    return {
        "property": "testgenTerm", "vendor": "testgen",
        "value": {"id": term_id, "testType": test_type, "declares": list(paths)},
    }


def _rendered(**ship_date):
    rendered = {"schema": [{**SCHEMA_DOCUMENT["schema"][0], "properties": [
        SCHEMA_DOCUMENT["schema"][0]["properties"][0],
        {**SCHEMA_DOCUMENT["schema"][0]["properties"][1], **ship_date},
    ]}]}
    return rendered


def _definition(table, column, test_type="Required", test_name_short="Required Entry"):
    return TestDefinitionMinimal(
        id=uuid4(), table_groups_id=uuid4(), test_type=test_type, test_suite_id=uuid4(), schema_name="public",
        table_name=table, column_name=column, test_active=True, lock_refresh=False, test_name_short=test_name_short,
    )


def _schema(**kwargs):
    return _tab(SCHEMA_DOCUMENT, ["orders"], **kwargs)["schema"]


def test_each_declared_table_lists_its_descriptor_fields():
    table, = _schema()

    assert table["name"] == "orders"
    assert table["fields"] == [
        {"label": "Description", "value": "One row per order."},
        {"label": "Granularity", "value": "Order"},
        {"label": "Logical type", "value": "object"},
    ]


def test_each_column_lists_its_descriptor_fields():
    order_id, ship_date = _schema()[0]["columns"]

    assert order_id["name"] == "order_id"
    assert ship_date["fields"] == [
        {"label": "Logical type", "value": "date"},
        {"label": "Physical type", "value": "DATE"},
        {"label": "Primary key", "value": "No"},
        {"label": "Primary key position", "value": None},
        {"label": "Classification", "value": "internal"},
        {"label": "Critical data element", "value": "Yes"},
        {"label": "Description", "value": "Date the order left."},
        {"label": "Examples", "value": "2026-03-01 · 2026-03-04"},
        {"label": "Required", "value": "No"},
        {"label": "Unique", "value": "Yes"},
    ]
    assert {"label": "Primary key position", "value": "1"} in order_id["fields"]


def test_a_column_is_identified_by_its_physical_name_and_labeled_by_its_name():
    document = {"schema": [{"name": "orders", "properties": [
        {"name": "Ship Date", "physicalName": "ship_dt", "logicalType": "date", "required": True,
         "customProperties": [_marker("ship-required", "Required", "required")]},
        {"name": "total"},
    ]}]}
    definitions = [_definition("orders", "ship_dt"), _definition("orders", "ship_dt", "Unique", "Unique")]

    ship_date, total = _tab(document, ["orders"], definitions=definitions)["schema"][0]["columns"]

    assert (ship_date["name"], ship_date["label"]) == ("ship_dt", "Ship Date")
    assert (total["name"], total["label"]) == ("total", "total")
    assert ship_date["rule_count"] == 2
    assert [field["label"] for field in ship_date["declared"]] == ["Required"]


def test_a_rule_backed_field_is_shown_under_its_rule_from_the_rendered_document():
    rendered = _rendered(required=True, customProperties=[_marker("ship-required", "Required", "required")])
    definitions = [_definition("orders", "ship_date")]

    ship_date = _schema(rendered=rendered, definitions=definitions)[0]["columns"][1]

    assert ship_date["declared"] == [
        {"label": "Required", "value": "Yes", "test_type": "Required", "test_name": "Required Entry"},
    ]
    assert "Required" not in [field["label"] for field in ship_date["fields"]]
    assert {"label": "Unique", "value": "Yes"} in ship_date["fields"]


def test_a_rule_declaring_two_fields_lists_both():
    rendered = _rendered(
        logicalTypeOptions={"minLength": 1, "maxLength": 10},
        customProperties=[_marker("len", "Text_Length_Range", "logicalTypeOptions.minLength", "logicalTypeOptions.maxLength")],
    )
    definitions = [_definition("orders", "ship_date", "Text_Length_Range", "Text Length Range")]

    declared = _schema(rendered=rendered, definitions=definitions)[0]["columns"][1]["declared"]

    assert [(field["label"], field["value"], field["test_name"]) for field in declared] == [
        ("Minimum length", "1", "Text Length Range"), ("Maximum length", "10", "Text Length Range"),
    ]


def test_a_bound_the_stored_document_declares_without_a_rule_is_shown_with_the_columns_fields():
    document = {"schema": [{"name": "orders", "properties": [
        {"name": "total", "logicalType": "number", "logicalTypeOptions": {"minimum": 0, "timezone": "UTC"}},
    ]}]}

    total, = _tab(document, ["orders"])["schema"][0]["columns"]

    assert {"label": "Minimum", "value": "0"} in total["fields"]
    assert {"label": "timezone", "value": "UTC"} in total["fields"]
    assert total["declared"] == []


def test_the_rule_counts_match_what_the_quality_rules_tab_lists_for_each_table_and_column():
    definitions = [
        _definition("orders", "ship_date"), _definition("orders", "ship_date"), _definition("orders", None),
        _definition("customers", "id"),
    ]

    table, = _schema(definitions=definitions)

    assert table["rule_count"] == 3
    assert [column["rule_count"] for column in table["columns"]] == [0, 2]


def test_a_version_whose_terms_cannot_be_rendered_shows_its_descriptors_without_rule_backed_fields():
    with patch.object(service, "render_document", side_effect=service.OrphanedTermError("orphan")):
        version = SuiteVersion(id=uuid4(), version=3, metadata_document=SCHEMA_DOCUMENT)
        with (
            patch.object(service, "catalog_table_names", return_value=["orders"]),
            patch.object(service.TableGroup, "get", return_value=TableGroup(table_groups_name="g")),
            patch.object(service.TestDefinition, "select_minimal_where", return_value=[]),
        ):
            table, = service.metadata_tab(_suite(), version, True)["schema"]

    assert [column["declared"] for column in table["columns"]] == [[], []]
    assert table["columns"][1]["fields"][-1] == {"label": "Unique", "value": "Yes"}


def test_the_rule_links_name_the_contract_and_the_version_on_screen():
    suite = _suite()
    version = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN, metadata_document={})
    with (
        patch.object(service, "catalog_table_names", return_value=[]),
        patch.object(service.TableGroup, "get", return_value=TableGroup(table_groups_name="g")),
        patch.object(service.contract_service, "document_status", return_value="active"),
        patch.object(service, "render_document", return_value={}),
        patch.object(service.TestDefinition, "select_minimal_where", return_value=[]),
    ):
        tab = service.metadata_tab(suite, version, True)

    assert tab["link_params"] == {"test_suite_id": str(suite.id), "version": "3"}


def test_a_column_offers_its_form_values_and_the_declarations_no_rule_backs():
    rendered = _rendered(required=True, customProperties=[_marker("ship-required", "Required", "required")])

    ship_date = _schema(rendered=rendered)[0]["columns"][1]

    assert ship_date["form"] == {
        "logicalType": "date", "physicalType": "DATE", "primaryKey": False, "primaryKeyPosition": "",
        "classification": "internal", "criticalDataElement": True, "description": "Date the order left.",
        "examples": ["2026-03-01", "2026-03-04"], "unique": True,
    }
    assert ship_date["declarable"] == ["unique"]


def test_a_table_offers_its_form_values():
    assert _schema()[0]["form"] == {
        "description": "One row per order.", "dataGranularityDescription": "Order", "logicalType": "object",
    }


STORED_SCHEMA = {
    "name": "orders_contract",
    "schema": [
        {"name": "orders", "description": "Old", "quality": [{"type": "text", "description": "kept"}], "properties": [
            {"name": "ship_date", "logicalType": "date", "examples": [20260301, "2026-03-04"], "tags": ["kept"],
             "required": False},
            {"name": "total", "logicalType": "number"},
        ]},
        {"name": "customers", "description": "Untouched"},
    ],
    "team": {"name": "Kept"},
}


def _saved_schema(section, values, saved=None, stored=STORED_SCHEMA):
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), version=4, metadata_document=stored)
    saved = saved or SavedMetadata(
        version_id=draft.id, unverifiable_rules=[], unresolved_declarations=[], untested_declarations=[],
        overridden_declarations=[], unchecked_paths=[], problems=[],
    )
    with (
        patch.object(service.SuiteVersion, "draft_for", return_value=draft),
        patch.object(service.SuiteVersion, "get", return_value=draft),
        patch.object(service.contract_service, "save_metadata_document", return_value=saved) as save,
    ):
        result = service.save_section(suite, section, values)
    return result, (save.call_args.args[1] if save.called else None)


def test_saving_a_table_replaces_only_its_descriptor_fields():
    values = {"table": "orders", "description": "One row per order.", "dataGranularityDescription": "",
              "logicalType": "object"}

    result, document = _saved_schema(service.MetadataSection.SCHEMA_TABLE, values)

    orders, customers = document["schema"]
    assert {key: orders.get(key) for key in ("description", "dataGranularityDescription", "logicalType")} == {
        "description": "One row per order.", "dataGranularityDescription": None, "logicalType": "object",
    }
    assert orders["quality"] == STORED_SCHEMA["schema"][0]["quality"]
    assert orders["properties"] == STORED_SCHEMA["schema"][0]["properties"]
    assert customers == STORED_SCHEMA["schema"][1]
    assert document["team"] == {"name": "Kept"}
    assert result["message"] == "orders saved to v4 draft."


COLUMN_VALUES = {
    "table": "orders", "column": "ship_date", "logicalType": "date", "physicalType": "DATE", "primaryKey": True,
    "primaryKeyPosition": "2", "classification": "", "criticalDataElement": False, "description": "Shipped on.",
    "examples": ["20260301", "2026-03-04"],
}


def test_saving_a_column_replaces_only_the_fields_its_form_edits():
    _, document = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, COLUMN_VALUES)

    ship_date, total = document["schema"][0]["properties"]
    assert ship_date == {
        "name": "ship_date", "logicalType": "date", "physicalType": "DATE", "primaryKey": True, "primaryKeyPosition": 2,
        "description": "Shipped on.", "examples": [20260301, "2026-03-04"], "tags": ["kept"], "required": False,
    }
    assert total == {"name": "total", "logicalType": "number"}


def test_saving_a_column_finds_it_by_the_physical_name_the_card_sends():
    stored = {"schema": [{"name": "orders", "properties": [
        {"name": "Ship Date", "physicalName": "ship_dt", "logicalType": "date"},
    ]}]}

    result, document = _saved_schema(
        service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "column": "ship_dt"}, stored=stored,
    )

    assert result["success"] is True
    column, = document["schema"][0]["properties"]
    assert (column["name"], column["physicalName"], column["description"]) == ("Ship Date", "ship_dt", "Shipped on.")


def test_changed_examples_are_stored_as_entered():
    _, document = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "examples": ["2026-03-01", " "]})

    assert document["schema"][0]["properties"][0]["examples"] == ["2026-03-01"]


def test_a_cleared_primary_key_and_critical_data_element_are_removed():
    values = {**COLUMN_VALUES, "primaryKey": False, "primaryKeyPosition": "", "criticalDataElement": False}
    stored = {"schema": [{"name": "orders", "properties": [
        {"name": "ship_date", "primaryKey": True, "primaryKeyPosition": 1, "criticalDataElement": True},
    ]}]}

    _, document = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, values, stored=stored)

    column = document["schema"][0]["properties"][0]
    assert not {"primaryKey", "primaryKeyPosition", "criticalDataElement"} & set(column)


def test_a_declaration_the_form_offers_is_set_and_one_it_leaves_unchanged_keeps_its_stored_value():
    _, document = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "unique": True, "required": False})

    column = document["schema"][0]["properties"][0]
    assert column["unique"] is True
    assert column["required"] is False


def test_a_declaration_the_form_turns_off_is_removed():
    stored = {"schema": [{"name": "orders", "properties": [{"name": "ship_date", "unique": True}]}]}

    _, document = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "unique": False}, stored=stored)

    assert "unique" not in document["schema"][0]["properties"][0]


def _unchecked(*paths):
    return SavedMetadata(
        version_id=uuid4(), unverifiable_rules=[], unresolved_declarations=[], untested_declarations=[],
        overridden_declarations=[], unchecked_paths=list(paths), problems=[],
    )


def test_a_declaration_no_rule_checks_saves_with_a_warning_naming_it():
    saved = _unchecked("orders.ship_date: unique", "orders.ship_date: required")

    result, _ = _saved_schema(
        service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "required": True, "unique": True}, saved=saved,
    )

    assert result["success"] is True
    assert result["warnings"] == [
        "`required` is declared on orders.ship_date, but no quality rule checks it.",
        "`unique` is declared on orders.ship_date, but no quality rule checks it.",
    ]


def test_only_the_declarations_no_rule_checks_are_warned_about():
    saved = _unchecked("orders.ship_date: unique", "orders.ship_date: logicalTypeOptions.minLength")

    result, _ = _saved_schema(
        service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "required": True, "unique": True}, saved=saved,
    )

    assert result["warnings"] == ["`unique` is declared on orders.ship_date, but no quality rule checks it."]


def test_an_unchecked_path_on_another_column_is_not_warned_about():
    saved = _unchecked("orders.total: required")

    result, _ = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "required": True}, saved=saved)

    assert result["warnings"] == []


def test_a_declaration_a_rule_checks_saves_without_a_warning():
    result, _ = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "required": True})

    assert result["warnings"] == []


def test_saving_a_column_the_contract_no_longer_declares_is_refused():
    result, document = _saved_schema(service.MetadataSection.SCHEMA_COLUMN, {**COLUMN_VALUES, "column": "gone"})

    assert document is None
    assert result == {
        "success": False, "message": "No changes saved. orders.gone is no longer in the contract.", "problems": [],
        "markers": [],
    }
