import logging
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

import streamlit as st

from testgen.commands.test_generation import run_monitor_generation
from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    MonitorNotificationSettings,
    MonitorNotificationTrigger,
    NotificationEvent,
)
from testgen.common.models.project import Project
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import PredictSensitivity, TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries.profiling_queries import get_tables_by_table_group
from testgen.ui.services.database_service import execute_db_query, fetch_all_from_db, fetch_one_from_db
from testgen.ui.session import session, temp_value
from testgen.ui.utils import get_cron_sample, get_cron_sample_handler
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.utils import make_json_safe

PAGE_ICON = "apps_outage"
PAGE_TITLE = "Monitors"
LOG = logging.getLogger("testgen")


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
        only_tables_with_anomalies: Literal["true", "false"] | None = None,
        sort_field: str | None = None,
        sort_order: str | None = None,
        items_per_page: str = "20",
        current_page: str = "0",
        **_kwargs,
    ) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "monitors-dashboard",
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
        
        current_page = int(current_page)
        items_per_page = int(items_per_page)
        page_start = current_page * items_per_page

        if table_group_id:
            selected_table_group = next(item for item in table_groups if str(item.id) == table_group_id)
            monitor_suite_id = selected_table_group.monitor_test_suite_id

            if monitor_suite_id:
                monitor_schedule = JobSchedule.get(
                    JobSchedule.key == RUN_MONITORS_JOB_KEY,
                    JobSchedule.kwargs["test_suite_id"].astext == str(monitor_suite_id),
                )

            monitored_tables_page = get_monitor_changes_by_tables(
                table_group_id,
                table_name_filter=table_name_filter,
                only_tables_with_anomalies=only_tables_with_anomalies and only_tables_with_anomalies.lower() == "true",
                sort_field=sort_field,
                sort_order=sort_order,
                limit=int(items_per_page),
                offset=page_start,
            )
            all_monitored_tables_count = count_monitor_changes_by_tables(
                table_group_id,
                table_name_filter=table_name_filter,
                only_tables_with_anomalies=only_tables_with_anomalies and only_tables_with_anomalies.lower() == "true",
            )
            monitor_changes_summary = summarize_monitor_changes(table_group_id)

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
                    "only_tables_with_anomalies": only_tables_with_anomalies,
                },
                "sort": {
                    "sort_field": sort_field,
                    "sort_order": sort_order,
                } if sort_field and sort_order else None,
                "has_monitor_test_suite": bool(selected_table_group and monitor_suite_id),
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
    only_tables_with_anomalies: bool = False,
    sort_field: str | None = None,
    sort_order: Literal["asc"] | Literal["desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict]:
    query, params = _monitor_changes_by_tables_query(
        table_group_id,
        table_name_filter=table_name_filter,
        only_tables_with_anomalies=only_tables_with_anomalies,
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
    only_tables_with_anomalies: bool = False,
) -> int:
    query, params = _monitor_changes_by_tables_query(
        table_group_id,
        table_name_filter=table_name_filter,
        only_tables_with_anomalies=only_tables_with_anomalies,
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
        BOOL_OR(freshness_is_training) AS freshness_is_training,
        BOOL_OR(volume_is_training) AS volume_is_training,
        BOOL_OR(freshness_is_pending) AS freshness_is_pending,
        BOOL_OR(volume_is_pending) AS volume_is_pending,
        BOOL_OR(schema_is_pending) AS schema_is_pending
    FROM ({query}) AS subquery
    GROUP BY lookback
    """

    result = fetch_one_from_db(count_query, params)
    return {**result} if result else {
        "lookback": 0,
        "freshness_anomalies": 0,
        "volume_anomalies": 0,
        "schema_anomalies": 0,
        "freshness_is_training": False,
        "volume_is_training": False,
        "freshness_is_pending": False,
        "volume_is_pending": False,
        "schema_is_pending": False,
    }


def _monitor_changes_by_tables_query(
    table_group_id: str,
    table_name_filter: str | None = None,
    only_tables_with_anomalies: bool = False,
    sort_field: str | None = None,
    sort_order: Literal["asc"] | Literal["desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[str, dict]:
    query = f"""
    WITH latest_tables AS (
        SELECT DISTINCT
            table_chars.schema_name,
            table_chars.table_name
        FROM data_table_chars table_chars
        WHERE table_chars.table_groups_id = :table_group_id
            AND table_chars.drop_date IS NULL
            {"AND table_chars.table_name ILIKE :table_name_filter" if table_name_filter else ''}
    ),
    ranked_test_runs AS (
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
            CASE WHEN results.test_type = 'Volume_Trend' THEN results.result_signal::BIGINT ELSE NULL END AS row_count,
            CASE WHEN results.test_type = 'Schema_Drift' THEN SPLIT_PART(results.result_signal, '|', 1) ELSE NULL END AS table_change,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 2), '')::INT ELSE 0 END AS col_adds,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 3), '')::INT ELSE 0 END AS col_drops,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 4), '')::INT ELSE 0 END AS col_mods
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
            MAX(test_time) FILTER (WHERE test_type = 'Freshness_Trend' AND result_code = 0) AS latest_update,
            MAX(row_count) FILTER (WHERE position = 1) AS row_count,
            SUM(col_adds) AS column_adds,
            SUM(col_drops) AS column_drops,
            SUM(col_mods) AS column_mods,
            BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Freshness_Trend' AND position = 1) AS freshness_is_training,
            BOOL_OR(is_training = 1) FILTER (WHERE test_type = 'Volume_Trend' AND position = 1) AS volume_is_training,
            BOOL_OR(test_type = 'Freshness_Trend') IS NOT TRUE AS freshness_is_pending,
            BOOL_OR(test_type = 'Volume_Trend') IS NOT TRUE AS volume_is_pending,
            -- Schema monitor only creates results on schema changes (Failed)
            -- Mark it as pending only if there are no results of any test type
            BOOL_OR(test_time IS NOT NULL) IS NOT TRUE AS schema_is_pending,
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
    {"WHERE (freshness_anomalies + schema_anomalies + volume_anomalies) > 0" if only_tables_with_anomalies else ''}
    {f"ORDER BY monitor_tables.{sort_field} {'ASC' if sort_order == 'asc' else 'DESC'} NULLS LAST" if sort_field else 'ORDER BY LOWER(monitor_tables.table_name)'}
    {"LIMIT :limit" if limit else ''}
    {"OFFSET :offset" if offset else ''}
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

        cron_sample_result, on_cron_sample = get_cron_sample_handler("monitors:cron_expr_validation", sample_count=0)
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
            st.rerun()
            st.cache_data.clear()
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


