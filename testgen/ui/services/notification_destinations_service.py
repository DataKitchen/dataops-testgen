"""Data-loading and CRUD helpers for the Notification Destinations project-settings section.

Called by both the core ``ProjectSettingsPage`` view and the multi-project-management
plugin subclass so the section renders and behaves identically in both frontends.
"""

from uuid import UUID

from sqlalchemy import func, select

from testgen.common.models import database_session, with_database_session
from testgen.common.models.notification_destinations import (
    EmailDestination,
    NotificationDestination,
)
from testgen.common.models.notification_settings import NotificationSettings
from testgen.common.notifications import messages


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
    recipients = destination.recipients if isinstance(destination, EmailDestination) else []
    return {
        "id": str(destination.id),
        "name": destination.name,
        "destination_type": destination.destination_type,
        "recipients": recipients,
        "target_summary": destination.target_summary,
        "rule_count": rule_count,
    }


@with_database_session
def add_destination(project_code: str, payload: dict) -> None:
    destination_type = payload.get("destination_type")
    if destination_type != "email":
        raise ValueError(messages.unsupported_destination_type(destination_type))
    EmailDestination.create(
        project_code=project_code,
        name=(payload.get("name") or "").strip(),
        recipients=payload.get("recipients") or [],
    )


@with_database_session
def edit_destination(project_code: str, payload: dict) -> None:
    destination = _get_owned(project_code, payload.get("id"))
    # Only update fields the payload actually supplied; a missing ``name`` would
    # otherwise clobber the stored value to an empty string and fail validation.
    if "name" in payload:
        destination.name = (payload.get("name") or "").strip()
    if isinstance(destination, EmailDestination) and "recipients" in payload:
        destination.recipients = payload.get("recipients") or []
    destination.save()


@with_database_session
def delete_destination(project_code: str, destination_id: str) -> None:
    destination = _get_owned(project_code, destination_id)
    destination.delete()


def _get_owned(project_code: str, destination_id) -> NotificationDestination:
    if not destination_id:
        raise ValueError(messages.DESTINATION_NOT_FOUND)
    if isinstance(destination_id, str):
        destination_id = UUID(destination_id)
    destination = NotificationDestination.get(destination_id)
    if destination is None or destination.project_code != project_code:
        raise ValueError(messages.DESTINATION_NOT_FOUND)
    return destination
