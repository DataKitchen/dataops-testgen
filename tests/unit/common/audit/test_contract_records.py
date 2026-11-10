from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.audit.contracts import (
    document_changes,
    record_document_imported,
    record_document_updated,
    record_draft_discarded,
    record_version_frozen,
)
from testgen.common.audit.test_definitions import AuditedTest
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_suite import TestSuite
from testgen.common.test_definition_export_import_service import ImportAction

pytestmark = pytest.mark.unit

MODULE = "testgen.common.audit.contracts"


def _contract() -> TestSuite:
    return TestSuite(id=uuid4(), project_code="demo", test_suite="Orders")


def _entries(audit_log) -> list[tuple]:
    return [
        (entry["action"], entry["target_type"], entry["targets"], entry["target_name"], entry["project_code"],
         entry["changes"])
        for entry in audit_log.records()
    ]


def _schema(*tables: str) -> list[dict]:
    return [{"name": table, "properties": [{"name": "id"}]} for table in tables]


def test_document_changes_lists_the_top_level_fields_that_differ():
    before = {"name": "Orders", "description": {"purpose": "a"}, "team": [{"username": "ana"}], "tags": ["x"]}
    after = {"name": "Orders", "description": {"purpose": "b"}, "team": [{"username": "ana"}], "slaProperties": []}

    assert document_changes(before, after) == {
        "description": {"from": {"purpose": "a"}, "to": {"purpose": "b"}},
        "tags": {"from": ["x"], "to": None},
        "slaProperties": {"from": None, "to": []},
    }


def test_document_changes_lists_the_schema_without_values_and_the_tables_only_when_one_is_added_or_removed():
    before = {"schema": _schema("orders", "customers")}
    edited_inside = {"schema": [{"name": "orders", "description": "new"}, {"name": "customers"}]}
    removed = {"schema": _schema("orders")}

    assert document_changes(before, before) == {}
    assert document_changes(before, edited_inside) == {"schema": {}}
    assert document_changes(before, removed) == {
        "schema": {}, "tables": {"from": ["orders", "customers"], "to": ["orders"]},
    }


def test_document_changes_leaves_out_the_version_number_and_the_name():
    assert document_changes({"version": "1.0.0", "name": "Orders"}, {"version": "2.0.0", "name": "Sales"}) == {}


def test_a_document_edit_is_recorded_on_the_contract_naming_the_version(audit_session, audit_log):
    contract = _contract()
    with patch(f"{MODULE}._version_document", return_value=(3, {"description": {"purpose": "b"}})):
        record_document_updated(contract, uuid4(), {"description": {"purpose": "a"}})
    audit_session.commit()

    assert _entries(audit_log) == [(
        "contract_version.updated", "contract_version", [str(contract.id)], "Orders v3", "demo",
        {"description": {"from": {"purpose": "a"}, "to": {"purpose": "b"}}},
    )]


def test_a_document_edit_whose_previous_document_is_unknown_records_nothing(audit_session, audit_log):
    with patch(f"{MODULE}._version_document", return_value=(3, {"description": {"purpose": "b"}})):
        record_document_updated(_contract(), uuid4(), None)
    audit_session.commit()

    assert audit_log.records() == []


def test_a_document_edit_that_changed_no_top_level_field_records_nothing(audit_session, audit_log):
    document = {"description": {"purpose": "a"}, "version": "3.0.0"}
    with patch(f"{MODULE}._version_document", return_value=(3, {**document, "version": "4.0.0"})):
        record_document_updated(_contract(), uuid4(), document)
    audit_session.commit()

    assert audit_log.records() == []


def test_an_import_records_the_tests_it_wrote_then_the_document(audit_session, audit_log):
    contract = _contract()
    created, updated, deleted = uuid4(), uuid4(), uuid4()
    described = {
        created: AuditedTest(id=created, project_code="demo", name="Unique Values on orders.id"),
        updated: AuditedTest(id=updated, project_code="demo", name="Row Count on orders"),
    }
    with (
        patch(f"{MODULE}._version_document", return_value=(2, {"description": {"purpose": "b"}})),
        patch("testgen.common.audit.test_definitions.describe_tests",
              side_effect=lambda ids: [described[identifier] for identifier in ids]),
    ):
        record_document_imported(
            contract,
            uuid4(),
            {"description": {"purpose": "a"}},
            {ImportAction.create: [created], ImportAction.update: [updated], ImportAction.delete: [deleted]},
        )
    audit_session.commit()

    assert [(entry[0], entry[2], entry[3]) for entry in _entries(audit_log)] == [
        ("test_definition.created", [str(created)], "Unique Values on orders.id"),
        ("test_definition.updated", [str(updated)], "Row Count on orders"),
        ("test_definition.deleted", [str(deleted)], None),
        ("contract_version.updated", [str(contract.id)], "Orders v2"),
    ]


def test_a_frozen_version_is_recorded_with_its_label(audit_session, audit_log):
    contract = _contract()
    record_version_frozen(contract, SuiteVersion(version=2, label="Q3 agreement"))
    record_version_frozen(contract, SuiteVersion(version=3))
    audit_session.commit()

    assert [(entry[0], entry[3], entry[5]) for entry in _entries(audit_log)] == [
        ("contract_version.frozen", "Orders v2", {"label": {"to": "Q3 agreement"}}),
        ("contract_version.frozen", "Orders v3", {}),
    ]


def test_a_discarded_draft_is_recorded_as_its_version_deleted(audit_session, audit_log):
    contract = _contract()
    record_draft_discarded(contract, 4)
    audit_session.commit()

    assert _entries(audit_log) == [
        ("contract_version.deleted", "contract_version", [str(contract.id)], "Orders v4", "demo", {}),
    ]
