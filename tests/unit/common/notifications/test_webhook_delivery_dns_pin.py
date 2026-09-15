"""Tests for pinning a webhook delivery to addresses the SSRF guard verified.

``http_guard`` resolves the destination host and refuses reserved-range
addresses, but the HTTP client resolves again when it connects. A rebinding
authoritative server can answer with a permitted address on the check and a
reserved-range address on the connect. The delivery session therefore mounts an
adapter that connects only to the verified addresses, leaving the Host header,
SNI and certificate matching on the hostname.
"""

import ipaddress
from unittest.mock import MagicMock, patch

import pytest

from testgen.common.notifications import messages
from testgen.common.notifications import webhook_delivery as wd

pytestmark = pytest.mark.unit


def _connection(addresses, *, proxy=None, tunnel_host=None):
    """A pinned connection with urllib3's constructor bypassed."""
    connection_cls = wd._pinned_connection_cls([str(a) for a in addresses])
    connection = object.__new__(connection_cls)
    connection.proxy = proxy
    connection._tunnel_host = tunnel_host
    connection._dns_host = "webhook.example.com"
    return connection


def test_connect_targets_the_verified_address_not_the_resolved_one():
    """The socket goes to the pinned address even when the name resolves elsewhere.

    This is the rebind window: whatever a fresh lookup would answer, the connect
    must use an address the guard already approved.
    """
    connection = _connection(["203.0.113.10"])
    seen = []

    def record_conn(self):
        seen.append(self._dns_host)
        return MagicMock()

    with patch("urllib3.connection.HTTPSConnection._new_conn", record_conn):
        connection._new_conn()

    assert seen == ["203.0.113.10"]


def test_hostname_is_restored_after_connecting():
    """``host`` drives Host header, SNI and cert matching, and is derived from
    ``_dns_host`` -- so the pin must not outlive the connect.
    """
    connection = _connection(["203.0.113.10"])

    def succeed(_self):
        return MagicMock()

    with patch("urllib3.connection.HTTPSConnection._new_conn", succeed):
        connection._new_conn()

    assert connection._dns_host == "webhook.example.com"


def test_hostname_is_restored_even_when_every_address_fails():
    connection = _connection(["203.0.113.10"])

    def always_fail(self):
        raise OSError("unreachable")

    with patch("urllib3.connection.HTTPSConnection._new_conn", always_fail):
        with pytest.raises(OSError):
            connection._new_conn()

    assert connection._dns_host == "webhook.example.com"


def test_addresses_are_tried_in_order_until_one_connects():
    connection = _connection(["203.0.113.10", "203.0.113.11"])
    seen = []

    def fail_first(self):
        seen.append(self._dns_host)
        if len(seen) == 1:
            raise OSError("unreachable")
        return MagicMock()

    with patch("urllib3.connection.HTTPSConnection._new_conn", fail_first):
        connection._new_conn()

    assert seen == ["203.0.113.10", "203.0.113.11"]


def test_delivery_through_a_proxy_is_refused():
    """A proxy resolves the destination itself, so no address this side checked is
    the one contacted. The guard would be decorative; refuse instead.
    """
    connection = _connection(["203.0.113.10"], proxy="http://proxy.example:3128")

    with pytest.raises(wd.WebhookDeliveryError) as excinfo:
        connection._new_conn()

    assert str(excinfo.value) == messages.WEBHOOK_PROXY_UNVERIFIABLE


def test_tunnelled_connection_is_refused():
    connection = _connection(["203.0.113.10"], tunnel_host="webhook.example.com")

    with pytest.raises(wd.WebhookDeliveryError) as excinfo:
        connection._new_conn()

    assert str(excinfo.value) == messages.WEBHOOK_PROXY_UNVERIFIABLE


def test_adapter_refuses_a_proxy_manager():
    adapter = wd._PinnedHTTPAdapter([ipaddress.ip_address("203.0.113.10")])

    with pytest.raises(wd.WebhookDeliveryError) as excinfo:
        adapter.proxy_manager_for("http://proxy.example:3128")

    assert str(excinfo.value) == messages.WEBHOOK_PROXY_UNVERIFIABLE


def test_session_cannot_be_built_without_a_verified_address():
    """An empty verified set must refuse rather than degrade to resolving freely."""
    with pytest.raises(wd.WebhookDeliveryError) as excinfo:
        wd._make_session([])

    assert str(excinfo.value) == messages.WEBHOOK_URL_ADDRESS_REFUSED


def test_session_mounts_the_pinned_adapter_for_https():
    session = wd._make_session([ipaddress.ip_address("203.0.113.10")])

    adapter = session.get_adapter("https://webhook.example.com/hook")
    assert isinstance(adapter, wd._PinnedHTTPAdapter)
    assert adapter._pinned_addresses == ["203.0.113.10"]


@pytest.mark.parametrize(
    ("url", "expected_host"),
    [
        ("https://bücher.example.com/hook", "xn--bcher-kva.example.com"),
        ("https://Example.COM/hook", "example.com"),
        ("https://example.com./hook", "example.com."),
        ("https://127.0.0.1:9099/hook", "127.0.0.1"),
        ("https://[::1]:9099/hook", "::1"),
    ],
)
def test_guard_checks_the_host_the_client_resolves(url, expected_host):
    """``prepare_url`` IDNA-encodes the hostname, so reading the host off the raw
    URL would check an address nobody contacts. The IPv6 literal also confirms
    the brackets are stripped.
    """
    assert wd._canonical_connect_target(url)[1] == expected_host


def test_connect_url_is_the_idna_encoded_url():
    connect_url, hostname = wd._canonical_connect_target("https://bücher.example.com/hook")

    assert connect_url == "https://xn--bcher-kva.example.com/hook"
    assert hostname in connect_url


def test_unpreparable_url_raises_delivery_error():
    with pytest.raises(wd.WebhookDeliveryError) as excinfo:
        wd._canonical_connect_target("https://")

    assert "not a valid URL" in str(excinfo.value)
