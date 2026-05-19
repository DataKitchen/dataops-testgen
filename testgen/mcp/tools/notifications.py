from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    MonitorNotificationTrigger,
    NotificationEvent,
    NotificationSettings,
    NotificationSummary,
    ProfilingRunNotificationSettings,
    ProfilingRunNotificationTrigger,
    ScoreDropNotificationSettings,
    TestRunNotificationSettings,
    TestRunNotificationTrigger,
    is_valid_email,
)
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    MONITOR_TRIGGER_LABEL_TO_INTERNAL,
    NOTIFICATION_EVENT_LABEL_TO_INTERNAL,
    PROFILING_RUN_TRIGGER_LABEL_TO_INTERNAL,
    TEST_RUN_TRIGGER_LABEL_TO_INTERNAL,
    DocGroup,
    MonitorTriggerLabel,
    NotificationEventLabel,
    ProfilingRunTriggerLabel,
    TestRunTriggerLabel,
    format_notification_event,
    format_notification_trigger,
    format_page_footer,
    format_page_info,
    resolve_notification,
    resolve_scorecard,
    resolve_table_group,
    resolve_test_suite,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MANAGE

# ``Monitor Alert`` is intentionally excluded from creation: a monitor notification is
# bound to its (internal, user-invisible) monitor test suite at monitor-setup time, so it
# can't be created standalone here. Existing monitor notifications are still managed via
# get/update/delete/list_notifications.
_CREATE_SUPPORTED_EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent.test_run,
    NotificationEvent.profiling_run,
    NotificationEvent.score_drop,
)


@with_database_session
@mcp_permission("view")
def list_notifications(
    project_code: str | None = None,
    test_suite_id: str | None = None,
    table_group_id: str | None = None,
    scorecard_id: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> str:
    """List notifications configured across projects, or scoped to a parent entity.

    With no scope argument, returns notifications across every project the caller can view.
    Provide one of ``project_code`` / ``test_suite_id`` / ``table_group_id`` / ``scorecard_id``
    to narrow the listing. Parent-entity scopes filter strictly on that entity — to also
    see project-wide notifications (those not bound to a specific suite, table group, or
    scorecard), use ``project_code``.

    Args:
        project_code: Scope to a specific project.
        test_suite_id: UUID of a test suite, e.g. from ``list_test_suites``. Returns only
            notifications bound to this suite.
        table_group_id: UUID of a table group, e.g. from ``get_data_inventory``. Returns
            only notifications bound to this table group.
        scorecard_id: UUID of a scorecard, e.g. from ``list_scorecards``. Returns only
            notifications bound to this scorecard.
        limit: Maximum number of notifications per page (default 50, max 200).
        page: Page number, starting from 1 (default 1).
    """
    validate_page(page)
    validate_limit(limit, 200)

    scope_args = {
        "project_code": project_code,
        "test_suite_id": test_suite_id,
        "table_group_id": table_group_id,
        "scorecard_id": scorecard_id,
    }
    provided = [name for name, value in scope_args.items() if value]
    if len(provided) > 1:
        raise MCPUserError(
            "Pass at most one of `project_code`, `test_suite_id`, `table_group_id`, `scorecard_id`."
        )

    perms = get_project_permissions()
    scope_label: str | None = None

    if test_suite_id:
        suite = resolve_test_suite(test_suite_id)
        rows, total = NotificationSettings.list_for_test_suite(suite.id, page=page, limit=limit)
        scope_label = f"Test Suite `{suite.test_suite}`"
    elif table_group_id:
        tg = resolve_table_group(table_group_id)
        rows, total = NotificationSettings.list_for_table_group(tg.id, page=page, limit=limit)
        scope_label = f"Table Group `{tg.table_groups_name}`"
    elif scorecard_id:
        scorecard = resolve_scorecard(scorecard_id)
        rows, total = NotificationSettings.list_for_score_definition(scorecard.id, page=page, limit=limit)
        scope_label = f"Scorecard `{scorecard.name}`"
    elif project_code:
        perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))
        rows, total = NotificationSettings.list_for_projects([project_code], page=page, limit=limit)
        scope_label = f"Project `{project_code}`"
    else:
        rows, total = NotificationSettings.list_for_projects(perms.allowed_codes, page=page, limit=limit)

    return _render(rows, total, page=page, limit=limit, scope_label=scope_label)


