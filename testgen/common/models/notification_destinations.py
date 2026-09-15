import re
from enum import StrEnum
from typing import ClassVar, Self
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, String, func, select
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import JSON_TYPE, SafeEncryptedJson
from testgen.common.models.entity import Entity
from testgen.common.models.notification_settings import (
    NotificationSettingsValidationError,
    is_valid_email,
)
from testgen.common.models.project import Project  # noqa: F401  (register table for FK resolution)
from testgen.common.notifications import messages

# Valid characters in an HTTP header field-name per RFC 7230 (token production).
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
# Reject any control character or leading whitespace in an authorization header
# value; these have been used as header-injection vectors on webhooks whose URLs
# passed validation but whose header values did not.
_HEADER_VALUE_FORBIDDEN = re.compile(r"[\r\n\0]")


class WebhookType(StrEnum):
    slack = "slack"
    microsoft_teams = "microsoft_teams"
    generic = "generic"


# Names the receiving service, for display alongside the destination type. ``generic`` is
# deliberately absent rather than an oversight: it names no service, so a generic webhook
# reads as plain "Webhook" instead of "Webhook | Generic". Adding an entry back changes what
# the destinations table and the notification dialogs show. "Generic" remains the label where
# the user is choosing a webhook type or reading one back as a stored field.
WEBHOOK_TYPE_LABELS: dict[WebhookType, str] = {
    WebhookType.slack: "Slack",
    WebhookType.microsoft_teams: "Microsoft Teams",
}

class DestinationType(StrEnum):
    email = "email"
    webhook = "webhook"


DESTINATION_TYPE_LABELS: dict[DestinationType, str] = {
    DestinationType.email: "Email",
    DestinationType.webhook: "Webhook",
}

# Every webhook type, for the surfaces where a user picks the type or reads back
# the one that is stored. ``WEBHOOK_TYPE_LABELS`` above names the receiving
# *service* and omits ``generic`` on purpose, so it cannot serve this.
WEBHOOK_TYPE_SELECTION_LABELS: dict[WebhookType, str] = {
    WebhookType.slack: "Slack",
    WebhookType.microsoft_teams: "Microsoft Teams",
    WebhookType.generic: "Generic",
}


