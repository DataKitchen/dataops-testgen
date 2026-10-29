"""Audit records of the UI's configuration pages and dialogs."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.enums import JobKey, SuiteType
from testgen.common.models.notification_destinations import WebhookDestination
from testgen.common.models.notification_settings import NotificationEvent, ProfilingRunNotificationSettings
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services import notification_destinations_service as destinations_service
from testgen.ui.views import score_details, table_groups, test_suites
from testgen.ui.views.dialogs import import_metadata_dialog, manage_notifications, manage_schedules
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase

pytestmark = pytest.mark.unit


def _stored(obj):
    """``obj`` as a dialog holds it after loading it: its values are the stored ones, with no changes pending."""
    make_transient_to_detached(obj)
    return obj


def _schedule(active: bool = True) -> JobSchedule:
    return _stored(JobSchedule(
        id=uuid4(), project_code="demo", key=JobKey.run_profile, kwargs={"table_group_id": "tg-1"},
        cron_expr="0 6 * * *", cron_tz="UTC", active=active,
    ))


def _entries(audit_log) -> list[tuple]:
    return [(entry["action"], entry["targets"], entry["project_code"], entry["changes"]) for entry in audit_log.records()]


def test_adding_a_schedule_records_it_with_what_it_runs(audit_session, audit_log):
    schedule = JobSchedule(
        project_code="demo", key=JobKey.run_profile, kwargs={"table_group_id": "tg-1"}, cron_expr="0 6 * * *",
        cron_tz="UTC", active=True,
    )
    with patch.object(JobSchedule, "save", autospec=True, side_effect=lambda obj: setattr(obj, "id", uuid4())):
        manage_schedules._add_schedule(schedule)
    audit_session.commit()

    assert _entries(audit_log) == [("schedule.created", [str(schedule.id)], "demo", {
        "key": {"to": "run-profile"},
        "kwargs": {"to": {"table_group_id": "tg-1"}},
        "cron_expr": {"to": "0 6 * * *"},
        "cron_tz": {"to": "UTC"},
        "active": {"to": True},
    })]


def test_deleting_a_schedule_records_it(audit_session, audit_log):
    schedule = _schedule()
    with patch.object(JobSchedule, "get", return_value=schedule), patch.object(JobSchedule, "delete") as delete:
        manage_schedules._delete_schedule(str(schedule.id))
    audit_session.commit()

    delete.assert_called_once_with(str(schedule.id))
    assert _entries(audit_log) == [("schedule.deleted", [str(schedule.id)], "demo", {})]


@pytest.mark.parametrize(
    ("stored_active", "active", "actions"),
    [
        (True, False, ["schedule.paused"]),
        (False, True, ["schedule.resumed"]),
        (False, False, []),
        (True, True, []),
    ],
    ids=["pause", "resume", "pause-paused", "resume-running"],
)
def test_pausing_or_resuming_a_schedule_is_recorded_when_it_changes_its_state(
    audit_session, audit_log, stored_active, active, actions
):
    schedule = _schedule(stored_active)
    with patch.object(JobSchedule, "get", return_value=schedule), patch.object(JobSchedule, "save", autospec=True) as save:
        manage_schedules._set_schedule_active(str(schedule.id), active)
    audit_session.commit()

    save.assert_called_once_with(schedule)
    assert schedule.active is active
    assert [entry["action"] for entry in audit_log.records()] == actions


def _notification(**values) -> ProfilingRunNotificationSettings:
    defaults = {"id": uuid4(), "project_code": "demo", "event": NotificationEvent.profiling_run, "enabled": True,
                "recipients": ["a@example.com"], "settings": {"trigger": "always"}}
    return _stored(ProfilingRunNotificationSettings(**{**defaults, **values}))


@pytest.fixture
def notification_dialog():
    dialog = NotificationSettingsDialogBase.__new__(NotificationSettingsDialogBase)
    dialog.ns_class = MagicMock()
    dialog._result_idx = iter(range(100))
    with (
        patch.object(manage_notifications, "st"),
        patch.object(ProfilingRunNotificationSettings, "save", autospec=True),
        patch.object(ProfilingRunNotificationSettings, "delete", autospec=True),
    ):
        yield dialog


@pytest.mark.parametrize(
    ("enabled", "method", "action"),
    [(True, "on_pause_item", "notification.paused"), (False, "on_resume_item", "notification.resumed")],
)
def test_pausing_or_resuming_a_notification_is_its_own_action(
    notification_dialog, audit_session, audit_log, enabled, method, action
):
    notification = _notification(enabled=enabled)
    notification_dialog.ns_class.get.return_value = notification

    getattr(notification_dialog, method)({"id": str(notification.id)})
    audit_session.commit()

    assert _entries(audit_log) == [(action, [str(notification.id)], "demo", {})]


def test_editing_a_notification_records_the_changed_fields(notification_dialog, audit_session, audit_log):
    notification = _notification()
    notification_dialog.ns_class.get.return_value = notification

    notification_dialog._update_item(notification.id, {"recipients": ["b@example.com"], "enabled": True})
    audit_session.commit()

    assert _entries(audit_log) == [("notification.updated", [str(notification.id)], "demo", {
        "recipients": {"from": ["a@example.com"], "to": ["b@example.com"]},
    })]


def test_deleting_a_notification_records_it(notification_dialog, audit_session, audit_log):
    notification = _notification()
    notification_dialog.ns_class.get.return_value = notification

    notification_dialog.on_delete_item({"id": str(notification.id)})
    audit_session.commit()

    assert _entries(audit_log) == [("notification.deleted", [str(notification.id)], "demo", {})]


def _suite(**values) -> TestSuite:
    columns = {column.key: None for column in TestSuite.__table__.columns}
    return _stored(TestSuite(**{
        **columns, "id": uuid4(), "project_code": "demo", "test_suite": "Orders", "suite_type": SuiteType.REGULAR,
        "test_suite_description": "Old", "export_to_observability": False, "dq_score_exclude": False,
        "deactivate_invalid_tests": False, "component_type": "dataset", **values,
    }))


def test_editing_a_test_suite_records_the_changed_fields(audit_session, audit_log):
    suite = _suite()
    with (
        patch.object(test_suites, "st"),
        patch.object(test_suites, "get_test_suite", return_value=suite),
        patch.object(test_suites, "get_test_suite_summaries"),
        patch.object(test_suites, "get_project_summary"),
        patch.object(TestSuite, "save", autospec=True),
    ):
        test_suites.save_test_suite_form({
            "test_suite_id": str(suite.id), "test_suite": "Orders", "test_suite_description": "New",
            "component_type": "dataset",
        })
    audit_session.commit()

    assert _entries(audit_log) == [("test_suite.updated", [str(suite.id)], "demo", {
        "test_suite_description": {"from": "Old", "to": "New"},
    })]


def test_deleting_a_test_suite_records_its_name(audit_session, audit_log):
    suite = _suite()
    with (
        patch.object(test_suites, "st"),
        patch.object(test_suites, "get_test_suite_summaries"),
        patch.object(test_suites, "get_project_summary"),
        patch.object(test_suites.TestRun, "has_active_job_for", return_value=False),
        patch.object(TestSuite, "get", return_value=suite),
        patch.object(TestSuite, "cascade_delete"),
    ):
        test_suites.execute_ts_delete(str(suite.id))
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"]) == ("test_suite.deleted", "Orders")


def test_a_test_suite_already_gone_records_nothing(audit_session, audit_log):
    with (
        patch.object(test_suites, "st"),
        patch.object(test_suites, "get_test_suite_summaries"),
        patch.object(test_suites, "get_project_summary"),
        patch.object(test_suites.TestRun, "has_active_job_for", return_value=False),
        patch.object(TestSuite, "get", return_value=None),
        patch.object(TestSuite, "cascade_delete"),
    ):
        test_suites.execute_ts_delete(str(uuid4()))
    audit_session.commit()

    assert audit_log.records() == []


def test_adding_a_test_suite_records_it(audit_session, audit_log):
    suite = TestSuite(project_code="demo", test_suite="Orders", suite_type=SuiteType.REGULAR)
    with (
        patch.object(TestSuite, "save", autospec=True, side_effect=lambda obj: setattr(obj, "id", uuid4())),
        patch.object(audit_session, "commit"),
    ):
        test_suites._add_test_suite(suite, {"generate": False})
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["targets"], entry["target_name"]) == (
        "test_suite.created", [str(suite.id)], "Orders",
    )


def _webhook(**values) -> WebhookDestination:
    return _stored(WebhookDestination(**{"id": uuid4(), "project_code": "demo", "name": "Ops hook",
                                         "destination_type": "webhook", "config": {"webhook_type": "generic"},
                                         "secrets": {"url": "https://hooks.example.com/old"}, **values}))


def test_editing_a_destination_records_a_url_change_without_the_url(audit_session, audit_log):
    destination = _webhook()
    with (
        patch.object(destinations_service, "_get_owned", return_value=destination),
        patch.object(WebhookDestination, "save", autospec=True),
    ):
        destinations_service.edit_destination("demo", {
            "id": str(destination.id), "name": "Ops alerts", "webhook_url": "https://hooks.example.com/new",
        })
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"]) == ("notification_destination.updated", "Ops alerts")
    assert entry["changes"] == {"name": {"from": "Ops hook", "to": "Ops alerts"}, "secrets": {}}
    assert "hooks.example.com" not in str(entry)


def test_deleting_a_destination_records_it(audit_session, audit_log):
    destination = _webhook()
    with (
        patch.object(destinations_service, "_get_owned", return_value=destination),
        patch.object(WebhookDestination, "delete", autospec=True),
    ):
        destinations_service.delete_destination("demo", str(destination.id))
    audit_session.commit()

    assert [entry["action"] for entry in audit_log.records()] == ["notification_destination.deleted"]


def test_deleting_a_scorecard_records_its_name(audit_session, audit_log):
    scorecard = _stored(ScoreDefinition(id=uuid4(), project_code="demo", name="Card", total_score=True,
                                        cde_score=False, category=None))
    with (
        patch.object(ScoreDefinition, "get", return_value=scorecard),
        patch.object(ScoreDefinition, "delete", autospec=True),
        patch.object(score_details, "get_all_score_cards"),
        patch.object(score_details, "Router"),
    ):
        score_details.delete_score_card(str(scorecard.id))
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"]) == ("scorecard.deleted", "Card")


def _table_group(**values) -> TableGroup:
    return _stored(TableGroup(**{"id": uuid4(), "project_code": "demo", "table_groups_name": "Sales",
                                 "profile_flag_cdes": True, "profile_flag_pii": True, **values}))


@pytest.mark.parametrize(("blocker", "actions"), [(None, ["table_group.deleted"]), ("job", [])])
def test_deleting_a_table_group_is_recorded_unless_refused(audit_session, audit_log, blocker, actions):
    table_group = _table_group()
    with (
        patch.object(table_groups, "st"),
        patch.object(TableGroup, "get", return_value=table_group),
        patch.object(table_groups, "cascade_delete_table_group", return_value=blocker),
        patch.object(table_groups, "select_table_groups_minimal_where"),
    ):
        table_groups.TableGroupsPage._execute_delete(MagicMock(), str(table_group.id))
    audit_session.commit()

    assert [entry["action"] for entry in audit_log.records()] == actions


def test_importing_flags_by_hand_records_the_detection_turned_off(audit_session, audit_log):
    table_group = _table_group()
    with (
        patch.object(import_metadata_dialog, "get_table_group", return_value=table_group),
        patch.object(TableGroup, "save", autospec=True),
    ):
        import_metadata_dialog._disable_autoflags(str(table_group.id), ["pii_flag"])
    audit_session.commit()

    assert _entries(audit_log) == [("table_group.updated", [str(table_group.id)], "demo", {
        "profile_flag_pii": {"from": True, "to": False},
    })]


def test_adding_a_notification_records_it(notification_dialog, audit_session, audit_log):
    notification = ProfilingRunNotificationSettings(
        id=uuid4(), project_code="demo", event=NotificationEvent.profiling_run, enabled=True,
        recipients=["a@example.com"], settings={"trigger": "always"},
    )
    notification_dialog.ns_class.create.return_value = notification
    notification_dialog.ns_attrs = {"project_code": "demo"}
    with patch.object(NotificationSettingsDialogBase, "_item_to_model_attrs", return_value={}):
        notification_dialog.on_add_item({"recipients": ["a@example.com"]})
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["targets"]) == ("notification.created", [str(notification.id)])
    assert entry["changes"]["recipients"] == {"to": ["a@example.com"]}


def test_adding_a_webhook_destination_records_it_without_its_url(audit_session, audit_log):
    def create(**values):
        url = values.pop("url")
        values.pop("webhook_type")
        values.pop("auth_header_name")
        values.pop("auth_header_value")
        return WebhookDestination(id=uuid4(), destination_type="webhook", config={"webhook_type": "generic"},
                                  secrets={"url": url}, **values)

    with patch.object(WebhookDestination, "create", side_effect=create):
        destinations_service.add_destination("demo", {
            "destination_type": "webhook", "name": "Ops hook", "webhook_type": "generic",
            "webhook_url": "https://hooks.example.com/secret",
        })
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"]) == ("notification_destination.created", "Ops hook")
    assert entry["changes"]["secrets"] == {}
    assert "hooks.example.com" not in str(entry)