@with_database_session
@mcp_permission("view")
def get_notification(notification_id: str) -> str:
    """Get full details of an email notification: event type, trigger or thresholds,
    scope (project, test suite, table group, or scorecard), and recipients.

    Works on any notification, including ``Monitor Alert`` notifications — those are
    created through monitor setup rather than this tool, but can be viewed here.

    Args:
        notification_id: UUID of the notification, e.g. from ``list_notifications``.
    """
    notif = resolve_notification(notification_id)
    return _render_one(notif)


@with_database_session
@mcp_permission("edit")
def create_notification(
    event_type: str,
    recipients: list[str],
    test_suite_id: str | None = None,
    table_group_id: str | None = None,
    scorecard_id: str | None = None,
    trigger_on: str | None = None,
    total_threshold: float | None = None,
    cde_threshold: float | None = None,
) -> str:
    """Create an email notification for a test-run, profiling-run, or score-drop event.

    Every invalid input is surfaced in a single error so the call can be corrected
    in one round-trip — no partial save occurs.

    Args:
        event_type: The event that triggers the notification. One of
            ``Test Run``, ``Profiling Run``, ``Score Drop``. ``Monitor Alert``
            notifications are configured in the TestGen UI and cannot be created
            here; ``update_notification`` can still modify them once they exist.
        recipients: One or more well-formed email addresses to notify.
        test_suite_id: UUID of the test suite, e.g. from ``list_test_suites``.
            Required when ``event_type`` is ``Test Run``; rejected otherwise.
        table_group_id: UUID of the table group, e.g. from ``get_data_inventory``.
            Required when ``event_type`` is ``Profiling Run``; rejected otherwise.
        scorecard_id: UUID of the scorecard, e.g. from ``list_scorecards``.
            Required when ``event_type`` is ``Score Drop``; rejected otherwise.
        trigger_on: When to fire the notification. Only used for ``Test Run``
            and ``Profiling Run``; rejected for ``Score Drop``.
            For ``Test Run`` (default ``On test failures``): one of ``Always``,
            ``On test failures``, ``On test failures and warnings``,
            ``On new test failures and warnings``.
            For ``Profiling Run`` (default ``On new hygiene issues``): one of
            ``Always``, ``On new hygiene issues``.
        total_threshold: Score-drop trigger for the total score (over 0, up to 100).
            Only used for ``Score Drop``; at least one of ``total_threshold`` or
            ``cde_threshold`` must be supplied.
        cde_threshold: Score-drop trigger for the critical-data-element score
            (over 0, up to 100). Only used for ``Score Drop``.
    """
    event = _parse_event_type(event_type)

    if event is NotificationEvent.test_run:
        _enforce_scope_shape(
            event_type,
            required=("test_suite_id", test_suite_id),
            forbidden=(("table_group_id", table_group_id), ("scorecard_id", scorecard_id)),
        )
        _reject_threshold_args(event_type, total_threshold, cde_threshold)
        suite = resolve_test_suite(test_suite_id)
        clean_recipients = _validate_recipients(recipients)
        trigger = _parse_test_run_trigger(trigger_on)
        notif = TestRunNotificationSettings.create(
            project_code=suite.project_code,
            test_suite_id=suite.id,
            recipients=clean_recipients,
            trigger=trigger,
        )
    elif event is NotificationEvent.profiling_run:
        _enforce_scope_shape(
            event_type,
            required=("table_group_id", table_group_id),
            forbidden=(("test_suite_id", test_suite_id), ("scorecard_id", scorecard_id)),
        )
        _reject_threshold_args(event_type, total_threshold, cde_threshold)
        tg = resolve_table_group(table_group_id)
        clean_recipients = _validate_recipients(recipients)
        trigger = _parse_profiling_run_trigger(trigger_on)
        notif = ProfilingRunNotificationSettings.create(
            project_code=tg.project_code,
            table_group_id=tg.id,
            recipients=clean_recipients,
            trigger=trigger,
        )
    else:
        # NotificationEvent.score_drop — _parse_event_type rejected anything else.
        _enforce_scope_shape(
            event_type,
            required=("scorecard_id", scorecard_id),
            forbidden=(("test_suite_id", test_suite_id), ("table_group_id", table_group_id)),
        )
        if trigger_on is not None:
            raise MCPUserError(
                f"`trigger_on` is not supported for event type `{event_type}` — thresholds drive the event."
            )
        scorecard = resolve_scorecard(scorecard_id)
        _validate_score_thresholds(total_threshold, cde_threshold)
        clean_recipients = _validate_recipients(recipients)
        notif = ScoreDropNotificationSettings.create(
            project_code=scorecard.project_code,
            score_definition_id=scorecard.id,
            recipients=clean_recipients,
            total_score_threshold=total_threshold,
            cde_score_threshold=cde_threshold,
        )

    return _render_created(notif)


