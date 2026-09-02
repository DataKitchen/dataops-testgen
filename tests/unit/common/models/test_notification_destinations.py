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
    WebhookDestination,
    WebhookType,
    mask_webhook_url,
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


# ─── WebhookDestination — accessors and validation ───────────────────


def _webhook(**kwargs) -> WebhookDestination:
    """Instantiate a webhook without saving, ready for _validate() calls."""
    kwargs.setdefault("project_code", "p")
    kwargs.setdefault("name", "Team Chat")
    kwargs.setdefault("destination_type", "webhook")
    kwargs.setdefault("config", {"webhook_type": WebhookType.slack.value})
    kwargs.setdefault("secrets", {"url": "https://hooks.slack.com/services/T024/B/xyz"})
    return WebhookDestination(**kwargs)


def test_webhook_destination_type_getter_returns_enum():
    dest = _webhook(config={"webhook_type": "microsoft_teams"})
    assert dest.webhook_type == WebhookType.microsoft_teams


def test_webhook_destination_type_getter_returns_none_when_unset():
    dest = _webhook(config={})
    assert dest.webhook_type is None


def test_webhook_destination_type_getter_raises_on_unknown_value():
    """A corrupted stored value must not silently degrade to a different envelope shape."""
    dest = _webhook(config={"webhook_type": "future_type"})
    with pytest.raises(ValueError):
        _ = dest.webhook_type


def test_webhook_destination_url_setter_preserves_other_secrets():
    dest = _webhook(secrets={"url": "https://a.example.com", "auth_header_value": "bearer x"})
    dest.url = "https://b.example.com"
    assert dest.secrets == {"url": "https://b.example.com", "auth_header_value": "bearer x"}


def test_webhook_destination_target_summary_shows_type_and_host():
    dest = _webhook(
        config={"webhook_type": "microsoft_teams"},
        secrets={"url": "https://prod-06.westus.logic.azure.com/workflows/abc/triggers/manual"},
    )
    assert dest.target_summary == "Microsoft Teams — prod-06.westus.logic.azure.com"


def test_webhook_destination_target_summary_falls_back_when_url_missing():
    dest = _webhook(secrets={})
    assert dest.target_summary == "Slack"


def test_webhook_destination_has_auth_header_reads_secret_presence():
    dest = _webhook(secrets={"url": "https://a", "auth_header_value": "bearer x"})
    assert dest.has_auth_header is True
    dest_no_auth = _webhook(secrets={"url": "https://a"})
    assert dest_no_auth.has_auth_header is False


# ─── WebhookDestination._validate — pure-input paths ─────────────────


def _uniqueness_ok():
    """Patch that makes the uniqueness lookup return zero collisions."""

    def _install(patcher):
        gcs = patcher.__enter__()
        gcs.return_value.scalar.return_value = 0

    return _install


def _validate_with_no_collisions(dest: WebhookDestination) -> None:
    with patch("testgen.common.models.notification_destinations.get_current_session") as gcs:
        gcs.return_value.scalar.return_value = 0
        dest._validate()


@pytest.mark.parametrize("url,message_key", [
    (None, "WEBHOOK_URL_REQUIRED"),
    ("", "WEBHOOK_URL_REQUIRED"),
    ("   ", "WEBHOOK_URL_REQUIRED"),
    ("http://insecure.example.com/hook", "WEBHOOK_URL_NOT_HTTPS"),
    ("ftp://ftp.example.com/hook", "WEBHOOK_URL_NOT_HTTPS"),
    ("https://", "WEBHOOK_URL_INVALID"),
])
def test_webhook_destination_rejects_bad_urls(url, message_key):
    dest = _webhook(secrets={"url": url})
    with pytest.raises(NotificationSettingsValidationError) as exc:
        _validate_with_no_collisions(dest)
    assert str(exc.value) == getattr(messages, message_key)


def test_webhook_destination_rejects_missing_webhook_type():
    dest = _webhook(config={})
    with pytest.raises(NotificationSettingsValidationError) as exc:
        _validate_with_no_collisions(dest)
    assert str(exc.value) == messages.WEBHOOK_TYPE_REQUIRED


