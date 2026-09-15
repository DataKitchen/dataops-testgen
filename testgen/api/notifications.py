"""API v1 -- notification destinations and rules.

Two polymorphic families: destinations (email / webhook) and rules (test_run /
profiling_run / monitor_run / score_drop). A rule addresses either an inline
recipient list or a destination in the same project. Webhook secrets are set on
create/update but never returned once saved; the URL comes back partially
masked and the authorization header value is represented only as a boolean.
"""

from typing import Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from testgen.api.deps import (
    api_error,
    db_session,
    resolve_notification_destination,
    resolve_notification_rule,
    resolve_project_code,
)
from testgen.api.schemas import (
    DestinationAddressing,
    DestinationAddressingOut,
    DestinationCreate,
    DestinationDeleteResponse,
    DestinationListResponse,
    DestinationResponse,
    DestinationTypeFilter,
    DestinationUpdate,
    EmailDestinationCreate,
    EmailDestinationResponse,
    EmailDestinationUpdate,
    ErrorResponse,
    InlineAddressing,
    InlineAddressingOut,
    MonitorRunRuleCreate,
    MonitorRunRuleResponse,
    ProfilingRunRuleCreate,
    ProfilingRunRuleResponse,
    RuleCreate,
    RuleListResponse,
    RuleResponse,
    RuleUpdate,
    ScoreDropRuleResponse,
    TestRunRuleCreate,
    TestRunRuleResponse,
    WebhookDestinationResponse,
    WebhookDestinationUpdate,
)
from testgen.common.enums import SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.notification_destinations import (
    EmailDestination,
    NotificationDestination,
    WebhookDestination,
    WebhookType,
)
from testgen.common.models.notification_settings import (
    MonitorNotificationSettings,
    MonitorNotificationTrigger,
    NotificationEvent,
    NotificationSettings,
    NotificationSettingsValidationError,
    ProfilingRunNotificationSettings,
    ProfilingRunNotificationTrigger,
    ScoreDropNotificationSettings,
    TestRunNotificationSettings,
    TestRunNotificationTrigger,
)
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