# --- create_notification helpers ---


def _parse_event_type(value: str) -> NotificationEvent:
    """Map the supplied display label to its ``NotificationEvent``.

    Rejects anything outside the create-supported subset (test_run / profiling_run /
    score_drop) — including the otherwise-valid ``Monitor Alert`` event. Raises
    ``MCPUserError`` listing every supported display label.
    """
    label: NotificationEventLabel | None
    try:
        label = NotificationEventLabel(value)
    except ValueError:
        label = None
    event = NOTIFICATION_EVENT_LABEL_TO_INTERNAL.get(label) if label is not None else None
    if event not in _CREATE_SUPPORTED_EVENTS:
        valid = ", ".join(f"`{format_notification_event(e)}`" for e in _CREATE_SUPPORTED_EVENTS)
        raise MCPUserError(f"Invalid `event_type` `{value}`. Valid values: {valid}.")
    return event


def _enforce_scope_shape(
    event_type: str,
    *,
    required: tuple[str, str | None],
    forbidden: tuple[tuple[str, str | None], ...],
) -> None:
    """Reject missing-required or any forbidden scope args for the chosen event."""
    required_name, required_value = required
    if not required_value:
        raise MCPUserError(f"`{required_name}` is required for event type `{event_type}`.")
    supplied_forbidden = [name for name, value in forbidden if value]
    if supplied_forbidden:
        joined = ", ".join(f"`{name}`" for name in supplied_forbidden)
        raise MCPUserError(f"{joined} not supported for event type `{event_type}`. Use only `{required_name}`.")


def _reject_threshold_args(
    event_type: str,
    total_threshold: float | None,
    cde_threshold: float | None,
) -> None:
    """Reject ``total_threshold`` / ``cde_threshold`` on non-score events."""
    stray = [
        name
        for name, value in (
            ("total_threshold", total_threshold),
            ("cde_threshold", cde_threshold),
        )
        if value is not None
    ]
    if stray:
        joined = ", ".join(f"`{name}`" for name in stray)
        raise MCPUserError(
            f"{joined} not supported for event type `{event_type}`. "
            "Only `Score Drop` notifications use score thresholds."
        )


def _validate_recipients(recipients: list[str]) -> list[str]:
    """Return the recipients list after batch-validating every entry.

    Raises ``MCPUserError`` if the list is empty or contains any malformed address —
    every bad address is named in the single error message so the caller can fix
    them all in one round-trip.
    """
    if not recipients:
        raise MCPUserError("`recipients` must contain at least one email address.")
    invalid = [addr for addr in recipients if not is_valid_email(addr)]
    if invalid:
        joined = ", ".join(f"`{addr}`" for addr in invalid)
        raise MCPUserError(f"Invalid email addresses: {joined}.")
    return list(recipients)


def _parse_test_run_trigger(value: str | None) -> TestRunNotificationTrigger:
    if value is None:
        return TestRunNotificationTrigger.on_failures
    try:
        label = TestRunTriggerLabel(value)
    except ValueError as err:
        valid = ", ".join(f"`{label.value}`" for label in TestRunTriggerLabel)
        raise MCPUserError(
            f"Invalid `trigger_on` `{value}` for event type `Test Run`. Valid values: {valid}."
        ) from err
    return TEST_RUN_TRIGGER_LABEL_TO_INTERNAL[label]


def _parse_profiling_run_trigger(value: str | None) -> ProfilingRunNotificationTrigger:
    if value is None:
        return ProfilingRunNotificationTrigger.on_changes
    try:
        label = ProfilingRunTriggerLabel(value)
    except ValueError as err:
        valid = ", ".join(f"`{label.value}`" for label in ProfilingRunTriggerLabel)
        raise MCPUserError(
            f"Invalid `trigger_on` `{value}` for event type `Profiling Run`. Valid values: {valid}."
        ) from err
    return PROFILING_RUN_TRIGGER_LABEL_TO_INTERNAL[label]


def _validate_score_thresholds(
    total_threshold: float | None,
    cde_threshold: float | None,
) -> None:
    """Reject missing-or-out-of-range thresholds for a score-drop notification.

    Surfaces every range violation in a single error.
    """
    if total_threshold is None and cde_threshold is None:
        raise MCPUserError(
            "At least one of `total_threshold` or `cde_threshold` must be set for event type `Score Drop`."
        )
    _validate_threshold_range(total_threshold, cde_threshold)


