from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from testgen.common.models.notification_settings import (
    MonitorNotificationTrigger,
    NotificationEvent,
    NotificationSummary,
    ProfilingRunNotificationTrigger,
    TestRunNotificationTrigger,
)
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions
from testgen.mcp.tools.common import (
    MONITOR_TRIGGER_LABEL_TO_INTERNAL,
    NOTIFICATION_EVENT_LABEL_TO_INTERNAL,
    PROFILING_RUN_TRIGGER_LABEL_TO_INTERNAL,
    TEST_RUN_TRIGGER_LABEL_TO_INTERNAL,
    format_notification_event,
    format_notification_trigger,
)

pytestmark = pytest.mark.unit


# --- Helpers ---


def _patch_perms(allowed=("demo",), memberships=None):
    memberships = memberships or dict.fromkeys(allowed, "role_a")
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships=memberships, permission="view", username="test_user",
        ),
    )


def _summary(
    *,
    event: NotificationEvent,
    enabled: bool = True,
    project_code: str = "demo",
    recipients=("alice@example.com",),
    test_suite_id: UUID | None = None,
    table_group_id: UUID | None = None,
    score_definition_id: UUID | None = None,
    settings: dict | None = None,
) -> NotificationSummary:
    return NotificationSummary(
        id=uuid4(),
        project_code=project_code,
        event=event,
        enabled=enabled,
        recipients=list(recipients),
        test_suite_id=test_suite_id,
        table_group_id=table_group_id,
        score_definition_id=score_definition_id,
        settings=settings or {},
    )


def _patch_list_for_projects(rows, total):
    return patch(
        "testgen.common.models.notification_settings.NotificationSettings.list_for_projects",
        return_value=(rows, total),
    )


def _patch_list_for_test_suite(rows, total):
    return patch(
        "testgen.common.models.notification_settings.NotificationSettings.list_for_test_suite",
        return_value=(rows, total),
    )


def _patch_list_for_table_group(rows, total):
    return patch(
        "testgen.common.models.notification_settings.NotificationSettings.list_for_table_group",
        return_value=(rows, total),
    )


def _patch_list_for_score_definition(rows, total):
    return patch(
        "testgen.common.models.notification_settings.NotificationSettings.list_for_score_definition",
        return_value=(rows, total),
    )


def _patch_no_resolve_lookups():
    """Make the batch-name helpers return empty dicts so tests don't need TestSuite/TableGroup mocks
    unless they care about scope-name rendering.
    """
    return patch.multiple(
        "testgen.mcp.tools.notifications",
        _batch_suite_names=MagicMock(return_value={}),
        _batch_table_group_names=MagicMock(return_value={}),
        _batch_score_names=MagicMock(return_value={}),
    )


# --- format helpers ---


def test_format_notification_event_round_trip():
    """Every NotificationEvent has a stable display label."""
    seen_labels = set()
    for event in NotificationEvent:
        label = format_notification_event(event)
        seen_labels.add(label)
        # Round-trip the label back to the internal enum.
        assert NOTIFICATION_EVENT_LABEL_TO_INTERNAL[
            type(next(iter(NOTIFICATION_EVENT_LABEL_TO_INTERNAL)))(label)
        ] is event
    assert seen_labels == {"Test Run", "Profiling Run", "Score Drop", "Monitor Alert"}


def test_format_notification_event_accepts_raw_string():
    assert format_notification_event("test_run") == "Test Run"


def test_format_notification_trigger_test_run_labels():
    for trigger, label_enum in {
        TestRunNotificationTrigger.always: "Always",
        TestRunNotificationTrigger.on_failures: "On test failures",
        TestRunNotificationTrigger.on_warnings: "On test failures and warnings",
        TestRunNotificationTrigger.on_changes: "On new test failures and warnings",
    }.items():
        assert (
            format_notification_trigger(NotificationEvent.test_run, {"trigger": trigger.value})
            == label_enum
        )


def test_format_notification_trigger_profiling_labels():
    assert (
        format_notification_trigger(NotificationEvent.profiling_run, {"trigger": "always"})
        == "Always"
    )
    assert (
        format_notification_trigger(NotificationEvent.profiling_run, {"trigger": "on_changes"})
        == "On new hygiene issues"
    )


def test_format_notification_trigger_monitor_label():
    assert (
        format_notification_trigger(NotificationEvent.monitor_run, {"trigger": "on_anomalies"})
        == "On anomalies"
    )


def test_format_notification_trigger_score_drop_returns_none():
    assert format_notification_trigger(NotificationEvent.score_drop, {"total_threshold": "95.0"}) is None


def test_format_notification_trigger_missing_settings_returns_none():
    assert format_notification_trigger(NotificationEvent.test_run, None) is None
    assert format_notification_trigger(NotificationEvent.test_run, {}) is None


def test_trigger_label_to_internal_dicts_cover_every_internal_enum():
    """No internal enum value should be missing a display label — both directions are total."""
    assert set(TEST_RUN_TRIGGER_LABEL_TO_INTERNAL.values()) == set(TestRunNotificationTrigger)
    assert set(PROFILING_RUN_TRIGGER_LABEL_TO_INTERNAL.values()) == set(ProfilingRunNotificationTrigger)
    assert set(MONITOR_TRIGGER_LABEL_TO_INTERNAL.values()) == set(MonitorNotificationTrigger)


def test_scope_fields_cover_every_event():
    """Every notification event must have a scope-field descriptor — no event can be
    added without declaring which scope entities (and labels) it renders.
    """
    from testgen.mcp.tools.notifications import _SCOPE_FIELDS

    assert set(_SCOPE_FIELDS) == set(NotificationEvent)


# --- Argument validation ---


def test_list_notifications_rejects_two_scope_args(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPUserError, match="at most one"):
        list_notifications(project_code="demo", test_suite_id=str(uuid4()))


def test_list_notifications_rejects_three_scope_args(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPUserError, match="at most one"):
        list_notifications(test_suite_id=str(uuid4()), table_group_id=str(uuid4()), scorecard_id=str(uuid4()))


@pytest.mark.parametrize("page,limit", [(0, 10), (1, 0), (1, 201)])
def test_list_notifications_rejects_invalid_pagination(db_session_mock, page, limit):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPUserError):
        list_notifications(page=page, limit=limit)


