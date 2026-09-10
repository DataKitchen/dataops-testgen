"""Data-loading and CRUD helpers for the Notification Destinations project-settings section."""

from uuid import UUID

from sqlalchemy import func, select

from testgen.common.models import database_session, with_database_session
from testgen.common.models.notification_destinations import (
    EmailDestination,
    NotificationDestination,
    WebhookDestination,
    WebhookType,
    _validate_webhook_auth_header,
    _validate_webhook_url,
)
from testgen.common.models.notification_settings import NotificationSettings, NotificationSettingsValidationError
from testgen.common.notifications import messages
from testgen.common.notifications.webhook_delivery import (
    DeliveryResult,
    WebhookDeliveryError,
    deliver_test_payload,
)


def load_destinations_data(project_code: str) -> list[dict]:
    """Return the destinations list shape the frontend section expects."""
    with database_session() as session:
        destinations = NotificationDestination.list_for_project(project_code)
        if not destinations:
            return []
        rule_counts = dict(session.execute(
            select(
                NotificationSettings.notification_destination_id,
                func.count(),
            )
            .where(NotificationSettings.notification_destination_id.in_([d.id for d in destinations]))
            .group_by(NotificationSettings.notification_destination_id)
        ).all())
    return [_serialize(d, rule_counts.get(d.id, 0)) for d in destinations]


def _serialize(destination: NotificationDestination, rule_count: int) -> dict:
    if isinstance(destination, EmailDestination):
        return {
            "id": str(destination.id),
            "name": destination.name,
            "destination_type": destination.destination_type,
            "recipients": destination.recipients,
            "target_summary": destination.target_summary,
            "type_summary": destination.type_summary,
            "rule_count": rule_count,
        }
    if isinstance(destination, WebhookDestination):
        return {
            "id": str(destination.id),
            "name": destination.name,
            "destination_type": destination.destination_type,
            "webhook_type": webhook_type.value if (webhook_type := destination.webhook_type_safe) else None,
            "url_masked": destination.url_masked,
            "auth_header_name": destination.auth_header_name or "",
            "has_auth_header": destination.has_auth_header,
            "target_summary": destination.target_summary,
            "type_summary": destination.type_summary,
            "rule_count": rule_count,
        }
    return {
        "id": str(destination.id),
        "name": destination.name,
        "destination_type": destination.destination_type,
        "target_summary": destination.target_summary,
        "type_summary": destination.type_summary,
        "rule_count": rule_count,
    }


@with_database_session
def add_destination(project_code: str, payload: dict) -> None:
    destination_type = payload.get("destination_type")
    if destination_type == "email":
        EmailDestination.create(
            project_code=project_code,
            name=(payload.get("name") or "").strip(),
            recipients=payload.get("recipients") or [],
        )
        return
    if destination_type == "webhook":
        webhook_type = _parse_webhook_type(payload.get("webhook_type"))
        # The form hides both auth inputs as soon as the type leaves generic, but the
        # payload still carries whatever they last held. Passing those through would
        # fail validation naming fields that are no longer on screen.
        is_generic = webhook_type is WebhookType.generic
        WebhookDestination.create(
            project_code=project_code,
            name=(payload.get("name") or "").strip(),
            webhook_type=webhook_type,
            url=(payload.get("webhook_url") or "").strip(),
            auth_header_name=((payload.get("auth_header_name") or "").strip() or None) if is_generic else None,
            auth_header_value=((payload.get("auth_header_value") or "").strip() or None) if is_generic else None,
        )
        return
    raise ValueError(messages.unsupported_destination_type(destination_type))


@with_database_session
def edit_destination(project_code: str, payload: dict) -> None:
    destination = _get_owned(project_code, payload.get("id"))
    # A destination's type is immutable: the field updates below dispatch on the
    # STORED polymorphic type, so accepting a switched type would apply only the
    # name and silently drop every type-specific field while reporting success.
    # Reject rather than no-op. The dialog also disables the type select on edit;
    # this is the server-side half so the frontend is not the only guard.
    requested_type = payload.get("destination_type")
    if requested_type and requested_type != destination.destination_type:
        raise ValueError(messages.DESTINATION_TYPE_IMMUTABLE)
    # Only update fields the payload actually supplied; a missing ``name`` would
    # otherwise clobber the stored value to an empty string and fail validation.
    if "name" in payload:
        destination.name = (payload.get("name") or "").strip()
    if isinstance(destination, EmailDestination) and "recipients" in payload:
        destination.recipients = payload.get("recipients") or []
    elif isinstance(destination, WebhookDestination):
        webhook_type_in = payload.get("webhook_type")
        if webhook_type_in:
            destination.webhook_type = _parse_webhook_type(webhook_type_in)
        webhook_url = payload.get("webhook_url")
        # A blank URL from a masked-field edit means "leave the stored one alone"
        # -- the frontend never sends the full stored URL back.
        if webhook_url:
            destination.url = webhook_url.strip()
        # Auth fields belong to the generic type only. The form removes both inputs
        # the moment the type changes, so a payload for a non-generic type still
        # carries whatever they last held; applying it would re-populate what the
        # type setter just cleared and make the switch unsavable.
        is_generic = destination.webhook_type is WebhookType.generic
        auth_header_name = payload.get("auth_header_name")
        if is_generic and auth_header_name is not None:
            destination.auth_header_name = auth_header_name.strip() or None
            # A stored value with no name cannot be sent, and the value field renders
            # empty for a stored secret -- so rejecting this would name a field the
            # user sees as blank. Clearing the name clears the header outright.
            if not destination.auth_header_name:
                destination.auth_header_value = None
        # ``auth_header_value`` is only sent when the user typed in the field: a
        # missing key means "keep the stored value"; an explicit empty string
        # means "clear it". This distinguishes an untouched edit from a delete.
        if is_generic and "auth_header_value" in payload:
            auth_header_value = payload.get("auth_header_value") or ""
            destination.auth_header_value = auth_header_value.strip() or None
    destination.save()