def _validate_threshold_range(
    total_threshold: float | None,
    cde_threshold: float | None,
) -> None:
    """Reject any out-of-range threshold value; surface every offender in one error.

    0 is rejected: a score can never drop below 0, so a 0 threshold would never fire.
    """
    range_errors = []
    for name, value in (("total_threshold", total_threshold), ("cde_threshold", cde_threshold)):
        if value is not None and not 0 < value <= 100:
            range_errors.append(f"`{name}` = {value} (must be greater than 0 and at most 100)")
    if range_errors:
        raise MCPUserError("Score threshold out of range: " + "; ".join(range_errors) + ".")


def _parse_monitor_trigger(value: str | None) -> MonitorNotificationTrigger:
    if value is None:
        return MonitorNotificationTrigger.on_anomalies
    try:
        label = MonitorTriggerLabel(value)
    except ValueError as err:
        valid = ", ".join(f"`{label.value}`" for label in MonitorTriggerLabel)
        raise MCPUserError(
            f"Invalid `trigger_on` `{value}` for event type `Monitor Alert`. Valid values: {valid}."
        ) from err
    return MONITOR_TRIGGER_LABEL_TO_INTERNAL[label]


@with_database_session
@mcp_permission("edit")
def update_notification(
    notification_id: str,
    *,
    enabled: bool | None = None,
    recipients: list[str] | None = None,
    trigger_on: str | None = None,
    total_threshold: float | None = None,
    cde_threshold: float | None = None,
    clear_total_threshold: bool = False,
    clear_cde_threshold: bool = False,
    table_name: str | None = None,
    clear_table_name: bool = False,
) -> str:
    """Update fields on an existing email notification. Pass only the fields to change.

    Works on any notification, including ``Monitor Alert`` notifications — those are
    created through monitor setup rather than this tool, but can be updated here.

    Every invalid input surfaces in a single error before any save — no partial save.
    The notification's event type and scope entity are immutable through this tool;
    delete and recreate to change them. (A Monitor Alert's optional table — a finer
    scope within its table group — can still be set or cleared here.)

    Args:
        notification_id: UUID of the notification, e.g. from ``list_notifications``.
        enabled: ``True`` to resume, ``False`` to pause. Omit to leave unchanged.
        recipients: Replace the recipient list with the supplied addresses (one or more
            well-formed emails). Omit to leave unchanged.
        trigger_on: New trigger condition. Only valid for ``Test Run``, ``Profiling Run``,
            and ``Monitor Alert`` notifications; rejected for ``Score Drop``.
            For ``Test Run``: one of ``Always``, ``On test failures``,
            ``On test failures and warnings``, ``On new test failures and warnings``.
            For ``Profiling Run``: one of ``Always``, ``On new hygiene issues``.
            For ``Monitor Alert``: ``On anomalies`` is the only supported value, so
            this field cannot meaningfully be changed on Monitor Alert notifications.
        total_threshold: New total score threshold (over 0, up to 100). Only valid for
            ``Score Drop`` notifications.
        cde_threshold: New critical-data-element score threshold (over 0, up to 100). Only valid
            for ``Score Drop`` notifications.
        clear_total_threshold: ``True`` to clear the overall-score threshold (set to
            NULL). At least one threshold must remain set after the call.
        clear_cde_threshold: ``True`` to clear the CDE-score threshold. At least one
            threshold must remain set after the call.
        table_name: Narrow a Monitor Alert notification's scope to a single table within
            its table group. Only valid for ``Monitor Alert`` notifications.
        clear_table_name: ``True`` to drop an existing table from a Monitor Alert
            notification (notifications then fire for any table in the table group).
    """
    if (
        enabled is None
        and recipients is None
        and trigger_on is None
        and total_threshold is None
        and cde_threshold is None
        and not clear_total_threshold
        and not clear_cde_threshold
        and table_name is None
        and not clear_table_name
    ):
        raise MCPUserError("No fields supplied to update.")

    notif = resolve_notification(notification_id)
    event = notif.event
    event_label = format_notification_event(event)

    _reject_event_stray_args(
        event,
        event_label,
        trigger_on=trigger_on,
        total_threshold=total_threshold,
        cde_threshold=cde_threshold,
        clear_total_threshold=clear_total_threshold,
        clear_cde_threshold=clear_cde_threshold,
        table_name=table_name,
        clear_table_name=clear_table_name,
    )

    _reject_set_and_clear_conflicts(
        total_threshold=total_threshold,
        clear_total_threshold=clear_total_threshold,
        cde_threshold=cde_threshold,
        clear_cde_threshold=clear_cde_threshold,
        table_name=table_name,
        clear_table_name=clear_table_name,
    )

    clean_recipients: list[str] | None = None
    if recipients is not None:
        clean_recipients = _validate_recipients(recipients)

    parsed_trigger = None
    if trigger_on is not None:
        if event is NotificationEvent.test_run:
            parsed_trigger = _parse_test_run_trigger(trigger_on)
        elif event is NotificationEvent.profiling_run:
            parsed_trigger = _parse_profiling_run_trigger(trigger_on)
        elif event is NotificationEvent.monitor_run:
            parsed_trigger = _parse_monitor_trigger(trigger_on)

    if event is NotificationEvent.score_drop:
        _validate_threshold_range(total_threshold, cde_threshold)
        _validate_score_drop_post_state(
            notif,
            total_threshold=total_threshold,
            cde_threshold=cde_threshold,
            clear_total_threshold=clear_total_threshold,
            clear_cde_threshold=clear_cde_threshold,
        )

    pending = _build_pending(
        notif,
        enabled=enabled,
        recipients=clean_recipients,
        trigger=parsed_trigger,
        total_threshold=total_threshold,
        cde_threshold=cde_threshold,
        clear_total_threshold=clear_total_threshold,
        clear_cde_threshold=clear_cde_threshold,
        table_name=table_name,
        clear_table_name=clear_table_name,
    )

    doc = MdDoc()
    doc.heading(1, f"{event_label} Notification updated")
    doc.field("Notification ID", notif.id, code=True)

    if not pending:
        doc.text("No fields changed — supplied values matched the current state.")
        return doc.render()

    before = {attr: _snapshot_attr(notif, attr) for attr in pending}
    for attr, value in pending.items():
        setattr(notif, attr, value)
    after = {attr: _snapshot_attr(notif, attr) for attr in pending}

    notif.save()

    rows = [[_DIFF_LABELS[attr], before[attr], after[attr]] for attr in pending]
    doc.table(["Field", "Before", "After"], rows)
    return doc.render()