def open_table_trends(table_group: TableGroupMinimal, payload: dict):
    table_name = payload.get("table_name")
    get_selected_data_point, set_selected_data_point = temp_value("table_monitoring_trends:dsl_time", default=None)

    @with_database_session
    def show_dialog():
        testgen.css_class("l-dialog")

        selected_data_point = get_selected_data_point()
        data_structure_logs = None
        if selected_data_point:
            data_structure_logs = get_data_structure_logs(
                table_group.id, table_name, *selected_data_point,
            )
        
        events = get_monitor_events_for_table(table_group.monitor_test_suite_id, table_name)
        definitions = TestDefinition.select_where(
            TestDefinition.test_suite_id == table_group.monitor_test_suite_id,
            TestDefinition.table_name == table_name,
            TestDefinition.prediction != None,
        )

        predictions = {}
        if len(definitions) > 0:
            test_suite = TestSuite.get(table_group.monitor_test_suite_id)
            monitor_lookback = test_suite.monitor_lookback
            predict_sensitivity = test_suite.predict_sensitivity or PredictSensitivity.medium
            for definition in definitions:
                if (base_mean_predictions := definition.prediction.get("mean")):
                    predicted_times = sorted([datetime.fromtimestamp(int(timestamp) / 1000.0, UTC) for timestamp in base_mean_predictions.keys()])
                    predicted_times = [str(int(t.timestamp() * 1000)) for idx, t in enumerate(predicted_times) if idx < monitor_lookback]

                    mean_predictions: dict = {}
                    lower_tolerance_predictions: dict = {}
                    upper_tolerance_predictions: dict = {}
                    for timestamp in predicted_times:
                        mean_predictions[timestamp] = base_mean_predictions[timestamp]
                        lower_tolerance_predictions[timestamp] = definition.prediction[f"lower_tolerance|{predict_sensitivity.value}"][timestamp]
                        upper_tolerance_predictions[timestamp] = definition.prediction[f"upper_tolerance|{predict_sensitivity.value}"][timestamp]

                    predictions[definition.test_type.lower()] = {
                        "mean": mean_predictions,
                        "lower_tolerance": lower_tolerance_predictions,
                        "upper_tolerance": upper_tolerance_predictions,
                    }

        testgen.table_monitoring_trends(
            "table_monitoring_trends",
            data={
                **make_json_safe(events),
                "data_structure_logs": make_json_safe(data_structure_logs),
                "predictions": predictions,
            },
            on_ShowDataStructureLogs_change=on_show_data_structure_logs,
        )

    def on_show_data_structure_logs(payload):
        try:
            set_selected_data_point(
                (float(payload.get("start_time")) / 1000, float(payload.get("end_time")) / 1000)
            )
        except: pass  # noqa: S110

    return st.dialog(title=f"Table: {table_name}")(show_dialog)()


@st.cache_data(show_spinner=False)
def get_monitor_events_for_table(test_suite_id: str, table_name: str) -> dict:
    query = """
    WITH ranked_test_runs AS (
        SELECT
            test_runs.id,
            test_runs.test_starttime,
            COALESCE(test_suites.monitor_lookback, 1) AS lookback,
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
    )
    SELECT 
        COALESCE(results.test_time, active_runs.test_starttime) AS test_time,
        tt.test_type,
        results.result_code,
        COALESCE(results.result_status, 'Log') AS result_status,
        results.result_signal
    FROM active_runs
    CROSS JOIN target_tests tt
    LEFT JOIN test_results AS results
        ON (
            results.test_run_id = active_runs.id 
            AND results.test_type = tt.test_type
            AND results.table_name = :table_name
        )
    ORDER BY active_runs.id, tt.test_type;
    """

    params = {
        "table_name": table_name,
        "test_suite_id": test_suite_id,
    }

    results = fetch_all_from_db(query, params)
    results = [ dict(row) for row in results ]

    return {
        "freshness_events": [
            {"changed": event["result_code"] is not None and int(event["result_code"]) == 0, "expected": None, "status": event["result_status"], "time": event["test_time"]}
            for event in results if event["test_type"] == "Freshness_Trend"
        ],
        "volume_events": [
            {"record_count": int(event["result_signal"] or 0), "time": event["test_time"]}
            for event in results if event["test_type"] == "Volume_Trend"
        ],
        "schema_events": [
            {
                "additions": signals[1],
                "deletions": signals[2],
                "modifications": signals[3],
                "time": event["test_time"],
                "window_start": datetime.fromisoformat(signals[4]) if signals[4] else None,
            }
            for event in results if event["test_type"] == "Schema_Drift"
            and (signals := (event["result_signal"] or "|0|0|0|").split("|") or True)
        ],
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
