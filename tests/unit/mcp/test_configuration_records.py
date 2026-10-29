"""Audit records of the MCP tools that change configuration."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.enums import JobKey, SuiteType
from testgen.common.models.notification_destinations import WebhookDestination
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.scores import ScoreCategory, ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS, TestSuite

pytestmark = pytest.mark.unit


def _stored(obj):
    """``obj`` as a tool holds it after resolving it: its values are the stored ones, with no changes pending."""
    make_transient_to_detached(obj)
    return obj


def _schedule(active: bool = True) -> JobSchedule:
    return _stored(JobSchedule(
        id=uuid4(), project_code="demo", key=JobKey.run_profile, kwargs={"table_group_id": str(uuid4())},
        cron_expr="0 3 * * *", cron_tz="UTC", active=active,
    ))


def _entries(audit_log) -> list[tuple]:
    return [(entry["action"], entry["source"], entry["changes"]) for entry in audit_log.records()]


@pytest.fixture
def saves():
    with (
        patch.object(JobSchedule, "save", autospec=True),
        patch.object(JobSchedule, "delete"),
        patch.object(TestSuite, "save", autospec=True),
        patch.object(ScoreDefinition, "delete", autospec=True),
        patch.object(WebhookDestination, "delete", autospec=True),
    ):
        yield


def test_pausing_a_schedule_records_the_pause_alone(saves, audit_session, audit_log):
    from testgen.mcp.tools.schedules import update_schedule

    schedule = _schedule()
    with patch("testgen.mcp.tools.schedules.resolve_schedule", return_value=schedule):
        update_schedule(schedule_id=str(schedule.id), active=False)
    audit_session.commit()

    assert _entries(audit_log) == [("schedule.paused", "mcp", {})]


def test_changing_a_schedule_and_resuming_it_writes_both_records(saves, audit_session, audit_log):
    from testgen.mcp.tools.schedules import update_schedule

    schedule = _schedule(active=False)
    with patch("testgen.mcp.tools.schedules.resolve_schedule", return_value=schedule):
        update_schedule(schedule_id=str(schedule.id), cron_expression="0 5 * * *", active=True)
    audit_session.commit()

    assert _entries(audit_log) == [
        ("schedule.updated", "mcp", {"cron_expr": {"from": "0 3 * * *", "to": "0 5 * * *"}}),
        ("schedule.resumed", "mcp", {}),
    ]


def test_deleting_a_schedule_records_it(saves, audit_session, audit_log):
    from testgen.mcp.tools.schedules import delete_schedule

    schedule = _schedule()
    with patch("testgen.mcp.tools.schedules.resolve_schedule", return_value=schedule):
        delete_schedule(schedule_id=str(schedule.id))
    audit_session.commit()

    assert [entry["targets"] for entry in audit_log.records()] == [[str(schedule.id)]]
    assert _entries(audit_log) == [("schedule.deleted", "mcp", {})]


def test_updating_a_test_suite_records_the_changed_fields(saves, audit_session, audit_log):
    from testgen.mcp.tools.test_suites import update_test_suite

    values = {column.key: None for column in TestSuite.__table__.columns}
    suite = _stored(TestSuite(**{
        **values, "id": uuid4(), "project_code": "demo", "test_suite": "Orders", "suite_type": SuiteType.REGULAR,
        "test_suite_description": "Old", "export_to_observability": False, "dq_score_exclude": False,
        "deactivate_invalid_tests": False,
    }))
    with patch("testgen.mcp.tools.test_suites.resolve_test_suite", return_value=suite):
        update_test_suite(test_suite_id=str(suite.id), description="New")
    audit_session.commit()

    assert _entries(audit_log) == [
        ("test_suite.updated", "mcp", {"test_suite_description": {"from": "Old", "to": "New"}}),
    ]


def test_deleting_a_scorecard_records_its_name(saves, audit_session, audit_log):
    from testgen.mcp.tools.quality_scores import delete_scorecard

    scorecard = _stored(ScoreDefinition(id=uuid4(), project_code="demo", name="Card", total_score=True,
                                        cde_score=False, category=ScoreCategory.impact_dimension))
    with patch("testgen.mcp.tools.quality_scores.resolve_scorecard", return_value=scorecard):
        delete_scorecard(scorecard_id=str(scorecard.id))
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"], entry["project_code"]) == ("scorecard.deleted", "Card", "demo")


def test_deleting_a_destination_records_its_name(saves, audit_session, audit_log):
    from testgen.mcp.tools.notification_destinations import delete_notification_destination

    destination = _stored(WebhookDestination(id=uuid4(), project_code="demo", name="Ops hook",
                                             destination_type="webhook", config={}))
    with (
        patch("testgen.mcp.tools.notification_destinations.resolve_destination", return_value=destination),
        patch("testgen.mcp.tools.notification_destinations._rule_counts_for", return_value={}),
    ):
        delete_notification_destination(destination_id=str(destination.id))
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"]) == ("notification_destination.deleted", "Ops hook")


def test_turning_monitoring_off_records_the_deleted_monitor_suite(audit_session, audit_log):
    from testgen.mcp.tools.monitors import disable_monitors

    suite = _stored(TestSuite(id=uuid4(), project_code="demo", test_suite="Sales Monitors",
                              suite_type=SuiteType.MONITOR, **MONITOR_SETTING_DEFAULTS))
    table_group = _stored(TableGroup(id=uuid4(), project_code="demo", table_groups_name="Sales"))
    with (
        patch("testgen.mcp.tools.monitors.resolve_monitored_table_group", return_value=(table_group, suite)),
        patch("testgen.mcp.tools.monitors.disable_monitoring",
              return_value={"monitors": 3, "events": 0, "runs": 0}),
    ):
        disable_monitors(table_group_id=str(table_group.id))
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_type"], entry["target_name"], entry["source"]) == (
        "monitor_suite.deleted", "monitor_suite", "Sales Monitors", "mcp",
    )


def test_creating_a_scorecard_records_its_fields_even_when_the_first_refresh_fails(audit_session, audit_log):
    from testgen.mcp.tools.quality_scores import create_scorecard

    def refresh_that_fails(definition, **_kwargs):
        # The refresh rolls back the session when it fails, which clears what the scorecard held.
        definition.id = uuid4()
        make_transient_to_detached(definition)
        for name in ("name", "total_score", "cde_score", "category"):
            definition.__dict__.pop(name, None)

    with patch("testgen.mcp.tools.quality_scores.save_and_refresh_score_definition", side_effect=refresh_that_fails):
        create_scorecard(project_code="demo", name="Card", filters=[{"field": "Table Group", "value": "tg1"}])
    audit_session.commit()

    [entry] = audit_log.records()
    assert entry["action"] == "scorecard.created"
    assert entry["changes"]["name"] == {"to": "Card"}
    assert entry["changes"]["criteria"]["to"]["filters"] == [
        {"field": "table_groups_name", "value": "tg1", "others": []},
    ]


def test_updating_a_scorecard_records_the_changed_name(audit_session, audit_log):
    from testgen.mcp.tools.quality_scores import update_scorecard

    scorecard = _stored(ScoreDefinition(id=uuid4(), project_code="demo", name="Card", total_score=True,
                                        cde_score=False, category=ScoreCategory.impact_dimension))
    with (
        patch("testgen.mcp.tools.quality_scores.resolve_scorecard", return_value=scorecard),
        patch("testgen.mcp.tools.quality_scores.save_and_refresh_score_definition"),
    ):
        update_scorecard(scorecard_id=str(scorecard.id), name="Renamed")
    audit_session.commit()

    assert _entries(audit_log) == [("scorecard.updated", "mcp", {"name": {"from": "Card", "to": "Renamed"}})]
