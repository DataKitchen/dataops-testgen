import json
import logging
import ssl
import uuid
from base64 import b64encode
from functools import cached_property, wraps
from hashlib import blake2b
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from testgen import settings
from testgen.ui.session import session
from testgen.utils.singleton import Singleton

LOG = logging.getLogger("testgen")


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

    @cached_property
    def instance_id(self):
        return settings.INSTANCE_ID or blake2b(uuid.getnode().to_bytes(8), digest_size=8).hexdigest()

    @cached_property
    def distinct_id(self):
        return self._hash_value(session.username)

    def _hash_value(self, value: bytes | str, digest_size: int = 8) -> str:
        if isinstance(value, str):
            value = value.encode()
        return blake2b(value, salt=self.instance_id.encode(), digest_size=digest_size).hexdigest()

    @safe_method
    def send_event(self, event_name, **properties):
        properties.setdefault("instance_id", self.instance_id)
        properties.setdefault("version", settings.VERSION)
        properties.setdefault("distinct_id", self.distinct_id)

        track_payload = {
            "event": event_name,
            "properties": {
                "token": settings.MIXPANEL_TOKEN,
                **properties,
            }
        }
        self.send_mp_request("track?ip=1", track_payload)

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