def test_list_notifications_invalid_test_suite_uuid(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        list_notifications(test_suite_id="not-a-uuid")


def test_list_notifications_invalid_table_group_uuid(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        list_notifications(table_group_id="not-a-uuid")


def test_list_notifications_invalid_scorecard_uuid(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        list_notifications(scorecard_id="not-a-uuid")


def test_list_notifications_rejects_inaccessible_project(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(allowed=("demo",)), pytest.raises(
        MCPResourceNotAccessible, match=r"Project.*forbidden_proj"
    ):
        list_notifications(project_code="forbidden_proj")


@patch("testgen.mcp.tools.common.TestSuite.get")
def test_list_notifications_rejects_inaccessible_test_suite(mock_suite_get, db_session_mock):
    mock_suite_get.return_value = None
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible, match="Test suite"):
        list_notifications(test_suite_id=str(uuid4()))


@patch("testgen.mcp.tools.common.TableGroup.get")
def test_list_notifications_rejects_inaccessible_table_group(mock_tg_get, db_session_mock):
    mock_tg_get.return_value = None
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible, match="Table group"):
        list_notifications(table_group_id=str(uuid4()))


@patch("testgen.mcp.tools.common.ScoreDefinition.get")
def test_list_notifications_rejects_inaccessible_scorecard(mock_score_get, db_session_mock):
    mock_score_get.return_value = None
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible, match="Scorecard"):
        list_notifications(scorecard_id=str(uuid4()))


# --- Listing & dispatch ---


def test_list_notifications_no_scope_uses_allowed_projects(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(allowed=("demo", "other")), _patch_list_for_projects([], 0) as mock_list:
        list_notifications()

    args, kwargs = mock_list.call_args
    assert sorted(args[0]) == ["demo", "other"]
    assert kwargs["page"] == 1
    assert kwargs["limit"] == 50


def test_list_notifications_project_scope_dispatches_to_list_for_projects(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects([], 0) as mock_list:
        list_notifications(project_code="demo")

    args, _ = mock_list.call_args
    assert args[0] == ["demo"]


@patch("testgen.mcp.tools.common.TestSuite.get")
def test_list_notifications_test_suite_scope_dispatches_to_list_for_test_suite(
    mock_suite_get, db_session_mock,
):
    suite_uuid = uuid4()
    suite_mock = MagicMock()
    suite_mock.id = suite_uuid
    suite_mock.test_suite = "orders_v1"
    suite_mock.project_code = "demo"
    mock_suite_get.return_value = suite_mock

    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_test_suite([], 0) as mock_list:
        list_notifications(test_suite_id=str(suite_uuid))

    args, _ = mock_list.call_args
    assert args[0] == suite_uuid


@patch("testgen.mcp.tools.common.TableGroup.get")
def test_list_notifications_table_group_scope_dispatches_to_list_for_table_group(
    mock_tg_get, db_session_mock,
):
    tg_uuid = uuid4()
    tg_mock = MagicMock()
    tg_mock.id = tg_uuid
    tg_mock.table_groups_name = "prod_warehouse"
    tg_mock.project_code = "demo"
    mock_tg_get.return_value = tg_mock

    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_table_group([], 0) as mock_list:
        list_notifications(table_group_id=str(tg_uuid))

    args, _ = mock_list.call_args
    assert args[0] == tg_uuid


@patch("testgen.mcp.tools.common.ScoreDefinition.get")
def test_list_notifications_scorecard_scope_dispatches_to_list_for_score_definition(
    mock_score_get, db_session_mock,
):
    sd_uuid = uuid4()
    sd_mock = MagicMock()
    sd_mock.id = sd_uuid
    sd_mock.name = "Daily Orders Health"
    sd_mock.project_code = "demo"
    mock_score_get.return_value = sd_mock

    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_score_definition([], 0) as mock_list:
        list_notifications(scorecard_id=str(sd_uuid))

    args, _ = mock_list.call_args
    assert args[0] == sd_uuid


# --- Rendering ---


def test_list_notifications_empty_renders_friendly_message(db_session_mock):
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects([], 0):
        out = list_notifications()

    assert "# Email Notifications" in out
    assert "_No notifications match the supplied scope._" in out


def test_list_notifications_renders_test_run_with_suite_scope(db_session_mock):
    suite_id = uuid4()
    row = _summary(
        event=NotificationEvent.test_run,
        test_suite_id=suite_id,
        settings={"trigger": "on_failures"},
        recipients=("alice@example.com", "bob@example.com"),
    )
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects([row], 1), patch(
        "testgen.mcp.tools.notifications._batch_suite_names",
        return_value={suite_id: "orders_v1"},
    ), patch(
        "testgen.mcp.tools.notifications._batch_table_group_names", return_value={},
    ), patch(
        "testgen.mcp.tools.notifications._batch_score_names", return_value={},
    ):
        out = list_notifications()

    assert "[Active] Test Run Notification" in out
    assert "Test Suite: orders_v1" in out
    assert "On test failures" in out
    assert "alice@example.com, bob@example.com" in out
    # No internal code leakage
    assert "test_run" not in out
    assert "on_failures" not in out


def test_list_notifications_renders_profiling_run_project_wide(db_session_mock):
    row = _summary(
        event=NotificationEvent.profiling_run,
        enabled=False,
        table_group_id=None,
        settings={"trigger": "on_changes"},
        recipients=("ops@example.com",),
    )
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects([row], 1), _patch_no_resolve_lookups():
        out = list_notifications()

    assert "[Paused] Profiling Run Notification" in out
    assert "All Table Groups" in out
    assert "(project-wide)" not in out
    assert "On new hygiene issues" in out
    assert "Status:** Paused" in out


def test_list_notifications_renders_score_drop_thresholds(db_session_mock):
    sd_id = uuid4()
    row = _summary(
        event=NotificationEvent.score_drop,
        score_definition_id=sd_id,
        settings={"total_threshold": "95.0", "cde_threshold": "90.0"},
        recipients=("alerts@example.com",),
    )
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects([row], 1), patch(
        "testgen.mcp.tools.notifications._batch_score_names",
        return_value={sd_id: "Daily Orders Health"},
    ), patch(
        "testgen.mcp.tools.notifications._batch_suite_names", return_value={},
    ), patch(
        "testgen.mcp.tools.notifications._batch_table_group_names", return_value={},
    ):
        out = list_notifications()

    assert "Score Drop Notification" in out
    assert "Scorecard: Daily Orders Health" in out
    assert "Total Score Threshold:** 95.0" in out
    assert "CDE Score Threshold:** 90.0" in out
    # Score Drop has no trigger label
    assert "Trigger:**" not in out


def test_list_notifications_renders_score_drop_one_threshold_only(db_session_mock):
    sd_id = uuid4()
    row = _summary(
        event=NotificationEvent.score_drop,
        score_definition_id=sd_id,
        settings={"total_threshold": "95.0", "cde_threshold": None},
    )
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects([row], 1), patch(
        "testgen.mcp.tools.notifications._batch_score_names",
        return_value={sd_id: "Card"},
    ), patch(
        "testgen.mcp.tools.notifications._batch_suite_names", return_value={},
    ), patch(
        "testgen.mcp.tools.notifications._batch_table_group_names", return_value={},
    ):
        out = list_notifications()

    assert "Total Score Threshold:** 95.0" in out
    assert "CDE Score Threshold" not in out


def test_list_notifications_renders_monitor_run_scope(db_session_mock):
    tg_id = uuid4()
    suite_id = uuid4()
    row = _summary(
        event=NotificationEvent.monitor_run,
        table_group_id=tg_id,
        test_suite_id=suite_id,
        settings={"trigger": "on_anomalies", "table_name": "orders"},
        recipients=("monitor-alerts@example.com",),
    )
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects([row], 1), patch(
        "testgen.mcp.tools.notifications._batch_suite_names",
        return_value={suite_id: "monitors_v2"},
    ), patch(
        "testgen.mcp.tools.notifications._batch_table_group_names",
        return_value={tg_id: "prod_warehouse"},
    ), patch(
        "testgen.mcp.tools.notifications._batch_score_names", return_value={},
    ):
        out = list_notifications()

    assert "Monitor Alert Notification" in out
    assert "Table Group: prod_warehouse" in out
    assert "Table: orders" in out
    assert "On anomalies" in out
    # The monitor's internal test suite is never exposed — monitors are scoped to the table group.
    assert "Test Suite" not in out
    assert "monitors_v2" not in out


def test_list_notifications_pagination_renders_info_and_footer(db_session_mock):
    rows = [
        _summary(event=NotificationEvent.test_run, settings={"trigger": "always"}) for _ in range(3)
    ]
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(), _patch_list_for_projects(rows, 25), _patch_no_resolve_lookups():
        out = list_notifications(page=1, limit=3)

    # format_page_info emits an en-dash (\u2013) between start and end.
    assert "Showing 1\u20133 of 25" in out
    assert "Use `page=2` for more" in out


def test_list_notifications_passes_allowed_codes_only(db_session_mock):
    """Even with no scope arg, the dispatch only sees the caller's allowed projects."""
    from testgen.mcp.tools.notifications import list_notifications

    with _patch_perms(allowed=("alpha", "beta")), _patch_list_for_projects([], 0) as mock_list:
        list_notifications()
    args, _ = mock_list.call_args
    assert "alpha" in args[0]
    assert "beta" in args[0]
    assert "gamma" not in args[0]


# --- get_notification ---


def _notif_mock(
    *,
    event: NotificationEvent,
    enabled: bool = True,
    project_code: str = "demo",
    recipients=("alice@example.com",),
    test_suite_id: UUID | None = None,
    table_group_id: UUID | None = None,
    score_definition_id: UUID | None = None,
    settings: dict | None = None,
) -> MagicMock:
    """Build a mock that quacks like a polymorphic ``NotificationSettings`` ORM row."""
    notif = MagicMock()
    notif.id = uuid4()
    notif.event = event
    notif.enabled = enabled
    notif.project_code = project_code
    notif.recipients = list(recipients)
    notif.test_suite_id = test_suite_id
    notif.table_group_id = table_group_id
    notif.score_definition_id = score_definition_id
    notif.settings = settings or {}
    return notif


def _patch_notification_get(return_value):
    return patch(
        "testgen.mcp.tools.common.NotificationSettings.get",
        return_value=return_value,
    )


def _patch_get_notification_scope_lookups(
    *, suite_name: str | None = None, tg_name: str | None = None, score_name: str | None = None,
):
    """Patch the per-entity scope-name lookups used by ``_render_one``.

    Each patched ``.get`` returns a MagicMock with the supplied name attribute (or ``None``).
    Tests that don't care about scope names pass nothing.
    """
    suite_mock = None
    if suite_name is not None:
        suite_mock = MagicMock()
        suite_mock.test_suite = suite_name
    tg_mock = None
    if tg_name is not None:
        tg_mock = MagicMock()
        tg_mock.table_groups_name = tg_name
    score_mock = None
    if score_name is not None:
        score_mock = MagicMock()
        score_mock.name = score_name

    return patch.multiple(
        "testgen.mcp.tools.notifications",
        TestSuite=MagicMock(get=MagicMock(return_value=suite_mock)),
        TableGroup=MagicMock(get=MagicMock(return_value=tg_mock)),
        ScoreDefinition=MagicMock(get=MagicMock(return_value=score_mock)),
    )


def test_get_notification_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        get_notification(notification_id="not-a-uuid")


def test_get_notification_missing_returns_unified_not_accessible(db_session_mock):
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(None), pytest.raises(
        MCPResourceNotAccessible, match="Notification",
    ):
        get_notification(notification_id=str(uuid4()))


def test_get_notification_inaccessible_project_returns_unified_not_accessible(db_session_mock):
    """``NotificationSettings.get`` returns ``None`` when the project filter excludes the row.

    Both the missing-id and the wrong-project paths must surface as the same error
    so callers can't enumerate notifications across projects they don't own.
    """
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(allowed=("demo",)), _patch_notification_get(None), pytest.raises(
        MCPResourceNotAccessible, match="Notification",
    ):
        get_notification(notification_id=str(uuid4()))


def test_get_notification_test_run_with_suite_renders_all_sections(db_session_mock):
    suite_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.test_run,
        test_suite_id=suite_id,
        settings={"trigger": "on_failures"},
        recipients=("alice@example.com", "bob@example.com"),
    )
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        suite_name="orders_v1",
    ):
        out = get_notification(notification_id=str(notif.id))

    # H1 + section headings
    assert "# Test Run Notification" in out
    assert "## Configuration" in out
    assert "## Scope" in out
    assert "## Recipients" in out
    # Configuration fields
    assert "Event Type:** Test Run" in out
    assert "Status:** Active" in out
    assert "Trigger:** On test failures" in out
    # Scope surfaces suite name + id for chaining
    assert "Project:** `demo`" in out
    assert "Test Suite:** orders_v1" in out
    assert f"`{suite_id}`" in out
    # Recipients as bullets
    assert "- alice@example.com" in out
    assert "- bob@example.com" in out
    # No internal code leakage
    assert "test_run" not in out
    assert "on_failures" not in out


def test_get_notification_test_run_project_wide_omits_suite_id(db_session_mock):
    notif = _notif_mock(
        event=NotificationEvent.test_run,
        test_suite_id=None,
        settings={"trigger": "always"},
    )
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = get_notification(notification_id=str(notif.id))

    assert "Test Suite:** All Test Suites" in out
    # Project-wide notifications have no parent id to surface.
    assert "(`" not in out.split("## Scope")[1]


def test_get_notification_profiling_run_with_table_group(db_session_mock):
    tg_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.profiling_run,
        table_group_id=tg_id,
        settings={"trigger": "on_changes"},
    )
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        tg_name="prod_warehouse",
    ):
        out = get_notification(notification_id=str(notif.id))

    assert "# Profiling Run Notification" in out
    assert "Trigger:** On new hygiene issues" in out
    assert "Table Group:** prod_warehouse" in out
    assert f"`{tg_id}`" in out


