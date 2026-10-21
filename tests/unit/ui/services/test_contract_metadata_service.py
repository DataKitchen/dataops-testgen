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


def _tab(document: dict, catalog: list[str], editable: bool = True) -> dict:
    version = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN, metadata_document=document)
    with (
        patch.object(service, "catalog_table_names", return_value=catalog),
        patch.object(service.TableGroup, "get", return_value=TableGroup(table_groups_name="sales_tables")),
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
    ):
        tab = service.metadata_tab(_suite(), version, True)

    assert tab["tables"] == []
    assert tab["document"] == service.serialize_document({})


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
        overridden_declarations=[], problems=[],
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
    }
    document = save.call_args.args[1]
    assert save.call_args.args[0] is suite
    assert document["schema"][1]["name"] == "customers"


def test_saving_reports_rules_stored_as_unverifiable_and_problems_left():
    saved = SavedMetadata(
        version_id=uuid4(), unverifiable_rules=["customers: rule 1", "orders: rule 2"], unresolved_declarations=[],
        untested_declarations=[], overridden_declarations=[], problems=["$.servers[0].account: 5 is not of type 'string'"],
    )

    result, _, _ = _save(DOCUMENT_TEXT, saved=saved)

    assert result["message"] == (
        "Contract document saved to v4 draft. 2 rules no test type checks were stored as unverifiable. "
        "The document still has 1 problem, and the draft cannot be frozen until it is fixed."
    )


def test_one_unverifiable_rule_and_several_problems_read_in_the_singular_and_plural():
    saved = SavedMetadata(
        version_id=uuid4(), unverifiable_rules=["customers: rule 1"], unresolved_declarations=[],
        untested_declarations=[], overridden_declarations=[], problems=["$.a: x", "$.b: y"],
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


def _save_tables(selected, declared, generations=(), removed_terms=0, side_effect=None):
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
    ):
        result = service.save_tables(suite, selected)
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
