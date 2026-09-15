"""MCP tools for managing project-level notification destinations.

Destinations are the named, reusable delivery targets a rule can point at instead
of carrying its own recipient list. Two types today: ``email`` (a recipient list)
and ``webhook`` (an HTTPS endpoint delivering Slack Block Kit, an Adaptive Card
for Microsoft Teams, or a generic JSON envelope).

Secret handling:

- Webhook URL: writable through ``webhook_url`` on create/update; never returned
  in full. Reads render the partial-mask form the UI shows.
- Webhook authorization header value: writable via ``auth_header_value``; never
  returned. Reads expose a ``has_auth_header`` boolean only.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import Field
from sqlalchemy import func, select

from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.notification_destinations import (
    DESTINATION_TYPE_LABELS,
    WEBHOOK_TYPE_SELECTION_LABELS,
    EmailDestination,
    NotificationDestination,
    WebhookDestination,
    WebhookType,
)
from testgen.common.models.notification_settings import (
    NotificationSettings,
    NotificationSettingsValidationError,
)
from testgen.common.notifications import messages
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_page_footer,
    format_page_info,
    match_enum,
    resolve_destination,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MANAGE


# Every label vocabulary here is derived from the model's maps. Restating them
# would make the tool arguments drift from what the rest of the product shows the
# moment a type is added or relabelled.
_TYPE_TO_LABEL: dict[str, str] = {kind.value: label for kind, label in DESTINATION_TYPE_LABELS.items()}
_WEBHOOK_TYPE_TO_LABEL: dict[str, str] = {
    kind.value: label for kind, label in WEBHOOK_TYPE_SELECTION_LABELS.items()
}

_DestinationTypeLabel = StrEnum("_DestinationTypeLabel", {kind.name: label for kind, label in DESTINATION_TYPE_LABELS.items()})
_LABEL_TO_TYPE: dict[str, str] = {label: kind.value for kind, label in DESTINATION_TYPE_LABELS.items()}

_WebhookTypeLabel = StrEnum("_WebhookTypeLabel", {kind.name: label for kind, label in WEBHOOK_TYPE_SELECTION_LABELS.items()})
_LABEL_TO_WEBHOOK_TYPE: dict[str, WebhookType] = {
    label: kind for kind, label in WEBHOOK_TYPE_SELECTION_LABELS.items()
}


@with_database_session
@mcp_permission("edit")
def list_notification_destinations(
    project_code: Annotated[str | None, Field(description="Scope to a specific project.")] = None,
    destination_type: Annotated[
        str | None,
        Field(description="Filter to a single type. One of ``Email``, ``Webhook``."),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of destinations per page (default 50, max 200).")] = 50,
    page: Annotated[int, Field(description="Page number, starting from 1 (default 1).")] = 1,
) -> str:
    """List notification destinations across projects, or scoped to a project.

    Each row includes the destination name, type, a short target summary, and the
    number of notification rules currently pointing at it. Webhook URLs and secret
    values are never returned; secret presence is exposed only through the
    per-destination detail (``has_auth_header``).
    """
    validate_page(page)
    validate_limit(limit, 200)

    perms = get_project_permissions()
    if project_code:
        perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))
        allowed_codes = [project_code]
    else:
        allowed_codes = list(perms.allowed_codes)

    session = get_current_session()
    type_filter: str | None = None
    if destination_type is not None:
        label = match_enum(destination_type, _DestinationTypeLabel)
        if label is None:
            valid = ", ".join(f"`{o.value}`" for o in _DestinationTypeLabel)
            raise MCPUserError(f"Invalid `destination_type` `{destination_type}`. Valid values: {valid}.")
        type_filter = _LABEL_TO_TYPE[label]

    query = select(NotificationDestination).where(
        NotificationDestination.project_code.in_(allowed_codes)
    )
    if type_filter is not None:
        query = query.where(NotificationDestination.destination_type == type_filter)
    query = query.order_by(NotificationDestination.project_code, func.lower(NotificationDestination.name))

    total = session.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    ) or 0
    rows = list(session.scalars(query.offset((page - 1) * limit).limit(limit)))
    rule_counts = _rule_counts_for(rows)

    doc = MdDoc()
    scope_label = f"Project `{project_code}`" if project_code else None
    header = f"Notification Destinations — {scope_label}" if scope_label else "Notification Destinations"
    doc.heading(1, header)
    if total == 0:
        doc.text("_No notification destinations found._")
        return doc.render()
    doc.text(format_page_info(total, page, limit))
    table_rows = [
        [
            str(d.id),
            d.name,
            d.type_summary,
            d.target_summary or "—",
            str(rule_counts.get(d.id, 0)),
            d.project_code,
        ]
        for d in rows
    ]
    doc.table(["ID", "Name", "Type", "Sends To", "Rules", "Project"], table_rows)
    if footer := format_page_footer(total, page, limit):
        doc.text(footer)
    return doc.render()


@with_database_session
@mcp_permission("edit")
def get_notification_destination(
    destination_id: Annotated[
        str,
        Field(description="UUID of the destination, e.g. from ``list_notification_destinations``."),
    ],
) -> str:
    """Get full non-secret details of a notification destination.

    Includes name, type, target summary, and the number of notification rules
    using it. For webhook destinations: the webhook subtype, the URL in its
    partial-mask form, the optional authorization header name (Generic only),
    and a ``has_auth_header`` boolean. The full URL and the header value are
    never returned.
    """
    destination = resolve_destination(destination_id)
    return _render_one(destination, _rule_counts_for([destination]).get(destination.id, 0))


@with_database_session
@mcp_permission("administer")
def create_notification_destination(
    project_code: Annotated[str, Field(description="Project code the destination belongs to.")],
    name: Annotated[str, Field(description="Display name for the destination (unique per project, case-insensitive).")],
    destination_type: Annotated[
        str,
        Field(description="Kind of destination. One of ``Email``, ``Webhook``."),
    ],
    recipients: Annotated[
        list[str] | None,
        Field(
            description="Email addresses (one or more well-formed emails). Required when "
            "``destination_type`` is ``Email``; rejected otherwise.",
        ),
    ] = None,
    webhook_type: Annotated[
        str | None,
        Field(
            description="Webhook subtype. Required when ``destination_type`` is ``Webhook``. "
            "One of ``Slack``, ``Microsoft Teams``, ``Generic``.",
        ),
    ] = None,
    webhook_url: Annotated[
        str | None,
        Field(
            description="HTTPS URL to POST to. Required when ``destination_type`` is ``Webhook``. "
            "Stored encrypted; never returned in full once saved.",
        ),
    ] = None,
    auth_header_name: Annotated[
        str | None,
        Field(
            description="Authorization header name to send with every request. Only accepted for "
            "``Webhook`` destinations with ``webhook_type`` = ``Generic``.",
        ),
    ] = None,
    auth_header_value: Annotated[
        str | None,
        Field(
            description="Authorization header value. Only accepted for ``Webhook`` destinations with "
            "``webhook_type`` = ``Generic``. Stored encrypted; never returned once saved.",
        ),
    ] = None,
) -> str:
    """Create a project-level notification destination.

    Rejects every invalid input in a single error so the call can be corrected in
    one round-trip — no partial save occurs.
    """
    perms = get_project_permissions()
    perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))

    kind = _parse_destination_type(destination_type)
    try:
        if kind == "email":
            _reject_webhook_args("Email", webhook_type, webhook_url, auth_header_name, auth_header_value)
            if not recipients:
                raise MCPUserError("`recipients` must contain at least one email address.")
            destination = EmailDestination.create(
                project_code=project_code,
                name=name.strip(),
                recipients=list(recipients),
            )
        else:
            if recipients:
                raise MCPUserError("`recipients` is not supported for `Webhook` destinations.")
            parsed_webhook_type = _parse_webhook_type(webhook_type)
            _check_generic_only(parsed_webhook_type, auth_header_name, auth_header_value)
            if not webhook_url:
                raise MCPUserError("`webhook_url` is required for `Webhook` destinations.")
            destination = WebhookDestination.create(
                project_code=project_code,
                name=name.strip(),
                webhook_type=parsed_webhook_type,
                url=webhook_url.strip(),
                auth_header_name=(auth_header_name or "").strip() or None,
                auth_header_value=(auth_header_value or "").strip() or None,
            )
    except NotificationSettingsValidationError as exc:
        raise MCPUserError(str(exc)) from exc

    return _render_created(destination, 0)


@with_database_session
@mcp_permission("administer")
def update_notification_destination(
    destination_id: Annotated[
        str,
        Field(description="UUID of the destination, e.g. from ``list_notification_destinations``."),
    ],
    name: Annotated[str | None, Field(description="New display name.")] = None,
    recipients: Annotated[
        list[str] | None,
        Field(
            description="Replace the email recipient list (one or more well-formed emails). "
            "Only valid for ``Email`` destinations.",
        ),
    ] = None,
    webhook_type: Annotated[
        str | None,
        Field(
            description="Change the webhook subtype. Only valid for ``Webhook`` destinations. "
            "One of ``Slack``, ``Microsoft Teams``, ``Generic``.",
        ),
    ] = None,
    webhook_url: Annotated[
        str | None,
        Field(
            description="Replace the stored URL. Only valid for ``Webhook`` destinations. "
            "Never returned in full after save.",
        ),
    ] = None,
    auth_header_name: Annotated[
        str | None,
        Field(
            description="Replace the authorization header name. Only valid for ``Webhook`` destinations "
            "with ``webhook_type`` = ``Generic``.",
        ),
    ] = None,
    auth_header_value: Annotated[
        str | None,
        Field(
            description="Replace the authorization header value. Pass an empty string to clear it. "
            "Only valid for ``Webhook`` destinations with ``webhook_type`` = ``Generic``.",
        ),
    ] = None,
) -> str:
    """Update a notification destination. Pass only the fields to change."""
    destination = resolve_destination(destination_id)

    if all(
        v is None
        for v in (name, recipients, webhook_type, webhook_url, auth_header_name, auth_header_value)
    ):
        raise MCPUserError("No fields supplied to update.")

    try:
        if isinstance(destination, EmailDestination):
            _reject_webhook_args(
                "Email", webhook_type, webhook_url, auth_header_name, auth_header_value,
            )
            if name is not None:
                destination.name = name.strip()
            if recipients is not None:
                destination.recipients = list(recipients)
        elif isinstance(destination, WebhookDestination):
            if recipients is not None:
                raise MCPUserError("`recipients` is not supported for `Webhook` destinations.")
            if name is not None:
                destination.name = name.strip()
            if webhook_type is not None:
                destination.webhook_type = _parse_webhook_type(webhook_type)
            if webhook_url is not None:
                destination.url = webhook_url.strip()
            if auth_header_name is not None:
                destination.auth_header_name = auth_header_name.strip() or None
            if auth_header_value is not None:
                destination.auth_header_value = auth_header_value.strip() or None
            _check_generic_only(destination.webhook_type, destination.auth_header_name, destination.auth_header_value)
        destination.save()
    except NotificationSettingsValidationError as exc:
        raise MCPUserError(str(exc)) from exc

    return _render_one(destination, _rule_counts_for([destination]).get(destination.id, 0))


@with_database_session
@mcp_permission("administer")
def delete_notification_destination(
    destination_id: Annotated[
        str,
        Field(description="UUID of the destination, e.g. from ``list_notification_destinations``."),
    ],
) -> str:
    """Delete a notification destination.

    Every rule pointing at the destination is deleted through the same cascade
    the UI applies; the response reports how many rules were removed so the caller
    learns the blast radius without a follow-up call.
    """
    destination = resolve_destination(destination_id)
    rule_count = _rule_counts_for([destination]).get(destination.id, 0)
    name = destination.name
    destination.delete()

    doc = MdDoc()
    doc.heading(1, f"Notification Destination deleted — {name}")
    doc.field("Destination ID", destination_id, code=True)
    doc.field("Rules deleted through cascade", rule_count)
    return doc.render()


def _rule_counts_for(destinations) -> dict:
    if not destinations:
        return {}
    session = get_current_session()
    return dict(session.execute(
        select(
            NotificationSettings.notification_destination_id,
            func.count(),
        )
        .where(
            NotificationSettings.notification_destination_id.in_([d.id for d in destinations])
        )
        .group_by(NotificationSettings.notification_destination_id)
    ).all())


def _render_one(destination: NotificationDestination, rule_count: int) -> str:
    doc = MdDoc()
    kind_label = _TYPE_TO_LABEL.get(destination.destination_type, destination.destination_type)
    doc.heading(1, f"{kind_label} Notification Destination")
    _render_body(doc, destination, rule_count)
    return doc.render()


def _render_created(destination: NotificationDestination, rule_count: int) -> str:
    doc = MdDoc()
    kind_label = _TYPE_TO_LABEL.get(destination.destination_type, destination.destination_type)
    doc.heading(1, f"{kind_label} Notification Destination created")
    _render_body(doc, destination, rule_count)
    return doc.render()


def _render_body(doc: MdDoc, destination: NotificationDestination, rule_count: int) -> None:
    doc.heading(2, "Configuration")
    doc.field("Destination ID", destination.id, code=True)
    doc.field("Name", destination.name)
    doc.field("Type", _TYPE_TO_LABEL.get(destination.destination_type, destination.destination_type))
    doc.field("Project", destination.project_code, code=True)
    doc.field("Rules using this destination", rule_count)

    if isinstance(destination, EmailDestination):
        doc.heading(2, "Recipients")
        if destination.recipients:
            doc.bullets(list(destination.recipients))
        else:
            doc.text("_No recipients configured._")
    elif isinstance(destination, WebhookDestination):
        doc.heading(2, "Webhook")
        wt = destination.webhook_type_safe
        doc.field("Webhook Type", _WEBHOOK_TYPE_TO_LABEL.get(wt.value if wt else "", "—"))
        doc.field("URL", destination.url_masked or "—")
        if destination.auth_header_name:
            doc.field("Authorization Header Name", destination.auth_header_name)
        doc.field("Authorization Header Set", "Yes" if destination.has_auth_header else "No")


def _parse_destination_type(value: str) -> str:
    label = match_enum(value, _DestinationTypeLabel)
    if label is None:
        valid = ", ".join(f"`{o.value}`" for o in _DestinationTypeLabel)
        raise MCPUserError(f"Invalid `destination_type` `{value}`. Valid values: {valid}.")
    return _LABEL_TO_TYPE[label]


def _parse_webhook_type(value: str | None) -> WebhookType:
    if not value:
        raise MCPUserError(messages.WEBHOOK_TYPE_REQUIRED)
    label = match_enum(value, _WebhookTypeLabel)
    if label is None:
        valid = ", ".join(f"`{o.value}`" for o in _WebhookTypeLabel)
        raise MCPUserError(f"Invalid `webhook_type` `{value}`. Valid values: {valid}.")
    return _LABEL_TO_WEBHOOK_TYPE[label]


def _reject_webhook_args(kind_label, webhook_type, webhook_url, auth_header_name, auth_header_value):
    stray = [
        name
        for name, value in (
            ("webhook_type", webhook_type),
            ("webhook_url", webhook_url),
            ("auth_header_name", auth_header_name),
            ("auth_header_value", auth_header_value),
        )
        if value is not None
    ]
    if stray:
        joined = ", ".join(f"`{name}`" for name in stray)
        raise MCPUserError(f"{joined} not supported for `{kind_label}` destinations.")


def _check_generic_only(webhook_type: WebhookType | None, auth_header_name: str | None, auth_header_value: str | None):
    """Reject auth-header args for Slack / Teams webhook subtypes."""
    if webhook_type == WebhookType.generic:
        return
    if auth_header_name or auth_header_value:
        raise MCPUserError(
            "`auth_header_name` and `auth_header_value` are only supported when `webhook_type` "
            "is `Generic`."
        )
