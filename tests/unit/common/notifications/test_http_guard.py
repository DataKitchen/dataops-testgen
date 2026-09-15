"""Tests for the outbound-webhook address restriction module.

The failure catalog matters more than the code -- what makes ``http_guard`` correct
is the exact list of addresses it refuses and admits. Each table entry names a
scenario a naive check would miss and the address that would leak through.
"""

import ipaddress
import socket
from unittest.mock import patch

import pytest

from testgen.common.notifications import http_guard
from testgen.common.notifications.http_guard import (
    EMPTY_ALLOWLIST,
    AddressNotAllowedError,
    is_address_refused,
    parse_allowlist,
    resolve_and_verify,
    unwrap_ipv4_mapped,
)

pytestmark = pytest.mark.unit


# ─── Explicit-range refusal ──────────────────────────────────────────

# Each row is a single address that must be refused, tagged with what it would
# reach if the check missed it. The tag doubles as a failure-mode label in test
# output; the address is the assertion.
REFUSED_ADDRESSES = [
    ("loopback v4", "127.0.0.1"),
    ("loopback v4 anywhere in /8", "127.4.5.6"),
    ("loopback v6", "::1"),
    ("private 10/8", "10.0.0.1"),
    ("private 172.16/12", "172.20.0.5"),
    ("private 192.168/16", "192.168.1.1"),
    ("private v6 fc00/7", "fc00::1"),
    ("link-local v4 (AWS/GCP metadata)", "169.254.169.254"),
    ("link-local v6", "fe80::1"),
    ("site-local v6 (deprecated but still routed)", "fec0::1"),
    ("carrier-grade NAT (Alibaba metadata)", "100.64.169.254"),
    ("multicast v4", "224.0.0.1"),
    ("multicast v6", "ff00::1"),
    ("reserved v4", "241.0.0.1"),
    ("this-network 0/8 (not just the /32)", "0.1.2.3"),
    ("unspecified v4", "0.0.0.0"),  # noqa: S104  test data, not a bind address
    ("unspecified v6", "::"),
    ("IETF protocol assignments", "192.0.0.170"),
    ("benchmarking range", "198.18.0.1"),
    # NAT64 / 6to4 / IPv4-compatible v6 pseudo-addresses: they embed a v4 address
    # in a v6 wrapper and reach the same targets those v4 ranges reach on a
    # gateway that translates them. Each must be refused via its own range entry.
    ("NAT64 well-known -> metadata", "64:ff9b::a9fe:a9fe"),
    ("NAT64 local-use -> metadata", "64:ff9b:1:ffff::a9fe:a9fe"),
    ("6to4 -> metadata", "2002:a9fe:a9fe::"),
    ("IPv4-compatible v6 -> metadata", "::169.254.169.254"),
    ("IPv4-compatible v6 -> loopback", "::127.0.0.1"),
]

# A short list of addresses that MUST pass. These are the anchors that catch
# a regression that over-broadens the refused ranges.
ADMITTED_ADDRESSES = [
    ("public IPv4", "8.8.8.8"),
    ("public IPv4 in a large block", "203.0.113.10"),  # documentation range, still not in refused categories
    ("public IPv6", "2606:4700::1"),
]


@pytest.mark.parametrize("tag,address", REFUSED_ADDRESSES, ids=[t for t, _ in REFUSED_ADDRESSES])
def test_refuses_reserved_address(tag, address):
    assert is_address_refused(ipaddress.ip_address(address)), f"{tag} should be refused"


@pytest.mark.parametrize("tag,address", ADMITTED_ADDRESSES, ids=[t for t, _ in ADMITTED_ADDRESSES])
def test_admits_public_address(tag, address):
    assert not is_address_refused(ipaddress.ip_address(address)), f"{tag} should be admitted"


# ─── IPv4-mapped IPv6 unwrap ─────────────────────────────────────────


@pytest.mark.parametrize("wrapped,expected_v4", [
    ("::ffff:169.254.169.254", "169.254.169.254"),
    ("::ffff:10.0.0.1", "10.0.0.1"),
    ("::ffff:8.8.8.8", "8.8.8.8"),
])
def test_ipv4_mapped_ipv6_unwraps_before_refusal_check(wrapped, expected_v4):
    unwrapped = unwrap_ipv4_mapped(ipaddress.ip_address(wrapped))
    assert unwrapped == ipaddress.ip_address(expected_v4)


def test_ipv4_mapped_metadata_endpoint_is_refused_via_v6_notation():
    assert is_address_refused(ipaddress.ip_address("::ffff:169.254.169.254"))


def test_ipv4_mapped_public_v4_is_admitted_via_v6_notation():
    assert not is_address_refused(ipaddress.ip_address("::ffff:8.8.8.8"))


# ─── Every resolver address is checked ───────────────────────────────