@with_database_session
def delete_destination(project_code: str, destination_id: str) -> None:
    destination = _get_owned(project_code, destination_id)
    destination.delete()


def send_test_delivery(project_code: str, payload: dict) -> DeliveryResult:
    """Deliver a test payload using the values currently in the form.

    A saved destination whose URL has not been edited is looked up so its stored
    URL is used; a form with a fresh URL uses that URL directly. Either way the
    delivery goes through the same address check, headers, and transport a live
    notification uses.
    """
    with database_session():
        webhook_type = _parse_webhook_type(payload.get("webhook_type"))
        url = (payload.get("webhook_url") or "").strip()
        # Auth fields apply to the generic type only; the form stops showing them the
        # moment the type changes, so a stale name in the payload must not be sent.
        is_generic = webhook_type is WebhookType.generic
        auth_header_name = ((payload.get("auth_header_name") or "").strip() or None) if is_generic else None
        auth_header_value = ((payload.get("auth_header_value") or "").strip() or None) if is_generic else None
        destination_id = payload.get("id")
        if destination_id and (not url or not auth_header_value):
            stored = _get_owned(project_code, destination_id)
            if isinstance(stored, WebhookDestination):
                stored_url = stored.url or ""
                if not url:
                    url = stored_url
                if is_generic and not auth_header_name:
                    auth_header_name = stored.auth_header_name
                if is_generic and not auth_header_value and stored.has_auth_header:
                    # The stored header value is write-only: it is never serialized
                    # back to the browser. Reusing it for a URL the caller supplied
                    # would hand it to whatever host they name, turning Send Test
                    # into a read primitive for a secret they cannot otherwise see.
                    # Reuse it only when the delivery still targets the stored URL.
                    if url == stored_url:
                        auth_header_value = stored.auth_header_value
                    else:
                        raise NotificationSettingsValidationError(
                            messages.WEBHOOK_AUTH_HEADER_REQUIRED_FOR_NEW_URL
                        )
        transient = WebhookDestination(
            project_code=project_code,
            name=payload.get("name") or "Send Test",
            destination_type="webhook",
            config={
                "webhook_type": webhook_type.value,
                "auth_header_name": auth_header_name,
            },
            secrets={
                "url": url,
                "auth_header_value": auth_header_value,
            },
        )
        # Run the same URL + auth-header validation ``.save()`` would run on a real
        # destination. Send Test would otherwise skip HTTPS enforcement, RFC 7230
        # header-name syntax, CR/LF/NUL rejection, and the "auth headers are
        # Generic-only" invariant -- ``http_guard`` alone would not catch a
        # malformed auth header value used for header injection, and the
        # frontend hiding the field is not a server-side defense.
        _validate_webhook_url(transient.url)
        _validate_webhook_auth_header(transient.auth_header_name, transient.auth_header_value)
        if transient.webhook_type is not WebhookType.generic and (
            transient.auth_header_name or transient.auth_header_value
        ):
            raise NotificationSettingsValidationError(messages.WEBHOOK_AUTH_HEADER_ONLY_GENERIC)
        return deliver_test_payload(transient)


def _parse_webhook_type(raw: str | None) -> WebhookType:
    if not raw:
        raise ValueError(messages.WEBHOOK_TYPE_REQUIRED)
    try:
        return WebhookType(raw)
    except ValueError as exc:
        raise ValueError(messages.invalid_webhook_type(raw)) from exc


def _get_owned(project_code: str, destination_id) -> NotificationDestination:
    if not destination_id:
        raise ValueError(messages.DESTINATION_NOT_FOUND)
    if isinstance(destination_id, str):
        destination_id = UUID(destination_id)
    destination = NotificationDestination.get(destination_id)
    if destination is None or destination.project_code != project_code:
        raise ValueError(messages.DESTINATION_NOT_FOUND)
    return destination


__all__ = [
    "DeliveryResult",
    "WebhookDeliveryError",
    "add_destination",
    "delete_destination",
    "edit_destination",
    "load_destinations_data",
    "send_test_delivery",
]