_error_responses: dict[int | str, dict] = {
    400: {"model": ErrorResponse, "description": "Invalid request"},
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(
    tags=["notifications"],
    dependencies=[Depends(db_session)],
    responses=_error_responses,
)


# Module-level Query defaults so route signatures avoid B008 (function-call-in-defaults).
# Request / response models live in ``api.schemas`` per the convention every other
# router follows -- see ``JobListResponse`` / ``TestResultListResponse`` etc.
_DestinationTypeQuery = Query(default=None, description="Filter to a single destination type.")
_EventQuery = Query(default=None)
_EnabledQuery = Query(default=None)
# ``page`` / ``limit`` defaults match every other list endpoint in the API
# (``page=1``, ``limit=20``, hard cap ``100``) -- see ``api/monitors.py``,
# ``api/scores.py``, ``api/jobs.py``, ``api/test_definitions.py``.
_PageQuery = Query(default=1, ge=1)
_LimitQuery = Query(default=20, ge=1, le=100)
_BodyRequired = Body(...)


# =====================================================================
# ---------- Destination endpoints ----------
# =====================================================================


@router.get(
    "/projects/{project_code}/notification-destinations",
    response_model=DestinationListResponse,
)
def list_destinations(
    project_code: str = resolve_project_code("edit"),
    destination_type: DestinationTypeFilter | None = _DestinationTypeQuery,
    page: int = _PageQuery,
    limit: int = _LimitQuery,
) -> DestinationListResponse:
    """List notification destinations in the project."""
    session = get_current_session()
    query = select(NotificationDestination).where(NotificationDestination.project_code == project_code)
    if destination_type is not None:
        query = query.where(NotificationDestination.destination_type == destination_type)
    query = query.order_by(func.lower(NotificationDestination.name))

    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = list(session.scalars(query.offset((page - 1) * limit).limit(limit)))
    rule_counts = _rule_counts(rows)
    return DestinationListResponse(
        items=[_dest_to_response(d, rule_counts.get(d.id, 0)) for d in rows],
        page=page,
        limit=limit,
        total=total,
    )


@router.post(
    "/projects/{project_code}/notification-destinations",
    response_model=DestinationResponse,
    status_code=201,
)
def create_destination(
    project_code: str = resolve_project_code("administer"),
    body: DestinationCreate = _BodyRequired,
) -> DestinationResponse:
    """Create a new notification destination."""
    payload = body.root
    try:
        if isinstance(payload, EmailDestinationCreate):
            destination = EmailDestination.create(
                project_code=project_code,
                name=payload.name.strip(),
                recipients=list(payload.recipients),
            )
        else:
            destination = WebhookDestination.create(
                project_code=project_code,
                name=payload.name.strip(),
                webhook_type=WebhookType(payload.webhook_type),
                url=payload.url.strip(),
                auth_header_name=(payload.auth_header_name or "").strip() or None,
                auth_header_value=(payload.auth_header_value or "").strip() or None,
            )
    except NotificationSettingsValidationError as exc:
        raise api_error(400, "invalid_destination", str(exc)) from exc
    return _dest_to_response(destination, 0)


@router.get(
    "/notification-destinations/{destination_id}",
    response_model=DestinationResponse,
)
def get_destination(
    destination: NotificationDestination = resolve_notification_destination("edit"),  # noqa: B008
) -> DestinationResponse:
    """Get a single notification destination by ID."""
    return _dest_to_response(destination, _rule_counts([destination]).get(destination.id, 0))


@router.patch(
    "/notification-destinations/{destination_id}",
    response_model=DestinationResponse,
)
def update_destination(
    destination: NotificationDestination = resolve_notification_destination("administer"),  # noqa: B008
    body: DestinationUpdate = _BodyRequired,
) -> DestinationResponse:
    """Update fields on a destination. Passing an empty string as ``auth_header_value`` clears it."""
    payload = body.root
    try:
        if isinstance(destination, EmailDestination):
            if not isinstance(payload, EmailDestinationUpdate):
                raise api_error(400, "type_mismatch", "Payload does not match the destination type.")
            if payload.name is not None:
                destination.name = payload.name.strip()
            if payload.recipients is not None:
                destination.recipients = list(payload.recipients)
        elif isinstance(destination, WebhookDestination):
            if not isinstance(payload, WebhookDestinationUpdate):
                raise api_error(400, "type_mismatch", "Payload does not match the destination type.")
            if payload.name is not None:
                destination.name = payload.name.strip()
            if payload.webhook_type is not None:
                destination.webhook_type = WebhookType(payload.webhook_type)
            if payload.url is not None:
                destination.url = payload.url.strip()
            if payload.auth_header_name is not None:
                destination.auth_header_name = payload.auth_header_name.strip() or None
            if payload.auth_header_value is not None:
                destination.auth_header_value = payload.auth_header_value.strip() or None
        destination.save()
    except NotificationSettingsValidationError as exc:
        raise api_error(400, "invalid_destination", str(exc)) from exc
    return _dest_to_response(destination, _rule_counts([destination]).get(destination.id, 0))


@router.delete(
    "/notification-destinations/{destination_id}",
    response_model=DestinationDeleteResponse,
)
def delete_destination(
    destination: NotificationDestination = resolve_notification_destination("administer"),  # noqa: B008
) -> DestinationDeleteResponse:
    """Delete a destination. Every rule pointing at it is cascade-deleted; the count is reported."""
    rule_count = _rule_counts([destination]).get(destination.id, 0)
    destination_id = destination.id
    destination.delete()
    return DestinationDeleteResponse(id=destination_id, deleted_rule_count=rule_count)


# =====================================================================
# ---------- Rule endpoints ----------
# =====================================================================


@router.get(
    "/projects/{project_code}/notification-rules",
    response_model=RuleListResponse,
)
def list_rules(
    project_code: str = resolve_project_code("view"),
    event: Literal["test_run", "profiling_run", "monitor_run", "score_drop"] | None = _EventQuery,
    enabled: bool | None = _EnabledQuery,
    page: int = _PageQuery,
    limit: int = _LimitQuery,
) -> RuleListResponse:
    """List notification rules in the project.

    Filter with ``event`` (``test_run``, ``profiling_run``, ``monitor_run``, ``score_drop``)
    and/or ``enabled`` (``true`` / ``false``); leave both unset to return every rule.
    """
    clauses = []
    if event is not None:
        clauses.append(NotificationSettings.event == NotificationEvent(event))
    if enabled is not None:
        clauses.append(NotificationSettings.enabled == enabled)
    rows, total = NotificationSettings.paginate_for_projects(
        [project_code], *clauses, page=page, limit=limit,
    )
    return RuleListResponse(
        items=[_rule_to_response(r) for r in rows],
        page=page,
        limit=limit,
        total=total,
    )


@router.post(
    "/projects/{project_code}/notification-rules",
    response_model=RuleResponse,
    status_code=201,
)
def create_rule(
    project_code: str = resolve_project_code("edit"),
    body: RuleCreate = _BodyRequired,
) -> RuleResponse:
    """Create a notification rule addressing either inline recipients or a destination."""
    payload = body.root
    addressing = _resolve_addressing_in(payload.addressing, project_code)
    try:
        if isinstance(payload, TestRunRuleCreate):
            # A ``test_run`` rule must not point at a monitor suite -- monitor
            # suites are a parallel surface and their rules use the ``monitor_run``
            # event. See CLAUDE.md 'Monitor suites are a parallel surface'.
            if payload.test_suite_id is not None:
                _require_scope(TestSuite, payload.test_suite_id, project_code, suite_type=SuiteType.REGULAR)
            rule = TestRunNotificationSettings.create(
                project_code=project_code,
                test_suite_id=payload.test_suite_id,
                trigger=TestRunNotificationTrigger(payload.trigger),
                **addressing,
            )
        elif isinstance(payload, ProfilingRunRuleCreate):
            if payload.table_group_id is not None:
                _require_scope(TableGroup, payload.table_group_id, project_code)
            rule = ProfilingRunNotificationSettings.create(
                project_code=project_code,
                table_group_id=payload.table_group_id,
                trigger=ProfilingRunNotificationTrigger(payload.trigger),
                **addressing,
            )
        elif isinstance(payload, MonitorRunRuleCreate):
            # The table group comes off the suite rather than the request, so a
            # suite/table-group mismatch is unrepresentable instead of merely
            # rejected. Matches how every other write endpoint derives its
            # parent scope (see ``submit_profiling`` / ``submit_test_run``).
            suite = _require_scope(TestSuite, payload.test_suite_id, project_code, suite_type=SuiteType.MONITOR)
            rule = MonitorNotificationSettings.create(
                project_code=project_code,
                table_group_id=suite.table_groups_id,
                test_suite_id=payload.test_suite_id,
                trigger=MonitorNotificationTrigger.on_anomalies,
                table_name=payload.table_name,
                **addressing,
            )
        else:  # ScoreDropRuleCreate
            _require_scope(ScoreDefinition, payload.score_definition_id, project_code)
            rule = ScoreDropNotificationSettings.create(
                project_code=project_code,
                score_definition_id=payload.score_definition_id,
                total_score_threshold=payload.total_threshold,
                cde_score_threshold=payload.cde_threshold,
                **addressing,
            )
    except NotificationSettingsValidationError as exc:
        raise api_error(400, "invalid_rule", str(exc)) from exc
    return _rule_to_response(rule)


@router.get(
    "/notification-rules/{rule_id}",
    response_model=RuleResponse,
)
def get_rule(
    rule: NotificationSettings = resolve_notification_rule("view"),  # noqa: B008
) -> RuleResponse:
    """Get a single notification rule by ID, including its event-specific fields and addressing."""
    return _rule_to_response(rule)


@router.patch(
    "/notification-rules/{rule_id}",
    response_model=RuleResponse,
)
def update_rule(
    rule: NotificationSettings = resolve_notification_rule("edit"),  # noqa: B008
    body: RuleUpdate = _BodyRequired,
) -> RuleResponse:
    """Update a rule's addressing, trigger, thresholds, or table filter.

    Event and scope entity are immutable; pass only the fields to change. Clear an
    optional field with the matching ``clear_*`` flag rather than a null value --
    ``null`` cannot be distinguished from "field omitted" in JSON.
    """
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.addressing is not None:
        addressing = _resolve_addressing_in(body.addressing, rule.project_code)
        rule.recipients = addressing.get("recipients", [])
        rule.notification_destination_id = addressing.get("notification_destination_id")
    if body.trigger is not None:
        try:
            # ``trigger``'s setter replaces the whole ``settings`` JSONB blob, so
            # assigning the same value the rule already has silently wipes
            # sibling keys (``table_name`` on a monitor rule). Skip when the
            # trigger already matches; assign only on an actual change.
            if isinstance(rule, TestRunNotificationSettings):
                new_trigger = TestRunNotificationTrigger(body.trigger)
                if rule.trigger is not new_trigger:
                    rule.trigger = new_trigger
            elif isinstance(rule, ProfilingRunNotificationSettings):
                new_trigger = ProfilingRunNotificationTrigger(body.trigger)
                if rule.trigger is not new_trigger:
                    rule.trigger = new_trigger
            elif isinstance(rule, MonitorNotificationSettings):
                new_trigger = MonitorNotificationTrigger(body.trigger)
                if rule.trigger is not new_trigger:
                    # A monitor rule's ``table_name`` lives in the same settings
                    # blob the trigger setter replaces. Capture it here and
                    # restore below so a rule-scope change is not implicit in a
                    # trigger update.
                    table_name = rule.table_name
                    rule.trigger = new_trigger
                    rule.table_name = table_name
            else:
                raise api_error(400, "invalid_field", "`trigger` is not supported on score-drop rules.")
        except ValueError as exc:
            raise api_error(400, "invalid_field", f"Invalid trigger value: {body.trigger}") from exc
    if isinstance(rule, ScoreDropNotificationSettings):
        if body.clear_total_threshold:
            rule.total_score_threshold = None
        elif body.total_threshold is not None:
            rule.total_score_threshold = body.total_threshold
        if body.clear_cde_threshold:
            rule.cde_score_threshold = None
        elif body.cde_threshold is not None:
            rule.cde_score_threshold = body.cde_threshold
    if isinstance(rule, MonitorNotificationSettings):
        if body.clear_table_name:
            rule.table_name = None
        elif body.table_name is not None:
            rule.table_name = body.table_name
    try:
        rule.save()
    except NotificationSettingsValidationError as exc:
        raise api_error(400, "invalid_rule", str(exc)) from exc
    return _rule_to_response(rule)


@router.delete("/notification-rules/{rule_id}", status_code=204)
def delete_rule(
    rule: NotificationSettings = resolve_notification_rule("edit"),  # noqa: B008
) -> None:
    """Delete a notification rule. The destination it addresses is untouched."""
    rule.delete()
    return None


@router.post("/notification-rules/{rule_id}/pause", response_model=RuleResponse)
def pause_rule(
    rule: NotificationSettings = resolve_notification_rule("edit"),  # noqa: B008
) -> RuleResponse:
    """Pause a rule (sets ``enabled=false``). The rule stops firing but its configuration is kept."""
    return _set_rule_enabled(rule, False)


@router.post("/notification-rules/{rule_id}/resume", response_model=RuleResponse)
def resume_rule(
    rule: NotificationSettings = resolve_notification_rule("edit"),  # noqa: B008
) -> RuleResponse:
    """Resume a paused rule (sets ``enabled=true``). No-op on an already-enabled rule."""
    return _set_rule_enabled(rule, True)


def _set_rule_enabled(rule: NotificationSettings, enabled: bool) -> RuleResponse:
    rule.enabled = enabled
    rule.save()
    return _rule_to_response(rule)


# =====================================================================
# ---------- Helpers ----------
# =====================================================================


def _require_scope(entity_class, entity_id, project_code: str, *, suite_type: SuiteType | None = None):
    """Load an entity and 400 if it isn't in ``project_code``, or is a suite of the wrong type."""
    entity = entity_class.get(entity_id)
    if entity is None or entity.project_code != project_code:
        raise api_error(400, "invalid_scope", f"Scope entity {entity_id} not found in this project.")
    if suite_type is not None:
        # Read the attribute rather than assuming the entity has it: this helper also
        # resolves table groups and score definitions, which carry no suite type.
        # Compare by value, not identity: the column round-trips as a plain string,
        # so ``is`` against the enum member is False for every row.
        actual = getattr(entity, "suite_type", None)
        if suite_type == SuiteType.REGULAR and actual != SuiteType.REGULAR:
            raise api_error(
                400, "invalid_scope",
                "This test suite belongs to a monitor -- use event=monitor_run instead.",
            )
        if suite_type == SuiteType.MONITOR and actual != SuiteType.MONITOR:
            raise api_error(
                400, "invalid_scope",
                "This test suite is not a monitor -- use event=test_run instead.",
            )
    return entity


def _rule_counts(destinations) -> dict:
    if not destinations:
        return {}
    session = get_current_session()
    return dict(session.execute(
        select(
            NotificationSettings.notification_destination_id,
            func.count(),
        )
        .where(NotificationSettings.notification_destination_id.in_([d.id for d in destinations]))
        .group_by(NotificationSettings.notification_destination_id)
    ).all())


def _dest_to_response(destination: NotificationDestination, rule_count: int) -> BaseModel:
    if isinstance(destination, EmailDestination):
        return EmailDestinationResponse(
            id=destination.id,
            project_code=destination.project_code,
            name=destination.name,
            recipients=destination.recipients,
            rule_count=rule_count,
        )
    if isinstance(destination, WebhookDestination):
        return WebhookDestinationResponse(
            id=destination.id,
            project_code=destination.project_code,
            name=destination.name,
            webhook_type=(destination.webhook_type_safe or WebhookType.generic).value,
            url_masked=destination.url_masked,
            auth_header_name=destination.auth_header_name,
            has_auth_header=destination.has_auth_header,
            rule_count=rule_count,
        )
    # Unknown polymorphic subclass should never reach here; surface as 500.
    raise api_error(500, "unknown_destination_type", "Unknown destination type.")


def _rule_to_response(rule: NotificationSettings) -> BaseModel:
    addressing = _rule_addressing_out(rule)
    if isinstance(rule, TestRunNotificationSettings):
        return TestRunRuleResponse(
            id=rule.id,
            project_code=rule.project_code,
            enabled=rule.enabled,
            addressing=addressing,
            test_suite_id=rule.test_suite_id,
            trigger=rule.trigger.value if rule.trigger else "on_failures",
        )
    if isinstance(rule, ProfilingRunNotificationSettings):
        return ProfilingRunRuleResponse(
            id=rule.id,
            project_code=rule.project_code,
            enabled=rule.enabled,
            addressing=addressing,
            table_group_id=rule.table_group_id,
            trigger=rule.trigger.value if rule.trigger else "on_changes",
        )
    if isinstance(rule, MonitorNotificationSettings):
        return MonitorRunRuleResponse(
            id=rule.id,
            project_code=rule.project_code,
            enabled=rule.enabled,
            addressing=addressing,
            test_suite_id=rule.test_suite_id,
            table_group_id=rule.table_group_id,
            table_name=rule.table_name,
        )
    if isinstance(rule, ScoreDropNotificationSettings):
        return ScoreDropRuleResponse(
            id=rule.id,
            project_code=rule.project_code,
            enabled=rule.enabled,
            addressing=addressing,
            score_definition_id=rule.score_definition_id,
            total_threshold=float(rule.total_score_threshold) if rule.total_score_threshold is not None else None,
            cde_threshold=float(rule.cde_score_threshold) if rule.cde_score_threshold is not None else None,
        )
    raise api_error(500, "unknown_rule_event", "Unknown rule event type.")


def _rule_addressing_out(rule: NotificationSettings) -> BaseModel:
    if rule.notification_destination_id is not None:
        destination = rule.destination
        return DestinationAddressingOut(
            destination_id=rule.notification_destination_id,
            destination_name=destination.name if destination else None,
            destination_type=destination.destination_type if destination else None,
        )
    return InlineAddressingOut(recipients=list(rule.recipients or []))


def _resolve_addressing_in(addressing, project_code: str) -> dict:
    """Return kwargs to pass to a rule's ``create``/mutation for the given addressing."""
    if isinstance(addressing, InlineAddressing):
        return {"recipients": list(addressing.recipients)}
    if isinstance(addressing, DestinationAddressing):
        destination = NotificationDestination.get(addressing.destination_id)
        if destination is None or destination.project_code != project_code:
            raise api_error(400, "invalid_addressing", "Destination not found in this project.")
        return {"notification_destination_id": destination.id}
    raise api_error(400, "invalid_addressing", "Addressing must specify a kind.")