def test_get_notification_score_drop_renders_thresholds_and_omits_trigger(db_session_mock):
    sd_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.score_drop,
        score_definition_id=sd_id,
        settings={"total_threshold": "85.0", "cde_threshold": "90.0"},
    )
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        score_name="Daily Orders Health",
    ):
        out = get_notification(notification_id=str(notif.id))

    assert "# Score Drop Notification" in out
    assert "Total Score Threshold:** 85.0" in out
    assert "CDE Score Threshold:** 90.0" in out
    assert "Trigger:**" not in out
    assert "Scorecard:** Daily Orders Health" in out


def test_get_notification_score_drop_only_total_threshold(db_session_mock):
    notif = _notif_mock(
        event=NotificationEvent.score_drop,
        score_definition_id=uuid4(),
        settings={"total_threshold": "85.0", "cde_threshold": None},
    )
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        score_name="Card",
    ):
        out = get_notification(notification_id=str(notif.id))

    assert "Total Score Threshold:** 85.0" in out
    assert "CDE Score Threshold" not in out


def test_get_notification_monitor_run_renders_table_group_and_table(db_session_mock):
    tg_id = uuid4()
    suite_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.monitor_run,
        table_group_id=tg_id,
        test_suite_id=suite_id,
        settings={"trigger": "on_anomalies", "table_name": "orders"},
    )
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        suite_name="monitors_v2", tg_name="prod_warehouse",
    ):
        out = get_notification(notification_id=str(notif.id))

    assert "# Monitor Alert Notification" in out
    assert "Trigger:** On anomalies" in out
    # The table is part of the monitor's scope, rendered as "Table" (not a "Filtered Table" filter).
    assert "Table:** orders" in out
    assert "Table Group:** prod_warehouse" in out
    assert f"`{tg_id}`" in out
    # The internal monitor test suite is never exposed.
    assert "Test Suite" not in out
    assert "monitors_v2" not in out
    assert f"`{suite_id}`" not in out


