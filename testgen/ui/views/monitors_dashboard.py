import logging
from datetime import UTC, date, datetime
from math import ceil
from typing import Any, ClassVar, Literal

import pandas as pd
import streamlit as st

from testgen.commands.test_generation import run_monitor_generation
from testgen.common.freshness_service import add_business_minutes, get_schedule_params, resolve_holiday_dates
from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    MonitorNotificationSettings,
    MonitorNotificationTrigger,
    NotificationEvent,
)
from testgen.common.models.project import Project
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_definition import TestDefinition, TestDefinitionSummary, TestType
from testgen.common.models.test_suite import PredictSensitivity, TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries.profiling_queries import get_tables_by_table_group
from testgen.ui.services.database_service import execute_db_query, fetch_all_from_db, fetch_one_from_db
from testgen.ui.session import session, temp_value
from testgen.ui.utils import dict_from_kv, get_cron_sample, get_cron_sample_handler
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.utils import make_json_safe

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

        project_summary = Project.get_summary(project_code)
        table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)

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
                    monitor_schedule = JobSchedule.get(
                        JobSchedule.key == RUN_MONITORS_JOB_KEY,
                        JobSchedule.kwargs["test_suite_id"].astext == str(monitor_suite_id),
                    )

                    anomaly_type_filter = [t for t in anomaly_type_filter.split(",") if t in ANOMALY_TYPE_FILTERS] if anomaly_type_filter else None
                    if sort_field and sort_field not in ALLOWED_SORT_FIELDS:
                        sort_field = None

                    monitored_tables_page = get_monitor_changes_by_tables(
                        table_group_id,
                        table_name_filter=table_name_filter,
                        anomaly_type_filter=anomaly_type_filter,
                        sort_field=sort_field,
                        sort_order=sort_order,
                        limit=int(items_per_page),
                        offset=page_start,
                    )
                    all_monitored_tables_count = count_monitor_changes_by_tables(
                        table_group_id,
                        table_name_filter=table_name_filter,
                        anomaly_type_filter=anomaly_type_filter,
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

        return testgen.testgen_component(
            "monitors_dashboard",
            props={
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
            },
            on_change_handlers={
                "OpenSchemaChanges": lambda payload: open_schema_changes(selected_table_group, payload),
                "OpenMonitoringTrends": lambda payload: open_table_trends(selected_table_group, payload),
                "SetParamValues": lambda payload: set_param_values(payload),
                "EditNotifications": manage_notifications(project_code, selected_table_group),
                "EditMonitorSettings": lambda *_: edit_monitor_settings(selected_table_group, monitor_schedule),
                "DeleteMonitorSuite": lambda *_: delete_monitor_suite(selected_table_group),
                "EditTableMonitors": lambda payload: edit_table_monitors(selected_table_group, payload),
            },
        )


def manage_notifications(project_code: str, selected_table_group: TableGroupMinimal):
    def open_dialog(*_):
        MonitorNotificationSettingsDialog(
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
        ).open(),
    return open_dialog


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
) -> list[dict]:
    query, params = _monitor_changes_by_tables_query(
        table_group_id,
        table_name_filter=table_name_filter,
        anomaly_type_filter=anomaly_type_filter,
        sort_field=sort_field,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )

    results = fetch_all_from_db(query, params)
    return [ dict(row) for row in results ]


@st.cache_data(show_spinner=False)
def count_monitor_changes_by_tables(
    table_group_id: str,
    table_name_filter: str | None = None,
    anomaly_type_filter: list[str] | None = None,
) -> int:
    query, params = _monitor_changes_by_tables_query(
        table_group_id,
        table_name_filter=table_name_filter,
        anomaly_type_filter=anomaly_type_filter,
    )
    count_query = f"SELECT COUNT(*) AS count FROM ({query}) AS subquery"
    result = execute_db_query(count_query, params)
    return result or 0


