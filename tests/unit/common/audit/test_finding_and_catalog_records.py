from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.audit.catalog import record_catalog_changes
from testgen.common.audit.findings import record_issue_dispositions, record_result_dispositions
from testgen.common.audit.selections import AuditedObject
from testgen.common.audit.test_definitions import AuditedTest
from testgen.common.enums import Disposition
from testgen.common.models.data_column import CATALOG_TAG_FIELDS, DataColumnChars
from testgen.common.models.data_table import CATALOG_TAG_LABELS, DataTable
from testgen.common.test_result_disposition_service import DispositionUpdate

pytestmark = pytest.mark.unit

FINDINGS = "testgen.common.audit.findings"
CATALOG = "testgen.common.audit.catalog"


def _entries(audit_log) -> list[tuple]:
    return [
        (entry["action"], entry["target_type"], entry["target_count"], entry["target_name"], entry["project_code"],
         entry["cause_type"], entry["changes"])
        for entry in audit_log.records()
    ]


def _named(identifier, name="Value Match on customers.income", project_code="demo"):
    return AuditedObject(id=identifier, project_code=project_code, name=name)


def test_muting_a_result_records_it_and_its_test_disabled_and_locked(audit_session, audit_log):
    result_id, test_id = uuid4(), uuid4()
    update = DispositionUpdate(matched=1, passed_skipped=0, changed={result_id: None}, switched=(test_id,),
                               relocked=(test_id,))
    test = AuditedTest(id=test_id, project_code="demo", name="Value Match on customers.income")
    with (
        patch(f"{FINDINGS}._describe_results", return_value=[_named(result_id)]),
        patch(f"{FINDINGS}.describe_tests", return_value=[test]),
    ):
        record_result_dispositions(update, Disposition.INACTIVE)
    audit_session.commit()

    name = "Value Match on customers.income"
    assert _entries(audit_log) == [
        ("test_result.updated", "test_result", 1, name, "demo", None,
         {"disposition": {"from": None, "to": "Inactive"}}),
        ("test_definition.disabled", "test_definition", 1, name, "demo", None, {}),
        ("test_definition.updated", "test_definition.state", 1, name, "demo", None,
         {"lock_refresh": {"from": False, "to": True}}),
    ]


def test_clearing_a_muted_selection_records_the_reverse_once(audit_session, audit_log):
    results = [uuid4(), uuid4()]
    tests = [AuditedTest(id=uuid4(), project_code="demo", name=None) for _ in results]
    update = DispositionUpdate(matched=2, passed_skipped=0, changed=dict.fromkeys(results, "Inactive"),
                               switched=tuple(test.id for test in tests), relocked=tuple(test.id for test in tests))
    with (
        patch(f"{FINDINGS}._describe_results", return_value=[_named(result) for result in results]),
        patch(f"{FINDINGS}.describe_tests", return_value=tests),
    ):
        record_result_dispositions(update, None)
    audit_session.commit()

    assert [(entry[0], entry[1], entry[2], entry[6]) for entry in _entries(audit_log)] == [
        ("test_result.updated", "test_result", 2, {"disposition": {"to": None}}),
        ("test_definition.enabled", "test_definition", 2, {}),
        ("test_definition.updated", "test_definition.state", 2, {"lock_refresh": {"to": False}}),
    ]


def test_a_disposition_that_changed_no_result_records_nothing(audit_session, audit_log):
    with patch(f"{FINDINGS}._describe_results", return_value=[]):
        record_result_dispositions(DispositionUpdate(matched=1, passed_skipped=0), Disposition.CONFIRMED)
    audit_session.commit()

    assert audit_log.records() == []


def test_a_hygiene_issue_disposition_records_its_previous_value(audit_session, audit_log):
    issue = uuid4()
    with patch(f"{FINDINGS}._describe_issues", return_value=[_named(issue, "Non-Standard Blanks on orders.notes")]):
        record_issue_dispositions({issue: "Confirmed"}, "Dismissed")
    audit_session.commit()

    assert _entries(audit_log) == [(
        "hygiene_issue.updated", "hygiene_issue", 1, "Non-Standard Blanks on orders.notes", "demo", None,
        {"disposition": {"from": "Confirmed", "to": "Dismissed"}},
    )]


