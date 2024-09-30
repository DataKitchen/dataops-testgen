import typing
from functools import partial

import pandas as pd
import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
from testgen.commands.run_profiling_bridge import update_profile_run_status
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.session import session
from testgen.utils import to_int

FORM_DATA_WIDTH = 400
PAGE_SIZE = 10


class DataProfilingPage(Page):
    path = "profiling-runs"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="problem", label="Data Profiling", order=1)

    def render(self, project_code: str | None = None, table_group_id: str | None = None, **_kwargs) -> None:
        project_code = project_code or session.project

        testgen.page_header(
            "Profiling Runs",
            "https://docs.datakitchen.io/article/dataops-testgen-help/investigate-profiling",
        )

        group_filter_column, actions_column = st.columns([.3, .7], vertical_alignment="bottom")

        with group_filter_column:
            table_groups_df = get_db_table_group_choices(project_code)
            table_group_id = testgen.toolbar_select(
                options=table_groups_df,
                value_column="id",
                display_column="table_groups_name",
                default_value=table_group_id,
                bind_to_query="table_group_id",
                label="Table Group",
            )

        testgen.flex_row_end(actions_column)
        fm.render_refresh_button(actions_column)

        testgen.whitespace(0.5)
        list_container = st.container(border=True)

        profiling_runs_df = get_db_profiling_runs(project_code, table_group_id)

        run_count = len(profiling_runs_df)
        page_index = testgen.paginator(count=run_count, page_size=PAGE_SIZE)

        with list_container:
            testgen.css_class("bg-white")
            column_spec = [.2, .2, .2, .4]

            run_column, status_column, schema_column, issues_column = st.columns(column_spec, vertical_alignment="top")
            header_styles = "font-size: 12px; text-transform: uppercase; margin-bottom: 8px;"
            testgen.caption("Start Time | Table Group", header_styles, run_column)
            testgen.caption("Status | Duration", header_styles, status_column)
            testgen.caption("Schema", header_styles, schema_column)
            testgen.caption("Hygiene Issues", header_styles, issues_column)
            testgen.divider(-8)

            paginated_df = profiling_runs_df[PAGE_SIZE * page_index : PAGE_SIZE * (page_index + 1)]
            for index, profiling_run in paginated_df.iterrows():
                with st.container():
                    render_profiling_run_row(profiling_run, column_spec)

                    if (index + 1) % PAGE_SIZE and index != run_count - 1:
                        testgen.divider(-4, 4)


def render_profiling_run_row(profiling_run: pd.Series, column_spec: list[int]) -> None:
    profiling_run_id = profiling_run["profiling_run_id"]
    status = profiling_run["status"]

    run_column, status_column, schema_column, issues_column = st.columns(column_spec, vertical_alignment="top")

    with run_column:
        start_time = date_service.get_timezoned_timestamp(st.session_state, profiling_run["start_time"]) if pd.notnull(profiling_run["start_time"]) else "--"
        testgen.no_flex_gap()
        testgen.text(start_time)
        testgen.caption(profiling_run["table_groups_name"])

    with status_column:
        testgen.flex_row_start()

        status_display_map = {
            "Running": { "label": "Running", "color": "blue" },
            "Complete": { "label": "Completed", "color": "" },
            "Error": { "label": "Error", "color": "red" },
            "Cancelled": { "label": "Canceled", "color": "purple" },
        }
        status_attrs = status_display_map.get(status, { "label": "Unknown", "color": "grey" })

        st.html(f"""
                <p class="text" style="color: var(--{status_attrs["color"]})">{status_attrs["label"]}</p>
                <p class="caption">{date_service.get_formatted_duration(profiling_run["duration"])}</p>
                """)

        if status == "Error" and (log_message := profiling_run["log_message"]):
            st.markdown("", help=log_message)

        if status == "Running" and pd.notnull(profiling_run["process_id"]):
            testgen.button(
                type_="stroked",
                label="Cancel Run",
                style="width: auto; height: 32px; color: var(--purple); margin-left: 16px;",
                on_click=partial(on_cancel_run, profiling_run),
                key=f"profiling_run:keys:cancel-run:{profiling_run_id}",
            )

    with schema_column:
        column_count = to_int(profiling_run["column_ct"])
        testgen.no_flex_gap()
        testgen.text(profiling_run["schema_name"])
        testgen.caption(
            f"{to_int(profiling_run['table_ct'])} tables, {column_count} columns",
            f"margin-bottom: 3px;{' color: var(--red);' if status == 'Complete' and not column_count else ''}",
        )

        if column_count:
            testgen.link(
                label="View results",
                href="profiling-runs:results",
                params={ "run_id": str(profiling_run_id) },
                right_icon="chevron_right",
                height=18,
                key=f"profiling_run:keys:go-to-runs:{profiling_run_id}",
            )

    with issues_column:
        if anomaly_count := to_int(profiling_run["anomaly_ct"]):
            testgen.no_flex_gap()
            testgen.summary_bar(
                items=[
                    { "label": "Definite", "value": to_int(profiling_run["anomalies_definite_ct"]), "color": "red" },
                    { "label": "Likely", "value": to_int(profiling_run["anomalies_likely_ct"]), "color": "orange" },
                    { "label": "Possible", "value": to_int(profiling_run["anomalies_possible_ct"]), "color": "yellow" },
                    { "label": "Dismissed", "value": to_int(profiling_run["anomalies_dismissed_ct"]), "color": "grey" },
                ],
                height=10,
                width=280,
            )
            testgen.link(
                label=f"View {anomaly_count} issues",
                href="profiling-runs:hygiene",
                params={ "run_id": str(profiling_run_id) },
                right_icon="chevron_right",
                height=18,
                key=f"profiling_run:keys:go-to-hygiene:{profiling_run_id}",
            )
        else:
            st.markdown("--")