@st.cache_data(show_spinner=False)
def summarize_monitor_changes(table_group_id: str) -> dict:
    query, params = _monitor_changes_by_tables_query(table_group_id)
    count_query = f"""
    SELECT
        lookback,
        MIN(lookback_start) AS lookback_start,
        MAX(lookback_end) AS lookback_end,
        SUM(freshness_anomalies)::INTEGER AS freshness_anomalies,
        SUM(volume_anomalies)::INTEGER AS volume_anomalies,
        SUM(schema_anomalies)::INTEGER AS schema_anomalies,
        SUM(metric_anomalies)::INTEGER AS metric_anomalies,
        BOOL_OR(freshness_error_message IS NOT NULL) AS freshness_has_errors,
        BOOL_OR(volume_error_message IS NOT NULL) AS volume_has_errors,
        BOOL_OR(schema_error_message IS NOT NULL) AS schema_has_errors,
        BOOL_OR(metric_error_message IS NOT NULL) AS metric_has_errors,
        BOOL_OR(freshness_is_training) AND BOOL_AND(freshness_is_training OR freshness_is_pending) AS freshness_is_training,
        BOOL_OR(volume_is_training) AND BOOL_AND(volume_is_training OR volume_is_pending) AS volume_is_training,
        BOOL_OR(metric_is_training) AND BOOL_AND(metric_is_training OR metric_is_pending) AS metric_is_training,
        BOOL_AND(freshness_is_pending) AS freshness_is_pending,
        BOOL_AND(volume_is_pending) AS volume_is_pending,
        BOOL_AND(schema_is_pending) AS schema_is_pending,
        BOOL_AND(metric_is_pending) AS metric_is_pending
    FROM ({query}) AS subquery
    GROUP BY lookback
    """

    result = fetch_one_from_db(count_query, params)
    return {**result} if result else {
        "lookback": 0,
        "freshness_anomalies": 0,
        "volume_anomalies": 0,
        "schema_anomalies": 0,
        "metric_anomalies": 0,
        "freshness_is_training": False,
        "volume_is_training": False,
        "metric_is_training": False,
        "freshness_is_pending": False,
        "volume_is_pending": False,
        "schema_is_pending": False,
        "metric_is_pending": False,
        "freshness_has_errors": False,
        "volume_has_errors": False,
        "schema_has_errors": False,
        "metric_has_errors": False,
    }


