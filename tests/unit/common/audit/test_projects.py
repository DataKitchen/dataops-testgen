from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached
from sqlalchemy.orm.attributes import set_committed_value

from testgen.common.audit.projects import record_project_created, record_project_updated
from testgen.common.enums import JobKey
from testgen.common.models.project import Project
from testgen.common.models.scheduler import JobSchedule

pytestmark = pytest.mark.unit


def _stored(obj):
    """``obj`` as a page holds it after loading it: its values are the stored ones, with no changes pending."""
    make_transient_to_detached(obj)
    return obj


def _project(**values) -> Project:
    defaults = {
        "project_code": "SALES", "project_name": "Sales", "use_dq_score_weights": True,
        "observability_api_url": None, "observability_api_key": None,
        "data_retention_enabled": True, "data_retention_days": 180,
    }
    return _stored(Project(**{**defaults, **values}))


def _cleanup_schedule(**values) -> JobSchedule:
    defaults = {"id": uuid4(), "project_code": "SALES", "key": JobKey.run_data_cleanup, "kwargs": {},
                "cron_expr": "0 1 * * *", "cron_tz": "UTC", "active": True}
    return JobSchedule(**{**defaults, **values})


def _entries(audit_log) -> list[tuple]:
    return [
        (entry["action"], entry["target_type"], entry["targets"], entry["target_name"], entry["changes"])
        for entry in audit_log.records()
    ]


def test_each_section_that_changed_is_its_own_record(audit_session, audit_log):
    project = _project()
    project.project_name = "Sales EU"
    project.observability_api_key = "api-key-value"
    project.data_retention_days = 30
    schedule = _stored(_cleanup_schedule())
    schedule.cron_expr = "0 2 * * *"

    record_project_updated(project, schedule)
    audit_session.commit()

    assert _entries(audit_log) == [
        ("project.updated", "project.info", ["SALES"], "Sales EU", {"project_name": {"from": "Sales", "to": "Sales EU"}}),
        ("project.updated", "project.observability", ["SALES"], "Sales EU", {"observability_api_key": {}}),
        ("project.updated", "project.retention", ["SALES"], "Sales EU", {
            "data_retention_days": {"from": 180, "to": 30},
            "retention_cron_expr": {"from": "0 1 * * *", "to": "0 2 * * *"},
        }),
    ]
    assert "api-key-value" not in str(audit_log.records())


def test_a_retention_schedule_change_alone_is_a_retention_record(audit_session, audit_log):
    schedule = _stored(_cleanup_schedule())
    schedule.cron_tz = "America/New_York"

    record_project_updated(_project(), schedule)
    audit_session.commit()

    assert _entries(audit_log) == [
        ("project.updated", "project.retention", ["SALES"], "Sales", {
            "retention_cron_tz": {"from": "UTC", "to": "America/New_York"},
        }),
    ]


def test_saving_unchanged_settings_records_nothing(audit_session, audit_log):
    record_project_updated(_project(), _stored(_cleanup_schedule()))
    audit_session.commit()

    assert audit_log.records() == []


def test_a_new_project_records_its_retention_settings_even_when_defaulted(audit_session, audit_log):
    project = Project(project_code="SALES", project_name="Sales")
    # Column defaults are applied by the insert, with no change history.
    set_committed_value(project, "data_retention_enabled", True)
    set_committed_value(project, "data_retention_days", 180)

    record_project_created(project, _cleanup_schedule())
    audit_session.commit()

    assert _entries(audit_log) == [
        ("project.created", "project", ["SALES"], "Sales", {
            "project_name": {"to": "Sales"},
            "data_retention_enabled": {"to": True},
            "data_retention_days": {"to": 180},
            "retention_cron_expr": {"to": "0 1 * * *"},
            "retention_cron_tz": {"to": "UTC"},
        }),
    ]
