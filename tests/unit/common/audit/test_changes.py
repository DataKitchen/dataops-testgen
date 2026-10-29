import enum
import pickle  # noqa: S403

import pytest
from sqlalchemy import Boolean, Column, Enum, Integer, String, create_engine, update
from sqlalchemy.orm import DeclarativeBase

from testgen.common.audit.actions import AuditAction
from testgen.common.audit.fields import SECRET_INFO_KEY, AuditFields, declaration_errors
from testgen.common.audit.recorder import changes_of, record, record_switch, record_update
from testgen.common.models import Session, bound_session
from testgen.common.models.custom_types import NullIfEmptyString

pytestmark = pytest.mark.unit


class _Base(DeclarativeBase):
    pass


class Size(enum.Enum):
    small = "S"
    large = "L"


class Widget(_Base):
    __tablename__ = "widgets"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(NullIfEmptyString)
    enabled = Column(Boolean, default=False)
    password = Column(String, info={SECRET_INFO_KEY: True})
    undeclared = Column(String)
    project = Column(String)
    size = Column(Enum(Size))

    __audit__ = AuditFields(
        target_type="widget",
        name="name",
        project="project",
        values=("name", "email", "enabled", "size"),
        withheld=("password",),
    )


class LeakyWidget(_Base):
    __tablename__ = "leaky_widgets"

    id = Column(Integer, primary_key=True)
    password = Column(String, info={SECRET_INFO_KEY: True})

    __audit__ = AuditFields(target_type="widget", values=("password",))


class MisdeclaredWidget(_Base):
    __tablename__ = "misdeclared_widgets"

    id = Column(Integer, primary_key=True)

    __audit__ = AuditFields(target_type="widget", values=("missing",))


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(bind=engine) as setup:
        setup.add(Widget(id=1, name="first", email=None, enabled=False, password="hash-1", project="P1"))  # noqa: S106
        setup.commit()
    return engine


@pytest.fixture
def session(engine):
    db_session = Session(bind=engine)
    with bound_session(db_session):
        yield db_session
    db_session.close()


def _cached_copy(engine) -> Widget:
    """A widget as the web UI holds it: loaded by another session, then pickled and unpickled."""
    with Session(bind=engine) as loader:
        widget = loader.get(Widget, 1)
        loader.expunge(widget)
    return pickle.loads(pickle.dumps(widget))  # noqa: S301


def _save(session, widget) -> None:
    session.add(widget)
    session.flush([widget])


def test_update_records_only_the_changed_fields_with_both_values(session, audit_log):
    widget = session.get(Widget, 1)
    widget.name = "renamed"
    widget.enabled = True
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    [entry] = audit_log.records()
    assert entry["changes"] == {"name": {"from": "first", "to": "renamed"}, "enabled": {"from": False, "to": True}}
    assert (entry["target_type"], entry["targets"], entry["target_name"]) == ("widget", ["1"], "renamed")
    assert entry["project_code"] == "P1"


def test_cached_copy_saved_by_a_flush_reports_its_changes(engine, session, audit_log):
    widget = _cached_copy(engine)
    widget.enabled = True
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"enabled": {"from": False, "to": True}}


def test_cached_copy_written_without_a_flush_reports_its_changes(engine, session, audit_log):
    widget = _cached_copy(engine)
    widget.name = "renamed"
    session.execute(update(Widget).where(Widget.id == 1).values(name=widget.name))

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"name": {"from": "first", "to": "renamed"}}


def test_values_are_compared_as_the_column_stores_them(engine, session, audit_log):
    widget = _cached_copy(engine)
    widget.email = ""
    widget.name = "first"
    widget.enabled = True
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"enabled": {"from": False, "to": True}}


def test_value_stored_as_null_is_reported_as_null(session, audit_log):
    widget = session.get(Widget, 1)
    widget.email = "jdoe@example.com"
    _save(session, widget)
    session.commit()

    widget.email = ""
    _save(session, widget)
    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"email": {"from": "jdoe@example.com", "to": None}}


def test_update_that_changes_nothing_records_nothing(engine, session, audit_log):
    widget = _cached_copy(engine)
    widget.name = "first"
    widget.email = ""
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records() == []


def test_changes_undone_before_the_record_record_nothing(session, audit_log):
    widget = session.get(Widget, 1)
    widget.enabled = True
    _save(session, widget)
    widget.enabled = False
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records() == []


def test_several_saves_report_the_first_value_and_the_last(session, audit_log):
    widget = session.get(Widget, 1)
    widget.name = "second"
    _save(session, widget)
    widget.name = "third"
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"name": {"from": "first", "to": "third"}}


def test_withheld_field_is_reported_without_values(session, audit_log):
    widget = session.get(Widget, 1)
    widget.password = "hash-2"  # noqa: S105
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"password": {}}


def test_secret_declared_with_values_is_still_withheld(session, audit_log):
    leaky = LeakyWidget(id=1, password="hash-1")  # noqa: S106
    session.add(leaky)
    session.flush()
    leaky.password = "hash-2"  # noqa: S105
    session.flush()

    record(AuditAction.USER_UPDATED, leaky)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"password": {}}


def test_undeclared_column_never_appears(session, audit_log):
    widget = session.get(Widget, 1)
    widget.undeclared = "changed"
    widget.enabled = True
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert set(audit_log.records()[0]["changes"]) == {"enabled"}


