"""Audit records of the REST endpoints that change configuration."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import make_transient_to_detached

from testgen.api.notifications import (
    create_rule,
    delete_destination,
    delete_rule,
    pause_rule,
    resume_rule,
    update_rule,
)
from testgen.api.schemas import RuleCreate, RuleUpdate
from testgen.api.table_groups import delete_table_group
from testgen.common.models.notification_destinations import WebhookDestination
from testgen.common.models.notification_settings import NotificationEvent, ProfilingRunNotificationSettings
from testgen.common.models.table_group import TableGroup

pytestmark = pytest.mark.unit


def _stored(obj):
    """``obj`` as an endpoint holds it after resolving it: its values are the stored ones, with no changes pending."""
    make_transient_to_detached(obj)
    return obj


def _rule(enabled: bool = True) -> ProfilingRunNotificationSettings:
    return _stored(ProfilingRunNotificationSettings(
        id=uuid4(), project_code="demo", event=NotificationEvent.profiling_run, enabled=enabled,
        recipients=["a@example.com"], settings={"trigger": "always"},
    ))


@pytest.fixture(autouse=True)
def writes():
    with (
        patch.object(ProfilingRunNotificationSettings, "save", autospec=True),
        patch.object(ProfilingRunNotificationSettings, "delete", autospec=True),
        patch.object(WebhookDestination, "delete", autospec=True),
        patch("testgen.api.notifications._rule_to_response"),
    ):
        yield


def _actions(audit_log) -> list[str]:
    return [entry["action"] for entry in audit_log.records()]


def test_pausing_a_rule_records_the_pause_and_pausing_a_paused_rule_records_nothing(audit_session, audit_log):
    pause_rule(rule=_rule())
    pause_rule(rule=_rule(enabled=False))
    audit_session.commit()

    assert _actions(audit_log) == ["notification.paused"]
    assert audit_log.records()[0]["changes"] == {}


def test_resuming_a_rule_is_its_own_action(audit_session, audit_log):
    resume_rule(rule=_rule(enabled=False))
    audit_session.commit()

    assert _actions(audit_log) == ["notification.resumed"]


def test_a_rule_update_that_pauses_records_the_pause_not_an_update(audit_session, audit_log):
    update_rule(rule=_rule(), body=RuleUpdate.model_validate({"enabled": False}))
    audit_session.commit()

    assert _actions(audit_log) == ["notification.paused"]


def test_deleting_a_rule_records_it(audit_session, audit_log):
    rule = _rule()

    delete_rule(rule=rule)
    audit_session.commit()

    assert [(entry["action"], entry["targets"]) for entry in audit_log.records()] == [
        ("notification.deleted", [str(rule.id)]),
    ]


def test_deleting_a_destination_records_its_name(audit_session, audit_log):
    destination = _stored(WebhookDestination(id=uuid4(), project_code="demo", name="Ops hook",
                                             destination_type="webhook", config={}))

    with patch("testgen.api.notifications._rule_counts", return_value={}):
        delete_destination(destination=destination)
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["target_name"], entry["project_code"]) == (
        "notification_destination.deleted", "Ops hook", "demo",
    )


def test_deleting_a_table_group_records_its_name(audit_session, audit_log):
    table_group = _stored(TableGroup(id=uuid4(), project_code="demo", table_groups_name="Sales"))

    with patch("testgen.api.table_groups.cascade_delete_table_group", return_value=None):
        delete_table_group(table_group=table_group)
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["targets"], entry["target_name"]) == (
        "table_group.deleted", [str(table_group.id)], "Sales",
    )


def test_a_refused_table_group_delete_records_nothing(audit_session, audit_log):
    table_group = _stored(TableGroup(id=uuid4(), project_code="demo", table_groups_name="Sales"))

    with (
        patch("testgen.api.table_groups.cascade_delete_table_group", return_value="job"),
        pytest.raises(HTTPException),
    ):
        delete_table_group(table_group=table_group)
    audit_session.commit()

    assert audit_log.records() == []


def test_creating_a_rule_records_it(audit_session, audit_log):
    rule = ProfilingRunNotificationSettings(
        id=uuid4(), project_code="demo", event=NotificationEvent.profiling_run, enabled=True,
        recipients=["a@example.com"], settings={"trigger": "always"},
    )
    body = RuleCreate.model_validate({
        "event": "profiling_run", "addressing": {"kind": "inline", "recipients": ["a@example.com"]},
    })

    with patch.object(ProfilingRunNotificationSettings, "create", return_value=rule):
        create_rule(project_code="demo", body=body)
    audit_session.commit()

    [entry] = audit_log.records()
    assert (entry["action"], entry["targets"], entry["project_code"]) == (
        "notification.created", [str(rule.id)], "demo",
    )
