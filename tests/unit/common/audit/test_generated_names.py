from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.enums import JobKey
from testgen.common.models.notification_settings import (
    MonitorNotificationSettings,
    NotificationEvent,
    ProfilingRunNotificationSettings,
    ScoreDropNotificationSettings,
    TestRunNotificationSettings,
)
from testgen.common.models.scheduler import JobSchedule

pytestmark = pytest.mark.unit


def _stored(obj):
    make_transient_to_detached(obj)
    return obj


def _names(name: str | None):
    """Answer every name lookup with ``name``."""
    patcher = patch("testgen.common.audit.safety.get_current_session")
    session = patcher.start()
    session.return_value.scalar.return_value = name
    return patcher


@pytest.fixture
def lookups():
    patchers = []

    def answer(name: str | None) -> None:
        patchers.append(_names(name))

    yield answer
    for patcher in patchers:
        patcher.stop()


def _schedule(key: str, kwargs: dict) -> JobSchedule:
    return _stored(JobSchedule(id=uuid4(), project_code="demo", key=key, kwargs=kwargs, cron_expr="0 6 * * *",
                               cron_tz="UTC", active=True))


def _target_name(audit_session, audit_log, subject) -> str | None:
    record(AuditAction.SCHEDULE_DELETED, subject)
    audit_session.commit()
    return audit_log.records()[-1]["target_name"]


@pytest.mark.parametrize(("key", "kwargs", "expected"), [
    (JobKey.run_profile, {"table_group_id": "tg-1"}, "Profiling of Sales"),
    (JobKey.run_tests, {"test_suite_id": "ts-1"}, "Test run of Sales"),
])
def test_a_schedule_is_named_after_its_job_and_what_it_runs_for(
    audit_session, audit_log, lookups, key, kwargs, expected
):
    lookups("Sales")

    assert _target_name(audit_session, audit_log, _schedule(key, kwargs)) == expected


def test_a_schedule_whose_target_is_gone_is_named_with_its_id(audit_session, audit_log, lookups):
    lookups(None)

    assert _target_name(
        audit_session, audit_log, _schedule(JobKey.run_profile, {"table_group_id": "tg-1"})
    ) == "Profiling of tg-1"


def _notification(cls, event: NotificationEvent, **scope):
    scope = {"test_suite_id": None, "table_group_id": None, "score_definition_id": None, "settings": {}, **scope}
    return _stored(cls(id=uuid4(), project_code="demo", event=event, enabled=True, recipients=[], **scope))


@pytest.mark.parametrize(("notification", "expected"), [
    (lambda: _notification(TestRunNotificationSettings, NotificationEvent.test_run, test_suite_id=uuid4()),
     "Test run notification for Sales"),
    (lambda: _notification(TestRunNotificationSettings, NotificationEvent.test_run),
     "Test run notification for all test suites"),
    (lambda: _notification(ProfilingRunNotificationSettings, NotificationEvent.profiling_run, table_group_id=uuid4()),
     "Profiling notification for Sales"),
    (lambda: _notification(ScoreDropNotificationSettings, NotificationEvent.score_drop, score_definition_id=uuid4()),
     "Score drop notification for Sales"),
    (lambda: _notification(MonitorNotificationSettings, NotificationEvent.monitor_run, table_group_id=uuid4(),
                           test_suite_id=uuid4(), settings={"table_name": "orders"}),
     "Monitor notification for Sales, table orders"),
], ids=["suite", "all-suites", "table-group", "scorecard", "monitor-table"])
def test_a_notification_is_named_after_its_event_and_what_it_watches(
    audit_session, audit_log, lookups, notification, expected
):
    lookups("Sales")

    assert _target_name(audit_session, audit_log, notification()) == expected


def test_a_name_that_cannot_be_built_leaves_the_record_without_one(audit_session, audit_log, caplog):
    schedule = _schedule(JobKey.run_profile, {"table_group_id": "tg-1"})

    with patch("testgen.common.models.scheduler.get_current_session", side_effect=RuntimeError("database gone")):
        record(AuditAction.SCHEDULE_DELETED, schedule)
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["targets"], entry["target_name"]) == (
        "schedule.deleted", [str(schedule.id)], None,
    )
    assert "Audit _name_of failed" in caplog.text
