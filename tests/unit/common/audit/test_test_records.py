from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.names import object_name
from testgen.common.audit.selections import AuditedObject, common_changes, record_selection
from testgen.common.audit.test_definitions import (
    AuditedTest,
    record_import,
    record_status_changed,
    record_test_saved,
    record_tests_deleted,
    record_tests_moved,
)
from testgen.common.models.test_definition import TestDefinition
from testgen.common.test_definition_export_import_service import (
    ImportAction,
    ImportConfig,
    ImportItem,
    ImportItemTD,
    ImportMode,
    ImportReason,
    ImportResponse,
    ImportSummary,
    OnAbsence,
    OnMatch,
    OnNew,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.common.audit.test_definitions"


@pytest.fixture(autouse=True)
def named_definitions(monkeypatch):
    """Name and place test definitions without a database to look them up in."""
    monkeypatch.setattr(
        TestDefinition,
        "__audit__",
        replace(
            TestDefinition.__audit__,
            name=lambda definition: object_name("Alpha Truncation", definition.table_name, definition.column_name),
            project=lambda _definition: "demo",
        ),
    )


def _entries(audit_log) -> list[tuple]:
    return [
        (entry["action"], entry["target_type"], entry["target_count"], entry["target_name"], entry["project_code"],
         entry["changes"])
        for entry in audit_log.records()
    ]


def _definition(**values) -> TestDefinition:
    defaults = {"id": uuid4(), "test_suite_id": uuid4(), "test_type": "Alpha_Trunc", "table_name": "orders",
                "column_name": "amount"}
    return TestDefinition(**{**defaults, **values})


def _stored_of(definition: TestDefinition, **values) -> dict:
    declared = TestDefinition.__audit__.declared()
    return {name: getattr(definition, name, None) for name in declared} | values


def _test(project_code="demo", name="Alpha Truncation on orders.amount", **values) -> AuditedTest:
    return AuditedTest(id=uuid4(), project_code=project_code, name=name, **values)


def test_a_form_edit_records_only_the_fields_it_changed(audit_session, audit_log):
    definition = _definition(threshold_value="60", severity="Fail", test_description="")
    stored = _stored_of(definition, threshold_value="58", test_description=None)

    record_test_saved(definition, created=False, stored=stored)
    audit_session.commit()

    assert _entries(audit_log) == [(
        "test_definition.updated", "test_definition", 1, "Alpha Truncation on orders.amount", "demo",
        {"threshold_value": {"from": "58", "to": "60"}},
    )]


def test_a_form_edit_that_changed_nothing_records_nothing(audit_session, audit_log):
    definition = _definition(threshold_value="58")

    record_test_saved(definition, created=False, stored=_stored_of(definition))
    audit_session.commit()

    assert audit_log.records() == []


def test_an_edit_records_the_lock_as_state_and_the_switch_on_its_own(audit_session, audit_log):
    definition = _definition(threshold_value="60", lock_refresh=True, test_active=False)
    stored = _stored_of(definition, threshold_value="58", lock_refresh=False, test_active=True)

    record_test_saved(definition, created=False, stored=stored)
    audit_session.commit()

    assert [entry[:2] + entry[5:] for entry in _entries(audit_log)] == [
        ("test_definition.updated", "test_definition", {"threshold_value": {"from": "58", "to": "60"}}),
        ("test_definition.updated", "test_definition.state", {"lock_refresh": {"from": False, "to": True}}),
        ("test_definition.disabled", "test_definition", {}),
    ]


def test_a_tool_edit_reads_its_changes_from_the_loaded_test(audit_session, audit_log):
    definition = _definition(threshold_value="58", flagged=False)
    make_transient_to_detached(definition)
    definition.threshold_value = "70"
    definition.flagged = True

    record_test_saved(definition, created=False)
    audit_session.commit()

    assert [entry[:2] + entry[5:] for entry in _entries(audit_log)] == [
        ("test_definition.updated", "test_definition", {"threshold_value": {"from": "58", "to": "70"}}),
        ("test_definition.updated", "test_definition.state", {"flagged": {"from": False, "to": True}}),
    ]


def test_a_created_test_records_the_values_it_was_given(audit_session, audit_log):
    definition = _definition(threshold_value="5")

    record_test_saved(definition, created=True)
    audit_session.commit()

    [(action, target_type, count, name, project, changes)] = _entries(audit_log)
    assert (action, target_type, count, name, project) == (
        "test_definition.created", "test_definition", 1, "Alpha Truncation on orders.amount", "demo",
    )
    assert changes["threshold_value"] == {"to": "5"}
    assert changes["test_type"] == {"to": "Alpha_Trunc"}


def test_a_monitor_edit_is_one_monitor_update_including_its_thresholds_and_lock(audit_session, audit_log):
    monitor = _definition(test_type="Volume_Trend", column_name=None, lower_tolerance="10", lock_refresh=True)
    stored = _stored_of(monitor, lower_tolerance=None, lock_refresh=False)

    record_test_saved(monitor, created=False, stored=stored)
    audit_session.commit()

    assert [entry[:3] + entry[5:] for entry in _entries(audit_log)] == [(
        "monitor.updated", "monitor", 1,
        {"lower_tolerance": {"from": None, "to": "10"}, "lock_refresh": {"from": False, "to": True}},
    )]


@pytest.mark.parametrize(("value", "action"), [(True, "test_definition.enabled"), (False, "test_definition.disabled")])
def test_switching_tests_on_or_off_carries_no_changes(audit_session, audit_log, value, action):
    tests = [_test(), _test()]
    with patch(f"{MODULE}.describe_tests", return_value=tests):
        record_status_changed("test_active", value, [test.id for test in tests])
    audit_session.commit()

    assert _entries(audit_log) == [(action, "test_definition", 2, None, "demo", {})]


def test_locking_a_selection_records_the_new_value_and_how_many(audit_session, audit_log):
    tests = [_test() for _ in range(3)]
    with patch(f"{MODULE}.describe_tests", return_value=tests):
        record_status_changed("lock_refresh", True, [test.id for test in tests])
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_type"], entry["target_count"], entry["target_name"]) == (
        "test_definition.updated", "test_definition.state", 3, None,
    )
    assert entry["targets"] == [str(test.id) for test in tests]
    assert entry["changes"] == {"lock_refresh": {"to": True}}


