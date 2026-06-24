import dataclasses
import logging
from datetime import UTC, date, datetime
from math import ceil
from typing import Any, ClassVar, Literal, cast

import pandas as pd
import streamlit as st

from testgen.common.cron_service import get_cron_sample
from testgen.common.freshness_service import add_business_minutes, get_schedule_params, resolve_holiday_dates
from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    MonitorNotificationSettings,
    MonitorNotificationTrigger,
    NotificationEvent,
)
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_definition import TestDefinition, TestDefinitionSummary
from testgen.common.models.test_suite import PredictSensitivity, TestSuite
from testgen.common.monitor_service import disable_monitoring, enable_monitoring, update_monitoring
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries.profiling_queries import get_tables_by_table_group
from testgen.ui.services.database_service import fetch_all_from_db
from testgen.ui.services.query_cache import (
    get_monitor_schedule,
    get_project_summary,
    get_table_group,
    get_test_definition,
    get_test_suite,
    get_test_type_summaries,
    select_table_groups_minimal_where,
    select_test_definitions_where,
)
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session, temp_value
from testgen.ui.utils import dict_from_kv, get_cron_sample_handler
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.utils import make_json_safe

# Maps the user-facing ``anomaly_type_filter`` values supplied by the dashboard
# frontend to the internal ``test_type`` codes the model method expects.
_DASHBOARD_ANOMALY_TYPE_TO_DB: dict[str, str] = {
    "freshness": "Freshness_Trend",
    "volume": "Volume_Trend",
    "schema": "Schema_Drift",
    "metrics": "Metric_Trend",
}

PAGE_ICON = "apps_outage"
PAGE_TITLE = "Monitors"
LOG = logging.getLogger("testgen")

ALLOWED_SORT_FIELDS = {
    "table_name", "freshness_anomalies", "volume_anomalies", "schema_anomalies",
    "metric_anomalies", "latest_update", "row_count",
}
ANOMALY_TYPE_FILTERS = {
    "freshness": "freshness_anomalies",
    "volume": "volume_anomalies",
    "schema": "schema_anomalies",
    "metrics": "metric_anomalies",
}
DIALOG_AUTO_OPENED_KEY = "monitors:dialog_auto_opened"
EDIT_MONITOR_SETTINGS_DIALOG_KEY = "monitors:edit_monitor_settings_open"
EDIT_TABLE_MONITORS_DIALOG_KEY = "monitors:edit_table_monitors_table"
TABLE_TRENDS_DIALOG_KEY = "monitors:trends_table"
SCHEMA_CHANGES_DIALOG_KEY = "monitors:schema_changes_payload"
EDIT_NOTIFICATIONS_DIALOG_KEY = "monitors:edit_notifications_open"


