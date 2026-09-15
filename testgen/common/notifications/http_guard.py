"""Address restriction for outbound webhook deliveries.

Resolves a hostname to every IP address the DNS returns, and refuses if any of them
sits in a reserved range that must not be reached from an outbound webhook (loopback,
private, link-local, carrier-grade NAT, cloud metadata via link-local, multicast,
reserved, unspecified). Overridable at deployment time with a comma-separated
allow-list of hostnames or CIDR ranges.

Four traps this implementation is designed to close:

- Ranges are asserted explicitly rather than through ``ipaddress.is_private``.
  ``is_private`` returns False for the carrier-grade NAT range 100.64.0.0/10,
  which is where Alibaba Cloud's instance metadata endpoint lives; a "refuse if
  private" check would let that pass.
- IPv4-mapped IPv6 addresses (``::ffff:x.x.x.x``) are unwrapped before comparison,
  so the AWS/GCP metadata address ``169.254.169.254`` cannot bypass a naive check
  by presenting as ``::ffff:169.254.169.254``.
- Every address the resolver returns is checked, not just the first. A dual-stack
  hostname with a permitted A record and a refused AAAA record is still refused.
- The verification loop is a resolve + compare. The actual HTTP client that
  consumes the verified addresses must also refuse redirects, or a permitted
  host answering ``302 http://169.254.169.254/`` bypasses everything.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass


class AddressNotAllowedError(Exception):
    """Raised when a hostname resolves to any address in a refused range."""


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


# Refused ranges are stated in full so a reader can audit every entry without
# reaching for the stdlib's implicit categories.
_REFUSED_V4: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("0.0.0.0/8"),        # this-network (0.x.x.x, RFC 1122)
    ipaddress.IPv4Network("10.0.0.0/8"),       # private
    ipaddress.IPv4Network("100.64.0.0/10"),    # carrier-grade NAT (Alibaba metadata)
    ipaddress.IPv4Network("127.0.0.0/8"),      # loopback
    ipaddress.IPv4Network("169.254.0.0/16"),   # link-local (AWS/GCP metadata)
    ipaddress.IPv4Network("172.16.0.0/12"),    # private
    ipaddress.IPv4Network("192.0.0.0/24"),     # IETF protocol assignments (RFC 6890)
    ipaddress.IPv4Network("192.168.0.0/16"),   # private
    ipaddress.IPv4Network("198.18.0.0/15"),    # benchmarking (RFC 2544)
    ipaddress.IPv4Network("224.0.0.0/4"),      # multicast
    ipaddress.IPv4Network("240.0.0.0/4"),      # reserved
)

_REFUSED_V6: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.IPv6Network("::/128"),           # unspecified
    ipaddress.IPv6Network("::1/128"),          # loopback
    ipaddress.IPv6Network("::/96"),            # IPv4-compatible IPv6 (embeds v4 address in the low 32 bits)
    ipaddress.IPv6Network("64:ff9b::/96"),     # NAT64 well-known prefix (embeds v4 address; reaches metadata on IPv6-only clusters)
    ipaddress.IPv6Network("64:ff9b:1::/48"),   # NAT64 local-use prefix
    ipaddress.IPv6Network("2002::/16"),        # 6to4 (embeds v4 in the pseudo-address)
    ipaddress.IPv6Network("fc00::/7"),         # unique local (private)
    ipaddress.IPv6Network("fe80::/10"),        # link-local
    ipaddress.IPv6Network("fec0::/10"),        # deprecated site-local; still routed by some stacks
    ipaddress.IPv6Network("ff00::/8"),         # multicast
)


@dataclass(frozen=True)
class Allowlist:
    """Deployment-configured override for the refusal rules.

    Constructed from the ``TG_WEBHOOK_ALLOWED_HOSTS`` environment variable value.
    Entries are matched case-insensitively for hostnames; CIDR entries admit any
    address contained in the network.
    """

    hostnames: frozenset[str]
    networks: tuple[IPNetwork, ...]

    def admits_hostname(self, hostname: str) -> bool:
        return hostname.lower().strip() in self.hostnames

    def admits_address(self, address: IPAddress) -> bool:
        return any(address in net for net in self.networks)


EMPTY_ALLOWLIST = Allowlist(hostnames=frozenset(), networks=())


def parse_allowlist(spec: str | None) -> Allowlist:
    """Parse a comma-separated allow-list of hostnames and CIDR ranges."""
    if not spec:
        return EMPTY_ALLOWLIST
    hosts: set[str] = set()
    networks: list[IPNetwork] = []
    for raw in spec.split(","):
        entry = raw.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            hosts.add(entry.lower())
    return Allowlist(hostnames=frozenset(hosts), networks=tuple(networks))


def unwrap_ipv4_mapped(address: IPAddress) -> IPAddress:
    """Return the embedded IPv4 address of an IPv4-mapped IPv6, or ``address`` unchanged."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_address_refused(address: IPAddress) -> bool:
    """True if ``address`` sits in any of the refused ranges."""
    address = unwrap_ipv4_mapped(address)
    if isinstance(address, ipaddress.IPv4Address):
        return any(address in net for net in _REFUSED_V4)
    return any(address in net for net in _REFUSED_V6)


def resolve_hostname(hostname: str) -> list[IPAddress]:
    """Return every address the resolver returns for ``hostname``.

    A literal IP address is returned unchanged in a single-element list.
    Raises ``AddressNotAllowedError`` if the hostname cannot be resolved -- the
    delivery caller cannot proceed without an address, and this is the message
    the receiver sees.
    """
    hostname = hostname.strip()
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AddressNotAllowedError(str(exc)) from exc
    seen: set[IPAddress] = set()
    addresses: list[IPAddress] = []
    for _family, _type, _proto, _canonname, sockaddr in results:
        raw = sockaddr[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if address not in seen:
            seen.add(address)
            addresses.append(address)
    if not addresses:
        # The resolver answered, but nothing in the answer parsed as an address.
        # Returning an empty list would let the caller proceed having verified
        # nothing, so this is a refusal like an unresolvable name.
        raise AddressNotAllowedError(f"No usable address for host {hostname}.")
    return addresses


def resolve_and_verify(hostname: str, allowlist: Allowlist = EMPTY_ALLOWLIST) -> list[IPAddress]:
    """Resolve ``hostname`` and refuse if any returned address is in a reserved range.

    The allow-list bypasses the refusal on a per-hostname or per-CIDR basis. A
    hostname that admits at all bypasses the address check entirely; a CIDR entry
    admits addresses contained in that network. ``AddressNotAllowedError`` is
    raised on any refusal or on DNS failure so the caller can map to a stable
    user-facing message.
    """
    if allowlist.admits_hostname(hostname):
        return resolve_hostname(hostname)
    addresses = resolve_hostname(hostname)
    for address in addresses:
        if is_address_refused(address) and not allowlist.admits_address(unwrap_ipv4_mapped(address)):
            raise AddressNotAllowedError(
                f"Address {address} for host {hostname} is in a refused range."
            )
    return addresses