def test_issues_already_in_the_new_disposition_are_left_out(audit_session, audit_log):
    changed, unchanged = uuid4(), uuid4()
    with patch(f"{FINDINGS}._describe_issues", side_effect=lambda ids: [_named(i) for i in ids]) as describe:
        record_issue_dispositions({changed: None, unchanged: "Dismissed"}, "Dismissed")
    audit_session.commit()

    assert list(describe.call_args.args[0]) == [changed]
    [entry] = audit_log.records()
    assert entry["target_count"] == 1


def _column(table_groups_id, **values) -> DataColumnChars:
    defaults = {"description": None, "data_source": None, "pii_flag": None, "critical_data_element": None}
    column = DataColumnChars(id=uuid4(), table_groups_id=table_groups_id, table_name="orders", column_name="amount",
                             **{**defaults, **values})
    make_transient_to_detached(column)
    return column


def test_a_catalog_edit_of_one_column_records_its_previous_and_new_values(audit_session, audit_log):
    group = uuid4()
    column = _column(group)
    column.description = "Order total"
    column.pii_flag = "MANUAL"
    with patch(f"{CATALOG}._projects", return_value={group: "demo"}):
        record_catalog_changes([column])
    audit_session.commit()

    assert _entries(audit_log) == [(
        "catalog_column.updated", "catalog_column", 1, "orders.amount", "demo", None,
        {"description": {"from": None, "to": "Order total"}, "pii_flag": {"from": None, "to": "MANUAL"}},
    )]


def test_a_catalog_edit_of_a_selection_records_the_values_they_share_per_kind(audit_session, audit_log):
    group = uuid4()
    columns = [_column(group), _column(group, data_source="erp")]
    table = DataTable(id=uuid4(), table_groups_id=group, table_name="orders", data_source=None)
    make_transient_to_detached(table)
    for entry in (*columns, table):
        entry.data_source = "crm"
    columns[0].description = "only on one"
    unchanged = _column(group, data_source="crm")
    unchanged.data_source = "crm"
    with patch(f"{CATALOG}._projects", return_value={group: "demo"}):
        record_catalog_changes([*columns, table, unchanged])
    audit_session.commit()

    assert _entries(audit_log) == [
        ("catalog_column.updated", "catalog_column", 2, None, "demo", None, {"data_source": {"to": "crm"}}),
        ("catalog_table.updated", "catalog_table", 1, "orders", "demo", None,
         {"data_source": {"from": None, "to": "crm"}}),
    ]


def test_a_catalog_edit_across_projects_writes_one_record_per_project(audit_session, audit_log):
    sales, finance = uuid4(), uuid4()
    columns = [_column(sales), _column(sales), _column(finance)]
    for column in columns:
        column.data_source = "crm"
    with patch(f"{CATALOG}._projects", return_value={sales: "sales", finance: "finance"}):
        record_catalog_changes(columns)
    audit_session.commit()

    assert sorted((entry["project_code"], entry["target_count"]) for entry in audit_log.records()) == [
        ("finance", 1), ("sales", 2),
    ]


def test_catalog_records_declare_every_catalog_tag():
    assert tuple(CATALOG_TAG_LABELS) == CATALOG_TAG_FIELDS
    assert set(CATALOG_TAG_FIELDS) <= set(DataTable.__audit__.values)
    assert set(CATALOG_TAG_FIELDS) <= set(DataColumnChars.__audit__.values)


def test_a_selection_split_by_project_keeps_each_single_issues_previous_value(audit_session, audit_log):
    sales, finance = uuid4(), uuid4()
    described = [_named(sales, project_code="sales"), _named(finance, project_code="finance")]
    with patch(f"{FINDINGS}._describe_issues", return_value=described):
        record_issue_dispositions({sales: None, finance: "Dismissed"}, "Confirmed")
    audit_session.commit()

    previous = {
        entry["project_code"]: entry["changes"]["disposition"].get("from", "-") for entry in audit_log.records()
    }
    assert previous == {"finance": "Dismissed", "sales": None}