# --- update_notification helpers ---


_DIFF_LABELS: dict[str, str] = {
    "enabled": "Status",
    "recipients": "Recipients",
    "trigger": "Trigger",
    "total_score_threshold": "Total Score Threshold",
    "cde_score_threshold": "CDE Score Threshold",
    "table_name": "Table",
}


def _reject_event_stray_args(
    event: NotificationEvent,
    event_label: str,
    *,
    trigger_on: str | None,
    total_threshold: float | None,
    cde_threshold: float | None,
    clear_total_threshold: bool,
    clear_cde_threshold: bool,
    table_name: str | None,
    clear_table_name: bool,
) -> None:
    """Reject args that are meaningless for the resolved event.

    Collects every stray arg into a single ``MCPUserError`` so the caller can fix
    them all in one round-trip. The message names the relevant supported event
    for each stray so the LLM knows where each arg actually applies.
    """
    threshold_strays = [
        name
        for name, supplied in (
            ("total_threshold", total_threshold is not None),
            ("cde_threshold", cde_threshold is not None),
            ("clear_total_threshold", clear_total_threshold),
            ("clear_cde_threshold", clear_cde_threshold),
        )
        if supplied
    ]
    table_strays = [
        name
        for name, supplied in (
            ("table_name", table_name is not None),
            ("clear_table_name", clear_table_name),
        )
        if supplied
    ]

    messages: list[str] = []
    if event is NotificationEvent.score_drop:
        if trigger_on is not None:
            messages.append(
                f"`trigger_on` is not supported for event type `{event_label}` — thresholds drive the event."
            )
        if table_strays:
            joined = ", ".join(f"`{name}`" for name in table_strays)
            messages.append(
                f"{joined} not supported for event type `{event_label}`. "
                "Only `Monitor Alert` notifications can be scoped to a table."
            )
    else:
        if threshold_strays:
            joined = ", ".join(f"`{name}`" for name in threshold_strays)
            messages.append(
                f"{joined} not supported for event type `{event_label}`. "
                "Only `Score Drop` notifications use score thresholds."
            )
        if event is not NotificationEvent.monitor_run and table_strays:
            joined = ", ".join(f"`{name}`" for name in table_strays)
            messages.append(
                f"{joined} not supported for event type `{event_label}`. "
                "Only `Monitor Alert` notifications can be scoped to a table."
            )

    if messages:
        raise MCPUserError(" ".join(messages))


