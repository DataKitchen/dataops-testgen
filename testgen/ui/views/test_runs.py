import typing
from functools import partial

import pandas as pd
import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
import testgen.ui.services.test_run_service as test_run_service
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.session import session
from testgen.utils import to_int

PAGE_SIZE = 10


class TestRunsPage(Page):
    path = "test-runs"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: session.project != None or "overview",
    ]
    menu_item = MenuItem(icon="labs", label="Data Quality Testing", order=2)

    def render(self, project_code: str | None = None, table_group_id: str | None = None, test_suite_id: str | None = None, **_kwargs) -> None:
        project_code = project_code or st.session_state["project"]

        testgen.page_header(
            "Test Runs",
            "https://docs.datakitchen.io/article/dataops-testgen-help/test-results",
        )

        group_filter_column, suite_filter_column, actions_column = st.columns([.3, .3, .4], vertical_alignment="bottom")

        with group_filter_column:
            table_groups_df = get_db_table_group_choices(project_code)
            table_groups_id = testgen.toolbar_select(
                options=table_groups_df,
                value_column="id",
                display_column="table_groups_name",
                default_value=table_group_id,
                bind_to_query="table_group_id",
                label="Table Group",
            )

        with suite_filter_column:
            test_suites_df = get_db_test_suite_choices(project_code, table_groups_id)
            test_suite_id = testgen.toolbar_select(
                options=test_suites_df,
                value_column="id",
                display_column="test_suite",
                default_value=test_suite_id,
                bind_to_query="test_suite_id",
                label="Test Suite",
            )

        testgen.flex_row_end(actions_column)
        fm.render_refresh_button(actions_column)

        testgen.whitespace(0.5)
        list_container = st.container(border=True)

        test_runs_df = get_db_test_runs(project_code, table_groups_id, test_suite_id)

        run_count = len(test_runs_df)
        page_index = testgen.paginator(count=run_count, page_size=PAGE_SIZE)

        with list_container:
            testgen.css_class("bg-white")
            column_spec = [.3, .2, .5]

            run_column, status_column, results_column = st.columns(column_spec, vertical_alignment="top")
            header_styles = "font-size: 12px; text-transform: uppercase; margin-bottom: 8px;"
            testgen.caption("Start Time | Table Group | Test Suite", header_styles, run_column)
            testgen.caption("Status | Duration", header_styles, status_column)
            testgen.caption("Results Summary", header_styles, results_column)
            testgen.divider(-8)

            paginated_df = test_runs_df[PAGE_SIZE * page_index : PAGE_SIZE * (page_index + 1)]
            for index, test_run in paginated_df.iterrows():
                with st.container():
                    render_test_run_row(test_run, column_spec)

                    if (index + 1) % PAGE_SIZE and index != run_count - 1:
                        testgen.divider(-4, 4)