class MonitorsDashboardPage(Page):
    path = "monitors"
    can_activate: ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=0,
    )

    def render(
        self,
        project_code: str,
        table_group_id: str | None = None,
        table_name_filter: str | None = None,
        anomaly_type_filter: str | None = None,
        sort_field: str | None = None,
        sort_order: str | None = None,
        items_per_page: str = "20",
        current_page: str = "0",
        table_name: str | None = None,
        **_kwargs,
    ) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "monitor-tables",
        )

        project_summary = get_project_summary(project_code)
        table_groups = select_table_groups_minimal_where(TableGroup.project_code == project_code)

        if not table_group_id or table_group_id not in [ str(item.id) for item in table_groups ]:
            table_group_id = str(table_groups[0].id) if table_groups else None

        selected_table_group = None
        monitor_schedule = None
        monitored_tables_page = []
        all_monitored_tables_count = 0
        monitor_changes_summary = None
        auto_open_table = None

        current_page = int(current_page)
        items_per_page = int(items_per_page)
        page_start = current_page * items_per_page

        if table_group_id:
            selected_table_group = next(item for item in table_groups if str(item.id) == table_group_id)
            monitor_suite_id = selected_table_group.monitor_test_suite_id

            if monitor_suite_id:
                with st.spinner(text="Loading data ..."):
                    monitor_schedule = get_monitor_schedule(monitor_suite_id)

                    anomaly_type_filter = [t for t in anomaly_type_filter.split(",") if t in ANOMALY_TYPE_FILTERS] if anomaly_type_filter else None
                    if sort_field and sort_field not in ALLOWED_SORT_FIELDS:
                        sort_field = None

                    monitored_tables_page, all_monitored_tables_count = get_monitor_changes_by_tables(
                        table_group_id,
                        table_name_filter=table_name_filter,
                        anomaly_type_filter=anomaly_type_filter,
                        sort_field=sort_field,
                        sort_order=sort_order,
                        limit=int(items_per_page),
                        offset=page_start,
                    )
                    monitor_changes_summary = summarize_monitor_changes(table_group_id)

                monitored_table_names = {table["table_name"] for table in monitored_tables_page}
                if table_name:
                    if st.session_state.get(DIALOG_AUTO_OPENED_KEY) != table_name:
                        if table_name in monitored_table_names:
                            auto_open_table = table_name
                        else:
                            Router().set_query_params({"table_name": None})
                else:
                    st.session_state.pop(DIALOG_AUTO_OPENED_KEY, None)

        edit_settings_open = st.session_state.get(EDIT_MONITOR_SETTINGS_DIALOG_KEY)
        edit_monitors_table = st.session_state.get(EDIT_TABLE_MONITORS_DIALOG_KEY)
        trends_table = st.session_state.get(TABLE_TRENDS_DIALOG_KEY)

        def on_open_monitor_settings(*_) -> None:
            st.session_state[EDIT_MONITOR_SETTINGS_DIALOG_KEY] = True

        def on_open_table_trends(payload) -> None:
            table_name_val = payload.get("table_name") if isinstance(payload, dict) else payload
            st.session_state[DIALOG_AUTO_OPENED_KEY] = table_name_val
            Router().set_query_params({"table_name": table_name_val})
            st.session_state[TABLE_TRENDS_DIALOG_KEY] = table_name_val

        def on_open_edit_table_monitors(payload) -> None:
            table_name_val = payload.get("table_name") if isinstance(payload, dict) else payload
            st.session_state[EDIT_TABLE_MONITORS_DIALOG_KEY] = table_name_val

        def on_open_schema_changes(payload: dict) -> None:
            st.session_state[SCHEMA_CHANGES_DIALOG_KEY] = payload

        def on_edit_notifications(*_) -> None:
            st.session_state[EDIT_NOTIFICATIONS_DIALOG_KEY] = True

        ns_obj = None
        notifications_data = None
        if st.session_state.get(EDIT_NOTIFICATIONS_DIALOG_KEY) and selected_table_group:
            ns_obj = MonitorNotificationSettingsDialog(
                MonitorNotificationSettings,
                ns_attrs={
                    "project_code": project_code,
                    "table_group_id": str(selected_table_group.id),
                    "test_suite_id": str(selected_table_group.monitor_test_suite_id),
                },
                component_props={
                    "subtitle": {
                        "label": "Table Group",
                        "value": selected_table_group.table_groups_name,
                    },
                },
            )
            notifications_data = ns_obj.build_data()
            notifications_data["open"] = True

        def on_notifications_dialog_closed(*_) -> None:
            if ns_obj:
                ns_obj.clear_state()
            st.session_state.pop(EDIT_NOTIFICATIONS_DIALOG_KEY, None)

        # Build dialog data
        edit_settings_data = None
        edit_settings_handlers = {}
        if edit_settings_open and selected_table_group:
            is_configured = bool(selected_table_group.monitor_test_suite_id)
            monitor_suite_title = "Edit Monitor Settings" if is_configured else "Configure Monitors"
            edit_settings_data, edit_settings_handlers = build_edit_monitor_settings_data(
                selected_table_group,
                monitor_schedule,
                dialog={"open": True, "title": monitor_suite_title},
            )

        trends_data = None
        trends_handlers = {}
        if trends_table and selected_table_group:
            trends_data, trends_handlers = build_table_trends_data(
                selected_table_group,
                {"table_name": trends_table},
                dialog={"open": True, "title": f"Table: {trends_table}"},
            )

        edit_monitors_data = None
        edit_monitors_handlers = {}
        if edit_monitors_table and selected_table_group:
            edit_monitors_data, edit_monitors_handlers = build_edit_table_monitors_data(
                selected_table_group,
                {"table_name": edit_monitors_table},
                dialog={"open": True, "title": f"Table Monitors: {edit_monitors_table}"},
            )

        schema_changes_data = None
        schema_changes_handlers = {}
        if schema_changes_payload := st.session_state.get(SCHEMA_CHANGES_DIALOG_KEY):
            if selected_table_group:
                schema_changes_data, schema_changes_handlers = build_schema_changes_data(
                    selected_table_group,
                    schema_changes_payload,
                )

        testgen.monitors_dashboard_widget(
            key="monitors_dashboard",
            data={
                "project_summary": project_summary.to_dict(json_safe=True),
                "summary": make_json_safe(monitor_changes_summary),
                "schedule": {
                    "active": monitor_schedule.active,
                    "cron_tz": monitor_schedule.cron_tz,
                    "cron_sample": get_cron_sample(monitor_schedule.cron_expr, monitor_schedule.cron_tz, 1)
                } if monitor_schedule else None,
                "table_group_filter_options": [
                    {
                        "value": str(table_group.id),
                        "label": table_group.table_groups_name,
                        "selected": str(table_group_id) == str(table_group.id),
                        "has_monitors": bool(table_group.monitor_test_suite_id),
                    } for table_group in table_groups
                ],
                "monitors": {
                    "items": make_json_safe(monitored_tables_page),
                    "current_page": current_page,
                    "items_per_page": items_per_page,
                    "total_count": all_monitored_tables_count,
                },
                "filters": {
                    "table_group_id": table_group_id,
                    "table_name_filter": table_name_filter,
                    "anomaly_type_filter": list(anomaly_type_filter) if anomaly_type_filter else None,
                },
                "sort": {
                    "sort_field": sort_field,
                    "sort_order": sort_order,
                } if sort_field and sort_order else None,
                "has_monitor_test_suite": bool(selected_table_group and monitor_suite_id),
                "auto_open_table": auto_open_table,
                "permissions": {
                    "can_edit": session.auth.user_has_permission("edit"),
                },
                "notifications_dialog": notifications_data,
                "edit_monitor_settings_dialog": edit_settings_data,
                "trends_dialog": trends_data,
                "edit_table_monitors_dialog": edit_monitors_data,
                "schema_changes_dialog": schema_changes_data,
            },
            on_OpenSchemaChanges_change=on_open_schema_changes,
            on_OpenMonitoringTrends_change=on_open_table_trends,
            on_SetParamValues_change=lambda payload: set_param_values(payload),
            on_EditNotifications_change=on_edit_notifications,
            on_EditMonitorSettings_change=on_open_monitor_settings,
            on_DeleteMonitorSuiteConfirmed_change=lambda *_: delete_monitor_suite(selected_table_group),
            on_EditTableMonitors_change=on_open_edit_table_monitors,
            # NotificationSettings events
            on_AddNotification_change=lambda item: ns_obj.on_add_item(item) if ns_obj else None,
            on_UpdateNotification_change=lambda item: ns_obj.on_update_item(item) if ns_obj else None,
            on_DeleteNotification_change=lambda item: ns_obj.on_delete_item(item) if ns_obj else None,
            on_PauseNotification_change=lambda item: ns_obj.on_pause_item(item) if ns_obj else None,
            on_ResumeNotification_change=lambda item: ns_obj.on_resume_item(item) if ns_obj else None,
            on_NotificationsDialogClosed_change=on_notifications_dialog_closed,
            # Edit monitor settings events
            **edit_settings_handlers,
            # Trends events
            **trends_handlers,
            # Edit table monitors events
            **edit_monitors_handlers,
            # Schema changes events
            **schema_changes_handlers,
        )