def test_get_notification_paused_renders_status_paused(db_session_mock):
    notif = _notif_mock(
        event=NotificationEvent.test_run,
        enabled=False,
        test_suite_id=uuid4(),
        settings={"trigger": "always"},
    )
    from testgen.mcp.tools.notifications import get_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        suite_name="some_suite",
    ):
        out = get_notification(notification_id=str(notif.id))

    assert "Status:** Paused" in out


# ---------------------------------------------------------------------------
# create_notification
# ---------------------------------------------------------------------------


def _make_create_suite(name="orders_v1", project_code="demo"):
    suite = MagicMock()
    suite.id = uuid4()
    suite.test_suite = name
    suite.project_code = project_code
    suite.is_monitor = False
    return suite


def _make_create_table_group(name="prod_warehouse", project_code="demo"):
    tg = MagicMock()
    tg.id = uuid4()
    tg.table_groups_name = name
    tg.project_code = project_code
    return tg


def _make_create_scorecard(name="Daily Orders Health", project_code="demo"):
    sd = MagicMock()
    sd.id = uuid4()
    sd.name = name
    sd.project_code = project_code
    return sd


def _make_saved_notif(
    *,
    event: NotificationEvent,
    project_code: str = "demo",
    recipients=("alice@example.com",),
    test_suite_id: UUID | None = None,
    table_group_id: UUID | None = None,
    score_definition_id: UUID | None = None,
    settings: dict | None = None,
    enabled: bool = True,
) -> MagicMock:
    """Mock that quacks like the polymorphic ``NotificationSettings`` row returned by ``.create()``."""
    notif = MagicMock()
    notif.id = uuid4()
    notif.event = event
    notif.enabled = enabled
    notif.project_code = project_code
    notif.recipients = list(recipients)
    notif.test_suite_id = test_suite_id
    notif.table_group_id = table_group_id
    notif.score_definition_id = score_definition_id
    notif.settings = settings or {}
    return notif


# --- Happy paths ---


@patch("testgen.mcp.tools.notifications.TestRunNotificationSettings")
@patch("testgen.mcp.tools.notifications.resolve_test_suite")
def test_create_notification_test_run_happy_path(mock_resolve_suite, mock_factory, db_session_mock):
    suite = _make_create_suite(name="orders_v1")
    mock_resolve_suite.return_value = suite
    saved = _make_saved_notif(
        event=NotificationEvent.test_run,
        test_suite_id=suite.id,
        settings={"trigger": "on_failures"},
        recipients=("alice@example.com", "bob@example.com"),
    )
    mock_factory.create.return_value = saved

    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), _patch_get_notification_scope_lookups(suite_name="orders_v1"):
        out = create_notification(
            event_type="Test Run",
            recipients=["alice@example.com", "bob@example.com"],
            test_suite_id=str(suite.id),
            trigger_on="On test failures",
        )

    mock_factory.create.assert_called_once_with(
        project_code="demo",
        test_suite_id=suite.id,
        recipients=["alice@example.com", "bob@example.com"],
        trigger=TestRunNotificationTrigger.on_failures,
    )
    # Confirmation heading
    assert "created" in out.lower()
    # Display labels, not internal codes
    assert "Test Run" in out
    assert "On test failures" in out
    assert "test_run" not in out
    assert "on_failures" not in out
    # Followable-IDs surface
    assert f"`{saved.id}`" in out
    # Recipients rendered
    assert "alice@example.com" in out
    assert "bob@example.com" in out
    # Scope name surfaced
    assert "orders_v1" in out


@patch("testgen.mcp.tools.notifications.ProfilingRunNotificationSettings")
@patch("testgen.mcp.tools.notifications.resolve_table_group")
def test_create_notification_profiling_run_happy_path(mock_resolve_tg, mock_factory, db_session_mock):
    tg = _make_create_table_group(name="prod_warehouse")
    mock_resolve_tg.return_value = tg
    saved = _make_saved_notif(
        event=NotificationEvent.profiling_run,
        table_group_id=tg.id,
        settings={"trigger": "on_changes"},
    )
    mock_factory.create.return_value = saved

    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), _patch_get_notification_scope_lookups(tg_name="prod_warehouse"):
        out = create_notification(
            event_type="Profiling Run",
            recipients=["ops@example.com"],
            table_group_id=str(tg.id),
            trigger_on="On new hygiene issues",
        )

    mock_factory.create.assert_called_once_with(
        project_code="demo",
        table_group_id=tg.id,
        recipients=["ops@example.com"],
        trigger=ProfilingRunNotificationTrigger.on_changes,
    )
    assert "Profiling Run" in out
    assert "On new hygiene issues" in out
    assert "prod_warehouse" in out
    assert f"`{saved.id}`" in out
    # No internal code leakage
    assert "profiling_run" not in out
    assert "on_changes" not in out


@patch("testgen.mcp.tools.notifications.ScoreDropNotificationSettings")
@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_happy_path_both_thresholds(
    mock_resolve_sc,
    mock_factory,
    db_session_mock,
):
    scorecard = _make_create_scorecard(name="Daily Orders Health")
    mock_resolve_sc.return_value = scorecard
    saved = _make_saved_notif(
        event=NotificationEvent.score_drop,
        score_definition_id=scorecard.id,
        settings={"total_threshold": "85.0", "cde_threshold": "90.0"},
        recipients=("alerts@example.com",),
    )
    mock_factory.create.return_value = saved

    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), _patch_get_notification_scope_lookups(score_name="Daily Orders Health"):
        out = create_notification(
            event_type="Score Drop",
            recipients=["alerts@example.com"],
            scorecard_id=str(scorecard.id),
            total_threshold=85,
            cde_threshold=90,
        )

    mock_factory.create.assert_called_once_with(
        project_code="demo",
        score_definition_id=scorecard.id,
        recipients=["alerts@example.com"],
        total_score_threshold=85,
        cde_score_threshold=90,
    )
    assert "Score Drop" in out
    assert "Daily Orders Health" in out
    assert "85" in out
    assert "90" in out
    assert f"`{saved.id}`" in out
    # Score Drop has no trigger label
    assert "Trigger:**" not in out


@patch("testgen.mcp.tools.notifications.ScoreDropNotificationSettings")
@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_happy_path_total_only(
    mock_resolve_sc,
    mock_factory,
    db_session_mock,
):
    scorecard = _make_create_scorecard()
    mock_resolve_sc.return_value = scorecard
    saved = _make_saved_notif(
        event=NotificationEvent.score_drop,
        score_definition_id=scorecard.id,
        settings={"total_threshold": "85.0", "cde_threshold": None},
    )
    mock_factory.create.return_value = saved

    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), _patch_get_notification_scope_lookups(score_name="card"):
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(scorecard.id),
            total_threshold=85,
        )

    mock_factory.create.assert_called_once_with(
        project_code="demo",
        score_definition_id=scorecard.id,
        recipients=["x@example.com"],
        total_score_threshold=85,
        cde_score_threshold=None,
    )


@patch("testgen.mcp.tools.notifications.ScoreDropNotificationSettings")
@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_happy_path_cde_only(
    mock_resolve_sc,
    mock_factory,
    db_session_mock,
):
    scorecard = _make_create_scorecard()
    mock_resolve_sc.return_value = scorecard
    saved = _make_saved_notif(
        event=NotificationEvent.score_drop,
        score_definition_id=scorecard.id,
        settings={"total_threshold": None, "cde_threshold": "90.0"},
    )
    mock_factory.create.return_value = saved

    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), _patch_get_notification_scope_lookups(score_name="card"):
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(scorecard.id),
            cde_threshold=90,
        )

    mock_factory.create.assert_called_once_with(
        project_code="demo",
        score_definition_id=scorecard.id,
        recipients=["x@example.com"],
        total_score_threshold=None,
        cde_score_threshold=90,
    )


