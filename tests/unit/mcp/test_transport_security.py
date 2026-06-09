"""Tests for testgen.mcp.server._build_transport_security — DNS rebinding allowlist builder."""

from unittest.mock import patch

from testgen.mcp.server import _build_transport_security


def _build_with(base_url: str, extras: list[str] | None = None):
    with (
        patch("testgen.mcp.server.settings.BASE_URL", base_url),
        patch("testgen.mcp.server.settings.MCP_EXTRA_ALLOWED_HOSTS", extras or []),
    ):
        return _build_transport_security()


def test_loopback_and_base_url_always_present():
    """With no extras, the allowlist is BASE_URL hosts + loopback variants."""
    settings = _build_with("http://tg.example.com:8530")

    assert settings.enable_dns_rebinding_protection is True
    assert "tg.example.com:8530" in settings.allowed_hosts
    assert "tg.example.com:*" in settings.allowed_hosts
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "localhost:*" in settings.allowed_hosts
    assert "[::1]:*" in settings.allowed_hosts

    assert "http://tg.example.com:8530" in settings.allowed_origins
    # Loopback origins covered for both schemes
    assert "http://localhost:*" in settings.allowed_origins
    assert "https://localhost:*" in settings.allowed_origins


def test_extra_host_without_port_gets_wildcard_and_bare():
    """An extras entry without `:` is allowed both with a `:*` port wildcard and bare.

    The bare (port-less) form is required because some MCP gateways (e.g. Databricks)
    send an Origin with no port, which the `:*` wildcard does not match.
    """
    settings = _build_with("http://localhost:8530", extras=["tg.example.com"])

    assert "tg.example.com:*" in settings.allowed_hosts
    assert "tg.example.com" in settings.allowed_hosts
    assert "http://tg.example.com:*" in settings.allowed_origins
    assert "https://tg.example.com:*" in settings.allowed_origins
    assert "http://tg.example.com" in settings.allowed_origins
    assert "https://tg.example.com" in settings.allowed_origins


def test_extra_host_with_explicit_port_preserved_literally():
    """An extras entry with an explicit port is kept as-is, no wildcard appended."""
    settings = _build_with("http://localhost:8530", extras=["tg.example.com:8080"])

    assert "tg.example.com:8080" in settings.allowed_hosts
    assert "tg.example.com:8080:*" not in settings.allowed_hosts  # no double-port

    assert "http://tg.example.com:8080" in settings.allowed_origins
    assert "https://tg.example.com:8080" in settings.allowed_origins


def test_extra_host_with_explicit_wildcard_preserved():
    """An extras entry with `:*` is kept as-is."""
    settings = _build_with("http://localhost:8530", extras=["tg.example.com:*"])

    assert "tg.example.com:*" in settings.allowed_hosts
    assert "http://tg.example.com:*" in settings.allowed_origins


def test_mixed_extras():
    """Multiple extras with different shapes are all handled correctly."""
    settings = _build_with(
        "http://localhost:8530",
        extras=["foo.com", "bar.io:9000", "baz.net:*"],
    )

    assert "foo.com:*" in settings.allowed_hosts
    assert "bar.io:9000" in settings.allowed_hosts
    assert "baz.net:*" in settings.allowed_hosts


def test_https_base_url_origin_uses_https_scheme():
    """Origin scheme tracks BASE_URL's scheme."""
    settings = _build_with("https://tg.example.com")

    assert "https://tg.example.com" in settings.allowed_origins


def test_results_are_sorted_lists():
    """allowed_hosts and allowed_origins are deterministic (sorted) for stable diffs."""
    settings = _build_with("http://localhost:8530", extras=["zeta.com", "alpha.com"])

    assert settings.allowed_hosts == sorted(settings.allowed_hosts)
    assert settings.allowed_origins == sorted(settings.allowed_origins)