def _reject_set_and_clear_conflicts(
    *,
    total_threshold: float | None,
    clear_total_threshold: bool,
    cde_threshold: float | None,
    clear_cde_threshold: bool,
    table_name: str | None,
    clear_table_name: bool,
) -> None:
    """Reject any (set, clear) pair where the caller supplied both for the same field."""
    conflicts = [
        name
        for name, set_supplied, clear_supplied in (
            ("total_threshold", total_threshold is not None, clear_total_threshold),
            ("cde_threshold", cde_threshold is not None, clear_cde_threshold),
            ("table_name", table_name is not None, clear_table_name),
        )
        if set_supplied and clear_supplied
    ]
    if conflicts:
        joined = ", ".join(f"`{name}`" for name in conflicts)
        raise MCPUserError(f"{joined} cannot be both set and cleared in the same call.")


def _validate_score_drop_post_state(
    notif: NotificationSettings,
    *,
    total_threshold: float | None,
    cde_threshold: float | None,
    clear_total_threshold: bool,
    clear_cde_threshold: bool,
) -> None:
    """Pre-empt model.save()'s "at least one threshold" invariant.

    Compute the effective threshold values that would result from applying the
    pending change and reject up-front if both would be NULL.
    """
    if clear_total_threshold:
        effective_total = None
    elif total_threshold is not None:
        effective_total = total_threshold
    else:
        effective_total = notif.total_score_threshold

    if clear_cde_threshold:
        effective_cde = None
    elif cde_threshold is not None:
        effective_cde = cde_threshold
    else:
        effective_cde = notif.cde_score_threshold

    if effective_total is None and effective_cde is None:
        raise MCPUserError(
            "At least one of `total_threshold` or `cde_threshold` must remain set "
            "for a `Score Drop` notification."
        )


def _build_pending(
    notif: NotificationSettings,
    *,
    enabled: bool | None,
    recipients: list[str] | None,
    trigger: object,
    total_threshold: float | None,
    cde_threshold: float | None,
    clear_total_threshold: bool,
    clear_cde_threshold: bool,
    table_name: str | None,
    clear_table_name: bool,
) -> dict[str, object]:
    """Return only the changes that actually differ from the current state."""
    pending: dict[str, object] = {}

    if enabled is not None and notif.enabled != enabled:
        pending["enabled"] = enabled

    if recipients is not None and list(notif.recipients or []) != recipients:
        pending["recipients"] = recipients

    if trigger is not None and notif.trigger != trigger:
        pending["trigger"] = trigger

    if clear_total_threshold and notif.total_score_threshold is not None:
        pending["total_score_threshold"] = None
    elif total_threshold is not None and notif.total_score_threshold != total_threshold:
        pending["total_score_threshold"] = total_threshold

    if clear_cde_threshold and notif.cde_score_threshold is not None:
        pending["cde_score_threshold"] = None
    elif cde_threshold is not None and notif.cde_score_threshold != cde_threshold:
        pending["cde_score_threshold"] = cde_threshold

    if clear_table_name and notif.table_name is not None:
        pending["table_name"] = None
    elif table_name is not None and notif.table_name != table_name:
        pending["table_name"] = table_name

    return pending


def _snapshot_attr(notif: NotificationSettings, attr: str) -> object:
    """Render a single attribute's current value in display form for the diff table."""
    if attr == "enabled":
        return "Active" if notif.enabled else "Paused"
    if attr == "recipients":
        return ", ".join(notif.recipients or []) or None
    if attr == "trigger":
        return _label_for_trigger(notif.event, notif.trigger)
    if attr == "total_score_threshold":
        return _format_threshold(notif.total_score_threshold)
    if attr == "cde_score_threshold":
        return _format_threshold(notif.cde_score_threshold)
    if attr == "table_name":
        return notif.table_name or None
    return None


def _label_for_trigger(event: NotificationEvent, trigger: object) -> str | None:
    """Render the user-facing label for an in-memory trigger enum value."""
    if trigger is None:
        return None
    if event is NotificationEvent.test_run and isinstance(trigger, TestRunNotificationTrigger):
        return format_notification_trigger(event, {"trigger": trigger.value})
    if event is NotificationEvent.profiling_run and isinstance(trigger, ProfilingRunNotificationTrigger):
        return format_notification_trigger(event, {"trigger": trigger.value})
    if event is NotificationEvent.monitor_run and isinstance(trigger, MonitorNotificationTrigger):
        return format_notification_trigger(event, {"trigger": trigger.value})
    return None


