import functools
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
from testgen.common.models import with_database_session
from testgen.common.models.settings import PersistedSetting, SettingNotFound
from testgen.ui.services.database_service import fetch_one_from_db
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
        properties.setdefault("instance_id", self.instance_id)
        properties.setdefault("edition", settings.DOCKER_HUB_REPOSITORY)
        properties.setdefault("version", settings.VERSION)
        properties.setdefault("username", session.username)
        properties.setdefault("distinct_id", self.get_distinct_id(properties["username"]))
        if include_usage:
            properties.update(self.get_usage())

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
