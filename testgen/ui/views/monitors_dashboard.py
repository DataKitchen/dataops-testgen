import logging
from datetime import UTC, datetime
from typing import ClassVar, Literal

import streamlit as st

from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services.database_service import execute_db_query, fetch_all_from_db, fetch_one_from_db
from testgen.ui.session import session, temp_value
from testgen.ui.views.test_suites import edit_test_suite_dialog
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
        monitored_tables_page = []
        all_monitored_tables_count = 0
        monitor_changes_summary = None
                    
        current_page = int(current_page)
        items_per_page = int(items_per_page)
        page_start = current_page * items_per_page

        if table_group_id:
            selected_table_group = next(item for item in table_groups if str(item.id) == table_group_id)

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
                "has_monitor_test_suite": bool(selected_table_group and selected_table_group.monitor_test_suite_id),
                "permissions": {
                    "can_edit": session.auth.user_has_permission("edit"),
                },
            },
            on_change_handlers={
                "OpenSchemaChanges": lambda payload: open_schema_changes(selected_table_group, payload),
                "OpenMonitoringTrends": lambda payload: open_table_trends(selected_table_group, payload),
                "SetParamValues": lambda payload: set_param_values(payload),
                "EditTestSuite": lambda *_: edit_monitor_test_suite(project_code, selected_table_group),
            },
        )


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
        SUM(schema_anomalies)::INTEGER AS schema_anomalies
    FROM ({query}) AS subquery
    GROUP BY lookback
    """

    result = fetch_one_from_db(count_query, params)
    return {**result} if result else {
        "lookback": 0,
        "freshness_anomalies": 0,
        "schema_anomalies": 0,
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
    monitor_results AS (
        SELECT 
            results.test_time,
            results.table_name,
            results.test_type,
            results.result_code,
            ranked_test_runs.lookback,
            ranked_test_runs.position,
            ranked_test_runs.test_starttime,
            CASE WHEN results.test_type = 'Table_Freshness' AND results.result_code = 0 THEN 1 ELSE 0 END AS freshness_anomaly,
            CASE WHEN results.test_type = 'Volume_Trend' AND results.result_code = 0 THEN 1 ELSE 0 END AS volume_anomaly,
            CASE WHEN results.test_type = 'Schema_Drift' AND results.result_code = 0 THEN 1 ELSE 0 END AS schema_anomaly,
            CASE WHEN results.test_type = 'Volume_Trend' THEN results.result_signal::BIGINT ELSE NULL END AS row_count,
            CASE WHEN results.test_type = 'Schema_Drift' THEN SPLIT_PART(results.result_signal, '|', 1) ELSE NULL END AS table_change,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 2), '')::INT ELSE 0 END AS col_adds,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 3), '')::INT ELSE 0 END AS col_drops,
            CASE WHEN results.test_type = 'Schema_Drift' THEN NULLIF(SPLIT_PART(results.result_signal, '|', 4), '')::INT ELSE 0 END AS col_mods
        FROM ranked_test_runs
        INNER JOIN test_results AS results
            ON (results.test_run_id = ranked_test_runs.id)
        -- Also capture 1 run before the lookback to get baseline results
        WHERE ranked_test_runs.position <= ranked_test_runs.lookback + 1
            AND results.table_name IS NOT NULL
            {"AND results.table_name ILIKE :table_name_filter" if table_name_filter else ''}
    ),
    monitor_tables AS (
        SELECT
            :table_group_id AS table_group_id,
            table_name,
            lookback,
            SUM(freshness_anomaly) AS freshness_anomalies,
            SUM(volume_anomaly) AS volume_anomalies,
            SUM(schema_anomaly) AS schema_anomalies,
            MAX(test_time) FILTER (WHERE test_type = 'Table_Freshness' AND result_code = 0) AS latest_update,
            MAX(row_count) FILTER (WHERE position = 1) AS row_count,
            SUM(col_adds) AS column_adds,
            SUM(col_drops) AS column_drops,
            SUM(col_mods) AS column_mods,
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
        WHERE position <= lookback
        GROUP BY table_name, lookback
    ),
    table_bounds AS (
        SELECT 
            table_name,
            MIN(position) AS min_position,
            MAX(position) AS max_position
        FROM monitor_results
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
        baseline_tables.*
    FROM monitor_tables
    LEFT JOIN baseline_tables ON monitor_tables.table_name = baseline_tables.table_name
    {"WHERE (freshness_anomalies + schema_anomalies + volume_anomalies) > 0" if only_tables_with_anomalies else ''}
    {f"ORDER BY {sort_field} {'ASC' if sort_order == 'asc' else 'DESC'} NULLS LAST" if sort_field else ''}
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


def edit_monitor_test_suite(project_code: str, table_group: TableGroupMinimal | None = None):
    if table_group and table_group.monitor_test_suite_id:
        edit_test_suite_dialog(project_code, [table_group], table_group.monitor_test_suite_id)


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

        testgen.testgen_component(
            "table_monitoring_trends",
            props={
                **make_json_safe(events),
                "data_structure_logs": make_json_safe(data_structure_logs),
            },
            on_change_handlers={
                "ShowDataStructureLogs": on_show_data_structure_logs,
            },
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
            COALESCE(test_suites.monitor_lookback, 1) AS lookback,
            ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
        FROM test_suites
        INNER JOIN test_runs
            ON (test_suites.id = test_runs.test_suite_id)
        WHERE test_suites.id = :test_suite_id
    )
    SELECT 
        results.test_time,
        results.test_type,
        results.result_code,
        COALESCE(results.result_status, 'Log') AS result_status,
        results.result_signal
    FROM ranked_test_runs
    INNER JOIN test_results AS results
        ON (results.test_run_id = ranked_test_runs.id)
    WHERE ranked_test_runs.position <= ranked_test_runs.lookback
        AND results.table_name = :table_name
        AND results.test_type in ('Table_Freshness', 'Volume_Trend', 'Schema_Drift')
    ORDER BY results.test_time ASC;
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
            for event in results if event["test_type"] == "Table_Freshness"
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
                "window_start": datetime.fromisoformat(signals[4]),
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
