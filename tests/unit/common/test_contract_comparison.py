from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common import contract_comparison
from testgen.common.contract_comparison import (
    DocumentChangeKind,
    HiddenValue,
    ItemName,
    TermChangeKind,
    document_changes,
    term_changes,
    version_document_changes,
)
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite

pytestmark = pytest.mark.unit

EARLIER = datetime(2026, 9, 1, tzinfo=UTC)
LATER = datetime(2026, 10, 1, tzinfo=UTC)
SOURCE = uuid4()
TARGET = uuid4()


def _term(term_id, **fields):
    return TestDefinition(
        id=uuid4(), contract_term_id=term_id, test_type=fields.pop("test_type", "Required"),
        table_name=fields.pop("table_name", "orders"), column_name=fields.pop("column_name", "amount"),
        last_auto_gen_date=fields.pop("last_auto_gen_date", EARLIER),
        last_manual_update=fields.pop("last_manual_update", None), **fields,
    )


def _changes(before, after):
    terms = {
        SOURCE: {term.contract_term_id: term for term in before},
        TARGET: {term.contract_term_id: term for term in after},
    }
    with patch.object(contract_comparison, "_terms_by_identity", side_effect=lambda version_id: terms[version_id]):
        return term_changes(SOURCE, TARGET)


def test_a_changed_generation_stamp_reads_as_regenerated():
    [change] = _changes(
        [_term("max", baseline_value="100")], [_term("max", baseline_value="120", last_auto_gen_date=LATER)],
    )

    assert change.kind is TermChangeKind.REGENERATED
    assert change.fields == ["baseline_value"]


def test_a_changed_edit_stamp_reads_as_edited():
    [change] = _changes([_term("req", threshold_value="0")], [_term("req", threshold_value="5", last_manual_update=LATER)])

    assert change.kind is TermChangeKind.EDITED
    assert change.fields == ["threshold_value"]


def test_both_stamps_changed_read_as_regenerated_and_edited():
    [change] = _changes(
        [_term("req", threshold_value="0")],
        [_term("req", threshold_value="5", last_auto_gen_date=LATER, last_manual_update=LATER)],
    )

    assert change.kind is TermChangeKind.REGENERATED_AND_EDITED


def test_a_difference_with_neither_stamp_moved_reads_as_changed():
    [change] = _changes([_term("req", severity="Fail")], [_term("req", severity="Warning")])

    assert change.kind is TermChangeKind.CHANGED
    assert change.fields == ["severity"]


def test_a_term_is_matched_by_its_term_id():
    [change] = _changes([_term("req")], [_term("req", column_name="total", last_manual_update=LATER)])

    assert change.kind is TermChangeKind.EDITED
    assert change.fields == ["column_name"]
    assert change.term.column_name == "total"


def test_added_and_removed_terms_carry_only_their_own_side():
    changes = {change.kind: change for change in _changes([_term("gone")], [_term("new", column_name="b")])}

    added, removed = changes[TermChangeKind.ADDED], changes[TermChangeKind.REMOVED]
    assert added.before is None and added.after.contract_term_id == "new" and added.fields == []
    assert removed.after is None and removed.before.contract_term_id == "gone" and removed.fields == []


def test_values_a_column_stores_alike_are_not_a_change():
    assert _changes(
        [_term("req", window_days=None, history_lookback=None, test_description="")],
        [_term("req", window_days=0, history_lookback=0, test_description=None)],
    ) == []


def test_changes_are_ordered_by_table_column_and_test_type():
    after = [
        _term("c", table_name="orders", column_name="b"),
        _term("a", table_name="customers", column_name="z"),
        _term("b", table_name="orders", column_name="a", test_type="Unique"),
        _term("d", table_name="orders", column_name="a", test_type="Max_Val"),
    ]

    assert [change.term.contract_term_id for change in _changes([], after)] == ["a", "d", "b", "c"]


def test_a_term_with_no_change_is_not_listed():
    assert _changes([_term("req", threshold_value="1")], [_term("req", threshold_value="1")]) == []


def test_document_changes_report_paths_in_todays_notation():
    before = {"name": "Orders", "schema": [{"name": "orders", "description": "Old"}, {"name": "gone"}]}
    after = {"name": "Orders", "team": {"name": "Data"}, "schema": [{"name": "orders", "description": "New"}]}

    changes = [(change.path, change.kind) for change in document_changes(before, after, hide_source_data=False)]

    assert changes == [
        ("$.schema[orders].description", DocumentChangeKind.CHANGED),
        ("$.schema[gone]", DocumentChangeKind.REMOVED),
        ("$.team", DocumentChangeKind.ADDED),
    ]


def test_a_changed_scalar_carries_both_values():
    [change] = document_changes({"description": {"usage": "Old"}}, {"description": {"usage": "New"}}, False)

    assert change.steps == ("description", "usage")
    assert (change.before, change.after) == ("Old", "New")


