import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from testgen.common.audit import recorder
from testgen.common.audit.actions import AuditAction, Outcome
from testgen.common.audit.record import TARGETS_CAP, Actor
from testgen.common.audit.recorder import AuditContext, bind, record, set_context_resolver
from testgen.common.enums import JobSource
from testgen.common.models import Session, bound_session

pytestmark = pytest.mark.unit


@pytest.fixture
def session():
    db_session = Session(bind=create_engine("sqlite://"))
    with bound_session(db_session):
        yield db_session
    db_session.close()


@pytest.fixture(autouse=True)
def no_resolver(monkeypatch):
    monkeypatch.setattr(recorder, "_context_resolver", None)


def _user(username="alice", name="Alice A."):
    return SimpleNamespace(id=uuid4(), username=username, name=name)


def test_record_is_written_when_the_session_commits(session, audit_log):
    record(AuditAction.USER_SIGNED_IN)
    session.execute(text("SELECT 1"))
    assert audit_log.records() == []

    session.commit()

    assert [entry["action"] for entry in audit_log.records()] == ["user.signed_in"]


def test_record_is_discarded_on_rollback(session, audit_log):
    record(AuditAction.USER_SIGNED_IN)
    session.execute(text("SELECT 1"))
    session.rollback()
    session.commit()

    assert audit_log.records() == []


def test_record_is_discarded_when_the_session_closes_without_committing(session, audit_log):
    record(AuditAction.USER_SIGNED_IN)
    session.execute(text("SELECT 1"))
    session.close()
    session.commit()

    assert audit_log.records() == []


def test_each_record_is_written_once_at_the_commit_that_carries_it(session, audit_log):
    record(AuditAction.USER_SIGNED_IN)
    session.commit()
    record(AuditAction.USER_SIGNED_OUT)
    session.commit()
    session.commit()

    assert [entry["action"] for entry in audit_log.records()] == ["user.signed_in", "user.signed_out"]


def test_failed_outcome_is_written_at_once(session, audit_log):
    record(AuditAction.USER_SIGNED_IN, outcome=Outcome.FAILED)
    session.rollback()

    assert [entry["outcome"] for entry in audit_log.records()] == ["failed"]


def test_record_without_a_session_is_written_at_once(audit_log):
    record(AuditAction.USER_SIGNED_OUT)

    assert len(audit_log.records()) == 1


def test_record_carries_the_bound_context(session, audit_log):
    user = _user()
    bind(AuditContext(source=JobSource.api, actor=Actor.of(user), cause_type="schedule", cause_id="s1"))
    record(AuditAction.USER_SIGNED_IN)
    session.commit()

    [entry] = audit_log.records()
    assert entry["source"] == "api"
    assert entry["actor_id"] == str(user.id)
    assert entry["actor_username"] == "alice"
    assert entry["actor_display_name"] == "Alice A."
    assert (entry["cause_type"], entry["cause_id"]) == ("schedule", "s1")


def test_resolver_supplies_the_context_when_none_is_bound(session, audit_log):
    set_context_resolver(lambda: AuditContext(source=JobSource.ui, actor=Actor.of(_user("bob"))))
    record(AuditAction.USER_SIGNED_IN)
    session.commit()

    [entry] = audit_log.records()
    assert (entry["source"], entry["actor_username"]) == ("ui", "bob")


def test_bound_context_wins_over_the_resolver(session, audit_log):
    set_context_resolver(lambda: AuditContext(source=JobSource.ui))
    bind(AuditContext(source=JobSource.mcp))
    record(AuditAction.USER_SIGNED_IN)
    session.commit()

    assert audit_log.records()[0]["source"] == "mcp"


def test_record_without_context_is_attributed_to_the_system(audit_log):
    record(AuditAction.USER_SIGNED_IN)

    [entry] = audit_log.records()
    assert entry["source"] == "system"
    assert entry["actor_id"] is None
    assert entry["actor_username"] is None


def test_attempted_actor_carries_the_username_and_no_id(session, audit_log):
    bind(AuditContext(source=JobSource.api, actor=Actor.of(_user("alice"))))
    record(AuditAction.USER_SIGNED_IN, outcome=Outcome.FAILED, actor=Actor.attempted("mallory"))

    [entry] = audit_log.records()
    assert entry["actor_id"] is None
    assert entry["actor_username"] == "mallory"
    assert entry["actor_display_name"] is None


def test_record_has_the_full_field_set(audit_log):
    record(AuditAction.USER_SIGNED_IN)

    [entry] = audit_log.records()
    assert set(entry) == {
        "schema_version", "id", "occurred_at", "action", "outcome", "actor_id", "actor_username",
        "actor_display_name", "source", "project_code", "target_type", "target_count", "targets",
        "target_name", "cause_type", "cause_id", "changes",
    }
    assert entry["schema_version"] == 1
    assert entry["target_count"] == 0
    assert entry["targets"] == []
    assert entry["changes"] == {}


def test_record_ids_are_unique(audit_log):
    record(AuditAction.USER_SIGNED_IN)
    record(AuditAction.USER_SIGNED_IN)

    first, second = audit_log.records()
    assert first["id"] != second["id"]


def test_targets_are_capped_and_count_stays_authoritative(audit_log):
    record(AuditAction.USER_SIGNED_IN, target_type="user", targets=range(TARGETS_CAP + 5))

    [entry] = audit_log.records()
    assert entry["target_count"] == TARGETS_CAP + 5
    assert len(entry["targets"]) == TARGETS_CAP


def test_target_name_is_written_only_for_a_single_target(audit_log):
    record(AuditAction.USER_SIGNED_IN, target_type="user", targets=["a"], target_name="Alice")
    record(AuditAction.USER_SIGNED_IN, target_type="user", targets=["a", "b"], target_name="Alice")

    single, multiple = audit_log.records()
    assert single["target_name"] == "Alice"
    assert multiple["target_name"] is None


def test_explicit_target_count_overrides_the_targets_length(audit_log):
    record(AuditAction.USER_SIGNED_IN, target_type="user", targets=["a"], target_count=7)

    assert audit_log.records()[0]["target_count"] == 7


def test_a_failing_sink_does_not_interrupt_the_action(session, audit_log, caplog):
    sink = MagicMock()
    sink.write.side_effect = OSError("disk full")
    with patch.object(recorder, "get_sink", return_value=sink), caplog.at_level(logging.ERROR, "testgen"):
        record(AuditAction.USER_SIGNED_IN)
        session.commit()
        record(AuditAction.USER_SIGNED_IN, outcome=Outcome.FAILED)

    assert audit_log.records() == []
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 2
