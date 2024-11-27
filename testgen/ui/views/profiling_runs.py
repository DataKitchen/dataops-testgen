import typing
from functools import partial

import pandas as pd
import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
from testgen.commands.run_profiling_bridge import update_profile_run_status
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import project_queries
from testgen.ui.services import authentication_service
from testgen.ui.session import session
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog
from testgen.utils import to_int

FORM_DATA_WIDTH = 400
PAGE_SIZE = 50
PAGE_ICON = "data_thresholding"


class DataProfilingPage(Page):
    path = "profiling-runs"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon=PAGE_ICON, label="Data Profiling", order=1)

    def render(self, project_code: str | None = None, table_group_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            "Profiling Runs",
            "investigate-profiling",
        )

        project_code = project_code or session.project
        if render_empty_state(project_code):
            return

        group_filter_column, actions_column = st.columns([.3, .7], vertical_alignment="bottom")

        with group_filter_column:
            table_groups_df = get_db_table_group_choices(project_code)
            table_group_id = testgen.select(
                options=table_groups_df,
                value_column="id",
                display_column="table_groups_name",
                default_value=table_group_id,
                bind_to_query="table_group_id",
                label="Table Group",
            )

        with actions_column:
            testgen.flex_row_end()

            if authentication_service.current_user_has_edit_role():
                st.button(
                    ":material/play_arrow: Run Profiling",
                    help="Run profiling for a table group",
                    on_click=partial(run_profiling_dialog, project_code, None, table_group_id)
                )
        fm.render_refresh_button(actions_column)

        testgen.whitespace(0.5)
        list_container = st.container()

        profiling_runs_df = get_db_profiling_runs(project_code, table_group_id)

        run_count = len(profiling_runs_df)
        page_index = testgen.paginator(count=run_count, page_size=PAGE_SIZE)
        paginated_df = profiling_runs_df[PAGE_SIZE * page_index : PAGE_SIZE * (page_index + 1)]

        with list_container:
            testgen_component(
                "profiling_runs",
                props={ "items": paginated_df.to_json(orient="records") },
                event_handlers={ "RunCanceled": on_cancel_run }
            )


def render_empty_state(project_code: str) -> bool:
    project_summary_df = project_queries.get_summary_by_code(project_code)
    if project_summary_df["profiling_runs_ct"]:
        return False

    label = "No profiling runs yet"
    testgen.whitespace(5)
    if not project_summary_df["connections_ct"]:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.Connection,
            action_label="Go to Connections",
            link_href="connections",
        )
    elif not project_summary_df["table_groups_ct"]:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.TableGroup,
            action_label="Go to Table Groups",
            link_href="connections:table-groups",
            link_params={ "connection_id": str(project_summary_df["default_connection_id"]) }
        )
    else:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.Profiling,
            action_label="Run Profiling",
            button_onclick=partial(run_profiling_dialog, project_code),
            button_icon="play_arrow",
        )
    return True


def on_cancel_run(profiling_run: pd.Series) -> None:
    process_status, process_message = process_service.kill_profile_run(to_int(profiling_run["process_id"]))
    if process_status:
        update_profile_run_status(profiling_run["profiling_run_id"], "Cancelled")

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