def _format_threshold(value: object) -> str | None:
    """Render a stored Decimal threshold (or an in-memory float/int) as a display string."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


@with_database_session
@mcp_permission("edit")
def delete_notification(notification_id: str) -> str:
    """Delete an email notification.

    Works on any notification, including ``Monitor Alert`` notifications — those are
    created through monitor setup rather than this tool, but can be deleted here.

    Args:
        notification_id: UUID of the notification, e.g. from ``list_notifications``.
    """
    notif = resolve_notification(notification_id)
    event_label = format_notification_event(notif.event)

    doc = MdDoc()
    doc.heading(1, f"{event_label} Notification deleted")
    doc.field("Notification ID", notif.id, code=True)
    doc.field("Event Type", event_label)
    doc.field("Project", notif.project_code, code=True)
    _render_scope_fields(doc, notif)

    notif.delete()

    return doc.render()


def _render_one(notif: NotificationSettings) -> str:
    doc = MdDoc()
    event_label = format_notification_event(notif.event)
    doc.heading(1, f"{event_label} Notification")
    _render_notification_body(doc, notif)
    return doc.render()


def _render_created(notif: NotificationSettings) -> str:
    doc = MdDoc()
    event_label = format_notification_event(notif.event)
    doc.heading(1, f"{event_label} Notification created")
    _render_notification_body(doc, notif)
    return doc.render()


def _render_notification_body(doc: MdDoc, notif: NotificationSettings) -> None:
    event_label = format_notification_event(notif.event)
    status_word = "Active" if notif.enabled else "Paused"

    doc.heading(2, "Configuration")
    doc.field("Notification ID", notif.id, code=True)
    doc.field("Event Type", event_label)
    doc.field("Status", status_word)
    if trigger_label := format_notification_trigger(notif.event, notif.settings):
        doc.field("Trigger", trigger_label)
    if notif.event == NotificationEvent.score_drop:
        total_threshold = (notif.settings or {}).get("total_threshold")
        cde_threshold = (notif.settings or {}).get("cde_threshold")
        if total_threshold is not None:
            doc.field("Total Score Threshold", total_threshold)
        if cde_threshold is not None:
            doc.field("CDE Score Threshold", cde_threshold)

    doc.heading(2, "Scope")
    doc.field("Project", notif.project_code, code=True)
    _render_scope_fields(doc, notif)

    doc.heading(2, "Recipients")
    if notif.recipients:
        doc.bullets(list(notif.recipients))
    else:
        doc.text("_No recipients configured._")


class _ScopeEntityKind(StrEnum):
    SUITE = "suite"
    TABLE_GROUP = "table_group"
    SCORECARD = "scorecard"


@dataclass(frozen=True)
class _ScopeField:
    label: str
    id_attr: str
    all_label: str
    kind: _ScopeEntityKind


_SUITE_FIELD = _ScopeField("Test Suite", "test_suite_id", "All Test Suites", _ScopeEntityKind.SUITE)
_TABLE_GROUP_FIELD = _ScopeField("Table Group", "table_group_id", "All Table Groups", _ScopeEntityKind.TABLE_GROUP)
_SCORECARD_FIELD = _ScopeField("Scorecard", "score_definition_id", "All Scorecards", _ScopeEntityKind.SCORECARD)

# Single source of truth: which scope entities (and labels) each event renders.
# Both the detail view (_render_scope_fields) and the list view (_scope_text) iterate this.
# Monitors are scoped to their table group only — the underlying monitor test suite is an
# internal detail that is never surfaced. An optional table narrows the scope further (see
# the monitor ``table_name`` handling in both renderers).
_SCOPE_FIELDS: dict[NotificationEvent, tuple[_ScopeField, ...]] = {
    NotificationEvent.test_run: (_SUITE_FIELD,),
    NotificationEvent.profiling_run: (_TABLE_GROUP_FIELD,),
    NotificationEvent.score_drop: (_SCORECARD_FIELD,),
    NotificationEvent.monitor_run: (_TABLE_GROUP_FIELD,),
}


def _render_scope_fields(doc: MdDoc, notif: NotificationSettings) -> None:
    for field in _SCOPE_FIELDS.get(notif.event, ()):
        entity_id = getattr(notif, field.id_attr)
        name = _resolve_scope_name(field.kind, entity_id)
        doc.field(field.label, _scope_value(name, entity_id, field.all_label))
    if notif.event == NotificationEvent.monitor_run and (table_name := (notif.settings or {}).get("table_name")):
        doc.field("Table", table_name)


def _resolve_scope_name(kind: _ScopeEntityKind, entity_id: UUID | None) -> str | None:
    if kind is _ScopeEntityKind.SUITE:
        return _suite_name(entity_id)
    if kind is _ScopeEntityKind.TABLE_GROUP:
        return _table_group_name(entity_id)
    return _scorecard_name(entity_id)


def _scope_value(name: str | None, entity_id: UUID | None, project_wide_label: str) -> str:
    if entity_id is None:
        return project_wide_label
    display = name or str(entity_id)
    return f"{display} ({MdDoc.code(str(entity_id))})"


def _suite_name(suite_id: UUID | None) -> str | None:
    if suite_id is None:
        return None
    suite = TestSuite.get(suite_id)
    return suite.test_suite if suite else None


def _table_group_name(tg_id: UUID | None) -> str | None:
    if tg_id is None:
        return None
    tg = TableGroup.get(tg_id)
    return tg.table_groups_name if tg else None


def _scorecard_name(score_id: UUID | None) -> str | None:
    if score_id is None:
        return None
    sd = ScoreDefinition.get(str(score_id))
    return sd.name if sd else None


def _render(
    rows: list[NotificationSummary],
    total: int,
    *,
    page: int,
    limit: int,
    scope_label: str | None,
) -> str:
    doc = MdDoc()
    heading = f"Email Notifications — {scope_label}" if scope_label else "Email Notifications"
    doc.heading(1, heading)

    if not rows:
        doc.text("_No notifications match the supplied scope._")
        return doc.render()

    if info := format_page_info(total, page, limit):
        doc.text(info)

    suite_names = _batch_suite_names({r.test_suite_id for r in rows if r.test_suite_id})
    tg_names = _batch_table_group_names({r.table_group_id for r in rows if r.table_group_id})
    score_names = _batch_score_names({r.score_definition_id for r in rows if r.score_definition_id})

    for r in rows:
        status_word = "Active" if r.enabled else "Paused"
        event_label = format_notification_event(r.event)
        scope_text = _scope_text(r, suite_names, tg_names, score_names)
        doc.heading(2, f"[{status_word}] {event_label} Notification — {scope_text}")
        doc.field("Notification ID", r.id, code=True)
        doc.field("Event Type", event_label)
        doc.field("Status", status_word)
        doc.field("Project", r.project_code, code=True)
        doc.field("Scope", scope_text)
        if trigger_label := format_notification_trigger(r.event, r.settings):
            doc.field("Trigger", trigger_label)
        if r.event == NotificationEvent.score_drop:
            total_threshold = (r.settings or {}).get("total_threshold")
            cde_threshold = (r.settings or {}).get("cde_threshold")
            if total_threshold is not None:
                doc.field("Total Score Threshold", total_threshold)
            if cde_threshold is not None:
                doc.field("CDE Score Threshold", cde_threshold)
        doc.field("Recipients", ", ".join(r.recipients or []) or None)

    if footer := format_page_footer(total, page, limit):
        doc.text(footer)

    return doc.render()


def _scope_text(
    row: NotificationSummary,
    suite_names: dict[UUID, str],
    tg_names: dict[UUID, str],
    score_names: dict[UUID, str],
) -> str:
    batches = {
        _ScopeEntityKind.SUITE: suite_names,
        _ScopeEntityKind.TABLE_GROUP: tg_names,
        _ScopeEntityKind.SCORECARD: score_names,
    }
    fields = _SCOPE_FIELDS.get(row.event, ())
    if not fields:
        return "—"
    # A project-wide entity reads as a bare label, e.g. "All Table Groups".
    parts = []
    for field in fields:
        entity_id = getattr(row, field.id_attr)
        if entity_id is None:
            parts.append(field.all_label)
        else:
            parts.append(f"{field.label}: {batches[field.kind].get(entity_id, str(entity_id))}")
    if row.event == NotificationEvent.monitor_run and (table_name := (row.settings or {}).get("table_name")):
        parts.append(f"Table: {table_name}")
    return " · ".join(parts)


def _batch_suite_names(suite_ids: set[UUID]) -> dict[UUID, str]:
    if not suite_ids:
        return {}
    return {s.id: s.test_suite for s in TestSuite.select_minimal_where(TestSuite.id.in_(list(suite_ids)))}


def _batch_table_group_names(tg_ids: set[UUID]) -> dict[UUID, str]:
    if not tg_ids:
        return {}
    return {tg.id: tg.table_groups_name for tg in TableGroup.select_minimal_where(TableGroup.id.in_(list(tg_ids)))}


def _batch_score_names(score_ids: set[UUID]) -> dict[UUID, str]:
    if not score_ids:
        return {}
    return ScoreDefinition.names_by_id(score_ids)
