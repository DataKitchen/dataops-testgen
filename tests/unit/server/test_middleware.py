"""Tests for testgen.server.middleware — pure-ASGI body cap and security headers."""

# ASGI test stubs (receive/send/inner-app) must be async per protocol but don't
# await anything in these tests. RUF029 is a false positive for that pattern.
# ruff: noqa: RUF029

import asyncio
import json

from testgen.server.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware


def _http_scope(method: str = "POST", headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {"type": "http", "method": method, "headers": headers or []}


# -------------------------- BodySizeLimitMiddleware --------------------------


def test_body_cap_content_length_over_limit_rejects_immediately():
    """Content-Length > max_bytes → 413 sent without invoking the inner app."""
    inner_called = False

    async def inner(scope, receive, send):
        nonlocal inner_called
        inner_called = True

    mw = BodySizeLimitMiddleware(inner, max_bytes=1024)
    scope = _http_scope(headers=[(b"content-length", b"2048")])

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    assert not inner_called
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"]) == {"detail": "Request body too large"}


def test_body_cap_content_length_under_limit_passes_through():
    """Content-Length under the limit → inner app runs normally."""
    received_by_inner: list[dict] = []

    async def inner(scope, receive, send):
        received_by_inner.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})

    mw = BodySizeLimitMiddleware(inner, max_bytes=1024)
    scope = _http_scope(headers=[(b"content-length", b"100")])

    queued = [{"type": "http.request", "body": b"x" * 100, "more_body": False}]
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return queued.pop(0) if queued else {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    assert received_by_inner[0]["body"] == b"x" * 100
    assert sent[0]["status"] == 200


def test_body_cap_streaming_disconnects_when_exceeded():
    """Without Content-Length, accumulating body chunks past the limit returns disconnect."""
    received_by_inner: list[dict] = []

    async def inner(scope, receive, send):
        # Drain three chunks: third one pushes past the limit
        for _ in range(3):
            received_by_inner.append(await receive())

    mw = BodySizeLimitMiddleware(inner, max_bytes=150)
    scope = _http_scope(headers=[])

    queued = [
        {"type": "http.request", "body": b"x" * 100, "more_body": True},
        {"type": "http.request", "body": b"y" * 100, "more_body": True},
        {"type": "http.request", "body": b"z" * 100, "more_body": False},
    ]

    async def send(msg):
        pass

    async def receive():
        return queued.pop(0) if queued else {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    # First chunk passes (100 bytes < 150). Second chunk pushes total to 200, exceeds, returns disconnect.
    assert received_by_inner[0]["body"] == b"x" * 100
    assert received_by_inner[1]["type"] == "http.disconnect"


def test_body_cap_latch_holds_across_repeated_receives():
    """Regression: once exceeded, every subsequent receive() returns disconnect.

    Without the latch, an inner app that drains receive() multiple times after
    seeing http.disconnect could read more body bytes from the underlying socket,
    bypassing the cap.
    """
    received_by_inner: list[dict] = []

    async def inner(scope, receive, send):
        # Drain 5 times, well past the disconnect
        for _ in range(5):
            received_by_inner.append(await receive())

    mw = BodySizeLimitMiddleware(inner, max_bytes=50)
    scope = _http_scope(headers=[])

    queued = [
        {"type": "http.request", "body": b"x" * 100, "more_body": True},  # exceeds immediately
        {"type": "http.request", "body": b"y" * 100, "more_body": True},  # would exceed again if reached
        {"type": "http.request", "body": b"z" * 100, "more_body": False},
    ]

    async def send(msg):
        pass

    async def receive():
        return queued.pop(0) if queued else {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    # First call: real chunk (100 bytes), exceeds → returns disconnect
    assert received_by_inner[0]["type"] == "http.disconnect"
    # Subsequent calls: latch keeps returning disconnect, never forwards real chunks
    for msg in received_by_inner[1:]:
        assert msg["type"] == "http.disconnect"


def test_body_cap_get_request_bypasses():
    """GET requests skip the cap — no body to inspect."""
    received_by_inner: list[dict] = []

    async def inner(scope, receive, send):
        received_by_inner.append("called")

    mw = BodySizeLimitMiddleware(inner, max_bytes=100)
    scope = _http_scope(method="GET", headers=[(b"content-length", b"99999")])

    async def send(msg):
        pass

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    assert received_by_inner == ["called"]  # inner ran despite huge Content-Length


def test_body_cap_non_http_scope_passes_through():
    """Lifespan/websocket scopes bypass entirely."""
    inner_called = False

    async def inner(scope, receive, send):
        nonlocal inner_called
        inner_called = True

    mw = BodySizeLimitMiddleware(inner, max_bytes=10)
    scope = {"type": "lifespan"}

    async def send(msg):
        pass

    async def receive():
        return {"type": "lifespan.shutdown"}

    asyncio.run(mw(scope, receive, send))

    assert inner_called


def test_body_cap_malformed_content_length_falls_through_to_streaming():
    """Non-numeric Content-Length doesn't crash; streaming guard still applies."""
    received_by_inner: list[dict] = []

    async def inner(scope, receive, send):
        received_by_inner.append(await receive())

    mw = BodySizeLimitMiddleware(inner, max_bytes=50)
    scope = _http_scope(headers=[(b"content-length", b"not-a-number")])

    queued = [{"type": "http.request", "body": b"x" * 100, "more_body": False}]

    async def send(msg):
        pass

    async def receive():
        return queued.pop(0) if queued else {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    # Streaming guard catches the oversized body
    assert received_by_inner[0]["type"] == "http.disconnect"


# -------------------------- SecurityHeadersMiddleware --------------------------


def test_security_headers_added_to_response_start():
    """All configured headers are injected on http.response.start."""
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = SecurityHeadersMiddleware(
        inner,
        hsts="max-age=63072000",
        csp="frame-ancestors 'none'",
        referrer="no-referrer",
        nosniff=True,
    )
    scope = _http_scope(method="GET")
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    headers = dict(sent[0]["headers"])
    assert headers[b"strict-transport-security"] == b"max-age=63072000"
    assert headers[b"content-security-policy"] == b"frame-ancestors 'none'"
    assert headers[b"referrer-policy"] == b"no-referrer"
    assert headers[b"x-content-type-options"] == b"nosniff"


def test_security_headers_preserve_handler_set_value():
    """If the handler already sets CSP, the middleware does not override it.

    Case-insensitive: handler-set 'Content-Security-Policy' wins over middleware's lowercase form.
    """
    async def inner(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"Content-Security-Policy", b"default-src 'self'")],
        })

    mw = SecurityHeadersMiddleware(
        inner,
        hsts=None,
        csp="frame-ancestors 'none'",
        referrer="no-referrer",
        nosniff=True,
    )
    scope = _http_scope(method="GET")
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    csp_values = [v for k, v in sent[0]["headers"] if k.lower() == b"content-security-policy"]
    assert csp_values == [b"default-src 'self'"]


def test_security_headers_skip_hsts_when_none():
    """hsts=None → no HSTS header emitted (the API_TLS_ENABLED=False default path)."""
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    mw = SecurityHeadersMiddleware(
        inner, hsts=None, csp="frame-ancestors 'none'", referrer="no-referrer", nosniff=True,
    )
    scope = _http_scope(method="GET")
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(mw(scope, receive, send))

    header_names = {k.lower() for k, _ in sent[0]["headers"]}
    assert b"strict-transport-security" not in header_names


def test_security_headers_non_http_scope_passes_through():
    """Lifespan and other non-http scopes are unmodified."""
    inner_called = False

    async def inner(scope, receive, send):
        nonlocal inner_called
        inner_called = True

    mw = SecurityHeadersMiddleware(
        inner, hsts=None, csp="frame-ancestors 'none'", referrer="no-referrer", nosniff=True,
    )

    async def send(msg):
        pass

    async def receive():
        return {"type": "lifespan.shutdown"}

    asyncio.run(mw({"type": "lifespan"}, receive, send))

    assert inner_called
