"""Unit tests for ``NotificationDestination`` (email destination + delivery seam).

Uniqueness and destination-lookup rely on the DB session and are exercised in the
functional smoke; here we cover pure-Python behavior and mock the session where the
model calls into it.
"""

from unittest.mock import MagicMock, patch

import pytest

from testgen.common.models.notification_destinations import (
    EmailDestination,
    InlineRecipientList,
)
from testgen.common.models.notification_settings import (
    NotificationSettingsValidationError,
    TestRunNotificationSettings,
    TestRunNotificationTrigger,
)
from testgen.common.notifications import messages

pytestmark = pytest.mark.unit


# ─── EmailDestination — pure accessors ───────────────────────────────


def test_email_destination_recipients_getter_reads_config():
    dest = EmailDestination(destination_type="email", config={"recipients": ["a@x.co", "b@x.co"]})
    assert dest.recipients == ["a@x.co", "b@x.co"]


def test_email_destination_recipients_getter_defaults_to_empty_list():
    dest = EmailDestination(destination_type="email", config={})
    assert dest.recipients == []


def test_email_destination_recipients_getter_handles_none_config():
    dest = EmailDestination(destination_type="email")
    dest.config = None
    assert dest.recipients == []


def test_email_destination_recipients_setter_writes_config():
    dest = EmailDestination(destination_type="email", config={"unrelated": True})
    dest.recipients = ["c@x.co"]
    assert dest.config == {"unrelated": True, "recipients": ["c@x.co"]}


def test_email_destination_target_summary_joins_recipients():
    dest = EmailDestination(destination_type="email", config={"recipients": ["a@x.co", "b@x.co"]})
    assert dest.target_summary == "a@x.co, b@x.co"


# ─── EmailDestination._validate — pure-input paths ───────────────────


@pytest.mark.parametrize("name", ["", "   ", None])
def test_email_destination_rejects_empty_name(name):
    dest = EmailDestination(
        project_code="p", name=name, destination_type="email",
        config={"recipients": ["a@x.co"]},
    )
    with patch("testgen.common.models.notification_destinations.get_current_session") as gcs:
        gcs.return_value.scalar.return_value = 0
        with pytest.raises(NotificationSettingsValidationError) as exc:
            dest._validate()
    assert str(exc.value) == messages.NAME_REQUIRED


def test_email_destination_rejects_name_too_long():
    dest = EmailDestination(
        project_code="p", name="x" * 101, destination_type="email",
        config={"recipients": ["a@x.co"]},
    )
    with patch("testgen.common.models.notification_destinations.get_current_session") as gcs:
        gcs.return_value.scalar.return_value = 0
        with pytest.raises(NotificationSettingsValidationError) as exc:
            dest._validate()
    assert str(exc.value) == messages.NAME_TOO_LONG


def test_email_destination_rejects_empty_recipients():
    dest = EmailDestination(
        project_code="p", name="Team", destination_type="email", config={"recipients": []},
    )
    with patch("testgen.common.models.notification_destinations.get_current_session") as gcs:
        gcs.return_value.scalar.return_value = 0
        with pytest.raises(NotificationSettingsValidationError) as exc:
            dest._validate()
    assert str(exc.value) == messages.RECIPIENTS_REQUIRED


def test_email_destination_reports_each_invalid_address_on_its_own_line():
    dest = EmailDestination(
        project_code="p", name="Team", destination_type="email",
        config={"recipients": ["nope", "ok@x.co", "also-bad"]},
    )
    with patch("testgen.common.models.notification_destinations.get_current_session") as gcs:
        gcs.return_value.scalar.return_value = 0
        with pytest.raises(NotificationSettingsValidationError) as exc:
            dest._validate()
    text = str(exc.value)
    assert "nope is not a valid email address." in text
    assert "also-bad is not a valid email address." in text
    assert "ok@x.co is not a valid email address." not in text


def test_email_destination_reports_case_insensitive_name_clash():
    dest = EmailDestination(
        project_code="p", name="Team", destination_type="email",
        config={"recipients": ["a@x.co"]},
    )
    with patch("testgen.common.models.notification_destinations.get_current_session") as gcs:
        gcs.return_value.scalar.return_value = 1  # simulate an existing row
        with pytest.raises(NotificationSettingsValidationError) as exc:
            dest._validate()
    assert str(exc.value) == messages.name_already_exists("Team")


# ─── InlineRecipientList — wrapper for the send seam ─────────────────


def test_inline_recipient_list_defensively_copies_recipients():
    original = ["a@x.co"]
    wrapper = InlineRecipientList(original)
    original.append("b@x.co")
    assert wrapper.recipients == ["a@x.co"]


def test_inline_recipient_list_deliver_calls_template_send():
    template = MagicMock()
    wrapper = InlineRecipientList(["a@x.co", "b@x.co"])
    wrapper.deliver({"ctx": 1}, template)
    template.send.assert_called_once_with(["a@x.co", "b@x.co"], {"ctx": 1})


def test_email_destination_deliver_uses_stored_recipients():
    template = MagicMock()
    dest = EmailDestination(destination_type="email", config={"recipients": ["a@x.co"]})
    dest.deliver({"ctx": 1}, template)
    template.send.assert_called_once_with(["a@x.co"], {"ctx": 1})


# ─── NotificationSettings — addressing invariant + delivery_target ───


def _rule(**kwargs) -> TestRunNotificationSettings:
    kwargs.setdefault("project_code", "p")
    kwargs.setdefault("recipients", [])
    kwargs.setdefault("settings", {"trigger": TestRunNotificationTrigger.always.value})
    return TestRunNotificationSettings(**kwargs)


def test_rule_addressing_invariant_rejects_both_inline_and_destination():
    rule = _rule(
        recipients=["a@x.co"],
        notification_destination_id="00000000-0000-0000-0000-000000000001",
    )
    with pytest.raises(NotificationSettingsValidationError) as exc:
        rule.validate()
    assert str(exc.value) == messages.ADDRESSING_BOTH


def test_rule_addressing_invariant_rejects_neither():
    rule = _rule()
    with pytest.raises(NotificationSettingsValidationError) as exc:
        rule.validate()
    assert str(exc.value) == messages.ADDRESSING_NEITHER


def test_rule_addressing_invariant_reports_invalid_inline_email():
    rule = _rule(recipients=["not-an-email"])
    with pytest.raises(NotificationSettingsValidationError) as exc:
        rule.validate()
    assert str(exc.value) == messages.invalid_email("not-an-email")


def test_rule_delivery_target_returns_inline_wrapper_when_no_destination():
    rule = _rule(recipients=["a@x.co"])
    target = rule.delivery_target
    assert isinstance(target, InlineRecipientList)
    assert target.recipients == ["a@x.co"]


def test_rule_delivery_target_returns_linked_destination():
    dest = EmailDestination(destination_type="email", config={"recipients": ["a@x.co"]})
    rule = _rule(notification_destination_id="00000000-0000-0000-0000-000000000001")
    rule.destination = dest
    target = rule.delivery_target
    assert target is dest


def test_rule_delivery_target_description_names_the_destination():
    dest = EmailDestination(destination_type="email", name="Team Alpha")
    rule = _rule(notification_destination_id="00000000-0000-0000-0000-000000000001")
    rule.destination = dest
    assert rule.delivery_target_description == "destination='Team Alpha' (email)"


def test_rule_delivery_target_description_counts_inline_recipients():
    rule = _rule(recipients=["a@x.co", "b@x.co"])
    assert rule.delivery_target_description == "inline recipients=2"