def on_cancel_run(profiling_run: pd.Series) -> None:
    process_status, process_message = process_service.kill_test_run(profiling_run["process_id"])
    if process_status:
        update_profile_run_status(profiling_run["profile_run_id"], "Cancelled")

    fm.reset_post_updates(str_message=f":{'green' if process_status else 'red'}[{process_message}]", as_toast=True)


@st.cache_data(show_spinner=False)
def get_db_table_group_choices(project_code: str) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(schema, project_code)


@st.cache_data(show_spinner="Retrieving Data")
def get_db_profiling_runs(project_code: str, table_group_id: str | None = None) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    table_group_condition = f" AND v_profiling_runs.table_groups_id = '{table_group_id}' " if table_group_id else ""
    sql = f"""
    WITH profile_anomalies AS (
        SELECT profile_anomaly_results.profile_run_id,
            SUM(
                CASE
                    WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                    AND profile_anomaly_types.issue_likelihood = 'Definite' THEN 1
                    ELSE 0
                END
            ) as definite_ct,
            SUM(
                CASE
                    WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                    AND profile_anomaly_types.issue_likelihood = 'Likely' THEN 1
                    ELSE 0
                END
            ) as likely_ct,
            SUM(
                CASE
                    WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                    AND profile_anomaly_types.issue_likelihood = 'Possible' THEN 1
                    ELSE 0
                END
            ) as possible_ct,
            SUM(
                CASE
                    WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive')
                    AND profile_anomaly_types.issue_likelihood <> 'Potential PII' THEN 1
                    ELSE 0
                END
            ) as dismissed_ct
        FROM {schema}.profile_anomaly_results
            LEFT JOIN {schema}.profile_anomaly_types ON (
                profile_anomaly_types.id = profile_anomaly_results.anomaly_id
            )
        GROUP BY profile_anomaly_results.profile_run_id
    )
    SELECT v_profiling_runs.profiling_run_id::VARCHAR,
        v_profiling_runs.start_time,
        v_profiling_runs.table_groups_name,
        CASE
            WHEN v_profiling_runs.status = 'Running'
            AND v_profiling_runs.start_time < CURRENT_DATE - 1 THEN 'Error'
            ELSE v_profiling_runs.status
        END as status,
        v_profiling_runs.process_id,
        v_profiling_runs.duration,
        v_profiling_runs.log_message,
        v_profiling_runs.schema_name,
        v_profiling_runs.table_ct,
        v_profiling_runs.column_ct,
        v_profiling_runs.anomaly_ct,
        profile_anomalies.definite_ct as anomalies_definite_ct,
        profile_anomalies.likely_ct as anomalies_likely_ct,
        profile_anomalies.possible_ct as anomalies_possible_ct,
        profile_anomalies.dismissed_ct as anomalies_dismissed_ct
    FROM {schema}.v_profiling_runs
        LEFT JOIN profile_anomalies ON (v_profiling_runs.profiling_run_id = profile_anomalies.profile_run_id)
    WHERE project_code = '{project_code}'
    {table_group_condition}
    ORDER BY start_time DESC;
    """

    return db.retrieve_data(sql)
