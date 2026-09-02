"""HTTP delivery for webhook notification destinations.

The delivery path resolves the destination hostname, refuses it via ``http_guard`` if
any resolved address sits in a reserved range, builds the per-webhook-type payload,
and posts. Retries are bounded and cover only failures where the receiver cannot
have processed the message: HTTP 429/5xx and connect errors. A 4xx response is
permanent, and a read error may follow a request the receiver already acted on --
neither is retried, because a repost would duplicate the notification on a
receiver that creates records.

Guarantees the delivery caller can rely on:

- Redirects are not followed. A permitted host that answers with a redirect to a
  reserved-range URL would bypass the address check otherwise.
- Certificate verification is always on. There is no setting to turn it off;
  private CAs are served by the CA bundle the HTTP client reads from the
  environment (``REQUESTS_CA_BUNDLE`` / ``SSL_CERT_FILE``).
- The URL is never logged in full and the authorization header value is never
  logged; a receiver that gains the URL through a log leak can post to the
  channel.
- Delivery cannot block its caller for an unbounded time. The socket timeouts
  bound each attempt and the retry backoff is the only sleep on the path, so a
  receiver cannot hold a job subprocess or the Streamlit script-runner thread
  open by stalling or by asking for a long delay.
- Failed deliveries raise ``WebhookDeliveryError`` for the caller to swallow.
  The wrapping notification handlers already decorate with
  ``@log_and_swallow_exception`` so a failing rule cannot fail its run.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.util.retry import Retry

from testgen import settings
from testgen.common.models.notification_destinations import WebhookDestination
from testgen.common.notifications import http_guard, messages
from testgen.common.notifications.webhook_payload import build_envelope, retarget_url_source, wrap_for

LOG = logging.getLogger("testgen")

# Read timeout matters more than connect for the "notification held the job open"
# failure mode; a slow receiver must not delay the job callback indefinitely.
CONNECT_TIMEOUT_SECONDS = 3
READ_TIMEOUT_SECONDS = 5
DEFAULT_TIMEOUT: tuple[float, float] = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)

# Response body cap: 8 KB is enough to identify the receiver's error message but
# small enough that a hostile server cannot exhaust memory by claiming a huge body.
MAX_RESPONSE_BODY_BYTES = 8 * 1024

# Retry policy scoped to webhook posts. Explicit ``allowed_methods=["POST"]``
# overrides urllib3's default (which excludes POST) so 429/5xx do retry, while
# 4xx (documented as never retried) still won't -- Retry only acts on the codes
# in status_forcelist.
_RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
_RETRY_ATTEMPTS = 2
# urllib3 sleeps ``backoff_factor * 2 ** (n - 1)`` before retry n and skips the
# sleep entirely on the first, so this factor with ``_RETRY_ATTEMPTS`` bounds the
# total time spent sleeping on a delivery at two seconds.
_RETRY_BACKOFF_FACTOR = 1.0


class WebhookDeliveryError(Exception):
    """Raised on any delivery failure: address refused, network, non-2xx, malformed."""


@dataclass
class DeliveryResult:
    """What Send Test surfaces: HTTP status + timing + a short response snippet."""

    status_code: int
    elapsed_ms: int
    body_snippet: str


def deliver_webhook(destination: WebhookDestination, context: dict, template) -> DeliveryResult:
    """Deliver ``destination``'s webhook for the event carried in ``context``.

    ``template`` is the email template class the rule would otherwise render; it
    holds the ``event_type`` label and the ``webhook_summary`` / ``webhook_data``
    accessors so the payload extracts safe plain values from the same ORM-shaped
    context email templates use. On failure raises ``WebhookDeliveryError`` for
    the notification handler to log and swallow.
    """
    envelope = build_envelope(
        event_type=getattr(template, "event_type", "unknown") or "unknown",
        trigger=(context or {}).get("notification_trigger") or None,
        project_code=destination.project_code,
        project_name=template.webhook_project_name(context) if hasattr(template, "webhook_project_name") else None,
        summary=template.webhook_summary(context) if hasattr(template, "webhook_summary") else "",
        url=retarget_url_source(
            template.webhook_summary_url(context) if hasattr(template, "webhook_summary_url") else None,
            destination.webhook_type_safe,
        ),
        data=template.webhook_data(context) if hasattr(template, "webhook_data") else {},
    )
    return _post(destination, envelope, event_type=envelope["event"])


def deliver_test_payload(destination: WebhookDestination) -> DeliveryResult:
    """Send a documented ``event="test"`` payload so the user can prove connectivity.

    Used by the Send Test action in the destination dialog. Reads no rule state.
    """
    envelope = build_envelope(
        event_type="test",
        trigger=None,
        project_code=destination.project_code,
        project_name=None,
        summary="Test notification from TestGen",
        url=None,
        data={},
    )
    return _post(destination, envelope, event_type="test")


def _canonical_connect_target(url: str) -> tuple[str, str]:
    """Return the URL to post and the hostname the socket will resolve for it.

    Both come from ``PreparedRequest.prepare_url``, which is what requests runs
    before connecting. It IDNA-encodes the hostname, so reading the host off the
    raw URL instead yields the Unicode form for a non-ASCII host
    (``bücher.example.com``) while the socket resolves the punycode form
    (``xn--bcher-kva.example.com``). Checking and pinning a name that never gets
    looked up would check an address nobody contacts, so the guard reads the host
    from here. ``connect_url`` is what the caller posts: requests prepares the URL
    again regardless, so passing it changes nothing at the socket -- it keeps one
    spelling at the call site.

    Raises ``WebhookDeliveryError`` if the URL cannot be prepared.
    """
    try:
        prepared = requests.models.PreparedRequest()
        prepared.prepare_url(url, None)
        connect_url = prepared.url or ""
        # ``parse_url`` keeps the brackets on an IPv6 literal; ``http_guard``
        # wants the bare address.
        hostname = (urllib3.util.parse_url(connect_url).host or "").strip("[]")
    except (requests.RequestException, urllib3.exceptions.HTTPError, UnicodeError, ValueError) as exc:
        raise WebhookDeliveryError(messages.WEBHOOK_URL_INVALID) from exc
    return connect_url, hostname


def _post(destination: WebhookDestination, envelope: dict, *, event_type: str) -> DeliveryResult:
    url = destination.url
    if not url:
        raise WebhookDeliveryError(messages.WEBHOOK_URL_REQUIRED)

    connect_url, hostname = _canonical_connect_target(url)
    allowlist = http_guard.parse_allowlist(getattr(settings, "WEBHOOK_ALLOWED_HOSTS", None))
    try:
        verified_addresses = http_guard.resolve_and_verify(hostname, allowlist)
    except http_guard.AddressNotAllowedError as exc:
        _log_failure(destination, event_type, envelope["delivery_id"], f"address refused: {exc}")
        raise WebhookDeliveryError(messages.WEBHOOK_URL_ADDRESS_REFUSED) from exc

    body = wrap_for(destination, envelope)
    # Order matters: seed with the caller-configured authorization header first,
    # then overwrite with the built-in headers. Validation rejects reserved names
    # (``Content-Type`` / ``Host`` / ``Transfer-Encoding`` / any ``X-TestGen-*``)
    # at save/send-test time, but writing the built-ins last means the transport
    # is self-defending: a stored row that predates the denylist, or any future
    # bypass, cannot override the event tag a receiver may route on.
    headers: dict[str, str] = {}
    header_name = destination.auth_header_name
    header_value = destination.auth_header_value
    if header_name and header_value:
        headers[header_name] = header_value
    headers["Content-Type"] = "application/json"
    headers["X-TestGen-Delivery-Id"] = envelope["delivery_id"]
    headers["X-TestGen-Event"] = event_type

    # The session connects only to ``verified_addresses``; see ``_PinnedHTTPAdapter``.
    session = _make_session(verified_addresses)
    try:
        # Wrap the POST in ``with`` so the streamed response is released back to
        # the connection pool immediately -- ``stream=True`` otherwise defers the
        # release until GC and leaks sockets under sustained delivery load.
        with _suppress_delivery_url_logging(), session.post(
            connect_url,
            json=body,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=False,
            verify=True,
            # stream=True so ``_read_body_snippet`` can enforce the cap by reading
            # a bounded prefix of the response instead of eagerly consuming the
            # whole body into memory when a receiver returns a huge payload.
            stream=True,
        ) as response:
            body_snippet = _read_body_snippet(response)
            elapsed_ms = int(response.elapsed.total_seconds() * 1000)
            status_code = response.status_code
    except requests.RequestException as exc:
        _log_failure(destination, event_type, envelope["delivery_id"], f"transport error: {type(exc).__name__}")
        # ``str(exc)`` from requests can carry the full URL, including the credential
        # portion of a Slack/Teams webhook. Surface only the exception class so a
        # handler that echoes the raised message to the UI or a log cannot leak it.
        # ``from None`` drops the cause deliberately: the handlers log with
        # ``LOG.exception``, which formats the chained urllib3 error and would put
        # that URL in the log despite the sanitized message. ``_log_failure`` above
        # has already emitted the diagnostic this needs.
        raise WebhookDeliveryError(f"Delivery failed: {type(exc).__name__}") from None

    if 200 <= status_code < 300:
        LOG.info(
            "Webhook delivered (destination=%s [%s], event=%s, delivery=%s, status=%s, elapsed=%sms)",
            destination.name, destination.webhook_type_safe,
            event_type, envelope["delivery_id"], status_code, elapsed_ms,
        )
        return DeliveryResult(status_code, elapsed_ms, body_snippet)

    _log_failure(
        destination, event_type, envelope["delivery_id"],
        f"HTTP {status_code} in {elapsed_ms}ms",
    )
    # ``body_snippet`` is bounded but a well-known receiver (Slack, Teams) echoes
    # the posted URL in its 4xx response. The exception message is surfaced to
    # any caller that catches ``WebhookDeliveryError`` -- callers that need the
    # body for diagnostics can access ``DeliveryResult`` directly on success.
    raise WebhookDeliveryError(f"HTTP {status_code}")


def _make_session(verified_addresses: list) -> requests.Session:
    """A session that connects only to ``verified_addresses``, with a bounded POST retry."""
    session = requests.Session()
    retry = Retry(
        total=_RETRY_ATTEMPTS,
        status_forcelist=_RETRY_STATUS_CODES,
        allowed_methods=frozenset(["POST"]),
        backoff_factor=_RETRY_BACKOFF_FACTOR,
        # A receiver's ``Retry-After`` is ignored, so the backoff above is the
        # only sleep on the delivery path. Honouring the header would let a
        # receiver name its own delay: urllib3 sleeps for it directly, capped
        # only by ``Retry.retry_after_max`` (six hours by default), which the
        # socket timeouts do not bound because they bound reads, not sleeps.
        respect_retry_after_header=False,
        # Retry connect failures -- the request never reached the receiver, so a
        # repost cannot duplicate. Never retry read failures: the receiver may
        # already have processed the request that timed out on the way back.
        connect=_RETRY_ATTEMPTS,
        read=0,
        raise_on_status=False,
    )
    session.mount("https://", _PinnedHTTPAdapter(verified_addresses, max_retries=retry))
    return session


# The delivery session connects only to addresses ``http_guard`` already verified.
# Pinning at the adapter rather than by replacing ``socket.getaddrinfo`` keeps the
# mechanism local to one request: there is no process-global binding that another
# import can displace, and no hostname string that has to match what the HTTP
# client happens to resolve. ``_dns_host`` is the only field urllib3 resolves;
# ``host`` -- which drives the Host header, SNI and certificate matching -- is
# derived separately, so moving the socket target leaves TLS verification intact.
def _pinned_connection_cls(addresses: list[str]):
    class _PinnedHTTPSConnection(HTTPSConnection):
        def _new_conn(self):
            if self.proxy is not None or self._tunnel_host is not None:
                # The socket goes to the proxy and the proxy resolves the
                # destination, so no address this side verified is the one
                # contacted. Refuse rather than deliver unverified.
                raise WebhookDeliveryError(messages.WEBHOOK_PROXY_UNVERIFIABLE)
            original = self._dns_host
            last_error: BaseException | None = None
            for address in addresses:
                self._dns_host = address
                try:
                    return super()._new_conn()
                except Exception as exc:
                    last_error = exc
                finally:
                    self._dns_host = original
            raise last_error  # type: ignore[misc]

    return _PinnedHTTPSConnection


class _PinnedHTTPAdapter(HTTPAdapter):
    """Connects only to ``addresses``; Host header, SNI and cert matching stay on the hostname."""

    def __init__(self, addresses: list, **kwargs):
        if not addresses:
            # An empty verified set must not degrade into "resolve freely".
            raise WebhookDeliveryError(messages.WEBHOOK_URL_ADDRESS_REFUSED)
        self._pinned_addresses = [str(address) for address in addresses]
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        super().init_poolmanager(connections, maxsize, block, **pool_kwargs)
        pool_cls = type(
            "_PinnedHTTPSConnectionPool",
            (HTTPSConnectionPool,),
            {"ConnectionCls": _pinned_connection_cls(self._pinned_addresses)},
        )
        self.poolmanager.pool_classes_by_scheme = {
            **self.poolmanager.pool_classes_by_scheme,
            "https": pool_cls,
        }

    def proxy_manager_for(self, proxy, **proxy_kwargs):  # noqa: ARG002 -- signature fixed by requests
        raise WebhookDeliveryError(messages.WEBHOOK_PROXY_UNVERIFIABLE)


# Marks the delivering thread so ``_DeliveryUrlLogFilter`` can drop urllib3 records
# that carry the request path.
_delivery_local = threading.local()


class _DeliveryUrlLogFilter(logging.Filter):
    """Drop ``urllib3.connectionpool`` records emitted while this thread delivers.

    urllib3 logs the request path on every retry, and for a Slack or Teams
    destination that path is the credential itself. The filter is scoped to the
    delivering thread so urllib3 logging elsewhere in the process is untouched;
    the delivery's own diagnostic comes from ``_log_failure``.
    """

    def filter(self, _record: logging.LogRecord) -> bool:
        # Every record from this logger is dropped while the thread delivers; the
        # record's content is not consulted.
        return not getattr(_delivery_local, "delivering", False)


# urllib3 loggers that put the request path in a record. A filter on a logger does
# not apply to its children, so each emitter is named rather than filtering the
# ``urllib3`` parent: ``connectionpool`` logs the path on a retry warning and
# ``util.retry`` logs it again at debug level.
_URL_LOGGING_SOURCES = ("urllib3.connectionpool", "urllib3.util.retry")

for _source in _URL_LOGGING_SOURCES:
    _source_logger = logging.getLogger(_source)
    if not any(isinstance(existing, _DeliveryUrlLogFilter) for existing in _source_logger.filters):
        _source_logger.addFilter(_DeliveryUrlLogFilter())


@contextmanager
def _suppress_delivery_url_logging():
    """Mark this thread as delivering, so ``_DeliveryUrlLogFilter`` drops urllib3 records."""
    previous = getattr(_delivery_local, "delivering", False)
    _delivery_local.delivering = True
    try:
        yield
    finally:
        _delivery_local.delivering = previous


def _read_body_snippet(response: requests.Response) -> str:
    """Read at most ``MAX_RESPONSE_BODY_BYTES`` from the response body and decode.

    Content-Length is advisory and cannot be trusted; requires ``stream=True`` on
    the request so the underlying stream is not eagerly consumed. Anything past
    the cap is dropped without allocation -- a hostile receiver returning a huge
    payload cannot exhaust worker memory.
    """
    try:
        raw = response.raw.read(MAX_RESPONSE_BODY_BYTES, decode_content=True) or b""
    except Exception:
        raw = response.content[:MAX_RESPONSE_BODY_BYTES] if response.content else b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    return raw.decode(response.encoding or "utf-8", errors="replace")


def _log_failure(destination: WebhookDestination, event_type: str, delivery_id: str, detail: str) -> None:
    parsed = urlparse(destination.url or "")
    LOG.warning(
        "Webhook delivery failed (destination=%s [%s], host=%s, event=%s, delivery=%s): %s",
        destination.name, destination.webhook_type_safe, parsed.hostname or "",
        event_type, delivery_id, detail,
    )