def test_flagging_one_test_records_its_name_and_previous_value(audit_session, audit_log):
    test = _test()
    with patch(f"{MODULE}.describe_tests", return_value=[test]):
        record_status_changed("flagged", True, [test.id])
    audit_session.commit()

    assert _entries(audit_log) == [(
        "test_definition.updated", "test_definition.state", 1, "Alpha Truncation on orders.amount", "demo",
        {"flagged": {"from": False, "to": True}},
    )]


def test_a_status_change_that_changed_no_test_records_nothing(audit_session, audit_log):
    with patch(f"{MODULE}.describe_tests", return_value=[]):
        record_status_changed("lock_refresh", True, [])
    audit_session.commit()

    assert audit_log.records() == []


def test_a_selection_across_projects_writes_one_record_per_project(audit_session, audit_log):
    objects = [_test("sales"), _test("sales"), _test("finance")]

    record_selection(AuditAction.TEST_DEFINITION_DISABLED, objects, AuditTargetType.TEST_DEFINITION)
    audit_session.commit()

    assert sorted((entry["project_code"], entry["target_count"]) for entry in audit_log.records()) == [
        ("finance", 1), ("sales", 2),
    ]


def test_the_count_stays_true_beyond_the_listed_targets(audit_session, audit_log):
    objects = [AuditedObject(id=uuid4(), project_code="demo", name=None) for _ in range(150)]

    record_selection(AuditAction.TEST_DEFINITION_DISABLED, objects, AuditTargetType.TEST_DEFINITION)
    audit_session.commit()

    [entry] = audit_log.records()
    assert entry["target_count"] == 150
    assert len(entry["targets"]) == 100


def test_a_move_records_the_suite_it_left_and_the_one_it_joined(audit_session, audit_log):
    source_suite, target_suite, table_group = uuid4(), uuid4(), uuid4()
    moving = [_test(test_suite_id=source_suite, table_groups_id=table_group)]

    record_tests_moved(moving, [moving[0].id], target_suite, table_group)
    audit_session.commit()

    assert _entries(audit_log) == [(
        "test_definition.updated", "test_definition.placement", 1, "Alpha Truncation on orders.amount", "demo",
        {"test_suite_id": {"from": str(source_suite), "to": str(target_suite)}},
    )]


def test_a_move_onto_another_column_records_it(audit_session, audit_log):
    moving = [_test(test_suite_id=uuid4(), table_groups_id=uuid4())]
    target_suite, target_group = uuid4(), uuid4()

    record_tests_moved(moving, [moving[0].id], target_suite, target_group, "customers", "email")
    audit_session.commit()

    [entry] = audit_log.records()
    assert set(entry["changes"]) == {"test_suite_id", "table_groups_id", "table_name", "column_name"}
    assert entry["changes"]["column_name"] == {"to": "email"}


def test_a_contract_move_targets_the_draft_copies_it_wrote(audit_session, audit_log):
    moving = [_test(test_suite_id=uuid4(), table_groups_id=uuid4())]
    copy_id = uuid4()

    record_tests_moved(moving, [copy_id], uuid4(), uuid4())
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["targets"], entry["project_code"]) == ([str(copy_id)], "demo")