class MonitorNotificationSettingsDialog(NotificationSettingsDialogBase):
    title = "Monitor Notifications"

    def _item_to_model_attrs(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "trigger": MonitorNotificationTrigger.on_anomalies,
            "table_name": item["scope"],
        }

    def _model_to_item_attrs(self, model: MonitorNotificationSettings) -> dict[str, Any]:
        return {
            "trigger": model.trigger.value if model.trigger else None,
            "scope": table_name
                if model.settings and (table_name := model.settings.get("table_name")) else None,
        }

    def _get_component_props(self) -> dict[str, Any]:
        tables = get_tables_by_table_group(self.ns_attrs["table_group_id"])
        table_options = [
            (table["table_name"], table["table_name"]) for table in tables
        ]
        table_options.insert(0, (None, "All Tables"))
        trigger_labels = {
            MonitorNotificationTrigger.on_anomalies.value: "On Anomalies",
        }
        trigger_options = [(t.value, trigger_labels[t.value]) for t in MonitorNotificationTrigger]
        return {
            "event": NotificationEvent.monitor_run.value,
            "scope_label": "Table",
            "scope_options": table_options,
            "trigger_options": trigger_options,
        }


@st.cache_data(show_spinner=False)
def get_monitor_changes_by_tables(
    table_group_id: str,
    table_name_filter: str | None = None,
    anomaly_type_filter: list[str] | None = None,
    sort_field: str | None = None,
    sort_order: Literal["asc"] | Literal["desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[list[dict], int]:
    """Per-monitored-table summaries shaped for the dashboard's JSON payload.

    Returns ``(rows, total)`` so the dashboard can fill its pager without an extra
    round-trip to the model (which would re-run the heavy CTE twice — once for the
    rows, once for the count — just to throw the rows away). Rows are dicts (rather
    than ``MonitorTableSummary`` dataclasses) because the monitor-dashboard widget
    consumes the payload via ``make_json_safe``. Each row is augmented with
    ``table_group_id`` to match the historical payload shape.
    """
    page = 1 + (offset // limit) if limit and offset else 1
    summaries, total = TableGroup.list_monitor_table_summaries(
        table_group_id,
        anomaly_types=_dashboard_anomaly_types(anomaly_type_filter),
        sort_by=_dashboard_sort_to_model(sort_field, sort_order),
        table_name_filter=table_name_filter,
        page=page,
        limit=limit or 1000,
    )
    rows = [{**dataclasses.asdict(s), "table_group_id": table_group_id} for s in summaries]
    return rows, total


@st.cache_data(show_spinner=False)
def summarize_monitor_changes(table_group_id: str) -> dict:
    return dataclasses.asdict(TableGroup.get_monitor_group_summary(table_group_id))


def _dashboard_anomaly_types(anomaly_type_filter: list[str] | None) -> list[str] | None:
    """Map dashboard-form anomaly type labels to internal ``test_type`` codes."""
    if not anomaly_type_filter:
        return None
    return [
        _DASHBOARD_ANOMALY_TYPE_TO_DB[t]
        for t in anomaly_type_filter
        if t in _DASHBOARD_ANOMALY_TYPE_TO_DB
    ] or None


def _dashboard_sort_to_model(
    sort_field: str | None,
    sort_order: Literal["asc"] | Literal["desc"] | None,
) -> str | None:
    """Translate the dashboard's (sort_field, sort_order) pair into the model's
    ``sort_by`` form (the field name, optionally suffixed with ``_desc``)."""
    if not sort_field:
        return None
    return f"{sort_field}_desc" if sort_order == "desc" else sort_field


def set_param_values(payload: dict) -> None:
    Router().set_query_params(payload)


@with_database_session
def build_edit_monitor_settings_data(
    table_group: TableGroupMinimal, schedule: JobSchedule | None, dialog: dict | None = None,
) -> tuple[dict, dict]:
    monitor_suite_id = table_group.monitor_test_suite_id

    if monitor_suite_id:
        monitor_suite = get_test_suite(monitor_suite_id)
    else:
        monitor_suite = TestSuite(
            project_code=table_group.project_code,
            test_suite=f"{table_group.table_groups_name} Monitors",
            connection_id=table_group.connection_id,
            table_groups_id=table_group.id,
            export_to_observability=False,
            dq_score_exclude=True,
            is_monitor=True,
        )

    def on_save_settings_clicked(payload: dict) -> None:
        set_save(True)
        set_schedule(payload["schedule"])
        set_monitor_suite(payload["monitor_suite"])

    cron_sample_result, on_cron_sample = get_cron_sample_handler("monitors:cron_expr_validation", sample_count=2)
    should_save, set_save = temp_value(f"monitors:save:{monitor_suite_id}", default=False)
    get_schedule, set_schedule = temp_value(f"monitors:updated_schedule:{monitor_suite_id}", default={})
    get_monitor_suite, set_monitor_suite = temp_value(f"monitors:updated_suite:{monitor_suite_id}", default={})

    if should_save():
        schedule_config = get_schedule()
        if monitor_suite_id:
            # An existing monitor suite always has a run-monitors schedule.
            update_monitoring(
                monitor_suite,
                cast(JobSchedule, schedule),
                suite_attrs=get_monitor_suite(),
                cron_expr=schedule_config["cron_expr"],
                cron_tz=schedule_config["cron_tz"],
                active=schedule_config["active"],
            )
        else:
            enable_monitoring(
                get_table_group(table_group.id),
                schedule_config["cron_expr"],
                schedule_config["cron_tz"],
                suite_attrs=get_monitor_suite(),
                active=schedule_config["active"],
            )

        st.session_state.pop(EDIT_MONITOR_SETTINGS_DIALOG_KEY, None)
        safe_rerun()

    data = {
        "table_group": table_group.to_dict(json_safe=True),
        "monitor_suite": monitor_suite.to_dict(json_safe=True),
        "schedule": {
            "cron_tz": schedule.cron_tz,
            "cron_expr": schedule.cron_expr,
            "active": schedule.active,
        } if schedule else None,
        "cron_sample": cron_sample_result(),
        "dialog": dialog,
    }
    handlers = {
        "on_SaveSettingsClicked_change": on_save_settings_clicked,
        "on_GetCronSample_change": on_cron_sample,
        "on_CloseSettingsDialog_change": lambda *_: st.session_state.pop(EDIT_MONITOR_SETTINGS_DIALOG_KEY, None),
    }
    return data, handlers


@with_database_session
def delete_monitor_suite(table_group: TableGroupMinimal) -> None:
    try:
        monitor_suite = get_test_suite(table_group.monitor_test_suite_id)
        disable_monitoring(monitor_suite)
        st.cache_data.clear()
    except Exception:
        LOG.exception("Failed to delete monitor suite")
        st.toast("Unable to delete monitors for the table group, try again.", icon=":material/error:")


@with_database_session
def build_schema_changes_data(table_group: TableGroupMinimal, payload: dict) -> tuple[dict, dict]:
    table_name = payload.get("table_name")
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")
    data_structure_logs = get_data_structure_logs(table_group.id, table_name, start_time, end_time)
    data = {
        "dialog": {"open": True, "title": f"Table: {table_name}"},
        "window_start": start_time,
        "window_end": end_time,
        "data_structure_logs": make_json_safe(data_structure_logs),
    }
    handlers = {
        "on_CloseSchemaChangesDialog_change": lambda *_: st.session_state.pop(SCHEMA_CHANGES_DIALOG_KEY, None),
    }
    return data, handlers


def _resolve_holiday_dates(test_suite: TestSuite) -> set[date] | None:
    if not test_suite.holiday_codes_list:
        return None
    now = pd.Timestamp.now("UTC")
    idx = pd.DatetimeIndex([now - pd.Timedelta(days=7), now + pd.Timedelta(days=30)])
    return resolve_holiday_dates(test_suite.holiday_codes_list, idx)


def _freshness_next_update_window(
    freshness_definition: TestDefinition | None,
    events: dict,
    test_suite: TestSuite,
    monitor_schedule,
) -> dict | None:
    """Predicted next freshness-update window as {"start", "end"} epoch-ms, or None.

    The schedule-derived business-time interval from the last detected update out to the
    lower/upper staleness tolerance. Drives the Freshness_Trend display window and couples the
    freshness-gated Volume/Metric forecast to the expected next refresh.
    """
    if (
        freshness_definition is None
        or freshness_definition.history_calculation != "PREDICT"
        or (freshness_definition.prediction and not freshness_definition.prediction.get("schedule_stage"))
        or freshness_definition.upper_tolerance is None
    ):
        return None

    last_update_events = [
        e for e in events["freshness_events"]
        if e["changed"] and not e["is_training"] and not e["is_pending"]
    ]
    if not last_update_events:
        return None

    last_detection_time = max(e["time"] for e in last_update_events)
    holiday_dates = _resolve_holiday_dates(test_suite)
    tz = monitor_schedule.cron_tz or "UTC" if monitor_schedule else None
    sched = get_schedule_params(freshness_definition.prediction)

    window_end = add_business_minutes(
        pd.Timestamp(last_detection_time),
        float(freshness_definition.upper_tolerance),
        test_suite.predict_exclude_weekends,
        holiday_dates, tz,
        excluded_days=sched.excluded_days,
    )
    window_start = None
    if lower_minutes := (float(freshness_definition.lower_tolerance) if freshness_definition.lower_tolerance else None):
        window_start = add_business_minutes(
            pd.Timestamp(last_detection_time),
            lower_minutes,
            test_suite.predict_exclude_weekends,
            holiday_dates, tz,
            excluded_days=sched.excluded_days,
        )

    return {
        "start": int(window_start.timestamp() * 1000) if window_start else None,
        "end": int(window_end.timestamp() * 1000),
    }


def _build_gated_forecast_prediction(
    definition: TestDefinition,
    freshness_window: dict | None,
    last_run_time: datetime | None,
) -> dict | None:
    """Coupled forecast payload for a freshness-gated Volume/Metric monitor.

    Holds a flat baseline line from the latest run up to the predicted next-update window, then
    steps to the forecast's next-refresh value with the band opening to its tolerance. The anchor
    is never earlier than the latest run, so the forecast extends forward rather than back over
    history. Returns None when there is no usable forward window — the caller then falls back to a
    flat band — i.e. when freshness has no predicted window, the window has already elapsed, or the
    gated prediction carries no baseline.
    """
    baseline = definition.prediction.get("baseline_value") if definition.prediction else None
    window_end = freshness_window.get("end") if freshness_window else None
    now_ms = int(pd.Timestamp(last_run_time).timestamp() * 1000) if last_run_time is not None else None
    if window_end is None or now_ms is None or window_end <= now_ms or baseline is None:
        return None

    forecast_means = (definition.prediction.get("mean") if definition.prediction else None) or {}
    next_refresh_mean = forecast_means[min(forecast_means, key=lambda k: int(k))] if forecast_means else baseline
    flat_anchor = max(freshness_window.get("start") or now_ms, now_ms)
    # lower/upper_tolerance are VARCHAR columns — coerce to float so the band dicts are numerically
    # typed throughout (baseline is already a float).
    lower_tol = float(definition.lower_tolerance) if definition.lower_tolerance is not None else None
    upper_tol = float(definition.upper_tolerance) if definition.upper_tolerance is not None else None
    return {
        "method": "predict",
        "mean": {flat_anchor: baseline, window_end: next_refresh_mean},
        "lower_tolerance": {flat_anchor: baseline, window_end: lower_tol},
        "upper_tolerance": {flat_anchor: baseline, window_end: upper_tol},
    }


@with_database_session
def build_table_trends_data(
    table_group: TableGroupMinimal, payload: dict, dialog: dict | None = None,
) -> tuple[dict, dict]:
    table_name = payload.get("table_name")
    get_selected_data_point, set_selected_data_point = temp_value("table_monitoring_trends:dsl_time", default=None)
    extended_history_key = f"table_monitoring_trends:extended:{table_group.monitor_test_suite_id}:{table_name}"

    def on_show_data_structure_logs(payload):
        try:
            set_selected_data_point(
                (float(payload.get("start_time")) / 1000, float(payload.get("end_time")) / 1000)
            )
        except Exception:  # noqa: S110
            pass

    def on_toggle_extended_history(_payload):
        st.session_state[extended_history_key] = not st.session_state.get(extended_history_key, False)

    def on_close_trends(_payload=None):
        st.session_state.pop(TABLE_TRENDS_DIALOG_KEY, None)
        st.session_state.pop(DIALOG_AUTO_OPENED_KEY, None)
        Router().set_query_params({"table_name": None})

    extended_history = st.session_state.get(extended_history_key, False)

    selected_data_point = get_selected_data_point()
    data_structure_logs = None
    if selected_data_point:
        data_structure_logs = get_data_structure_logs(
            table_group.id, table_name, *selected_data_point,
        )

    lookback_multiplier = 3 if extended_history else 1
    events = get_monitor_events_for_table(table_group.monitor_test_suite_id, table_name, lookback_multiplier)
    definitions = select_test_definitions_where(
        TestDefinition.test_suite_id == table_group.monitor_test_suite_id,
        TestDefinition.table_name == table_name,
        TestDefinition.test_type.in_(["Freshness_Trend", "Volume_Trend", "Metric_Trend"]),
    )

    predictions = {}
    if len(definitions) > 0:
        test_suite = get_test_suite(table_group.monitor_test_suite_id)
        monitor_schedule = get_monitor_schedule(table_group.monitor_test_suite_id)
        monitor_lookback = test_suite.monitor_lookback
        predict_sensitivity = test_suite.predict_sensitivity or PredictSensitivity.medium

        last_run_time_per_test_key: dict[str, datetime] = {
            "volume_trend": max(e["time"] for e in events["volume_events"]),
        }
        for metric_group in events["metric_events"]:
            metric_definition_id = metric_group["test_definition_id"]
            last_run_time_per_test_key[f"metric:{metric_definition_id}"] = max(e["time"] for e in metric_group["events"])

        # Predicted next freshness-update window for the table — shared by the Freshness_Trend
        # display window and the freshness-gated Volume/Metric forecast (which expects no change
        # until a refresh lands in this window).
        freshness_definition = next((d for d in definitions if d.test_type == "Freshness_Trend"), None)
        freshness_window = _freshness_next_update_window(freshness_definition, events, test_suite, monitor_schedule)

        for definition in definitions:
            test_key = f"metric:{definition.id}" if definition.test_type == "Metric_Trend" else definition.test_type.lower()
            if (
                definition.history_calculation == "PREDICT"
                and definition.prediction
                and not definition.prediction.get("freshness_gated")
                and (base_mean_predictions := definition.prediction.get("mean"))
            ):
                predicted_times = sorted([datetime.fromtimestamp(int(timestamp) / 1000.0, UTC) for timestamp in base_mean_predictions.keys()])
                # Limit predictions to 1/3 of the lookback, with minimum 3 points
                predicted_times = [str(int(t.timestamp() * 1000)) for idx, t in enumerate(predicted_times) if idx < 3 or idx < monitor_lookback / 3]

                mean_predictions: dict = {}
                lower_tolerance_predictions: dict = {}
                upper_tolerance_predictions: dict = {}
                for timestamp in predicted_times:
                    mean_predictions[timestamp] = base_mean_predictions[timestamp]
                    lower_tolerance_predictions[timestamp] = definition.prediction[f"lower_tolerance|{predict_sensitivity.value}"][timestamp]
                    upper_tolerance_predictions[timestamp] = definition.prediction[f"upper_tolerance|{predict_sensitivity.value}"][timestamp]

                predictions[test_key] = {
                    "method": "predict",
                    "mean": mean_predictions,
                    "lower_tolerance": lower_tolerance_predictions,
                    "upper_tolerance": upper_tolerance_predictions,
                }
            elif (
                definition.history_calculation == "PREDICT"
                and definition.prediction
                and definition.prediction.get("freshness_gated")
                and (definition.lower_tolerance is not None or definition.upper_tolerance is not None)
            ):
                # A freshness-gated monitor holds at its baseline between refreshes (the stale-period
                # check is value == baseline), so it must never render the rising forecast cone.
                gated_prediction = _build_gated_forecast_prediction(
                    definition, freshness_window, last_run_time_per_test_key.get(test_key),
                )
                if gated_prediction is not None:
                    predictions[test_key] = gated_prediction
                else:
                    # No freshness window available — fall back to a flat band at the next-refresh
                    # tolerance sampled across upcoming scheduled runs.
                    cron_sample = get_cron_sample(
                        monitor_schedule.cron_expr,
                        monitor_schedule.cron_tz,
                        sample_count=ceil(min(max(3, monitor_lookback / 3), 10)),
                        reference_time=last_run_time_per_test_key.get(test_key),
                    )
                    mean_predictions: dict = {}
                    lower_tolerance_predictions: dict = {}
                    upper_tolerance_predictions: dict = {}
                    sample_next_runs = [timestamp * 1000 for timestamp in (cron_sample.get("samples") or [])]
                    for timestamp in sample_next_runs:
                        mean_predictions[timestamp] = None
                        lower_tolerance_predictions[timestamp] = definition.lower_tolerance
                        upper_tolerance_predictions[timestamp] = definition.upper_tolerance

                    predictions[test_key] = {
                        "method": "static",
                        "mean": mean_predictions,
                        "lower_tolerance": lower_tolerance_predictions,
                        "upper_tolerance": upper_tolerance_predictions,
                    }
            elif definition.history_calculation is None and (definition.lower_tolerance is not None or definition.upper_tolerance is not None):
                cron_sample = get_cron_sample(
                    monitor_schedule.cron_expr,
                    monitor_schedule.cron_tz,
                    sample_count=ceil(min(max(3, monitor_lookback / 3), 10)),
                    reference_time=last_run_time_per_test_key.get(test_key),
                )
                mean_predictions: dict = {}
                lower_tolerance_predictions: dict = {}
                upper_tolerance_predictions: dict = {}
                sample_next_runs = [timestamp * 1000 for timestamp in (cron_sample.get("samples") or [])]
                for timestamp in sample_next_runs:
                    mean_predictions[timestamp] = None
                    lower_tolerance_predictions[timestamp] = definition.lower_tolerance
                    upper_tolerance_predictions[timestamp] = definition.upper_tolerance

                predictions[test_key] = {
                    "method": "static",
                    "mean": mean_predictions,
                    "lower_tolerance": lower_tolerance_predictions,
                    "upper_tolerance": upper_tolerance_predictions,
                }
            elif definition.test_type == "Freshness_Trend" and freshness_window is not None:
                predictions["freshness_trend"] = {
                    "method": "freshness_window",
                    "window": freshness_window,
                }

    data = {
        **make_json_safe(events),
        "data_structure_logs": make_json_safe(data_structure_logs),
        "predictions": predictions,
        "extended_history": extended_history,
        "dialog": dialog,
    }
    handlers = {
        "on_ShowDataStructureLogs_change": on_show_data_structure_logs,
        "on_ToggleExtendedHistory_change": on_toggle_extended_history,
        "on_CloseTrendsDialog_change": on_close_trends,
    }
    return data, handlers


@st.cache_data(show_spinner=False)
def get_monitor_events_for_table(test_suite_id: str, table_name: str, lookback_multiplier: int = 1) -> dict:
    query = """
    WITH ranked_test_runs AS (
        SELECT
            test_runs.id,
            test_runs.test_starttime,
            COALESCE(test_suites.monitor_lookback, 1) * :lookback_multiplier AS lookback,
            ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
        FROM test_suites
        INNER JOIN test_runs
            ON (test_suites.id = test_runs.test_suite_id)
        WHERE test_suites.id = :test_suite_id
    ),
    active_runs AS (
        SELECT id, test_starttime FROM ranked_test_runs
        WHERE position <= lookback
    ),
    target_tests AS (
        SELECT 'Freshness_Trend' AS test_type
        UNION ALL SELECT 'Volume_Trend'
        UNION ALL SELECT 'Schema_Drift'
        UNION ALL SELECT 'Metric_Trend'
    )
    SELECT
        COALESCE(results.test_time, active_runs.test_starttime) AS test_time,
        tt.test_type,
        results.id AS result_id,
        results.result_code,
        COALESCE(results.result_status, 'Log') AS result_status,
        results.result_signal,
        results.result_message,
        results.test_definition_id::TEXT,
        COALESCE(results.input_parameters, '') AS input_parameters,
        results.column_names
    FROM active_runs
    CROSS JOIN target_tests tt
    LEFT JOIN test_results AS results
        ON (
            results.test_run_id = active_runs.id
            AND results.test_type = tt.test_type
            AND results.table_name = :table_name
        )
    LEFT JOIN test_definitions AS definition
        ON (definition.id = results.test_definition_id)
    ORDER BY active_runs.id, tt.test_type;
    """

    params = {
        "table_name": table_name,
        "test_suite_id": test_suite_id,
        "lookback_multiplier": lookback_multiplier,
    }

    results = fetch_all_from_db(query, params)
    results = [ dict(row) for row in results ]

    metric_events: dict[str, dict] = {}
    for event in results:
        if event["test_type"] == "Metric_Trend" and event["result_status"] != "Error" and (definition_id := event["test_definition_id"]):
            if definition_id not in metric_events:
                metric_events[definition_id] = {
                    "test_definition_id": definition_id,
                    "column_name": event["column_names"],
                    "events": [],
                }
            params = dict_from_kv(event.get("input_parameters") or "")
            metric_events[definition_id]["events"].append({
                "value": float(event["result_signal"]) if event["result_signal"] else None,
                "time": event["test_time"],
                "is_anomaly": int(event["result_code"]) == 0 if event["result_code"] is not None else None,
                "is_training": int(event["result_code"]) == -1 if event["result_code"] is not None else None,
                "is_pending": not bool(event["result_id"]),
                "lower_tolerance": params.get("lower_tolerance") if params.get("lower_tolerance") else None,
                "upper_tolerance": params.get("upper_tolerance") if params.get("upper_tolerance") else None,
                "threshold_value": params.get("threshold_value") if params.get("threshold_value") else None,
            })

    return {
        "freshness_events": [
            {
                "changed": "detected: Yes" in (result_message := event["result_message"] or ""),
                "message": parts[1].rstrip(".") if len(parts := result_message.split(". ", 1)) > 1 else None,
                "status": event["result_status"],
                "is_training": event["result_code"] == -1,
                "is_pending": not bool(event["result_id"]),
                "time": event["test_time"],
            }
            for event in results if event["test_type"] == "Freshness_Trend" and event["result_status"] != "Error"
        ],
        "volume_events": [
            {
                "record_count": int(event["result_signal"] or 0),
                "time": event["test_time"],
                "is_anomaly": int(event["result_code"]) == 0 if event["result_code"] is not None else None,
                "is_training": int(event["result_code"]) == -1 if event["result_code"] is not None else None,
                "is_pending": not bool(event["result_id"]),
                **params,
            }
            for event in results if event["test_type"] == "Volume_Trend" and event["result_status"] != "Error" and (
                params := dict_from_kv(event.get("input_parameters"))
                    or {"lower_tolerance": None, "upper_tolerance": None}
            )
        ],
        "schema_events": [
            {
                "table_change": signals[0] or None,
                "additions": signals[1],
                "deletions": signals[2],
                "modifications": signals[3],
                "time": event["test_time"],
                "window_start": datetime.fromisoformat(signals[4]) if signals[4] else None,
            }
            for event in results if event["test_type"] == "Schema_Drift" and event["result_status"] != "Error"
            and (signals := (event["result_signal"] or "|0|0|0|").split("|") or True)
        ],
        "metric_events": list(metric_events.values()),
    }


@st.cache_data(show_spinner=False)
def get_data_structure_logs(table_group_id: str, table_name: str, start_time: str, end_time: str):
    query = """
    SELECT
        change_date,
        change,
        old_data_type,
        new_data_type,
        column_name
    FROM data_structure_log
    WHERE table_groups_id = :table_group_id
        AND table_name = :table_name
        AND change_date > :start_time ::TIMESTAMP
        AND change_date <= :end_time ::TIMESTAMP;
    """
    params = {
        "table_group_id": str(table_group_id),
        "table_name": table_name,
        "start_time": datetime.fromtimestamp(start_time, UTC),
        "end_time": datetime.fromtimestamp(end_time, UTC),
    }

    results = fetch_all_from_db(query, params)
    return [ dict(row) for row in results ]


@with_database_session
def build_edit_table_monitors_data(
    table_group: TableGroupMinimal, payload: dict, dialog: dict | None = None,
) -> tuple[dict, dict]:
    table_name = payload.get("table_name")
    definitions = select_test_definitions_where(
        TestDefinition.test_suite_id == table_group.monitor_test_suite_id,
        TestDefinition.table_name == table_name,
        TestDefinition.test_type.in_(["Freshness_Trend", "Volume_Trend", "Metric_Trend"]),
    )

    def on_save_test_definition(payload: dict) -> None:
        set_save(True)
        set_close(payload.get("close", False))
        set_updated_definitions(payload.get("updated_definitions", []))
        set_new_metrics(payload.get("new_metrics", []))
        set_deleted_metric_ids(payload.get("deleted_metric_ids", []))

    should_save, set_save = temp_value(f"edit_table_monitors:save:{table_name}", default=False)
    should_close, set_close = temp_value(f"edit_table_monitors:close:{table_name}", default=False)
    get_updated_definitions, set_updated_definitions = temp_value(f"edit_table_monitors:updated_definitions:{table_name}", default=[])
    get_new_metrics, set_new_metrics = temp_value(f"edit_table_monitors:new_metrics:{table_name}", default=[])
    get_deleted_metric_ids, set_deleted_metric_ids = temp_value(f"edit_table_monitors:deleted_metric_ids:{table_name}", default=[])
    get_result, set_result = temp_value(f"edit_table_monitors:result:{table_name}", default=None)

    if should_save():
        valid_columns = {col.name for col in TestDefinition.__table__.columns}

        for updated_def in get_updated_definitions():
            current_def: TestDefinitionSummary = get_test_definition(updated_def.get("id"))
            if current_def:
                merged = {key: getattr(current_def, key, None) for key in valid_columns}
                merged.update({key: value for key, value in updated_def.items() if key in valid_columns})
                merged["lock_refresh"] = True

                # For Freshness static mode: set threshold_value and lower_tolerance
                # so the SQL template's staleness and BETWEEN checks work correctly.
                # Also clear prediction JSON to avoid stale schedule-based exclusions.
                if merged.get("test_type") == "Freshness_Trend" and merged.get("history_calculation") != "PREDICT":
                    merged["threshold_value"] = merged.get("upper_tolerance")
                    merged["lower_tolerance"] = 0
                    merged["prediction"] = None

                merged["last_manual_update"] = datetime.now(UTC)
                TestDefinition(**merged).save()

        for new_metric in get_new_metrics():
            new_def = TestDefinition(
                table_groups_id=table_group.id,
                test_type="Metric_Trend",
                test_suite_id=table_group.monitor_test_suite_id,
                schema_name=table_group.table_group_schema,
                table_name=table_name,
                test_active=True,
                lock_refresh=True,
            )
            for key, value in new_metric.items():
                if key in valid_columns:
                    setattr(new_def, key, value)
            new_def.last_manual_update = datetime.now(UTC)
            new_def.save()

        deleted_ids = get_deleted_metric_ids()
        if deleted_ids:
            TestDefinition.delete_where(
                TestDefinition.id.in_(deleted_ids),
                TestDefinition.test_type == "Metric_Trend",
            )

        if should_close():
            st.session_state.pop(EDIT_TABLE_MONITORS_DIALOG_KEY, None)
            safe_rerun()

        set_result({"success": True, "timestamp": datetime.now(UTC).isoformat()})
        safe_rerun()

    metric_test_types = get_test_type_summaries(test_type="Metric_Trend")
    metric_test_type = metric_test_types[0] if metric_test_types else None

    data = {
        "table_name": table_name,
        "definitions": [td.to_dict(json_safe=True) for td in definitions],
        "metric_test_type": metric_test_type.to_dict(json_safe=True) if metric_test_type else {},
        "result": get_result(),
        "dialog": dialog,
    }
    handlers = {
        "on_SaveTestDefinition_change": on_save_test_definition,
        "on_CloseEditMonitorsDialog_change": lambda *_: st.session_state.pop(EDIT_TABLE_MONITORS_DIALOG_KEY, None),
    }
    return data, handlers
