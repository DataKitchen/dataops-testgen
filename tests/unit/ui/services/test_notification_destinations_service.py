"""Tests for the Send Test path's handling of the stored authorization header.

The header value is write-only: it is encrypted at rest and never serialized back
to the browser. Send Test has to reuse it for the common case of testing an
unchanged destination, which makes it the one path that can put that secret on
the wire -- so which URL it is willing to send it to is a security property, not
a convenience.
"""

from unittest.mock import patch

import pytest

from testgen.common.models.notification_settings import NotificationSettingsValidationError
from testgen.common.notifications import messages
from testgen.ui.services import notification_destinations_service as svc

pytestmark = pytest.mark.unit

STORED_URL = "https://hooks.example.com/stored"
STORED_SECRET = "Bearer STORED-VALUE"  # noqa: S105 - test fixture, not a credential


def _stored_destination() -> svc.WebhookDestination:
    """A saved generic webhook destination carrying an authorization header."""
    return svc.WebhookDestination(
        project_code="P",
        name="stored",
        destination_type="webhook",
        config={"webhook_type": "generic", "auth_header_name": "Authorization"},
        secrets={"url": STORED_URL, "auth_header_value": STORED_SECRET},
    )


def _send(payload):
    """Run ``send_test_delivery`` with the DB lookup and the transport stubbed out."""
    delivered = {}

    def capture(destination):
        delivered["url"] = destination.url
        delivered["auth_header_value"] = destination.auth_header_value
        return svc.DeliveryResult(200, 1, "")

    with (
        patch.object(svc, "database_session"),
        patch.object(svc, "_get_owned", return_value=_stored_destination()),
        patch.object(svc, "deliver_test_payload", side_effect=capture),
    ):
        svc.send_test_delivery("P", payload)
    return delivered


def test_stored_header_is_reused_when_the_url_is_unchanged():
    """The ordinary case: open a saved destination and press Send Test."""
    delivered = _send({"id": "x", "webhook_type": "generic", "webhook_url": "", "auth_header_name": "Authorization"})

    assert delivered["url"] == STORED_URL
    assert delivered["auth_header_value"] == STORED_SECRET


def test_stored_header_is_not_sent_to_a_url_the_caller_supplied():
    """Editing the URL and pressing Send Test must not forward the stored secret.

    Without this the write-only header is readable by anyone who can edit the
    destination: point the URL at a host you control, press Send Test, and read
    the secret off your own receiver.
    """
    with pytest.raises(NotificationSettingsValidationError) as excinfo:
        _send({
            "id": "x",
            "webhook_type": "generic",
            "webhook_url": "https://attacker.example.com/collect",
            "auth_header_name": "Authorization",
        })

    assert str(excinfo.value) == messages.WEBHOOK_AUTH_HEADER_REQUIRED_FOR_NEW_URL


def test_a_freshly_typed_header_may_go_to_a_new_url():
    """Re-entering the value is the supported way to test a changed URL."""
    delivered = _send({
        "id": "x",
        "webhook_type": "generic",
        "webhook_url": "https://hooks.example.com/new",
        "auth_header_name": "Authorization",
        "auth_header_value": "Bearer TYPED",
    })

    assert delivered["url"] == "https://hooks.example.com/new"
    assert delivered["auth_header_value"] == "Bearer TYPED"
    assert STORED_SECRET not in (delivered["auth_header_value"] or "")