def test_deleting_tests_records_the_monitors_among_them_as_monitors(audit_session, audit_log):
    record_tests_deleted([_test(), _test(), _test(name="Metric on orders", test_type="Metric_Trend")])
    audit_session.commit()

    assert [(entry[0], entry[1], entry[2]) for entry in _entries(audit_log)] == [
        ("test_definition.deleted", "test_definition", 2),
        ("monitor.deleted", "monitor", 1),
    ]


def _import_config(mode: ImportMode) -> ImportConfig:
    return ImportConfig(mode=mode, on_match=OnMatch.overwrite_all, on_new=OnNew.create, on_absence=OnAbsence.delete_all)


def _import_response(**ids) -> ImportResponse:
    items = [
        ImportItem(action=action, reason=ImportReason.matched, tds=[ImportItemTD(idx=0, target_id=i) for i in values])
        for action, values in ((ImportAction(key), value) for key, value in ids.items())
    ]
    return ImportResponse(summary=ImportSummary(), items=items)


def test_an_import_writes_one_record_per_effect(audit_session, audit_log):
    created, updated, deleted = [uuid4(), uuid4()], [uuid4()], [uuid4(), uuid4(), uuid4()]
    suite = type("Suite", (), {"id": uuid4(), "project_code": "demo"})()
    described = {tuple(created): [_test(), _test()], tuple(updated): [_test()]}
    with patch(f"{MODULE}.describe_tests", side_effect=lambda ids: described.get(tuple(ids), [])):
        record_import(suite, _import_config(ImportMode.apply), _import_response(
            create=created, update=updated, delete=deleted,
        ))
    audit_session.commit()

    assert [(entry[0], entry[2], entry[5]) for entry in _entries(audit_log)] == [
        ("test_definition.created", 2, {}),
        ("test_definition.updated", 1, {}),
        ("test_definition.deleted", 3, {}),
    ]


def test_an_import_preview_records_nothing(audit_session, audit_log):
    suite = type("Suite", (), {"id": uuid4(), "project_code": "demo"})()
    with patch(f"{MODULE}.describe_tests", return_value=[_test()]):
        record_import(suite, _import_config(ImportMode.preview), _import_response(update=[uuid4()]))
    audit_session.commit()

    assert audit_log.records() == []


def test_common_changes_keeps_only_the_values_every_object_shares():
    assert common_changes([
        {"data_source": {"from": None, "to": "crm"}, "description": {"to": "a"}},
        {"data_source": {"from": "erp", "to": "crm"}, "description": {"to": "b"}},
    ]) == {"data_source": {"to": "crm"}}


@pytest.mark.parametrize(
    ("label", "table", "column", "expected"),
    [
        ("Alpha Truncation", "orders", "amount", "Alpha Truncation on orders.amount"),
        ("Row Count", "orders", None, "Row Count on orders"),
        ("Custom Test", None, None, "Custom Test"),
    ],
)
def test_an_object_with_no_name_is_named_by_its_kind_and_what_it_is_on(label, table, column, expected):
    assert object_name(label, table, column) == expected


def test_a_form_number_equal_to_the_stored_text_is_no_change(audit_session, audit_log):
    definition = _definition(lower_tolerance=0, upper_tolerance=5.5)
    stored = _stored_of(definition, lower_tolerance="0", upper_tolerance="4")

    record_test_saved(definition, created=False, stored=stored)
    audit_session.commit()

    [entry] = audit_log.records()
    assert entry["changes"] == {"upper_tolerance": {"from": "4", "to": "5.5"}}


def test_common_changes_leaves_out_a_field_not_every_object_changed():
    assert common_changes([
        {"data_source": {"to": "crm"}, "description": {"to": "a"}},
        {"data_source": {"to": "crm"}},
    ]) == {"data_source": {"to": "crm"}}


def test_common_changes_leaves_out_withheld_and_unhashable_values():
    assert common_changes([
        {"password": {}, "custom_metadata": {"to": {"a": 1}}},
        {"password": {}, "custom_metadata": {"to": {"a": 1}}},
    ]) == {}


def test_values_the_database_stores_alike_are_no_change_across_column_types(audit_session, audit_log):
    definition = _definition(
        window_days="7", skip_errors=0, test_active=True, custom_metadata={"owner": "sales"}, severity="",
    )
    stored = _stored_of(
        definition, window_days=7, skip_errors=None, test_active=True, custom_metadata={"owner": "sales"},
        severity=None,
    )

    record_test_saved(definition, created=False, stored=stored)
    audit_session.commit()

    assert audit_log.records() == []


def test_a_real_change_is_reported_as_the_column_stores_it(audit_session, audit_log):
    definition = _definition(window_days="8", threshold_value=12)
    stored = _stored_of(definition, window_days=7, threshold_value="10")

    record_test_saved(definition, created=False, stored=stored)
    audit_session.commit()

    [entry] = audit_log.records()
    assert entry["changes"] == {
        "window_days": {"from": 7, "to": 8},
        "threshold_value": {"from": "10", "to": "12"},
    }
