from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.scorecards import record_scorecard_created, scorecard_changes
from testgen.common.audit.table_groups import record_table_group_created
from testgen.common.audit.test_suites import record_contract_created
from testgen.common.enums import SuiteType
from testgen.common.models.scores import ScoreCategory, ScoreDefinition, ScoreDefinitionCriteria
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

pytestmark = pytest.mark.unit

TG1 = {"field": "table_groups_name", "value": "tg1", "others": []}
TG2 = {"field": "table_groups_name", "value": "tg2", "others": []}


def _scorecard(filters: list[dict]) -> ScoreDefinition:
    scorecard = ScoreDefinition(id=uuid4(), project_code="demo", name="Card", total_score=True, cde_score=False,
                                category=ScoreCategory.impact_dimension)
    scorecard.criteria = ScoreDefinitionCriteria.from_filters(filters)
    return scorecard


def test_scorecard_changes_report_the_fields_and_filters_before_the_save(audit_session, audit_log):
    scorecard = _scorecard([TG1])
    make_transient_to_detached(scorecard)
    scorecard.name = "Renamed"
    scorecard.criteria = ScoreDefinitionCriteria.from_filters([TG2])

    record(AuditAction.SCORECARD_UPDATED, scorecard, changes=scorecard_changes(scorecard))
    audit_session.commit()

    assert audit_log.records()[0]["changes"] == {
        "name": {"from": "Card", "to": "Renamed"},
        "criteria": {
            "from": {"filters": [TG1], "group_by_field": True},
            "to": {"filters": [TG2], "group_by_field": True},
        },
    }


def test_the_same_filters_in_another_order_are_not_a_change(audit_session, audit_log):
    scorecard = _scorecard([TG1, TG2])
    make_transient_to_detached(scorecard)
    scorecard.criteria = ScoreDefinitionCriteria.from_filters([TG2, TG1])

    record(AuditAction.SCORECARD_UPDATED, scorecard, changes=scorecard_changes(scorecard))
    audit_session.commit()

    assert audit_log.records() == []


def test_a_created_scorecard_records_what_it_holds_after_the_save(audit_session, audit_log):
    scorecard = _scorecard([TG1])
    make_transient_to_detached(scorecard)  # saved and committed: no change history left

    record_scorecard_created(scorecard)
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"], entry["project_code"]) == ("scorecard.created", "Card", "demo")
    assert entry["changes"] == {
        "name": {"to": "Card"},
        "total_score": {"to": True},
        "cde_score": {"to": False},
        "category": {"to": "impact_dimension"},
        "criteria": {"to": {"filters": [TG1], "group_by_field": True}},
    }


def test_a_table_group_and_its_scorecard_are_recorded_separately(audit_session, audit_log):
    table_group = TableGroup(id=uuid4(), project_code="demo", connection_id=1, table_groups_name="Sales",
                             table_group_schema="sales")

    record_table_group_created(table_group, _scorecard([TG1]))
    record_table_group_created(TableGroup(id=uuid4(), project_code="demo", table_groups_name="Ops"))
    audit_session.commit()

    assert [(entry["action"], entry["target_name"]) for entry in audit_log.records()] == [
        ("table_group.created", "Sales"),
        ("scorecard.created", "Card"),
        ("table_group.created", "Ops"),
    ]
    assert audit_log.records()[0]["changes"]["table_group_schema"] == {"to": "sales"}


def test_a_contract_is_recorded_with_what_it_holds_after_its_creation_committed(audit_session, audit_log):
    contract = TestSuite(id=uuid4(), project_code="demo", test_suite="Orders contract", suite_type=SuiteType.CONTRACT,
                         monitor_lookback=14, predict_exclude_weekends=False)
    make_transient_to_detached(contract)

    record_contract_created(contract)
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"]) == ("test_suite.created", "Orders contract")
    assert entry["changes"]["suite_type"] == {"to": "contract"}
    assert not {"monitor_lookback", "predict_exclude_weekends"} & set(entry["changes"])
