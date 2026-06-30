import atexit
import functools
import json
import logging
import queue
import ssl
import threading
import time
import uuid
from base64 import b64encode
from functools import cached_property, wraps
from hashlib import blake2b
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from testgen import settings
from testgen.common.models import with_database_session
from testgen.common.models.settings import PersistedSetting, SettingNotFound
from testgen.ui.services.database_service import fetch_one_from_db
from testgen.ui.session import session
from testgen.utils.singleton import Singleton

LOG = logging.getLogger("testgen")

_BATCH_SIZE = 50           # Mixpanel /track array cap
_FLUSH_INTERVAL_SEC = 10   # Time-based flush
_QUEUE_MAX_SIZE = 1000     # Memory cap before drop-on-overflow
_DRAIN_TIMEOUT_SEC = 5     # Bounded shutdown drain

_SHUTDOWN = object()       # sentinel enqueued by drain() to stop the worker


def safe_method(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        if settings.ANALYTICS_ENABLED:
            try:
                method(*args, **kwargs)
            except Exception:
                LOG.exception("Error processing analytics data")

    return wrapped


class MixpanelService(Singleton):

    def __init__(self) -> None:
        self._queue: queue.Queue | None = None
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._started = False
        self._stopped = False
        atexit.register(self.drain)

    @cached_property
    @with_database_session
    def instance_id(self):
        try:
            instance_id = PersistedSetting.get("INSTANCE_ID")
        except SettingNotFound:
            instance_id = settings.INSTANCE_ID or blake2b(uuid.getnode().to_bytes(8), digest_size=8).hexdigest()
            PersistedSetting.set("INSTANCE_ID", instance_id)
        return instance_id

    def get_distinct_id(self, username):
        return self._hash_value(username or "")

    @functools.cache  # noqa: B019
    def _hash_value(self, value: bytes | str, digest_size: int = 8) -> str:
        if isinstance(value, str):
            value = value.encode()
        return blake2b(value, salt=self.instance_id.encode(), digest_size=digest_size).hexdigest()

    @safe_method
    def send_event(self, event_name, include_usage=False, **properties):
        self._enqueue(self._build_event(event_name, include_usage=include_usage, **properties))

    def send_feedback(self, **properties):
        # User-submitted feedback is content the user explicitly chose to share,
        # so it is not gated by the TG_ANALYTICS opt-out. It is a foreground action
        # posted synchronously — never enqueued — so it never starts the worker.
        try:
            self.send_mp_request("track?ip=1", self._build_event("feedback", **properties))
        except Exception:
            LOG.exception("Error sending feedback")

    def _build_event(self, event_name, include_usage=False, **properties) -> dict:
        properties.setdefault("instance_id", self.instance_id)
        properties.setdefault("edition", settings.DOCKER_HUB_REPOSITORY)
        properties.setdefault("version", settings.VERSION)
        properties.setdefault("username", session.auth.user_display if session.auth else None)
        properties.setdefault("distinct_id", self.get_distinct_id(properties["username"]))
        properties.setdefault("time", int(time.time()))
        if include_usage:
            properties.update(self.get_usage())

        return {
            "event": event_name,
            "properties": {
                "token": settings.MIXPANEL_TOKEN,
                **properties,
            },
        }

    def _ensure_worker(self) -> None:
        if self._started:
            return
        with self._worker_lock:
            if self._started:
                return
            self._queue = queue.Queue(maxsize=_QUEUE_MAX_SIZE)
            self._worker = threading.Thread(target=self._worker_loop, name="mixpanel-flush", daemon=True)
            self._worker.start()
            self._started = True

    def _enqueue(self, event: dict) -> None:
        if self._stopped:
            LOG.warning("analytics worker stopped; dropping event")
            return
        self._ensure_worker()
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            LOG.warning("analytics queue full; dropping event")

    def _worker_loop(self) -> None:
        while True:
            batch, stop = self._next_batch()
            if batch:
                self._flush(batch)
            if stop:
                return

    def _next_batch(self) -> tuple[list[dict], bool]:
        """Block up to _FLUSH_INTERVAL_SEC for the first event, then drain up to
        _BATCH_SIZE without blocking. Returns (batch, stop)."""
        try:
            first = self._queue.get(timeout=_FLUSH_INTERVAL_SEC)
        except queue.Empty:
            return [], False
        if first is _SHUTDOWN:
            return [], True
        batch = [first]
        while len(batch) < _BATCH_SIZE:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            if event is _SHUTDOWN:
                return batch, True
            batch.append(event)
        return batch, False

    def _flush(self, events: list[dict]) -> None:
        for start in range(0, len(events), _BATCH_SIZE):
            chunk = events[start:start + _BATCH_SIZE]
            try:
                self.send_mp_request("track?ip=1", chunk)
            except Exception:
                LOG.exception("Failed to flush analytics batch")

    def drain(self) -> None:
        """Flush queued events and stop the worker. Idempotent; bounded by
        _DRAIN_TIMEOUT_SEC. Called by the atexit hook and the server lifespan."""
        if not self._started or self._stopped:
            return
        self._stopped = True
        try:
            self._queue.put_nowait(_SHUTDOWN)
        except queue.Full:
            LOG.warning("analytics queue full at shutdown; in-flight events may be dropped")
        if self._worker is not None:
            self._worker.join(timeout=_DRAIN_TIMEOUT_SEC)
            if self._worker.is_alive():
                LOG.warning("analytics drain timed out after %ss", _DRAIN_TIMEOUT_SEC)

    def get_ssl_context(self):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def send_mp_request(self, endpoint, payload):
        try:
            post_data = urlencode(
                {"data": b64encode(json.dumps(payload).encode()).decode()}
            ).encode()

            req = Request(f"{settings.MIXPANEL_URL}/{endpoint}", data=post_data, method="POST")  # noqa: S310
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

            urlopen(req, context=self.get_ssl_context(), timeout=settings.MIXPANEL_TIMEOUT)  # noqa: S310
        except Exception:
            LOG.exception("Failed to send analytics data")

    @with_database_session
    def get_usage(self):
        query = """
        SELECT
            (SELECT COUNT(*) FROM auth_users) AS user_count,
            (SELECT COUNT(*) FROM projects) AS project_count,
            (SELECT COUNT(*) FROM connections) AS connection_count,
            (SELECT COUNT(*) FROM table_groups) AS table_group_count,
            (SELECT COUNT(*) FROM test_suites) AS test_suite_count;
        """
        return fetch_one_from_db(query)
