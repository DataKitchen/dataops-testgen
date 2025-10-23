import datetime
import logging
from typing import ClassVar, Literal

import pandas as pd
import streamlit as st

from testgen.common.models import with_database_session
from testgen.common.models.table_group import TableGroup
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services.database_service import execute_db_query, fetch_df_from_db, fetch_one_from_db
from testgen.ui.session import session, temp_value
from testgen.ui.views.test_suites import edit_test_suite_dialog

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

        table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
        selected_table_group_id = table_group_id or (str(table_groups[0].id) if table_groups else None)
        selected_table_group = TableGroup.get_minimal(selected_table_group_id or "")

        current_page = int(current_page)
        items_per_page = int(items_per_page)
        page_start = current_page * items_per_page

        monitored_tables_page = get_monitor_changes_by_tables(
            project_code,
            table_group_id=selected_table_group_id,
            table_name_filter=table_name_filter,
            only_tables_with_anomalies=only_tables_with_anomalies and only_tables_with_anomalies.lower() == "true",
            sort_field=sort_field,
            sort_order=sort_order,
            limit=int(items_per_page),
            offset=page_start,
        )
        all_monitored_tables_count = count_monitor_changes_by_tables(
            project_code,
            table_group_id=selected_table_group_id,
            table_name_filter=table_name_filter,
            only_tables_with_anomalies=only_tables_with_anomalies and only_tables_with_anomalies.lower() == "true",
        )
        monitor_changes_summary = summarize_monitor_changes(project_code, table_group_id=selected_table_group_id)

        return testgen.testgen_component(
            "monitors_dashboard",
            props={
                "summary": monitor_changes_summary,
                "table_group_filter_options": [
                    {
                        "value": str(table_group.id),
                        "label": table_group.table_groups_name,
                        "selected": str(selected_table_group_id) == str(table_group.id),
                    } for table_group in table_groups
                ],
                "monitors": {
                    "items": monitored_tables_page,
                    "current_page": current_page,
                    "items_per_page": items_per_page,
                    "total_count": all_monitored_tables_count,
                },
                "filters": {
                    "table_group_id": selected_table_group_id,
                    "table_name_filter": table_name_filter,
                    "only_tables_with_anomalies": only_tables_with_anomalies,
                },
                "sort": {
                    "sort_field": sort_field,
                    "sort_order": sort_order,
                } if sort_field and sort_order else None,
                "has_monitor_test_suite": bool(selected_table_group and selected_table_group.monitor_test_suite_id),
            },
            on_change_handlers={
                "OpenMonitoringTrends": lambda payload: open_table_trends(project_code, payload),
                "SetParamValues": lambda payload: set_param_values(payload),
                "EditTestSuite": lambda *_: edit_monitor_test_suite(project_code, selected_table_group_id),
            },
        )