def test_new_object_reports_the_values_it_was_given(session, audit_log):
    widget = Widget(id=2, name="new", email="", enabled=True, password="hash", undeclared="x")  # noqa: S106
    _save(session, widget)

    record(AuditAction.USER_CREATED, widget)
    session.commit()

    [entry] = audit_log.records()
    assert entry["changes"] == {"name": {"to": "new"}, "enabled": {"to": True}, "password": {}}
    assert entry["targets"] == ["2"]


def test_deleted_object_records_its_name_and_no_changes(session, audit_log):
    widget = session.get(Widget, 1)
    session.delete(widget)
    session.flush()

    record(AuditAction.USER_DELETED, widget)
    session.commit()

    [entry] = audit_log.records()
    assert (entry["target_name"], entry["changes"]) == ("first", {})


def test_fields_split_across_records_are_reported_once(session, audit_log):
    widget = session.get(Widget, 1)
    widget.name = "renamed"
    widget.enabled = True
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget, exclude=("enabled",))
    record(AuditAction.USER_ADMIN_GRANTED, widget, only=("enabled",))
    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert [(entry["action"], entry["changes"]) for entry in audit_log.records()] == [
        ("user.updated", {"name": {"from": "first", "to": "renamed"}}),
        ("user.admin_granted", {"enabled": {"from": False, "to": True}}),
    ]


def test_arguments_override_what_the_subject_supplies(session, audit_log):
    widget = session.get(Widget, 1)
    widget.enabled = True
    _save(session, widget)

    record(AuditAction.PROJECT_MEMBER_ROLE_CHANGED, widget, target_type="user", targets=["u-1"], target_name="jdoe")
    session.commit()

    [entry] = audit_log.records()
    assert (entry["target_type"], entry["targets"], entry["target_name"]) == ("user", ["u-1"], "jdoe")
    assert entry["changes"] == {"enabled": {"from": False, "to": True}}


def test_changes_flushed_then_rolled_back_are_forgotten(session, audit_log):
    widget = session.get(Widget, 1)
    widget.name = "rolled-back"
    _save(session, widget)
    session.rollback()

    widget = session.get(Widget, 1)
    widget.enabled = True
    _save(session, widget)
    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"enabled": {"from": False, "to": True}}


def test_explicit_changes_drop_unchanged_entries(session, audit_log):
    record(AuditAction.SETTING_UPDATED, changes={"value": {"from": 30, "to": 30}})
    record(AuditAction.SETTING_UPDATED, changes={"value": {"from": 30, "to": 60}})
    session.commit()

    assert [entry["changes"] for entry in audit_log.records()] == [{"value": {"from": 30, "to": 60}}]


def test_declaration_errors_name_missing_columns_and_secrets_with_values():
    assert declaration_errors(Widget) == []
    assert declaration_errors(LeakyWidget) == ["password holds a secret and can only be withheld"]
    assert declaration_errors(MisdeclaredWidget) == ["missing is not a column"]


def test_enum_values_are_reported_by_value(session, audit_log):
    widget = session.get(Widget, 1)
    widget.size = Size.large
    _save(session, widget)

    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"size": {"from": None, "to": "L"}}


def test_changes_of_reports_and_consumes_the_subjects_changes(session, audit_log):
    widget = session.get(Widget, 1)
    widget.name = "renamed"
    widget.enabled = True
    _save(session, widget)

    assert changes_of(widget, only=("name",)) == {"name": {"from": "first", "to": "renamed"}}
    record(AuditAction.USER_UPDATED, widget)
    session.commit()

    assert audit_log.records()[0]["changes"] == {"enabled": {"from": False, "to": True}}


def test_changes_of_a_subject_with_no_declaration_is_empty(session, caplog):
    assert changes_of(object()) == {}
    assert "Audit changes_of failed" in caplog.text


@pytest.mark.parametrize(("enabled", "action"), [(True, "schedule.resumed"), (False, None)])
def test_record_switch_records_the_new_state_without_changes(session, audit_log, enabled, action):
    widget = session.get(Widget, 1)
    widget.enabled = enabled
    _save(session, widget)

    record_switch(widget, "enabled", on=AuditAction.SCHEDULE_RESUMED, off=AuditAction.SCHEDULE_PAUSED)
    session.commit()

    assert [(entry["action"], entry["changes"]) for entry in audit_log.records()] == (
        [(action, {})] if action else []
    )


def test_record_switch_records_the_off_action(session, audit_log):
    widget = session.get(Widget, 1)
    widget.enabled = True
    _save(session, widget)
    session.commit()

    widget.enabled = False
    _save(session, widget)
    record_switch(widget, "enabled", on=AuditAction.SCHEDULE_RESUMED, off=AuditAction.SCHEDULE_PAUSED)
    session.commit()

    assert [entry["action"] for entry in audit_log.records()] == ["schedule.paused"]


def test_record_update_separates_the_switch_from_the_other_changes(session, audit_log):
    widget = session.get(Widget, 1)
    widget.name = "renamed"
    widget.enabled = True
    _save(session, widget)

    record_update(
        widget, AuditAction.USER_UPDATED, switch="enabled",
        on=AuditAction.SCHEDULE_RESUMED, off=AuditAction.SCHEDULE_PAUSED,
    )
    session.commit()

    assert [(entry["action"], entry["changes"]) for entry in audit_log.records()] == [
        ("user.updated", {"name": {"from": "first", "to": "renamed"}}),
        ("schedule.resumed", {}),
    ]