class NotificationDestination(Entity):
    __tablename__ = "notification_destinations"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(
        String,
        ForeignKey("projects.project_code", ondelete="CASCADE"),
        nullable=False,
    )
    name: str = Column(String(100), nullable=False)
    destination_type: DestinationType = Column(String(20), nullable=False)
    config: JSON_TYPE = Column(postgresql.JSONB, nullable=False, default=dict)
    # ``SafeEncryptedJson`` returns ``None`` (and logs) on decrypt failure
    # instead of raising during row hydration. A single undecryptable row
    # (typically from a ``TG_DECRYPT_PASSWORD`` rotation with no re-encryption)
    # would otherwise 500 the entire destinations list, email destinations
    # included. ``_validate`` still requires ``url`` at save time, so a live
    # destination will not silently deliver with missing secrets.
    secrets: JSON_TYPE = Column(SafeEncryptedJson, nullable=True)

    __mapper_args__: ClassVar = {
        "polymorphic_on": destination_type,
        "polymorphic_identity": "base",
    }

    _default_order_by: ClassVar = ("name",)

    def _validate(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise NotificationSettingsValidationError(messages.NAME_REQUIRED)
        if len(name) > 100:
            raise NotificationSettingsValidationError(messages.NAME_TOO_LONG)
        session = get_current_session()
        clash = session.scalar(
            select(func.count()).select_from(NotificationDestination).where(
                NotificationDestination.project_code == self.project_code,
                func.lower(NotificationDestination.name) == name.lower(),
                NotificationDestination.id != self.id,
            )
        )
        if clash:
            raise NotificationSettingsValidationError(messages.name_already_exists(name))

    def save(self) -> None:
        self._validate()
        super().save()

    @property
    def target_summary(self) -> str:
        """Short human-readable description of where this destination sends. Subclasses override."""
        return ""

    @property
    def type_summary(self) -> str:
        """Human-readable destination type, including the webhook subtype where there is one."""
        return DESTINATION_TYPE_LABELS.get(self.destination_type, self.destination_type)

    def deliver(self, context: dict, template) -> None:
        """Deliver a notification through this destination."""
        raise NotImplementedError

    @classmethod
    def list_for_project(cls, project_code: str) -> list[Self]:
        query = (
            select(cls)
            .where(cls.project_code == project_code)
            .order_by(func.lower(cls.name))
        )
        return list(get_current_session().scalars(query))

    @classmethod
    def get_by_name(cls, project_code: str, name: str) -> Self | None:
        query = select(cls).where(
            cls.project_code == project_code,
            func.lower(cls.name) == name.strip().lower(),
        )
        return get_current_session().scalars(query).first()


class EmailDestination(NotificationDestination):
    __mapper_args__: ClassVar = {
        "polymorphic_identity": DestinationType.email.value,
    }

    @property
    def recipients(self) -> list[str]:
        return list((self.config or {}).get("recipients") or [])

    @recipients.setter
    def recipients(self, value: list[str]) -> None:
        self.config = {**(self.config or {}), "recipients": list(value)}

    @property
    def target_summary(self) -> str:
        return ", ".join(self.recipients)

    def _validate(self) -> None:
        super()._validate()
        recipients = self.recipients
        if not recipients:
            raise NotificationSettingsValidationError(messages.RECIPIENTS_REQUIRED)
        invalid = [addr for addr in recipients if not is_valid_email(addr)]
        if invalid:
            raise NotificationSettingsValidationError(
                "\n".join(messages.invalid_email(addr) for addr in invalid)
            )

    def deliver(self, context: dict, template) -> None:
        template.send(self.recipients, context)

    @classmethod
    def create(cls, project_code: str, name: str, recipients: list[str]) -> Self:
        destination = cls(
            project_code=project_code,
            name=name,
            destination_type=DestinationType.email,
            config={"recipients": list(recipients)},
        )
        destination.save()
        return destination


class WebhookDestination(NotificationDestination):
    __mapper_args__: ClassVar = {
        "polymorphic_identity": DestinationType.webhook.value,
    }

    @property
    def webhook_type(self) -> WebhookType | None:
        raw = (self.config or {}).get("webhook_type")
        if not raw:
            return None
        # Do not silently coerce an unknown stored value to ``None`` (or via
        # ``wrap_for`` to the generic envelope): a corrupted config would
        # otherwise ship a differently-shaped payload to hooks.slack.com. Fail
        # loudly so the corruption surfaces on ``_validate`` and ``deliver``.
        # Read-path callers that must not 500 the whole list use
        # ``webhook_type_safe`` instead.
        return WebhookType(raw)

    @property
    def webhook_type_safe(self) -> WebhookType | None:
        """``webhook_type``, or ``None`` when the stored value is unrecognized.

        For read paths that render many destinations at once -- the REST and MCP
        list/detail serializers, the Project Settings table, the notification
        dialog's destination picker. One row with a corrupted ``config`` would
        otherwise raise mid-serialization and take down the whole surface.
        ``_validate`` and ``deliver`` deliberately use the strict property so
        the corruption still surfaces where acting on it matters.
        """
        try:
            return self.webhook_type
        except ValueError:
            return None

    @webhook_type.setter
    def webhook_type(self, value: WebhookType | str | None) -> None:
        stored = value.value if isinstance(value, WebhookType) else value
        config = {**(self.config or {}), "webhook_type": stored}
        # Only the generic type carries an authorization header, so moving to any
        # other type drops it here rather than failing validation. The fields are
        # hidden on the form the moment the type changes, which leaves no way to
        # clear them by hand, so a stored header would make the switch impossible
        # on every write path at once.
        if stored != WebhookType.generic.value:
            config.pop("auth_header_name", None)
            self.secrets = {**(self.secrets or {}), "auth_header_value": None}
        self.config = config

    @property
    def url(self) -> str | None:
        return (self.secrets or {}).get("url") if self.secrets else None

    @url.setter
    def url(self, value: str | None) -> None:
        self.secrets = {**(self.secrets or {}), "url": value}

    @property
    def url_masked(self) -> str:
        """The URL with everything after the leading path segment replaced with bullets."""
        return mask_webhook_url(self.url)

    @property
    def auth_header_name(self) -> str | None:
        return (self.config or {}).get("auth_header_name")

    @auth_header_name.setter
    def auth_header_name(self, value: str | None) -> None:
        self.config = {**(self.config or {}), "auth_header_name": value}

    @property
    def auth_header_value(self) -> str | None:
        return (self.secrets or {}).get("auth_header_value") if self.secrets else None

    @auth_header_value.setter
    def auth_header_value(self, value: str | None) -> None:
        self.secrets = {**(self.secrets or {}), "auth_header_value": value}

    @property
    def has_auth_header(self) -> bool:
        return bool(self.auth_header_value)

    @property
    def target_summary(self) -> str:
        # An undecryptable secrets blob must not 500 the destinations list from
        # inside ``list_for_project``, so this degrades instead of raising:
        # ``SafeEncryptedJson`` already returns ``None`` for one, so ``url``
        # cannot raise here.
        url = self.url
        # ``hostname`` strips userinfo so a stored ``user:pass@`` URL cannot
        # leak the credential portion into the Project Settings "Sends To"
        # column; matches ``mask_webhook_url`` on the same read path.
        return (urlparse(url).hostname or "") if url else ""

    @property
    def type_summary(self) -> str:
        # A corrupted ``webhook_type`` degrades to the bare type rather than raising.
        webhook_type = self.webhook_type_safe
        subtype = WEBHOOK_TYPE_LABELS.get(webhook_type)
        return f"Webhook | {subtype}" if subtype else "Webhook"

    def _validate(self) -> None:
        super()._validate()
        if self.webhook_type is None:
            raise NotificationSettingsValidationError(messages.WEBHOOK_TYPE_REQUIRED)
        _validate_webhook_url(self.url)
        _validate_webhook_auth_header(self.auth_header_name, self.auth_header_value)
        # Slack and Teams incoming webhooks authenticate by URL only -- accepting an
        # ``Authorization`` header for them would silently no-op (the header is dropped
        # by the receiver) and mislead operators into thinking the destination is
        # protected. The frontend hides the fields for these types; this guard closes
        # the same door on MCP, REST, and any other write path.
        if self.webhook_type is not WebhookType.generic and (self.auth_header_name or self.auth_header_value):
            raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_ONLY_GENERIC)

    def deliver(self, context: dict, template) -> None:
        # Deferred import keeps the model importable without the HTTP session helper.
        from testgen.common.notifications.webhook_delivery import deliver_webhook
        deliver_webhook(self, context, template)

    @classmethod
    def create(
        cls,
        project_code: str,
        name: str,
        webhook_type: WebhookType,
        url: str,
        auth_header_name: str | None = None,
        auth_header_value: str | None = None,
    ) -> Self:
        destination = cls(
            project_code=project_code,
            name=name,
            destination_type=DestinationType.webhook,
            config={
                "webhook_type": webhook_type.value if isinstance(webhook_type, WebhookType) else webhook_type,
                "auth_header_name": auth_header_name,
            },
            secrets={
                "url": url,
                "auth_header_value": auth_header_value,
            },
        )
        destination.save()
        return destination