def _monitor_changes_by_tables_query(
    table_group_id: str,
    table_name_filter: str | None = None,
    anomaly_type_filter: list[str] | None = None,
    sort_field: str | None = None,
    sort_order: Literal["asc"] | Literal["desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[str, dict]:
    query = f"""
    WITH ranked_test_runs AS (
        SELECT
            test_runs.id,
            test_runs.test_starttime,
            COALESCE(test_suites.monitor_lookback, 1) AS lookback,
            ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
        FROM table_groups
        INNER JOIN test_runs
            ON (test_runs.test_suite_id = table_groups.monitor_test_suite_id)
        INNER JOIN test_suites
            ON (table_groups.monitor_test_suite_id = test_suites.id)
        WHERE table_groups.id = :table_group_id
    ),
    lookback_window AS (
        SELECT MIN(test_starttime) AS lookback_start
        FROM ranked_test_runs
        WHERE position <= lookback
    ),
    latest_tables AS (
        SELECT DISTINCT
            table_chars.schema_name,
            table_chars.table_name
        FROM data_table_chars table_chars
        CROSS JOIN lookback_window
        WHERE table_chars.table_groups_id = :table_group_id
            -- Include current tables and tables dropped within lookback window
            AND (table_chars.drop_date IS NULL OR table_chars.drop_date >= lookback_window.lookback_start)
            {"AND table_chars.table_name ILIKE :table_name_filter" if table_name_filter else ''}
    ),
    monitor_results AS (
        SELECT
            latest_tables.table_name,
            results.test_time,
            results.test_type,
            results.result_code,
            ranked_test_runs.lookback,
            ranked_test_runs.position,
            ranked_test_runs.test_starttime,
            -- result_code = -1 indicates training mode
            CASE WHEN results.result_code = -1 THEN 1 ELSE 0 END AS is_training,
            CASE WHEN results.test_type = 'Freshness_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END AS freshness_anomaly,
            CASE WHEN results.test_type = 'Volume_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END AS volume_anomaly,
            CASE WHEN results.test_type = 'Schema_Drift' AND results.result_code = 0 THEN 1 ELSE 0 END AS schema_anomaly,
            CASE WHEN results.test_type = 'Metric_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END AS metric_anomaly,
            CASE WHEN results.test_type = 'Freshness_Trend' THEN results.result_signal ELSE NULL END AS freshness_interval,
            CASE WHEN results.test_type = 'Volume_Trend' THEN results.result_signal::BIGINT ELSE NULL END AS row_count,
            CASE WHEN results.test_type = 'Schema_Drift' THEN SPLIT_PART(results.result_signal, '|', 1) ELSE NULL END AS table_change,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 2), '')::INT ELSE 0 END AS col_adds,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 3), '')::INT ELSE 0 END AS col_drops,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 4), '')::INT ELSE 0 END AS col_mods,
            CASE WHEN results.result_status = 'Error' THEN results.result_message ELSE NULL END AS error_message
        FROM latest_tables
        LEFT JOIN ranked_test_runs ON TRUE
        LEFT JOIN test_results AS results
            ON results.test_run_id = ranked_test_runs.id
            AND results.table_name = latest_tables.table_name
        WHERE ranked_test_runs.position IS NULL
            -- Also capture 1 run before the lookback to get baseline results
            OR ranked_test_runs.position <= ranked_test_runs.lookback + 1
    ),
    monitor_tables AS (
        SELECT
            :table_group_id AS table_group_id,
            table_name,
            MAX(lookback) AS lookback,
            SUM(freshness_anomaly) AS freshness_anomalies,
            SUM(volume_anomaly) AS volume_anomalies,
            SUM(schema_anomaly) AS schema_anomalies,
            SUM(metric_anomaly) AS metric_anomalies,
            MAX(test_time - (COALESCE(NULLIF(freshness_interval, 'Unknown')::INTEGER, 0) * INTERVAL '1 minute'))
                FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS latest_update,
            MAX(row_count) FILTER (WHERE position = 1) AS row_count,
            SUM(col_adds) AS column_adds,
            SUM(col_drops) AS column_drops,
            SUM(col_mods) AS column_mods,
            MAX(error_message) FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS freshness_error_message,
            MAX(error_message) FILTER (WHERE test_type = 'Volume_Trend' AND position = 1) AS volume_error_message,
            MAX(error_message) FILTER (WHERE test_type = 'Schema_Drift' AND position = 1) AS schema_error_message,
            MAX(error_message) FILTER (WHERE test_type = 'Metric_Trend' AND position = 1) AS metric_error_message,
            BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS freshness_is_training,
            BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Volume_Trend' AND position = 1) AS volume_is_training,
            BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Metric_Trend' AND position = 1) AS metric_is_training,
            BOOL_OR(test_type = 'Freshness_Trend') IS NOT TRUE AS freshness_is_pending,
            BOOL_OR(test_type = 'Volume_Trend') IS NOT TRUE AS volume_is_pending,
            -- Schema monitor only creates results on schema changes (Failed)
            -- Mark it as pending only if there are no results of any test type
            BOOL_OR(test_time IS NOT NULL) IS NOT TRUE AS schema_is_pending,
            BOOL_OR(test_type = 'Metric_Trend') IS NOT TRUE AS metric_is_pending,
            CASE
                -- Mark as Dropped if latest Schema Drift result for the table indicates it was dropped
                WHEN (ARRAY_AGG(table_change ORDER BY test_time DESC) FILTER (WHERE table_change IS NOT NULL))[1] = 'D'
                    THEN 'dropped'
                -- Only mark as Added if latest change does not indicate a drop
                WHEN MAX(CASE WHEN table_change = 'A' THEN 1 ELSE 0 END) = 1
                    THEN 'added'
                WHEN SUM(schema_anomaly) > 0
                    THEN 'modified'
                ELSE NULL
            END AS table_state
        FROM monitor_results
        -- Only aggregate within lookback runs
        WHERE position IS NULL OR position <= COALESCE(lookback, 1)
        GROUP BY table_name
    ),
    table_bounds AS (
        SELECT
            table_name,
            MIN(position) AS min_position,
            MAX(position) AS max_position
        FROM monitor_results
        WHERE position IS NOT NULL
        GROUP BY table_name
    ),
    baseline_tables AS (
        SELECT
            monitor_results.table_name,
            MIN(monitor_results.test_starttime) FILTER (
                WHERE monitor_results.position = LEAST(monitor_results.lookback + 1, table_bounds.max_position)
            ) AS lookback_start,
            MAX(monitor_results.test_starttime) FILTER (
                WHERE monitor_results.position = GREATEST(1, table_bounds.min_position)
            ) AS lookback_end,
            MAX(monitor_results.row_count) FILTER (
                WHERE monitor_results.test_type = 'Volume_Trend'
                AND monitor_results.position = LEAST(monitor_results.lookback + 1, table_bounds.max_position)
            ) AS previous_row_count
        FROM monitor_results
        JOIN table_bounds ON monitor_results.table_name = table_bounds.table_name
        GROUP BY monitor_results.table_name
    )
    SELECT
        monitor_tables.*,
        baseline_tables.lookback_start,
        baseline_tables.lookback_end,
        baseline_tables.previous_row_count
    FROM monitor_tables
    LEFT JOIN baseline_tables ON monitor_tables.table_name = baseline_tables.table_name
    {f"WHERE ({' OR '.join(f'{ANOMALY_TYPE_FILTERS[t]} > 0' for t in anomaly_type_filter)})" if anomaly_type_filter else ""}
    ORDER BY {"LOWER(monitor_tables.table_name)" if not sort_field or sort_field == "table_name" else f"monitor_tables.{sort_field}"}
    {"DESC" if sort_order == "desc" else "ASC"} NULLS LAST
    {"LIMIT :limit" if limit else ""}
    {"OFFSET :offset" if offset else ""}
    """

    params = {
        "table_group_id": table_group_id,
        "table_name_filter": f"%{table_name_filter.replace('_', '\\_')}%" if table_name_filter else None,
        "sort_field": sort_field,
        "limit": limit,
        "offset": offset,
    }

    return query, params


def set_param_values(payload: dict) -> None:
    Router().set_query_params(payload)


def edit_monitor_settings(table_group: TableGroupMinimal, schedule: JobSchedule | None):
    monitor_suite_id = table_group.monitor_test_suite_id

    @with_database_session
    def show_dialog():
        if monitor_suite_id:
            monitor_suite = TestSuite.get(monitor_suite_id)
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
            for key, value in get_monitor_suite().items():
                setattr(monitor_suite, key, value)

            is_new = not monitor_suite.id
            monitor_suite.save()

            new_schedule_config = get_schedule()
            if ( # Check if schedule has to be created/recreated
                not schedule
                or schedule.cron_tz != new_schedule_config["cron_tz"]
                or schedule.cron_expr != new_schedule_config["cron_expr"]
            ):
                if schedule:
                    JobSchedule.delete(schedule.id)

                new_schedule = JobSchedule(
                    project_code=table_group.project_code,
                    key=RUN_MONITORS_JOB_KEY,
                    args=[],
                    kwargs={"test_suite_id": str(monitor_suite.id)},
                    **new_schedule_config,
                )
                new_schedule.save()

            elif schedule.active != new_schedule_config["active"]: # Only active status changed
                JobSchedule.update_active(schedule.id, new_schedule_config["active"])

            if is_new:
                updated_table_group = TableGroup.get(table_group.id)
                updated_table_group.monitor_test_suite_id = monitor_suite.id
                updated_table_group.save()
                run_monitor_generation(monitor_suite.id, ["Volume_Trend", "Schema_Drift"])

            st.rerun()

        testgen.edit_monitor_settings(
            key="edit_monitor_settings",
            data={
                "table_group": table_group.to_dict(json_safe=True),
                "monitor_suite": monitor_suite.to_dict(json_safe=True),
                "schedule": {
                    "cron_tz": schedule.cron_tz,
                    "cron_expr": schedule.cron_expr,
                    "active": schedule.active,
                } if schedule else None,
                "cron_sample": cron_sample_result(),
            },
            on_SaveSettingsClicked_change=on_save_settings_clicked,
            on_GetCronSample_change=on_cron_sample,
        )

    return st.dialog(title="Edit Monitor Settings" if monitor_suite_id else "Configure Monitors")(show_dialog)()


@st.dialog(title="Delete Monitors")
@with_database_session
def delete_monitor_suite(table_group: TableGroupMinimal) -> None:
    def on_delete_confirmed(*_args) -> None:
        set_delete_confirmed(True)

    message = f"Are you sure you want to delete all monitors for the table group '{table_group.table_groups_name}'?"
    constraint = {
        "warning": "All monitor configuration and historical results will be deleted.",
        "confirmation": "Yes, delete all monitors and historical results.",
    }

    result, set_result = temp_value(f"monitors:result-value:{table_group.id}", default=None)
    delete_confirmed, set_delete_confirmed = temp_value(f"monitors:confirm-delete:{table_group.id}", default=False)

    testgen.testgen_component(
        "confirm_dialog",
        props={
            "message": message,
            "constraint": constraint,
            "button_label": "Delete",
            "button_color": "warn",
            "result": result(),
        },
        on_change_handlers={
            "ActionConfirmed": on_delete_confirmed,
        },
    )

    if delete_confirmed():
        try:
            with st.spinner("Deleting monitors ..."):
                monitor_suite = TestSuite.get(table_group.monitor_test_suite_id)
                TestSuite.cascade_delete([monitor_suite.id])
            st.cache_data.clear()
            st.rerun()
        except Exception:
            LOG.exception("Failed to delete monitor suite")
            set_result({
                "success": False,
                "message": "Unable to delete monitors for the table group, try again.",
            })
            st.rerun(scope="fragment")


def open_schema_changes(table_group: TableGroupMinimal, payload: dict):
    table_name = payload.get("table_name")
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")

    @with_database_session
    def show_dialog():
        testgen.css_class("s-dialog")

        data_structure_logs = get_data_structure_logs(
            table_group.id, table_name, start_time, end_time,
        )

        testgen.testgen_component(
            "schema_changes_list",
            props={
                "window_start": start_time,
                "window_end": end_time,
                "data_structure_logs": make_json_safe(data_structure_logs),
            },
        )

    return st.dialog(title=f"Table: {table_name}")(show_dialog)()


def _resolve_holiday_dates(test_suite: TestSuite) -> set[date] | None:
    if not test_suite.holiday_codes_list:
        return None
    now = pd.Timestamp.now("UTC")
    idx = pd.DatetimeIndex([now - pd.Timedelta(days=7), now + pd.Timedelta(days=30)])
    return resolve_holiday_dates(test_suite.holiday_codes_list, idx)


def open_table_trends(table_group: TableGroupMinimal, payload: dict):
    table_name = payload.get("table_name")
    st.session_state[DIALOG_AUTO_OPENED_KEY] = table_name
    Router().set_query_params({"table_name": table_name})

    get_selected_data_point, set_selected_data_point = temp_value("table_monitoring_trends:dsl_time", default=None)
    extended_history_key = f"table_monitoring_trends:extended:{table_group.monitor_test_suite_id}:{table_name}"

    @with_database_session
    def show_dialog():
        testgen.css_class("l-dialog")

        extended_history = st.session_state.get(extended_history_key, False)

        selected_data_point = get_selected_data_point()
        data_structure_logs = None
        if selected_data_point:
            data_structure_logs = get_data_structure_logs(
                table_group.id, table_name, *selected_data_point,
            )

        lookback_multiplier = 3 if extended_history else 1
        events = get_monitor_events_for_table(table_group.monitor_test_suite_id, table_name, lookback_multiplier)
        definitions = TestDefinition.select_where(
            TestDefinition.test_suite_id == table_group.monitor_test_suite_id,
            TestDefinition.table_name == table_name,
            TestDefinition.test_type.in_(["Freshness_Trend", "Volume_Trend", "Metric_Trend"]),
        )

        predictions = {}
        if len(definitions) > 0:
            test_suite = TestSuite.get(table_group.monitor_test_suite_id)
            monitor_schedule = JobSchedule.get(
                JobSchedule.key == RUN_MONITORS_JOB_KEY,
                JobSchedule.kwargs["test_suite_id"].astext == str(table_group.monitor_test_suite_id),
            )
            monitor_lookback = test_suite.monitor_lookback
            predict_sensitivity = test_suite.predict_sensitivity or PredictSensitivity.medium

            last_run_time_per_test_key: dict[str, datetime] = {
                "volume_trend": max(e["time"] for e in events["volume_events"]),
            }
            for metric_group in events["metric_events"]:
                metric_definition_id = metric_group["test_definition_id"]
                last_run_time_per_test_key[f"metric:{metric_definition_id}"] = max(e["time"] for e in metric_group["events"])

            for definition in definitions:
                test_key = f"metric:{definition.id}" if definition.test_type == "Metric_Trend" else definition.test_type.lower()
                if definition.history_calculation == "PREDICT" and definition.prediction and (base_mean_predictions := definition.prediction.get("mean")):
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
                elif (
                    definition.test_type == "Freshness_Trend"
                    and definition.history_calculation == "PREDICT"
                    and (not definition.prediction or definition.prediction.get("schedule_stage"))
                    and definition.upper_tolerance is not None
                ):
                    last_update_events = [
                        e for e in events["freshness_events"]
                        if e["changed"] and not e["is_training"] and not e["is_pending"]
                    ]
                    if last_update_events:
                        last_detection_time = max(e["time"] for e in last_update_events)
                        holiday_dates = _resolve_holiday_dates(test_suite)
                        tz = monitor_schedule.cron_tz or "UTC" if monitor_schedule else None
                        sched = get_schedule_params(definition.prediction)

                        window_end = add_business_minutes(
                            pd.Timestamp(last_detection_time),
                            float(definition.upper_tolerance),
                            test_suite.predict_exclude_weekends,
                            holiday_dates, tz,
                            excluded_days=sched.excluded_days,
                        )
                        window_start = None
                        if lower_minutes := float(definition.lower_tolerance) if definition.lower_tolerance else None:
                            window_start = add_business_minutes(
                                pd.Timestamp(last_detection_time),
                                lower_minutes,
                                test_suite.predict_exclude_weekends,
                                holiday_dates, tz,
                                excluded_days=sched.excluded_days,
                            )

                        predictions["freshness_trend"] = {
                            "method": "freshness_window",
                            "window": {
                                "start": int(window_start.timestamp() * 1000) if window_start else None,
                                "end": int(window_end.timestamp() * 1000),
                            },
                        }

        testgen.table_monitoring_trends(
            "table_monitoring_trends",
            data={
                **make_json_safe(events),
                "data_structure_logs": make_json_safe(data_structure_logs),
                "predictions": predictions,
                "extended_history": extended_history,
            },
            on_ShowDataStructureLogs_change=on_show_data_structure_logs,
            on_ToggleExtendedHistory_change=on_toggle_extended_history,
        )

    def on_show_data_structure_logs(payload):
        try:
            set_selected_data_point(
                (float(payload.get("start_time")) / 1000, float(payload.get("end_time")) / 1000)
            )
        except: pass  # noqa: S110

    def on_toggle_extended_history(_payload):
        st.session_state[extended_history_key] = not st.session_state.get(extended_history_key, False)

    def on_dismiss():
        st.session_state.pop(DIALOG_AUTO_OPENED_KEY, None)
        Router().set_query_params({"table_name": None})

    return st.dialog(title=f"Table: {table_name}", on_dismiss=on_dismiss)(show_dialog)()


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


def edit_table_monitors(table_group: TableGroupMinimal, payload: dict):
    table_name = payload.get("table_name")

    @with_database_session
    def show_dialog():
        definitions = TestDefinition.select_where(
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
                current_def: TestDefinitionSummary = TestDefinition.get(updated_def.get("id"))
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
                new_def.save()

            deleted_ids = get_deleted_metric_ids()
            if deleted_ids:
                TestDefinition.delete_where(
                    TestDefinition.id.in_(deleted_ids),
                    TestDefinition.test_type == "Metric_Trend",
                )

            if should_close():
                st.rerun()

            set_result({"success": True, "timestamp": datetime.now(UTC).isoformat()})
            st.rerun(scope="fragment")

        metric_test_types = TestType.select_summary_where(TestType.test_type == "Metric_Trend")
        metric_test_type = metric_test_types[0] if metric_test_types else None

        testgen.edit_table_monitors(
            key="edit_table_monitors",
            data={
                "table_name": table_name,
                "definitions": [td.to_dict(json_safe=True) for td in definitions],
                "metric_test_type": metric_test_type.to_dict(json_safe=True) if metric_test_type else {},
                "result": get_result(),
            },
            on_SaveTestDefinition_change=on_save_test_definition,
        )

    return st.dialog(title=f"Table Monitors: {table_name}")(show_dialog)()
