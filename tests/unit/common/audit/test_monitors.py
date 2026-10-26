from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached

from testgen.common.audit.monitors import (
    record_monitoring_deleted,
    record_monitoring_enabled,
    record_monitoring_updated,
)
from testgen.common.enums import SuiteType
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS, TestSuite

pytestmark = pytest.mark.unit


def _stored(obj):
    """``obj`` as loaded from the database: its values are the stored ones, with no changes pending."""
    make_transient_to_detached(obj)
    return obj


def _monitor_suite(**values) -> TestSuite:
    return TestSuite(
        id=uuid4(), project_code="demo", test_suite="Sales Monitors", suite_type=SuiteType.MONITOR,
        **{**MONITOR_SETTING_DEFAULTS, **values},
    )


def _schedule(suite: TestSuite, **values) -> JobSchedule:
    defaults = {"id": uuid4(), "project_code": "demo", "key": "run-monitors",
                "kwargs": {"test_suite_id": str(suite.id)}, "cron_expr": "0 6 * * *", "cron_tz": "UTC",
                "active": True}
    return JobSchedule(**{**defaults, **values})


def _entries(audit_log) -> list[tuple]:
    return [
        (entry["action"], entry["target_type"], entry["targets"], entry["target_name"], entry["project_code"],
         entry["changes"])
        for entry in audit_log.records()
    ]


def test_enabling_records_the_settings_and_the_schedule(audit_session, audit_log):
    suite = _monitor_suite(monitor_lookback=20)
    schedule = _schedule(suite, active=False)

    record_monitoring_enabled(suite, schedule)
    audit_session.commit()

    [(action, target_type, targets, name, project, changes)] = _entries(audit_log)
    assert (action, target_type, targets, name, project) == (
        "monitor_suite.created", "monitor_suite", [str(suite.id)], "Sales Monitors", "demo",
    )
    assert changes == {
        "monitor_lookback": {"to": 20},
        "monitor_regenerate_freshness": {"to": True},
        "predict_min_lookback": {"to": 30},
        "predict_sensitivity": {"to": "medium"},
        "predict_exclude_weekends": {"to": False},
        "cron_expr": {"to": "0 6 * * *"},
        "cron_tz": {"to": "UTC"},
        "active": {"to": False},
    }


def test_enabling_still_records_when_the_schedule_cannot_be_read(audit_session, audit_log, caplog):
    suite = _monitor_suite()

    record_monitoring_enabled(suite)
    audit_session.commit()

    assert [entry["action"] for entry in audit_log.records()] == ["monitor_suite.created"]
    assert "Audit _schedule_of failed" in caplog.text


def test_updating_records_the_changes_and_a_pause_on_its_own(audit_session, audit_log):
    suite = _stored(_monitor_suite())
    schedule = _stored(_schedule(suite))
    suite.monitor_lookback = 30
    suite.predict_sensitivity = "medium"
    schedule.cron_expr = "0 7 * * *"
    schedule.active = False

    record_monitoring_updated(suite, schedule)
    audit_session.commit()

    assert _entries(audit_log) == [
        ("monitor_suite.updated", "monitor_suite", [str(suite.id)], "Sales Monitors", "demo", {
            "monitor_lookback": {"from": 14, "to": 30},
            "cron_expr": {"from": "0 6 * * *", "to": "0 7 * * *"},
        }),
        ("monitor_suite.paused", "monitor_suite", [str(suite.id)], "Sales Monitors", "demo", {}),
    ]


@pytest.mark.parametrize(("stored", "active", "actions"), [
    (False, True, ["monitor_suite.resumed"]),
    (True, True, []),
    (False, False, []),
])
def test_a_pause_or_resume_is_recorded_only_when_the_state_changes(audit_session, audit_log, stored, active, actions):
    suite = _stored(_monitor_suite())
    schedule = _stored(_schedule(suite, active=stored))
    schedule.active = active

    record_monitoring_updated(suite, schedule)
    audit_session.commit()

    assert [entry["action"] for entry in audit_log.records()] == actions


def test_a_schedule_created_with_the_update_is_not_recorded_as_resumed(audit_session, audit_log):
    suite = _stored(_monitor_suite())

    record_monitoring_updated(suite, _schedule(suite))
    audit_session.commit()

    assert [entry["action"] for entry in audit_log.records()] == ["monitor_suite.updated"]


def test_deleting_records_the_suite_name(audit_session, audit_log):
    suite = _stored(_monitor_suite())

    record_monitoring_deleted(suite)
    audit_session.commit()

    assert _entries(audit_log) == [
        ("monitor_suite.deleted", "monitor_suite", [str(suite.id)], "Sales Monitors", "demo", {}),
    ]