def _validate_webhook_url(url: str | None) -> None:
    if not url or not url.strip():
        raise NotificationSettingsValidationError(messages.WEBHOOK_URL_REQUIRED)
    if not url.lower().startswith("https://"):
        raise NotificationSettingsValidationError(messages.WEBHOOK_URL_NOT_HTTPS)
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise NotificationSettingsValidationError(messages.WEBHOOK_URL_INVALID) from exc
    if not parsed.hostname:
        raise NotificationSettingsValidationError(messages.WEBHOOK_URL_INVALID)


def _validate_webhook_auth_header(name: str | None, value: str | None) -> None:
    if not value:
        # A missing value is fine; a name without a value is fine too (harmless).
        if name and _HEADER_VALUE_FORBIDDEN.search(name):
            raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_NAME_INVALID)
        if name and _is_reserved_header_name(name):
            raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_NAME_RESERVED)
        return
    if not name or not name.strip():
        raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_NAME_MISSING)
    if not _HEADER_NAME_RE.match(name) or _HEADER_VALUE_FORBIDDEN.search(name):
        raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_NAME_INVALID)
    if _is_reserved_header_name(name):
        # Names on the transport denylist ``Host`` / ``Content-Type`` / ``Content-Length`` /
        # ``Transfer-Encoding`` / ``Connection`` and every ``X-TestGen-`` header would either
        # break delivery, spoof the built-in event tag a receiver may route on, or (in the
        # case of ``Host``) enable vhost confusion against a receiver on a shared IP.
        raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_NAME_RESERVED)
    if _HEADER_VALUE_FORBIDDEN.search(value):
        # Malformed header values are treated the same as invalid names -- the receiver
        # cannot distinguish, and this catches header-injection attempts.
        raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_NAME_INVALID)


_RESERVED_HEADER_NAMES: frozenset[str] = frozenset({
    "host",
    "content-type",
    "content-length",
    "transfer-encoding",
    "connection",
})


def _is_reserved_header_name(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in _RESERVED_HEADER_NAMES:
        return True
    return lowered.startswith("x-testgen-")


def mask_webhook_url(url: str | None) -> str:
    """Partially mask ``url`` for display: scheme, host, and leading path segment only.

    Example: ``https://hooks.slack.com/services/T024/B/xyz`` -> ``https://hooks.slack.com/services/•••``.
    The bullet marker is always present when a URL is returned so callers can tell
    at a glance that a value is stored. Anything that cannot be parsed into a
    scheme + hostname is masked entirely rather than returned raw -- returning the
    original string would leak the credential portion of a malformed URL.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "•••"
    # ``hostname`` strips userinfo and normalizes case; ``netloc`` preserves the
    # ``user:pass@`` prefix, which is the credential leak we're masking.
    host = parsed.hostname
    if not parsed.scheme or not host:
        return "•••"
    port_suffix = f":{parsed.port}" if parsed.port else ""
    base = f"{parsed.scheme}://{host}{port_suffix}"
    path = parsed.path.strip("/")
    if not path:
        return f"{base}/•••"
    first_segment, _, rest = path.partition("/")
    if rest:
        # Multi-segment path: keep the leading segment (Slack ``services``,
        # Teams ``workflows``, etc.) as identity and mask the rest.
        return f"{base}/{first_segment}/•••"
    # Single-segment path: ``first_segment`` IS the credential portion, drop it.
    return f"{base}/•••"


class InlineRecipientList:
    """Delivery target for rules that carry inline recipients.

    Not a persisted model. Constructed on-the-fly by
    ``NotificationSettings.delivery_target`` so the send path uses the same
    ``.deliver()`` shape whether a rule addresses inline or names a destination.
    """

    def __init__(self, recipients: list[str]) -> None:
        self.recipients = list(recipients)

    def deliver(self, context: dict, template) -> None:
        template.send(self.recipients, context)