def test_an_added_item_carries_its_name_as_a_step():
    [change] = document_changes({"schema": []}, {"schema": [{"name": "orders"}]}, False)

    assert change.steps == ("schema", ItemName("orders"))
    assert (change.before, change.after) == (None, {"name": "orders"})


def _column(examples):
    return {"schema": [{"name": "orders", "properties": [{"name": "amount", "examples": examples}]}]}


def test_under_hiding_a_changed_hidden_value_carries_hidden_values_only():
    [change] = document_changes(_column(["Jane Doe"]), _column(["John Roe"]), hide_source_data=True)

    assert change.path == "$.schema[orders].properties[amount].examples"
    assert isinstance(change.before, HiddenValue) and isinstance(change.after, HiddenValue)
    assert "Jane" not in repr(change) and "John" not in repr(change)


def test_under_hiding_an_unchanged_hidden_value_is_not_a_change():
    assert document_changes(_column([12.5]), _column([12.5]), hide_source_data=True) == []


def test_without_hiding_a_hidden_field_carries_its_values():
    [change] = document_changes(_column(["a"]), _column(["b"]), hide_source_data=False)

    assert (change.before, change.after) == (["a"], ["b"])


def test_a_missing_document_compares_as_empty():
    [change] = document_changes(None, {"name": "x"}, hide_source_data=False)

    assert (change.path, change.kind, change.after) == ("$.name", DocumentChangeKind.ADDED, "x")


def test_document_changes_do_not_modify_their_inputs():
    before, after = _column(["a"]), _column(["b"])
    document_changes(before, after, hide_source_data=True)

    assert before == _column(["a"]) and after == _column(["b"])


def _paths(before, after):
    return [(change.path, change.kind) for change in document_changes(before, after, hide_source_data=False)]


def test_team_members_are_matched_by_username():
    ana = {"username": "ana@acme.com", "role": "owner"}
    li = {"username": "li@acme.com", "role": "data steward"}

    assert _paths({"team": {"members": [ana]}}, {"team": {"members": [ana, li]}}) == [
        ("$.team.members[li@acme.com]", DocumentChangeKind.ADDED),
    ]


def test_the_deprecated_team_array_is_matched_by_username():
    ana = {"username": "ana@acme.com", "role": "owner"}

    assert _paths({"team": [ana]}, {"team": [{**ana, "role": "steward"}]}) == [
        ("$.team[ana@acme.com].role", DocumentChangeKind.CHANGED),
    ]


def test_service_levels_are_matched_by_property():
    [change] = document_changes(
        {"slaProperties": [{"property": "latency", "value": 6}, {"property": "retention", "value": 7}]},
        {"slaProperties": [{"property": "latency", "value": 4}, {"property": "retention", "value": 7}]},
        hide_source_data=False,
    )

    assert (change.path, change.before, change.after) == ("$.slaProperties[latency].value", 6, 4)


def test_a_list_is_matched_on_a_key_both_sides_share():
    before = {"team": {"members": [{"username": "ana@acme.com", "name": "Ana"}]}}
    after = {"team": {"members": [{"username": "ana@acme.com", "name": "Ana"}, {"username": "li@acme.com"}]}}

    assert _paths(before, after) == [("$.team.members[li@acme.com]", DocumentChangeKind.ADDED)]


def test_a_list_whose_items_share_a_key_is_compared_whole():
    before = {"team": {"members": [{"username": "ana"}, {"username": "ana"}]}}
    after = {"team": {"members": [{"username": "ana"}]}}

    assert _paths(before, after) == [("$.team.members", DocumentChangeKind.CHANGED)]


def test_a_versions_status_is_not_a_change():
    source = SuiteVersion(id=uuid4(), version=3, frozen_at=EARLIER, metadata_document={"status": "active"})
    target = SuiteVersion(id=uuid4(), version=4, frozen_at=None, metadata_document={"status": "draft"})

    assert version_document_changes(source, target, TestSuite(test_suite="orders"), hide_source_data=False) == []


def test_a_status_edit_is_a_document_change():
    assert _paths({"status": "active"}, {"status": "retired"}) == [("$.status", DocumentChangeKind.CHANGED)]


def test_fields_testgen_owns_are_not_a_change():
    source = SuiteVersion(
        id=uuid4(), version=1, frozen_at=EARLIER,
        metadata_document={"apiVersion": "v3.1.0", "kind": "DataContract", "id": "a", "version": "1.0.0"},
    )
    target = SuiteVersion(
        id=uuid4(), version=2, frozen_at=None,
        metadata_document={"apiVersion": "v3.2.0", "kind": "DataContract", "id": "b", "version": "2.0.0"},
    )

    assert version_document_changes(source, target, TestSuite(test_suite="orders"), hide_source_data=False) == []