@st.cache_data(show_spinner=False)
def get_monitor_changes_by_tables(
    project_code: str,
    *,
    table_group_id: str | None = None,
    table_name_filter: str | None = None,
    only_tables_with_anomalies: bool = False,
    sort_field: str | None = None,
    sort_order: Literal["asc"] | Literal["desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict]:
    query, params = _monitor_changes_by_tables_query(
        project_code,
        table_group_id=table_group_id,
        table_name_filter=table_name_filter,
        only_tables_with_anomalies=only_tables_with_anomalies,
        sort_field=sort_field,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )

    results = fetch_df_from_db(query, params)
    results["latest_update"] = pd.Series(results["latest_update"].apply(lambda dt: dt.tz_localize("UTC").isoformat() if not pd.isna(dt) else None), dtype="object")

    return results.replace({pd.NaT: None}).to_dict("records")


@st.cache_data(show_spinner=False)
def count_monitor_changes_by_tables(
    project_code: str,
    *,
    table_group_id: str | None = None,
    table_name_filter: str | None = None,
    only_tables_with_anomalies: bool = False,
) -> int:
    query, params = _monitor_changes_by_tables_query(
        project_code,
        table_group_id=table_group_id,
        table_name_filter=table_name_filter,
        only_tables_with_anomalies=only_tables_with_anomalies,
    )
    count_query = f"SELECT COUNT(*) AS count FROM ({query}) AS subquery"
    result = execute_db_query(count_query, params)
    return result or 0


@st.cache_data(show_spinner=False)
def summarize_monitor_changes(
    project_code: str,
    *,
    table_group_id: str | None = None,
) -> dict:
    query, params = _monitor_changes_by_tables_query(
        project_code,
        table_group_id=table_group_id,
    )
    count_query = f"""
    SELECT
        lookback,
        SUM(freshness_anomalies)::INTEGER AS freshness_anomalies,
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
    project_code: str,
    *,
    table_group_id: str | None = None,
    table_name_filter: str | None = None,
    only_tables_with_anomalies: bool = False,
    sort_field: str | None = None,
    sort_order: Literal["asc"] | Literal["desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[str, dict]:
    query = f"""
    WITH
        ranked_test_runs AS (
            SELECT
                test_runs.id as id,
                ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
            FROM table_groups
            INNER JOIN test_runs
                ON (test_runs.test_suite_id = table_groups.monitor_test_suite_id)
            WHERE table_groups.project_code = :project_code
                AND table_groups.monitor_test_suite_id IS NOT NULL
            ORDER BY test_runs.test_suite_id, test_runs.test_starttime
        ),
        monitor_tables AS (
            SELECT
                results.table_groups_id::text AS table_group_id,
                results.table_name,
                COALESCE(test_suites.monitor_lookback, 1) AS lookback,
                SUM(CASE WHEN results.test_type = 'Table_Freshness' THEN COALESCE(results.failed_ct, 0) ELSE 0 END) AS freshness_anomalies,
                SUM(CASE WHEN results.test_type = 'Schema_Drift' THEN COALESCE(results.failed_ct, 0) ELSE 0 END) AS schema_anomalies,
                MAX(results.test_date) FILTER (WHERE results.test_type = 'Table_Freshness' AND results.result_measure = 1) AS latest_update
            FROM ranked_test_runs
            INNER JOIN v_test_results AS results
                ON (results.test_run_id = ranked_test_runs.id)
            INNER JOIN test_suites
                ON (test_suites.id = results.test_suite_id)
            WHERE results.project_code = :project_code
                AND ranked_test_runs.position <= COALESCE(test_suites.monitor_lookback, 1)
                AND results.table_name IS NOT NULL
                {"AND results.table_groups_id = :table_group_id" if table_group_id else ''}
                {"AND results.table_name ILIKE :table_name_filter" if table_name_filter else ''}
            GROUP BY results.table_groups_id, results.table_name, COALESCE(test_suites.monitor_lookback, 1)
        )
    SELECT
        *
    FROM monitor_tables
    {"WHERE (freshness_anomalies + schema_anomalies) > 0" if only_tables_with_anomalies else ''}
    {f"ORDER BY {sort_field} {'ASC' if sort_order == 'asc' else 'DESC'} NULLS LAST" if sort_field else ''}
    {"LIMIT :limit" if limit else ''}
    {"OFFSET :offset" if offset else ''}
    """

    params = {
        "project_code": project_code,
        "table_group_id": table_group_id,
        "table_name_filter": f"%{table_name_filter.replace('_', '\\_')}%" if table_name_filter else None,
        "sort_field": sort_field,
        "limit": limit,
        "offset": offset,
    }

    return query, params


def set_param_values(payload: dict) -> None:
    Router().set_query_params(payload)


def edit_monitor_test_suite(project_code: str, table_group_id: str | None = None):
    if table_group_id:
        table_group = TableGroup.get_minimal(table_group_id)
        if table_group and table_group.monitor_test_suite_id:
            edit_test_suite_dialog(project_code, [table_group], table_group.monitor_test_suite_id)


def open_table_trends(project_code: str, payload: dict):
    table_group_id = payload.get("table_group_id")
    table_name = payload.get("table_name")
    get_selected_data_point, set_selected_data_point = temp_value("table_monitoring_trends:dsl_time", default=None)

    @with_database_session
    def show_dialog():
        testgen.css_class("l-dialog")

        table_group = TableGroup.get_minimal(table_group_id)
        selected_data_point = get_selected_data_point()
        data_structure_logs = None
        if selected_data_point:
            data_structure_logs = get_data_structure_logs(
                project_code=project_code,
                table_name=table_name,
                test_suite_id=table_group.monitor_test_suite_id,
                time=selected_data_point,
            )

        events = get_monitor_events_for_table(
            project_code,
            table_name=table_name,
            test_suite_id=table_group.monitor_test_suite_id,
        )

        testgen.testgen_component(
            "table_monitoring_trends",
            props={
                **events,
                "data_structure_logs": data_structure_logs,
            },
            on_change_handlers={
                "ShowDataStructureLogs": on_show_data_structure_logs,
            },
        )

    def on_show_data_structure_logs(payload):
        try:
            set_selected_data_point(float(payload.get("time")) / 1000)
        except: pass  # noqa: S110

    return st.dialog(title=f"Table: {table_name}")(show_dialog)()


@st.cache_data(show_spinner=False)
def get_monitor_events_for_table(
    project_code: str,
    *,
    table_name: str,
    test_suite_id: str,
) -> dict:
    query = f"""
    WITH ranked_test_runs AS ({_ranked_test_runs_query()}),
    test_filters AS (
        SELECT * FROM (
            VALUES
                ('{test_suite_id}'::uuid, '{table_name}'::varchar, 'Table_Freshness'::varchar)
        ) AS tt(test_suite_id, table_name, test_type)
    )
    SELECT
        COALESCE(results.test_time, ranked_test_runs.start) AS test_time,
        test_filters.test_type,
        results.result_signal,
        COALESCE(results.result_status, 'Log') AS result_status,
        COALESCE(results.result_measure, '0') AS result_measure
    FROM ranked_test_runs
    LEFT JOIN test_suites
        ON (test_suites.id = ranked_test_runs.test_suite_id)
    LEFT JOIN test_filters
        ON (test_filters.test_suite_id = test_suites.id)
    LEFT JOIN test_results AS results
        ON (
            results.test_run_id = ranked_test_runs.id
            AND results.table_name = test_filters.table_name
            AND results.test_type = test_filters.test_type
        )
    WHERE ranked_test_runs.position <= COALESCE(test_suites.monitor_lookback, 1)

    UNION

    SELECT
        COALESCE(data_structure_log.change_date, ranked_test_runs.start) AS test_time,
        'Schema_Drift' AS test_type,
        (
            SUM(CASE WHEN data_structure_log.change = 'A' THEN 1 ELSE 0 END)::varchar
            || '|'
            || SUM(CASE WHEN data_structure_log.change = 'M' THEN 1 ELSE 0 END)::varchar
            || '|'
            || SUM(CASE WHEN data_structure_log.change = 'D' THEN 1 ELSE 0 END)::varchar
        ) AS result_signal,
        'Log' AS result_status,
        '' AS result_measure
    FROM ranked_test_runs
    LEFT JOIN test_suites
        ON (test_suites.id = ranked_test_runs.test_suite_id)
    LEFT JOIN data_structure_log
        ON (
            data_structure_log.table_groups_id = test_suites.table_groups_id
            AND data_structure_log.change_date BETWEEN ranked_test_runs.start AND ranked_test_runs.end
            AND data_structure_log.table_name = :table_name
        )
    WHERE test_suites.project_code = :project_code
        AND test_suites.id = :test_suite_id
        AND ranked_test_runs.position <= COALESCE(test_suites.monitor_lookback, 1)
    GROUP BY data_structure_log.table_name, ranked_test_runs.start, data_structure_log.change_date, ranked_test_runs.position

    ORDER BY test_time ASC
    """

    params = {
        "project_code": project_code,
        "table_name": table_name,
        "test_suite_id": test_suite_id,
    }

    results = fetch_df_from_db(query, params)
    results["test_time"] = pd.Series(results["test_time"].apply(lambda dt: dt.tz_localize("UTC").isoformat() if not pd.isna(dt) else None), dtype="object")
    results = results.replace({pd.NaT: None})

    return {
        "freshness_events": [
            {"changed": int(event["result_measure"]) == 1, "expected": None, "status": event["result_status"], "time": event["test_time"]}
            for event in results[results["test_type"] == "Table_Freshness"].to_dict("records")
        ],
        "schema_events": [
            {"additions": counts[0], "modifications": counts[1], "deletions": counts[2], "time": event["test_time"]}
            for event in results[results["test_type"] == "Schema_Drift"].to_dict("records")
            if (counts := (event["result_signal"] or "0|0|0").split("|") or True)
        ],
    }


@st.cache_data(show_spinner=False)
def get_data_structure_logs(project_code: str, *, table_name: str, test_suite_id: str, time: int):
    query = f"""
        WITH ranked_test_runs AS ({_ranked_test_runs_query()})
        SELECT
            data_structure_log.change_date,
            data_structure_log.change,
            data_structure_log.old_data_type,
            data_structure_log.new_data_type,
            data_structure_log.column_name
        FROM ranked_test_runs
        LEFT JOIN test_suites
            ON (test_suites.id = ranked_test_runs.test_suite_id)
        LEFT JOIN data_structure_log
            ON (
                data_structure_log.table_groups_id = test_suites.table_groups_id
                AND data_structure_log.change_date BETWEEN ranked_test_runs.start AND ranked_test_runs.end
                AND data_structure_log.table_name = :table_name
            )
        WHERE test_suites.project_code = :project_code
            AND test_suites.id = :test_suite_id
            AND COALESCE(data_structure_log.change_date, ranked_test_runs.start)::timestamp(0) = :change_time ::timestamp(0)
            AND data_structure_log.change IS NOT NULL
    """
    params = {
        "project_code": project_code,
        "test_suite_id": str(test_suite_id),
        "table_name": table_name,
        "change_time": datetime.datetime.fromtimestamp(time, datetime.UTC).isoformat(),
    }

    results = fetch_df_from_db(query, params)
    results["change_date"] = pd.Series(results["change_date"].apply(lambda dt: dt.tz_localize("UTC").isoformat() if not pd.isna(dt) else None), dtype="object")

    return results.to_dict("records")

def _ranked_test_runs_query():
    return """
        SELECT
            test_runs.id as id,
            test_runs.test_suite_id,
            test_runs.test_starttime AS "start",
            (
                COALESCE(LEAD(test_runs.test_starttime) OVER (ORDER BY test_runs.test_suite_id, test_runs.test_starttime ASC), (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))
                - INTERVAL '1' MINUTE
            ) AS "end",
            ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
        FROM table_groups
        INNER JOIN test_runs
            ON (test_runs.test_suite_id = table_groups.monitor_test_suite_id)
        WHERE table_groups.project_code = :project_code
            AND table_groups.monitor_test_suite_id = :test_suite_id
        ORDER BY test_runs.test_suite_id, test_runs.test_starttime
    """