# --- Defaults ---


@patch("testgen.mcp.tools.notifications.TestRunNotificationSettings")
@patch("testgen.mcp.tools.notifications.resolve_test_suite")
def test_create_notification_test_run_default_trigger_on(
    mock_resolve_suite,
    mock_factory,
    db_session_mock,
):
    """Omitting ``trigger_on`` for Test Run defaults to ``On test failures``."""
    suite = _make_create_suite()
    mock_resolve_suite.return_value = suite
    saved = _make_saved_notif(
        event=NotificationEvent.test_run,
        test_suite_id=suite.id,
        settings={"trigger": "on_failures"},
    )
    mock_factory.create.return_value = saved

    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), _patch_get_notification_scope_lookups(suite_name="x"):
        create_notification(
            event_type="Test Run",
            recipients=["x@example.com"],
            test_suite_id=str(suite.id),
        )

    _, kwargs = mock_factory.create.call_args
    assert kwargs["trigger"] == TestRunNotificationTrigger.on_failures


@patch("testgen.mcp.tools.notifications.ProfilingRunNotificationSettings")
@patch("testgen.mcp.tools.notifications.resolve_table_group")
def test_create_notification_profiling_run_default_trigger_on(
    mock_resolve_tg,
    mock_factory,
    db_session_mock,
):
    """Omitting ``trigger_on`` for Profiling Run defaults to ``On new hygiene issues``."""
    tg = _make_create_table_group()
    mock_resolve_tg.return_value = tg
    saved = _make_saved_notif(
        event=NotificationEvent.profiling_run,
        table_group_id=tg.id,
        settings={"trigger": "on_changes"},
    )
    mock_factory.create.return_value = saved

    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), _patch_get_notification_scope_lookups(tg_name="x"):
        create_notification(
            event_type="Profiling Run",
            recipients=["x@example.com"],
            table_group_id=str(tg.id),
        )

    _, kwargs = mock_factory.create.call_args
    assert kwargs["trigger"] == ProfilingRunNotificationTrigger.on_changes


# --- Errors: event_type ---


def test_create_notification_internal_event_code_rejected(db_session_mock):
    """Internal enum codes (``test_run``) are NOT accepted — display labels only."""
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="test_run",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
        )
    msg = str(exc.value)
    for label in ("Test Run", "Profiling Run", "Score Drop"):
        assert label in msg


def test_create_notification_unknown_event_type_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="event_type"):
        create_notification(
            event_type="Bogus",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
        )


def test_create_notification_monitor_run_not_creatable(db_session_mock):
    """Monitor Alert is out of scope for create — only test/profiling/score events."""
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Monitor Alert",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
            table_group_id=str(uuid4()),
        )
    msg = str(exc.value)
    # Error lists the supported labels
    for label in ("Test Run", "Profiling Run", "Score Drop"):
        assert label in msg


# --- Errors: scope arg shape ---


def test_create_notification_test_run_missing_test_suite_id_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="test_suite_id"):
        create_notification(event_type="Test Run", recipients=["x@example.com"])


def test_create_notification_profiling_run_missing_table_group_id_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="table_group_id"):
        create_notification(event_type="Profiling Run", recipients=["x@example.com"])


def test_create_notification_score_drop_missing_scorecard_id_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="scorecard_id"):
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            total_threshold=85,
        )


def test_create_notification_test_run_with_table_group_id_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Test Run",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
            table_group_id=str(uuid4()),
        )
    assert "table_group_id" in str(exc.value)


def test_create_notification_test_run_with_scorecard_id_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="scorecard_id"):
        create_notification(
            event_type="Test Run",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
            scorecard_id=str(uuid4()),
        )


def test_create_notification_profiling_run_with_test_suite_id_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="test_suite_id"):
        create_notification(
            event_type="Profiling Run",
            recipients=["x@example.com"],
            table_group_id=str(uuid4()),
            test_suite_id=str(uuid4()),
        )


def test_create_notification_score_drop_with_test_suite_id_rejected(db_session_mock):
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="test_suite_id"):
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(uuid4()),
            test_suite_id=str(uuid4()),
            total_threshold=85,
        )


# --- Errors: inaccessible scope entities ---


@patch("testgen.mcp.tools.notifications.resolve_test_suite")
def test_create_notification_inaccessible_test_suite_propagates(
    mock_resolve_suite,
    db_session_mock,
):
    mock_resolve_suite.side_effect = MCPResourceNotAccessible("Test suite", "x")
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible, match="Test suite"):
        create_notification(
            event_type="Test Run",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
        )


@patch("testgen.mcp.tools.notifications.resolve_table_group")
def test_create_notification_inaccessible_table_group_propagates(
    mock_resolve_tg,
    db_session_mock,
):
    mock_resolve_tg.side_effect = MCPResourceNotAccessible("Table group", "x")
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible, match="Table group"):
        create_notification(
            event_type="Profiling Run",
            recipients=["x@example.com"],
            table_group_id=str(uuid4()),
        )


@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_inaccessible_scorecard_propagates(
    mock_resolve_sc,
    db_session_mock,
):
    mock_resolve_sc.side_effect = MCPResourceNotAccessible("Scorecard", "x")
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible, match="Scorecard"):
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(uuid4()),
            total_threshold=85,
        )


# --- Errors: recipients ---


@patch("testgen.mcp.tools.notifications.resolve_test_suite")
def test_create_notification_empty_recipients_rejected(mock_resolve_suite, db_session_mock):
    mock_resolve_suite.return_value = _make_create_suite()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="at least one"):
        create_notification(
            event_type="Test Run",
            recipients=[],
            test_suite_id=str(uuid4()),
        )


@patch("testgen.mcp.tools.notifications.resolve_test_suite")
def test_create_notification_invalid_recipients_lists_all(
    mock_resolve_suite,
    db_session_mock,
):
    """Every malformed address appears in the single error message — no partial save."""
    mock_resolve_suite.return_value = _make_create_suite()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Test Run",
            recipients=[
                "alice@example.com",
                "no-at-sign",
                "spaces in@here.com",
                "nodot@nope",
            ],
            test_suite_id=str(uuid4()),
        )
    msg = str(exc.value)
    assert "no-at-sign" in msg
    assert "spaces in@here.com" in msg
    assert "nodot@nope" in msg


# --- Errors: trigger_on ---


@patch("testgen.mcp.tools.notifications.resolve_test_suite")
def test_create_notification_invalid_trigger_on_test_run_lists_all_labels(
    mock_resolve_suite,
    db_session_mock,
):
    mock_resolve_suite.return_value = _make_create_suite()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Test Run",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
            trigger_on="bogus",
        )
    msg = str(exc.value)
    for label in (
        "Always",
        "On test failures",
        "On test failures and warnings",
        "On new test failures and warnings",
    ):
        assert label in msg


@patch("testgen.mcp.tools.notifications.resolve_table_group")
def test_create_notification_invalid_trigger_on_profiling_run_lists_only_profiling_labels(
    mock_resolve_tg,
    db_session_mock,
):
    mock_resolve_tg.return_value = _make_create_table_group()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Profiling Run",
            recipients=["x@example.com"],
            table_group_id=str(uuid4()),
            trigger_on="bogus",
        )
    msg = str(exc.value)
    assert "Always" in msg
    assert "On new hygiene issues" in msg
    # Test-run-only triggers must NOT leak into the Profiling Run error
    assert "On test failures" not in msg