def test_webhook_destination_requires_header_name_when_value_set():
    dest = _webhook(
        config={"webhook_type": "generic", "auth_header_name": ""},
        secrets={"url": "https://api.example.com/hook", "auth_header_value": "bearer x"},
    )
    with pytest.raises(NotificationSettingsValidationError) as exc:
        _validate_with_no_collisions(dest)
    assert str(exc.value) == messages.WEBHOOK_AUTH_HEADER_NAME_MISSING


@pytest.mark.parametrize("header_name", [
    "Authoriz ation",   # space
    "Auth\r\nSet-Cookie",  # CR/LF injection
    "Auth\0",            # NUL
    "=badstart",         # '=' not a token char
])
def test_webhook_destination_rejects_malformed_header_name(header_name):
    dest = _webhook(
        config={"webhook_type": "generic", "auth_header_name": header_name},
        secrets={"url": "https://api.example.com/hook", "auth_header_value": "bearer x"},
    )
    with pytest.raises(NotificationSettingsValidationError) as exc:
        _validate_with_no_collisions(dest)
    assert str(exc.value) == messages.WEBHOOK_AUTH_HEADER_NAME_INVALID


def test_webhook_destination_rejects_control_chars_in_auth_value():
    dest = _webhook(
        config={"webhook_type": "generic", "auth_header_name": "Authorization"},
        secrets={"url": "https://api.example.com/hook", "auth_header_value": "bearer\r\nInjected: yes"},
    )
    with pytest.raises(NotificationSettingsValidationError) as exc:
        _validate_with_no_collisions(dest)
    assert str(exc.value) == messages.WEBHOOK_AUTH_HEADER_NAME_INVALID


def test_webhook_destination_accepts_well_formed_generic_config():
    dest = _webhook(
        config={"webhook_type": "generic", "auth_header_name": "Authorization"},
        secrets={"url": "https://api.example.com/webhook/abc", "auth_header_value": "Bearer token"},
    )
    _validate_with_no_collisions(dest)  # must not raise


@pytest.mark.parametrize("webhook_type", ["slack", "microsoft_teams"])
def test_webhook_destination_rejects_auth_header_on_non_generic_type(webhook_type):
    dest = _webhook(
        config={"webhook_type": webhook_type, "auth_header_name": "Authorization"},
        secrets={"url": "https://hooks.example.com/services/abc", "auth_header_value": "Bearer x"},
    )
    with pytest.raises(NotificationSettingsValidationError) as exc:
        _validate_with_no_collisions(dest)
    assert str(exc.value) == messages.WEBHOOK_AUTH_HEADER_ONLY_GENERIC


@pytest.mark.parametrize("webhook_type", ["slack", "microsoft_teams"])
def test_webhook_destination_accepts_non_generic_without_auth_header(webhook_type):
    dest = _webhook(
        config={"webhook_type": webhook_type},
        secrets={"url": "https://hooks.example.com/services/abc"},
    )
    _validate_with_no_collisions(dest)  # must not raise


@pytest.mark.parametrize("reserved_name", [
    # Case-insensitivity check -- the denylist match lowercases first.
    "Host",
    "host",
    "HOST",
    "Content-Type",
    "content-length",
    "Transfer-Encoding",
    "Connection",
    # ``X-TestGen-*`` prefix reserves the event tag a receiver may route on.
    "X-TestGen-Event",
    "x-testgen-delivery-id",
    "X-TestGen-Anything",
])
def test_webhook_destination_rejects_reserved_auth_header_name(reserved_name):
    dest = _webhook(
        config={"webhook_type": "generic", "auth_header_name": reserved_name},
        secrets={"url": "https://api.example.com/hook", "auth_header_value": "Bearer x"},
    )
    with pytest.raises(NotificationSettingsValidationError) as exc:
        _validate_with_no_collisions(dest)
    assert str(exc.value) == messages.WEBHOOK_AUTH_HEADER_NAME_RESERVED


def test_webhook_destination_accepts_authorization_as_a_permitted_header_name():
    # ``Authorization`` is the canonical use case and is NOT reserved.
    dest = _webhook(
        config={"webhook_type": "generic", "auth_header_name": "Authorization"},
        secrets={"url": "https://api.example.com/hook", "auth_header_value": "Bearer x"},
    )
    _validate_with_no_collisions(dest)  # must not raise


