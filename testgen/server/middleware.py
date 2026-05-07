"""ASGI middlewares for the combined FastAPI + MCP server.

These are pure-ASGI implementations (not BaseHTTPMiddleware) to avoid buffering
responses, which would break MCP's text/event-stream transport.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_413_BODY = b'{"detail":"Request body too large"}'


async def _send_413(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_413_BODY)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _413_BODY})


class BodySizeLimitMiddleware:
    """Reject requests whose body exceeds *max_bytes* with HTTP 413.

    Checks Content-Length up front when present; otherwise tracks accumulated
    body bytes and disconnects when the limit is exceeded mid-stream. Only
    inspects http.request messages, so MCP SSE response streams pass through
    untouched.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        content_length = next(
            (v for k, v in scope.get("headers", []) if k == b"content-length"), None
        )
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await _send_413(send)
                    return
            except ValueError:
                pass

        received = 0
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, limited_receive, send)


class SecurityHeadersMiddleware:
    """Inject standard security headers on every HTTP response.

    Headers are added to http.response.start, so they apply uniformly to success
    and error responses. Existing headers (case-insensitive match) are preserved,
    letting per-route handlers override defaults.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        hsts: str | None,
        csp: str,
        referrer: str,
        nosniff: bool,
    ) -> None:
        self.app = app
        self.headers: list[tuple[bytes, bytes]] = []
        if hsts:
            self.headers.append((b"strict-transport-security", hsts.encode()))
        if nosniff:
            self.headers.append((b"x-content-type-options", b"nosniff"))
        if referrer:
            self.headers.append((b"referrer-policy", referrer.encode()))
        if csp:
            self.headers.append((b"content-security-policy", csp.encode()))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                for name, value in self.headers:
                    if name not in existing:
                        message["headers"].append((name, value))
            await send(message)

        await self.app(scope, receive, send_wrapper)