def _fake_getaddrinfo(mapping: dict[str, list[str]]):
    """Return a function that mimics ``socket.getaddrinfo`` for the given mapping."""

    def _fake(host, *_args, **_kwargs):
        addresses = mapping.get(host)
        if not addresses:
            raise OSError(f"no address for {host}")
        # Each result tuple matches getaddrinfo's shape (family, type, proto, canonname, sockaddr).
        return [(0, 0, 0, "", (addr, 0)) for addr in addresses]

    return _fake


def test_dual_stack_hostname_is_refused_when_only_the_aaaa_is_bad():
    fake = _fake_getaddrinfo({"mixed.example.com": ["8.8.8.8", "fe80::1"]})
    with patch("socket.getaddrinfo", side_effect=fake), pytest.raises(AddressNotAllowedError):
        resolve_and_verify("mixed.example.com")


def test_dual_stack_hostname_is_admitted_when_all_addresses_are_public():
    fake = _fake_getaddrinfo({"public.example.com": ["8.8.8.8", "2606:4700::1"]})
    with patch("socket.getaddrinfo", side_effect=fake):
        addresses = resolve_and_verify("public.example.com")
    assert len(addresses) == 2


def test_hostname_with_no_records_raises_a_stable_error():
    fake = _fake_getaddrinfo({})
    with patch("socket.getaddrinfo", side_effect=fake), pytest.raises(AddressNotAllowedError):
        resolve_and_verify("unresolvable.example.com")


def test_literal_ip_bypasses_the_resolver_but_still_faces_the_check():
    with patch("socket.getaddrinfo") as gai:
        with pytest.raises(AddressNotAllowedError):
            resolve_and_verify("127.0.0.1")
        gai.assert_not_called()


# ─── Deployment override (Allowlist) ─────────────────────────────────


def test_empty_spec_yields_empty_allowlist():
    assert parse_allowlist(None) is EMPTY_ALLOWLIST
    assert parse_allowlist("") is EMPTY_ALLOWLIST
    assert parse_allowlist("   ") == EMPTY_ALLOWLIST


def test_hostname_entries_are_case_insensitive():
    allow = parse_allowlist("chat.internal, ALERTS.INTERNAL")
    assert allow.admits_hostname("chat.internal")
    assert allow.admits_hostname("CHAT.INTERNAL")
    assert allow.admits_hostname("alerts.internal")
    assert not allow.admits_hostname("other.internal")


def test_cidr_entries_admit_addresses_in_the_network():
    allow = parse_allowlist("10.0.0.0/8, 192.168.1.5")
    assert allow.admits_address(ipaddress.ip_address("10.5.5.5"))
    assert allow.admits_address(ipaddress.ip_address("192.168.1.5"))
    assert not allow.admits_address(ipaddress.ip_address("192.168.1.6"))


def test_allowlist_hostname_bypasses_dual_stack_refusal():
    fake = _fake_getaddrinfo({"chat.internal": ["10.0.0.5"]})
    allow = parse_allowlist("chat.internal")
    with patch("socket.getaddrinfo", side_effect=fake):
        addresses = resolve_and_verify("chat.internal", allow)
    assert addresses == [ipaddress.ip_address("10.0.0.5")]


def test_allowlist_cidr_admits_matching_ip_without_hostname_entry():
    fake = _fake_getaddrinfo({"gate.internal": ["10.42.0.1"]})
    allow = parse_allowlist("10.42.0.0/16")
    with patch("socket.getaddrinfo", side_effect=fake):
        addresses = resolve_and_verify("gate.internal", allow)
    assert addresses == [ipaddress.ip_address("10.42.0.1")]


def test_allowlist_does_not_override_when_the_address_is_outside():
    fake = _fake_getaddrinfo({"gate.internal": ["169.254.169.254"]})
    allow = parse_allowlist("10.0.0.0/8")
    with patch("socket.getaddrinfo", side_effect=fake), pytest.raises(AddressNotAllowedError):
        resolve_and_verify("gate.internal", allow)


def test_allowlist_admits_ipv4_mapped_ipv6_via_unwrap():
    fake = _fake_getaddrinfo({"legacy.internal": ["::ffff:10.0.0.5"]})
    allow = parse_allowlist("10.0.0.0/8")
    with patch("socket.getaddrinfo", side_effect=fake):
        addresses = resolve_and_verify("legacy.internal", allow)
    assert addresses[0] == ipaddress.ip_address("::ffff:10.0.0.5")


def test_resolver_answer_with_no_usable_address_is_refused():
    """A resolver answering with nothing parseable must refuse, not return empty.

    An empty list reads as "verified, nothing objectionable" to the caller, which
    would then deliver having checked no address at all.
    """
    unparseable = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 0))]

    with patch.object(socket, "getaddrinfo", return_value=unparseable):
        with pytest.raises(http_guard.AddressNotAllowedError):
            http_guard.resolve_and_verify("webhook.example.com")

    with patch.object(socket, "getaddrinfo", return_value=[]):
        with pytest.raises(http_guard.AddressNotAllowedError):
            http_guard.resolve_and_verify("webhook.example.com")