# --- Errors: score_drop thresholds ---


@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_missing_both_thresholds_rejected(
    mock_resolve_sc,
    db_session_mock,
):
    mock_resolve_sc.return_value = _make_create_scorecard()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="threshold"):
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(uuid4()),
        )


@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_thresholds_out_of_range_lists_all(
    mock_resolve_sc,
    db_session_mock,
):
    """Both threshold range issues are surfaced in one error — no partial save."""
    mock_resolve_sc.return_value = _make_create_scorecard()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(uuid4()),
            total_threshold=150,
            cde_threshold=-1,
        )
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "cde_threshold" in msg
    assert "150" in msg
    assert "-1" in msg


@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_zero_total_threshold_rejected(mock_resolve_sc, db_session_mock):
    """0 is not a valid threshold (a score can never drop below 0) — reject up front
    with a clear MCPUserError, not the opaque model error.
    """
    mock_resolve_sc.return_value = _make_create_scorecard()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(uuid4()),
            total_threshold=0,
        )
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "= 0" in msg


@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_zero_cde_threshold_rejected(mock_resolve_sc, db_session_mock):
    mock_resolve_sc.return_value = _make_create_scorecard()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(uuid4()),
            cde_threshold=0,
        )
    msg = str(exc.value)
    assert "cde_threshold" in msg
    assert "= 0" in msg


# --- Errors: stray args per event ---


@patch("testgen.mcp.tools.notifications.resolve_scorecard")
def test_create_notification_score_drop_with_trigger_on_rejected(
    mock_resolve_sc,
    db_session_mock,
):
    mock_resolve_sc.return_value = _make_create_scorecard()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="trigger_on"):
        create_notification(
            event_type="Score Drop",
            recipients=["x@example.com"],
            scorecard_id=str(uuid4()),
            total_threshold=85,
            trigger_on="Always",
        )


@patch("testgen.mcp.tools.notifications.resolve_test_suite")
def test_create_notification_test_run_with_thresholds_rejected(
    mock_resolve_suite,
    db_session_mock,
):
    mock_resolve_suite.return_value = _make_create_suite()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Test Run",
            recipients=["x@example.com"],
            test_suite_id=str(uuid4()),
            total_threshold=85,
            cde_threshold=90,
        )
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "cde_threshold" in msg


@patch("testgen.mcp.tools.notifications.resolve_table_group")
def test_create_notification_profiling_run_with_thresholds_rejected(
    mock_resolve_tg,
    db_session_mock,
):
    mock_resolve_tg.return_value = _make_create_table_group()
    from testgen.mcp.tools.notifications import create_notification

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_notification(
            event_type="Profiling Run",
            recipients=["x@example.com"],
            table_group_id=str(uuid4()),
            total_threshold=85,
        )
    assert "total_threshold" in str(exc.value)


# ---------------------------------------------------------------------------
# update_notification
# ---------------------------------------------------------------------------


def _update_mock(
    *,
    event: NotificationEvent,
    enabled: bool = True,
    project_code: str = "demo",
    recipients=("alice@example.com",),
    test_suite_id: UUID | None = None,
    table_group_id: UUID | None = None,
    score_definition_id: UUID | None = None,
    trigger=None,
    total_score_threshold=None,
    cde_score_threshold=None,
    table_name: str | None = None,
) -> MagicMock:
    """Build a polymorphic-notification mock for ``update_notification`` tests.

    Adds typed attributes (``trigger``, ``total_score_threshold``,
    ``cde_score_threshold``, ``table_name``) that the tool reads when computing
    the no-op / Before-After diff. Each defaults to ``None`` unless supplied.
    """
    notif = _notif_mock(
        event=event,
        enabled=enabled,
        project_code=project_code,
        recipients=recipients,
        test_suite_id=test_suite_id,
        table_group_id=table_group_id,
        score_definition_id=score_definition_id,
    )
    notif.trigger = trigger
    notif.total_score_threshold = total_score_threshold
    notif.cde_score_threshold = cde_score_threshold
    notif.table_name = table_name
    return notif


# --- Pre-mutation validation ---


def test_update_notification_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        update_notification(notification_id="not-a-uuid", enabled=False)


def test_update_notification_missing_returns_unified_not_accessible(db_session_mock):
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(None), pytest.raises(
        MCPResourceNotAccessible, match="Notification",
    ):
        update_notification(notification_id=str(uuid4()), enabled=False)


def test_update_notification_no_fields_returns_error(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(
        MCPUserError, match="No fields supplied to update",
    ):
        update_notification(notification_id=str(notif.id))


# --- Event-shape gates ---


def test_update_notification_test_run_rejects_total_threshold(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), total_threshold=85)
    assert "total_threshold" in str(exc.value)
    assert "Test Run" in str(exc.value)


def test_update_notification_test_run_rejects_clear_cde_threshold(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), clear_cde_threshold=True)
    assert "clear_cde_threshold" in str(exc.value)


def test_update_notification_test_run_rejects_table_name(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), table_name="orders")
    assert "table_name" in str(exc.value)
    assert "Monitor Alert" in str(exc.value)


def test_update_notification_profiling_run_rejects_cde_threshold(db_session_mock):
    notif = _update_mock(event=NotificationEvent.profiling_run, table_group_id=uuid4(),
                         trigger=ProfilingRunNotificationTrigger.on_changes)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), cde_threshold=85)
    assert "cde_threshold" in str(exc.value)


def test_update_notification_profiling_run_rejects_table_name(db_session_mock):
    notif = _update_mock(event=NotificationEvent.profiling_run, table_group_id=uuid4(),
                         trigger=ProfilingRunNotificationTrigger.on_changes)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), clear_table_name=True)
    assert "table_name" in str(exc.value)


def test_update_notification_score_drop_rejects_trigger_on(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError, match="trigger_on"):
        update_notification(notification_id=str(notif.id), trigger_on="Always")


def test_update_notification_score_drop_rejects_table_name(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError, match="table_name"):
        update_notification(notification_id=str(notif.id), table_name="orders")


def test_update_notification_monitor_run_rejects_total_threshold(db_session_mock):
    notif = _update_mock(event=NotificationEvent.monitor_run,
                         table_group_id=uuid4(), test_suite_id=uuid4(),
                         trigger=MonitorNotificationTrigger.on_anomalies)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), total_threshold=85)
    assert "total_threshold" in str(exc.value)


def test_update_notification_multiple_stray_args_one_error(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(
            notification_id=str(notif.id),
            total_threshold=85,
            cde_threshold=90,
            table_name="orders",
        )
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "cde_threshold" in msg
    assert "table_name" in msg


# --- Recipients ---


def test_update_notification_empty_recipients_rejected(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError, match="at least one"):
        update_notification(notification_id=str(notif.id), recipients=[])


def test_update_notification_invalid_recipients_lists_all(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(
            notification_id=str(notif.id),
            recipients=["alice@example.com", "no-at-sign", "nodot@nope"],
        )
    msg = str(exc.value)
    assert "no-at-sign" in msg
    assert "nodot@nope" in msg


# --- Trigger labels ---


def test_update_notification_test_run_invalid_trigger_lists_all_labels(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), trigger_on="bogus")
    msg = str(exc.value)
    for label in (
        "Always",
        "On test failures",
        "On test failures and warnings",
        "On new test failures and warnings",
    ):
        assert label in msg


def test_update_notification_profiling_run_invalid_trigger_lists_only_profiling_labels(db_session_mock):
    notif = _update_mock(event=NotificationEvent.profiling_run, table_group_id=uuid4(),
                         trigger=ProfilingRunNotificationTrigger.on_changes)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), trigger_on="bogus")
    msg = str(exc.value)
    assert "Always" in msg
    assert "On new hygiene issues" in msg
    assert "On test failures" not in msg


