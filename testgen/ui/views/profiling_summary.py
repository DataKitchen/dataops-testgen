import typing

import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
import testgen.ui.services.toolbar_service as tb
from testgen.commands.run_profiling_bridge import update_profile_run_status
from testgen.common import date_service
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.session import session

FORM_DATA_WIDTH = 400


class DataProfilingPage(Page):
    path = "profiling"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="problem", label="Data Profiling", order=1)

    def render(self) -> None:
        fm.render_page_header(
            "Profiling Runs",
            "https://docs.datakitchen.io/article/dataops-testgen-help/investigate-profiling",
            lst_breadcrumbs=[
                {"label": "Overview", "path": "overview"},
                {"label": "Data Profiling", "path": None},
            ],
            boo_show_refresh=True,
        )

        if "project" not in st.session_state:
            st.write("Select a Project from the Overview page.")
        else:
            str_project = st.session_state["project"]

            # Setup Toolbar
            tool_bar = tb.ToolBar(3, 2, 0, None)

            with tool_bar.long_slots[0]:
                # Table Groups selection -- optional criterion
                df_tg = get_db_table_group_choices(str_project)
                str_table_groups_id = fm.render_select(
                    "Table Group", df_tg, "table_groups_name", "id", boo_required=False, str_default=None
                )

            df, show_columns = get_db_profiling_runs(str_project, str_table_groups_id)

            time_columns = ["start_time"]
            date_service.accommodate_dataframe_to_timezone(df, st.session_state, time_columns)

            dct_selected_rows = fm.render_grid_select(df, show_columns)

            open_drill_downs(dct_selected_rows, tool_bar.short_slots, self.router)

            if dct_selected_rows:
                show_record_detail(dct_selected_rows[0])
                st.markdown(":orange[Click a button to view profiling outcomes for the selected run.]")
            else:
                st.markdown(":orange[Select a run to see more information.]")


@st.cache_data(show_spinner=False)
def get_db_table_group_choices(str_project_code):
    str_schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(str_schema, str_project_code)


@st.cache_data(show_spinner="Retrieving Data")
def get_db_profiling_runs(str_project_code, str_tg=None):
    str_schema = st.session_state["dbschema"]
    str_tg_condition = f" AND table_groups_id = '{str_tg}' " if str_tg else ""
    str_sql = f"""
          SELECT project_code, connection_name,
                 connection_id::VARCHAR,
                 table_groups_id::VARCHAR,
                 profiling_run_id::VARCHAR,
                 table_groups_name, schema_name, start_time, duration,
                 CASE
                   WHEN status = 'Running' AND start_time < CURRENT_DATE - 1 THEN 'Error'
                   ELSE status
                 END as status,
                 COALESCE(log_message, '(No Errors)') as log_message,
                 table_ct, column_ct,
                 anomaly_ct, anomaly_table_ct, anomaly_column_ct, process_id
           FROM {str_schema}.v_profiling_runs
          WHERE project_code = '{str_project_code}' {str_tg_condition}
          ORDER BY start_time DESC;
    """

    show_columns = [
        "connection_name",
        "table_groups_name",
        "schema_name",
        "start_time",
        "duration",
        "status",
        "table_ct",
        "column_ct",
    ]

    return db.retrieve_data(str_sql), show_columns


def open_drill_downs(dct_selected_rows, button_slots, router):
    dct_selected_row = None
    if dct_selected_rows:
        dct_selected_row = dct_selected_rows[0]

    if button_slots[0].button(
        f":{'gray' if not dct_selected_rows else 'green'}[Profiling　→]",
        help="Review profiling characteristics for each data column",
        use_container_width=True,
        disabled=not dct_selected_rows,
    ):
        st.session_state["drill_profile_run"] = dct_selected_row["profiling_run_id"]
        router.navigate("profiling:results")

    if button_slots[1].button(
        f":{'gray' if not dct_selected_rows else 'green'}[Hygiene　→]",
        help="Review potential data problems identified in profiling",
        use_container_width=True,
        disabled=not dct_selected_rows,
    ):
        st.session_state["drill_profile_run"] = dct_selected_row["profiling_run_id"]
        st.session_state["drill_profile_tg"] = dct_selected_row["table_groups_id"]
        router.navigate("profiling:hygiene")


def show_record_detail(dct_selected_row):
    bottom_left_column, bottom_right_column = st.columns([0.5, 0.5])

    with bottom_left_column:
        str_header = "Profiling Run Information"
        lst_columns = [
            "connection_name",
            "table_groups_name",
            "schema_name",
            "log_message",
            "table_ct",
            "column_ct",
            "anomaly_ct",
            "anomaly_table_ct",
            "anomaly_column_ct",
        ]
        fm.render_html_list(dct_selected_row, lst_columns, str_header, FORM_DATA_WIDTH)

    with bottom_right_column:
        st.write("<br/><br/>", unsafe_allow_html=True)
        _, button_column = st.columns([0.3, 0.7])
        with button_column:
            enable_kill_button = dct_selected_row and dct_selected_row["process_id"] is not None and dct_selected_row["status"] == "Running"

            if enable_kill_button:
                if st.button(
                    ":red[Cancel Run]",
                    help="Kill the selected profile run",
                    use_container_width=True,
                    disabled=not enable_kill_button,
                ):
                    process_id = dct_selected_row["process_id"]
                    profile_run_id = dct_selected_row["profiling_run_id"]
                    status, message = process_service.kill_profile_run(process_id)

                    if status:
                        update_profile_run_status(profile_run_id, "Cancelled")

                    fm.reset_post_updates(str_message=f":{'green' if status else 'red'}[{message}]", as_toast=True)