# ─── Corrupt-config read-path degradation ────────────────────────────


def test_webhook_type_raises_on_unknown_stored_value():
    """The strict property still surfaces corruption for validate/deliver."""
    dest = _webhook(config={"webhook_type": "carrier-pigeon"})
    with pytest.raises(ValueError):
        _ = dest.webhook_type


def test_webhook_type_safe_returns_none_on_unknown_stored_value():
    """Read paths that render many rows degrade instead of raising."""
    dest = _webhook(config={"webhook_type": "carrier-pigeon"})
    assert dest.webhook_type_safe is None


def test_target_summary_survives_a_corrupt_webhook_type():
    """One bad row must not 500 the destinations list."""
    dest = _webhook(
        config={"webhook_type": "carrier-pigeon"},
        secrets={"url": "https://hooks.example.com/services/abc"},
    )
    assert dest.target_summary == "Webhook — hooks.example.com"


def test_target_summary_survives_undecryptable_secrets():
    """``SafeEncryptedJson`` hands back ``None``; the summary degrades to the label."""
    dest = _webhook(config={"webhook_type": "slack"})
    dest.secrets = None
    assert dest.target_summary == "Slack"


# ─── mask_webhook_url ────────────────────────────────────────────────


@pytest.mark.parametrize("url,expected", [
    ("", ""),
    (None, ""),
    # Fail-closed: anything without scheme + hostname is masked entirely.
    ("not-a-url", "•••"),
    ("http://", "•••"),
    ("https://hooks.slack.com/services/T024/B012/xyz",
     "https://hooks.slack.com/services/•••"),
    ("https://prod-06.westus.logic.azure.com/workflows/abc/triggers/manual",
     "https://prod-06.westus.logic.azure.com/workflows/•••"),
    # Bullet marker is always present so callers can tell a URL is stored.
    ("https://example.com", "https://example.com/•••"),
    # Single-segment path: ``first_segment`` IS the credential portion (webhook
    # tokens for Slack, Teams, and Generic all put the secret in the trailing
    # segment) -- keeping it would leak the very thing the mask is meant to hide.
    ("https://example.com/only-one-segment",
     "https://example.com/•••"),
    ("https://webhook.site/8f14e45f-ceea-467a-9b0f-CREDENTIAL",
     "https://webhook.site/•••"),
    # ``userinfo`` (``user:pass@``) is stripped -- ``netloc`` would leak it.
    # Single-segment path so the segment is masked, not kept.
    ("https://user:pass@example.com/hook",
     "https://example.com/•••"),
    # A non-default port is preserved (operators route non-443 webhooks);
    # single-segment path is still masked.
    ("https://example.com:8443/hook",
     "https://example.com:8443/•••"),
    ("https://example.com:8443/path/token",
     "https://example.com:8443/path/•••"),
])
def test_mask_webhook_url(url, expected):
    assert mask_webhook_url(url) == expected


def test_switching_off_generic_clears_the_authorization_header():
    """Only the generic type carries an auth header, so a type change drops it.

    The form removes both auth inputs as soon as the type changes, leaving no way
    to clear them by hand. Without this the stored header fails validation and the
    destination can never be switched to Slack or Teams.
    """
    destination = WebhookDestination(
        project_code="P",
        name="switcher",
        destination_type="webhook",
        config={"webhook_type": "generic", "auth_header_name": "Authorization"},
        secrets={"url": "https://hooks.example.com/x", "auth_header_value": "Bearer SECRET"},
    )
    assert destination.auth_header_name == "Authorization"

    destination.webhook_type = WebhookType.slack

    assert destination.auth_header_name is None
    assert destination.auth_header_value is None
    assert destination.url == "https://hooks.example.com/x"


def test_switching_between_generic_types_keeps_the_header():
    destination = WebhookDestination(
        project_code="P",
        name="switcher",
        destination_type="webhook",
        config={"webhook_type": "generic", "auth_header_name": "Authorization"},
        secrets={"url": "https://hooks.example.com/x", "auth_header_value": "Bearer SECRET"},
    )

    destination.webhook_type = WebhookType.generic

    assert destination.auth_header_name == "Authorization"
    assert destination.auth_header_value == "Bearer SECRET"