def render_test_run_row(test_run: pd.Series, column_spec: list[int]) -> None:
    test_run_id = test_run["test_run_id"]
    status = test_run["status"]

    run_column, status_column, results_column = st.columns(column_spec, vertical_alignment="top")

    with run_column:
        start_time = date_service.get_timezoned_timestamp(st.session_state, test_run["test_starttime"]) if pd.notnull(test_run["test_starttime"]) else "--"
        testgen.no_flex_gap()
        testgen.link(
            label=start_time,
            href="test-runs:results",
            params={ "run_id": str(test_run_id) },
            height=18,
            key=f"test_run:keys:go-to-run:{test_run_id}",
        )
        testgen.caption(
            f"{test_run['table_groups_name']} > {test_run['test_suite']}",
            "margin-top: -9px;"
        )

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
                <p class="caption">{date_service.get_formatted_duration(test_run["duration"])}</p>
                """)

        if status == "Error" and (log_message := test_run["log_message"]):
            st.markdown("", help=log_message)

        if status == "Running" and pd.notnull(test_run["process_id"]):
            testgen.button(
                type_="stroked",
                label="Cancel Run",
                style="width: auto; height: 32px; color: var(--purple); margin-left: 16px;",
                on_click=partial(on_cancel_run, test_run),
                key=f"test_run:keys:cancel-run:{test_run_id}",
            )

    with results_column:
        if to_int(test_run["test_ct"]):
            testgen.summary_bar(
                items=[
                    { "label": "Passed", "value": to_int(test_run["passed_ct"]), "color": "green" },
                    { "label": "Warning", "value": to_int(test_run["warning_ct"]), "color": "yellow" },
                    { "label": "Failed", "value": to_int(test_run["failed_ct"]), "color": "red" },
                    { "label": "Error", "value": to_int(test_run["error_ct"]), "color": "brown" },
                    { "label": "Dismissed", "value": to_int(test_run["dismissed_ct"]), "color": "grey" },
                ],
                height=10,
                width=300,
            )
        else:
            st.markdown("--")


def on_cancel_run(test_run: pd.Series) -> None:
    process_status, process_message = process_service.kill_test_run(test_run["process_id"])
    if process_status:
        test_run_service.update_status(test_run["test_run_id"], "Cancelled")

    fm.reset_post_updates(str_message=f":{'green' if process_status else 'red'}[{process_message}]", as_toast=True)


@st.cache_data(show_spinner=False)
def run_test_suite_lookup_query(schema: str, project_code: str, table_groups_id: str | None = None) -> pd.DataFrame:
    table_group_condition = f" AND test_suites.table_groups_id = '{table_groups_id}' " if table_groups_id else ""
    sql = f"""
    SELECT test_suites.id::VARCHAR(50),
        test_suites.test_suite
    FROM {schema}.test_suites
        LEFT JOIN {schema}.table_groups ON test_suites.table_groups_id = table_groups.id
    WHERE test_suites.project_code = '{project_code}'
    {table_group_condition}
    ORDER BY test_suites.test_suite
    """
    return db.retrieve_data(sql)


@st.cache_data(show_spinner=False)
def get_db_table_group_choices(project_code: str) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(schema, project_code)


@st.cache_data(show_spinner=False)
def get_db_test_suite_choices(project_code: str, table_groups_id: str | None = None) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    return run_test_suite_lookup_query(schema, project_code, table_groups_id)


# @st.cache_data(show_spinner="Retrieving Data")
def get_db_test_runs(project_code: str, table_groups_id: str | None = None, test_suite_id: str | None = None) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    table_group_condition = f" AND test_suites.table_groups_id = '{table_groups_id}' " if table_groups_id else ""
    test_suite_condition = f" AND test_suites.id = '{test_suite_id}' " if test_suite_id else ""
    sql = f"""
    WITH run_results AS (
        SELECT test_run_id,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Passed' THEN 1
                    ELSE 0
                END
            ) as passed_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Warning' THEN 1
                    ELSE 0
                END
            ) as warning_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Failed' THEN 1
                    ELSE 0
                END
            ) as failed_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Error' THEN 1
                    ELSE 0
                END
            ) as error_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                    ELSE 0
                END
            ) as dismissed_ct
        FROM {schema}.test_results
        GROUP BY test_run_id
    )
    SELECT test_runs.id::VARCHAR as test_run_id,
        test_runs.test_starttime,
        table_groups.table_groups_name,
        test_suites.test_suite,
        test_runs.status,
        test_runs.duration,
        test_runs.process_id,
        test_runs.log_message,
        test_runs.test_ct,
        run_results.passed_ct,
        run_results.warning_ct,
        run_results.failed_ct,
        run_results.error_ct,
        run_results.dismissed_ct
    FROM {schema}.test_runs
        LEFT JOIN run_results ON (test_runs.id = run_results.test_run_id)
        INNER JOIN {schema}.test_suites ON (test_runs.test_suite_id = test_suites.id)
        INNER JOIN {schema}.table_groups ON (test_suites.table_groups_id = table_groups.id)
        INNER JOIN {schema}.projects ON (test_suites.project_code = projects.project_code)
    WHERE test_suites.project_code = '{project_code}'
    {table_group_condition}
    {test_suite_condition}
    ORDER BY test_runs.test_starttime DESC;
    """

    return db.retrieve_data(sql)