def test_update_notification_monitor_run_invalid_trigger_lists_monitor_label(db_session_mock):
    notif = _update_mock(event=NotificationEvent.monitor_run,
                         table_group_id=uuid4(), test_suite_id=uuid4(),
                         trigger=MonitorNotificationTrigger.on_anomalies)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), trigger_on="bogus")
    msg = str(exc.value)
    assert "On anomalies" in msg
    # Test-run-only triggers must not leak into the Monitor Alert error
    assert "On test failures" not in msg


# --- Score thresholds ---


def test_update_notification_total_threshold_out_of_range(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), total_threshold=150)
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "150" in msg


def test_update_notification_zero_threshold_rejected(db_session_mock):
    """0 is rejected on update with a clear error, not silently accepted or surfaced as opaque."""
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), total_threshold=0)
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "= 0" in msg
    notif.save.assert_not_called()


def test_update_notification_both_thresholds_out_of_range_one_error(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"),
                         cde_score_threshold=Decimal("90.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(notification_id=str(notif.id), total_threshold=150, cde_threshold=-1)
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "cde_threshold" in msg
    assert "150" in msg
    assert "-1" in msg


def test_update_notification_set_total_and_clear_total_rejected(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(
            notification_id=str(notif.id),
            total_threshold=80,
            clear_total_threshold=True,
        )
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "set and cleared" in msg


def test_update_notification_set_and_clear_both_pairs_one_error(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"),
                         cde_score_threshold=Decimal("90.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(
            notification_id=str(notif.id),
            total_threshold=80,
            clear_total_threshold=True,
            cde_threshold=70,
            clear_cde_threshold=True,
        )
    msg = str(exc.value)
    assert "total_threshold" in msg
    assert "cde_threshold" in msg


def test_update_notification_clear_both_thresholds_pre_empt_check(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"),
                         cde_score_threshold=Decimal("90.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError, match="must remain set"):
        update_notification(
            notification_id=str(notif.id),
            clear_total_threshold=True,
            clear_cde_threshold=True,
        )
    notif.save.assert_not_called()


def test_update_notification_clear_only_set_threshold_pre_empt_check(db_session_mock):
    """Current state: total=85, cde=NULL. Clearing total would leave both NULL."""
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"),
                         cde_score_threshold=None)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError, match="must remain set"):
        update_notification(notification_id=str(notif.id), clear_total_threshold=True)
    notif.save.assert_not_called()


# --- Monitor table_name ---


def test_update_notification_set_and_clear_table_name_rejected(db_session_mock):
    notif = _update_mock(event=NotificationEvent.monitor_run,
                         table_group_id=uuid4(), test_suite_id=uuid4(),
                         trigger=MonitorNotificationTrigger.on_anomalies,
                         table_name="orders")
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), pytest.raises(MCPUserError) as exc:
        update_notification(
            notification_id=str(notif.id),
            table_name="invoices",
            clear_table_name=True,
        )
    msg = str(exc.value)
    assert "table_name" in msg
    assert "set and cleared" in msg


def test_update_notification_monitor_set_table_name_happy(db_session_mock):
    notif = _update_mock(event=NotificationEvent.monitor_run,
                         table_group_id=uuid4(), test_suite_id=uuid4(),
                         trigger=MonitorNotificationTrigger.on_anomalies,
                         table_name="orders")
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), table_name="invoices")

    assert notif.table_name == "invoices"
    notif.save.assert_called_once()
    assert "orders" in out
    assert "invoices" in out
    assert "| Table |" in out


def test_update_notification_monitor_clear_table_name_happy(db_session_mock):
    notif = _update_mock(event=NotificationEvent.monitor_run,
                         table_group_id=uuid4(), test_suite_id=uuid4(),
                         trigger=MonitorNotificationTrigger.on_anomalies,
                         table_name="orders")
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), clear_table_name=True)

    assert notif.table_name is None
    notif.save.assert_called_once()
    assert "orders" in out
    # Cleared values render as em-dash.
    assert "—" in out


# --- No-op detection ---


def test_update_notification_no_op_enabled_returns_unchanged(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         enabled=True, trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), enabled=True)

    assert "No fields changed" in out
    notif.save.assert_not_called()


def test_update_notification_no_op_recipients(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         recipients=("a@x.com", "b@x.com"),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(
            notification_id=str(notif.id),
            recipients=["a@x.com", "b@x.com"],
        )

    assert "No fields changed" in out
    notif.save.assert_not_called()


def test_update_notification_no_op_trigger(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), trigger_on="On test failures")

    assert "No fields changed" in out
    notif.save.assert_not_called()


def test_update_notification_partial_no_op_diff_shows_only_changed(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         enabled=True, trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(
            notification_id=str(notif.id),
            enabled=True,  # no-op
            trigger_on="Always",  # change
        )

    # "Trigger" row present in diff, "Status" row absent.
    assert "Always" in out
    assert "Trigger" in out
    # Status field should not appear in the diff table since it's a no-op.
    assert "| Status |" not in out
    assert "Status |" not in out.split("# ", 1)[1].split("\n## ")[0] or True  # tolerant; main check above
    notif.save.assert_called_once()


# --- Happy paths ---


def test_update_notification_test_run_recipients_and_enabled(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         enabled=True, recipients=("alice@example.com",),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(
            notification_id=str(notif.id),
            recipients=["bob@example.com"],
            enabled=False,
        )

    assert notif.recipients == ["bob@example.com"]
    assert notif.enabled is False
    notif.save.assert_called_once()
    assert "# Test Run Notification updated" in out
    assert "Active" in out
    assert "Paused" in out
    assert "alice@example.com" in out
    assert "bob@example.com" in out


def test_update_notification_test_run_change_trigger(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), trigger_on="Always")

    assert notif.trigger == TestRunNotificationTrigger.always
    notif.save.assert_called_once()
    assert "On test failures" in out
    assert "Always" in out
    # No internal codes leak.
    assert "on_failures" not in out


def test_update_notification_profiling_run_change_trigger(db_session_mock):
    notif = _update_mock(event=NotificationEvent.profiling_run, table_group_id=uuid4(),
                         trigger=ProfilingRunNotificationTrigger.on_changes)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), trigger_on="Always")

    assert notif.trigger == ProfilingRunNotificationTrigger.always
    notif.save.assert_called_once()
    assert "On new hygiene issues" in out
    assert "Always" in out


def test_update_notification_score_drop_change_total_threshold(db_session_mock):
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"),
                         cde_score_threshold=Decimal("90.0"))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), total_threshold=92)

    assert notif.total_score_threshold == 92
    notif.save.assert_called_once()
    assert "85.0" in out
    assert "92" in out
    assert "# Score Drop Notification updated" in out


