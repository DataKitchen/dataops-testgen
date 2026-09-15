"""Tests for the bounded retry policy on the webhook delivery session.

Delivery runs inline on the caller's thread -- inside a job subprocess on the
live path, and on the Streamlit script-runner thread for Send Test. The socket
timeouts bound reads but not sleeps, so the retry policy is the only thing
keeping a receiver from holding that thread. Two properties matter:

- The receiver cannot name its own delay. ``respect_retry_after_header=True``
  makes urllib3 sleep for whatever ``Retry-After`` says, capped only by
  ``Retry.retry_after_max`` (six hours), which two attempts turn into twelve.
- A retry cannot duplicate a notification. Connect errors are safe to repost
  because the request never arrived; a read error may follow a request the
  receiver already acted on.
"""

import ipaddress

import pytest
from urllib3.util.retry import Retry

from testgen.common.notifications import webhook_delivery as wd

pytestmark = pytest.mark.unit

# Anything above a couple of seconds means a receiver is holding the caller's
# thread; the policy exists to keep the total well under this.
MAX_ACCEPTABLE_SLEEP_SECONDS = 5


def _policy() -> Retry:
    # The session pins to verified addresses, so it needs one; the retry policy
    # under test is independent of which.
    session = wd._make_session([ipaddress.ip_address("203.0.113.1")])
    return session.get_adapter("https://example.com/").max_retries


def test_retry_after_header_is_not_honoured():
    """A receiver's ``Retry-After`` cannot introduce a sleep of its choosing."""
    assert _policy().respect_retry_after_header is False


def test_total_sleep_on_the_retry_chain_is_bounded():
    """Walking the whole chain, the sleeps sum to a couple of seconds.

    Asserts the bound rather than the exact sequence so an urllib3 change to the
    backoff formula surfaces as a failure only if it breaks the guarantee.
    """
    policy = _policy()
    sleeps = []
    for _ in range(policy.total + 1):
        sleeps.append(policy.get_backoff_time())
        try:
            policy = policy.increment(method="POST", url="/hook", error=OSError("boom"))
        except Exception:
            break

    assert sum(sleeps) <= MAX_ACCEPTABLE_SLEEP_SECONDS


def test_read_errors_are_never_retried():
    """A read timeout may follow a request the receiver already processed."""
    assert _policy().read == 0


def test_connect_errors_are_retried():
    """The request never reached the receiver, so a repost cannot duplicate."""
    assert _policy().connect == wd._RETRY_ATTEMPTS


def test_only_the_documented_status_codes_retry():
    policy = _policy()
    assert policy.status_forcelist == wd._RETRY_STATUS_CODES
    assert 400 not in policy.status_forcelist
    assert policy.allowed_methods == frozenset(["POST"])


def test_transport_failure_does_not_leak_the_url_into_logs(caplog):
    """A transport failure must not put the webhook URL in the log.

    For Slack and Teams the URL path *is* the credential. The raised message is
    sanitized, but the handlers log with ``LOG.exception``, which formats the
    chained cause -- so asserting on the raised message alone passes while the
    log still carries the secret.
    """
    import logging
    import socket
    from unittest.mock import patch

    from testgen.common.models.notification_destinations import WebhookDestination, WebhookType

    credential_path = "/services/T024TEAM/B01BOT/xyzTOKENVALUE"  # - fixture, not a real credential
    destination = WebhookDestination(project_code="DEFAULT", name="probe", webhook_type=WebhookType.slack)
    destination.url = f"https://hooks.slack.example{credential_path}"

    real = socket.getaddrinfo

    def resolve_to_test_net(host, port=None, *args, **kwargs):
        # TEST-NET-3 is outside the refused ranges, so the guard admits it and the
        # connect fails for real rather than being rejected before it is attempted.
        if "hooks.slack.example" in str(host):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.9", port or 443))]
        return real(host, port, *args, **kwargs)

    with patch.object(socket, "getaddrinfo", resolve_to_test_net):
        with caplog.at_level(logging.DEBUG):  # root: catches urllib3 loggers too
            # Mirror the handlers: they wrap the call and log with ``LOG.exception``,
            # which formats the chained cause -- the half a message-only assert misses.
            try:
                wd.deliver_test_payload(destination)
            except wd.WebhookDeliveryError as exc:
                raised = exc
                logging.getLogger("testgen").exception("Notification delivery failed")
            else:
                pytest.fail("delivery unexpectedly succeeded")

    assert credential_path not in str(raised)
    # Captured at root on purpose. Three routes have carried this path: the chained
    # cause ``LOG.exception`` formats, ``urllib3.connectionpool``'s retry warning and
    # ``urllib3.util.retry``'s debug record. Scoping the capture to one logger passes
    # while the others still leak.
    leaking = sorted({r.name for r in caplog.records if credential_path in r.getMessage()})
    assert not leaking, f"credential path leaked via {leaking}"
    assert credential_path not in caplog.text