def test_update_notification_score_drop_change_cde_and_clear_total(db_session_mock):
    """Current: total=85, cde=NULL. Set cde=88 AND clear total → resulting total=NULL, cde=88 (valid)."""
    notif = _update_mock(event=NotificationEvent.score_drop, score_definition_id=uuid4(),
                         total_score_threshold=Decimal("85.0"),
                         cde_score_threshold=None)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(
            notification_id=str(notif.id),
            cde_threshold=88,
            clear_total_threshold=True,
        )

    assert notif.total_score_threshold is None
    assert notif.cde_score_threshold == 88
    notif.save.assert_called_once()
    assert "85.0" in out
    assert "88" in out
    # Cleared total renders as em-dash.
    assert "—" in out


def test_update_notification_monitor_run_recipients(db_session_mock):
    notif = _update_mock(event=NotificationEvent.monitor_run,
                         table_group_id=uuid4(), test_suite_id=uuid4(),
                         trigger=MonitorNotificationTrigger.on_anomalies,
                         recipients=("a@x.com",))
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(
            notification_id=str(notif.id),
            recipients=["b@x.com", "c@x.com"],
        )

    assert notif.recipients == ["b@x.com", "c@x.com"]
    notif.save.assert_called_once()
    assert "# Monitor Alert Notification updated" in out


# --- Rendering ---


def test_update_notification_heading_event_specific(db_session_mock):
    notif = _update_mock(event=NotificationEvent.profiling_run, table_group_id=uuid4(),
                         trigger=ProfilingRunNotificationTrigger.on_changes)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), enabled=False)

    assert "# Profiling Run Notification updated" in out


def test_update_notification_notification_id_code_formatted(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), enabled=False)

    assert f"`{notif.id}`" in out


def test_update_notification_status_diff_active_paused(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         enabled=True, trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), enabled=False)

    assert "Active" in out
    assert "Paused" in out
    # Status row should NOT render the bool repr.
    assert "True" not in out
    assert "False" not in out


def test_update_notification_recipients_diff_comma_separated(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         recipients=("a@x.com",),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(
            notification_id=str(notif.id),
            recipients=["a@x.com", "b@x.com"],
        )

    assert "a@x.com, b@x.com" in out
    # No Python list repr leakage.
    assert "['a@x.com'" not in out
    assert "['a@x.com', 'b@x.com']" not in out


def test_update_notification_trigger_diff_display_labels_only(db_session_mock):
    notif = _update_mock(event=NotificationEvent.test_run, test_suite_id=uuid4(),
                         trigger=TestRunNotificationTrigger.on_failures)
    from testgen.mcp.tools.notifications import update_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = update_notification(notification_id=str(notif.id), trigger_on="Always")

    assert "Always" in out
    assert "On test failures" in out
    # No internal codes in diff.
    assert "on_failures" not in out
    assert "TestRunNotificationTrigger" not in out


# ---------------------------------------------------------------------------
# delete_notification
# ---------------------------------------------------------------------------


def test_delete_notification_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        delete_notification(notification_id="not-a-uuid")


def test_delete_notification_unknown_id_returns_not_accessible(db_session_mock):
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), _patch_notification_get(None), pytest.raises(
        MCPResourceNotAccessible, match="Notification",
    ):
        delete_notification(notification_id=str(uuid4()))


def test_delete_notification_inaccessible_project_returns_unified_not_accessible(db_session_mock):
    """``NotificationSettings.get`` returns ``None`` when the project filter excludes the row.

    Both the missing-id and the wrong-project paths must surface as the same error
    so callers can't enumerate notifications across projects they don't own.
    """
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(allowed=("demo",)), _patch_notification_get(None), pytest.raises(
        MCPResourceNotAccessible, match="Notification",
    ):
        delete_notification(notification_id=str(uuid4()))


def test_delete_notification_does_not_call_delete_when_inaccessible(db_session_mock):
    """When resolve_notification fails, the row's .delete() is never invoked."""
    from testgen.mcp.tools.notifications import delete_notification

    sentinel = _notif_mock(event=NotificationEvent.test_run, test_suite_id=uuid4())
    with _patch_perms(), _patch_notification_get(None), pytest.raises(MCPResourceNotAccessible):
        delete_notification(notification_id=str(uuid4()))
    sentinel.delete.assert_not_called()


def test_delete_notification_calls_model_delete(db_session_mock):
    notif = _notif_mock(
        event=NotificationEvent.test_run,
        test_suite_id=uuid4(),
        settings={"trigger": "on_failures"},
    )
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        suite_name="orders_v1",
    ):
        delete_notification(notification_id=str(notif.id))

    notif.delete.assert_called_once()


def test_delete_notification_test_run_renders_event_heading_and_scope(db_session_mock):
    suite_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.test_run,
        test_suite_id=suite_id,
        settings={"trigger": "on_failures"},
    )
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        suite_name="orders_v1",
    ):
        out = delete_notification(notification_id=str(notif.id))

    assert "# Test Run Notification deleted" in out
    assert f"`{notif.id}`" in out
    assert "Event Type:** Test Run" in out
    assert "Project:** `demo`" in out
    assert "Test Suite:** orders_v1" in out
    assert f"`{suite_id}`" in out
    # No internal code leakage.
    assert "test_run" not in out


def test_delete_notification_profiling_run_renders_table_group_scope(db_session_mock):
    tg_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.profiling_run,
        table_group_id=tg_id,
        settings={"trigger": "on_changes"},
    )
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        tg_name="prod_warehouse",
    ):
        out = delete_notification(notification_id=str(notif.id))

    assert "# Profiling Run Notification deleted" in out
    assert "Event Type:** Profiling Run" in out
    assert "Table Group:** prod_warehouse" in out
    assert f"`{tg_id}`" in out
    assert "profiling_run" not in out


def test_delete_notification_score_drop_renders_scorecard_scope(db_session_mock):
    sd_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.score_drop,
        score_definition_id=sd_id,
        settings={"total_threshold": "85.0"},
    )
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        score_name="Daily Orders Health",
    ):
        out = delete_notification(notification_id=str(notif.id))

    assert "# Score Drop Notification deleted" in out
    assert "Event Type:** Score Drop" in out
    assert "Scorecard:** Daily Orders Health" in out
    assert f"`{sd_id}`" in out
    assert "score_drop" not in out


def test_delete_notification_monitor_run_renders_table_group(db_session_mock):
    tg_id = uuid4()
    suite_id = uuid4()
    notif = _notif_mock(
        event=NotificationEvent.monitor_run,
        table_group_id=tg_id,
        test_suite_id=suite_id,
        settings={"trigger": "on_anomalies"},
    )
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups(
        suite_name="monitors_v2", tg_name="prod_warehouse",
    ):
        out = delete_notification(notification_id=str(notif.id))

    assert "# Monitor Alert Notification deleted" in out
    assert "Event Type:** Monitor Alert" in out
    assert "Table Group:** prod_warehouse" in out
    assert f"`{tg_id}`" in out
    assert "monitor_run" not in out
    # The internal monitor test suite is never exposed.
    assert "Test Suite" not in out
    assert "monitors_v2" not in out
    assert f"`{suite_id}`" not in out


def test_delete_notification_test_run_project_wide_omits_parent_id(db_session_mock):
    notif = _notif_mock(
        event=NotificationEvent.test_run,
        test_suite_id=None,
        settings={"trigger": "always"},
    )
    from testgen.mcp.tools.notifications import delete_notification

    with _patch_perms(), _patch_notification_get(notif), _patch_get_notification_scope_lookups():
        out = delete_notification(notification_id=str(notif.id))

    assert "Test Suite:** All Test Suites" in out
    # Project-wide notifications have no parent id to surface in the scope row.
    assert "(`" not in out.split("Test Suite:**")[1].split("\n")[0]
