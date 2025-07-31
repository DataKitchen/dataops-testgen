import typing
from functools import partial
from io import BytesIO
from itertools import zip_longest
from operator import attrgetter
from uuid import UUID

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

import testgen.ui.services.form_service as fm
from testgen.commands.run_rollup_scores import run_test_rollup_scoring_queries
from testgen.common import date_service
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
    zip_multi_file_data,
)
from testgen.ui.components.widgets.page import css_class, flex_row_end
from testgen.ui.navigation.page import Page
from testgen.ui.pdf.test_result_report import create_report
from testgen.ui.queries import test_result_queries
from testgen.ui.queries.source_data_queries import get_test_issue_source_data, get_test_issue_source_data_custom
from testgen.ui.services import user_session_service
from testgen.ui.services.database_service import execute_db_query, fetch_df_from_db, fetch_one_from_db
from testgen.ui.services.string_service import empty_if_null, snake_case_to_title_case
from testgen.ui.session import session
from testgen.ui.views.dialogs.profiling_results_dialog import view_profiling_button
from testgen.ui.views.test_definitions import show_test_form_by_id
from testgen.utils import friendly_score

PAGE_PATH = "test-runs:results"


class TestResultsPage(Page):
    path = PAGE_PATH
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "run_id" in st.query_params or "test-runs",
    ]

    def render(
        self,
        run_id: str,
        status: str | None = None,
        test_type: str | None = None,
        table_name: str | None = None,
        column_name: str | None = None,
        action: str | None = None,
        **_kwargs,
    ) -> None:
        run = TestRun.get_minimal(run_id)
        if not run:
            self.router.navigate_with_warning(
                f"Test run with ID '{run_id}' does not exist. Redirecting to list of Test Runs ...",
                "test-runs",
            )
            return

        run_date = date_service.get_timezoned_timestamp(st.session_state, run.test_starttime)
        session.set_sidebar_project(run.project_code)

        testgen.page_header(
            "Test Results",
            "view-testgen-test-results",
            breadcrumbs=[
                { "label": "Test Runs", "path": "test-runs", "params": { "project_code": run.project_code } },
                { "label": f"{run.test_suite} | {run_date}" },
            ],
        )

        summary_column, score_column, actions_column, export_button_column = st.columns([.3, .15, .3, .15], vertical_alignment="bottom")
        status_filter_column, table_filter_column, column_filter_column, test_type_filter_column, action_filter_column, sort_column = st.columns(
            [.175, .2, .2, .175, .15, .1], vertical_alignment="bottom"
        )

        testgen.flex_row_end(actions_column)
        testgen.flex_row_end(export_button_column)

        with summary_column:
            tests_summary = get_test_result_summary(run_id)
            testgen.summary_bar(items=tests_summary, height=20, width=800)

        with status_filter_column:
            status_options = [
                "Failed + Warning",
                "Failed",
                "Warning",
                "Passed",
                "Error",
            ]
            status = testgen.select(
                options=status_options,
                default_value=status or "Failed + Warning",
                bind_to_query="status",
                bind_empty_value=True,
                label="Status",
            )

        run_columns_df = get_test_run_columns(run_id)
        with table_filter_column:
            table_name = testgen.select(
                options=list(run_columns_df["table_name"].unique()),
                default_value=table_name,
                bind_to_query="table_name",
                label="Table",
            )

        with column_filter_column:
            if table_name:
                column_options = run_columns_df.loc[
                    run_columns_df["table_name"] == table_name
                    ]["column_name"].dropna().unique().tolist()
            else:
                column_options = run_columns_df.groupby("column_name").first().reset_index().sort_values("column_name")
            column_name = testgen.select(
                options=column_options,
                value_column="column_name",
                default_value=column_name,
                bind_to_query="column_name",
                label="Column",
                accept_new_options=True,
            )

        with test_type_filter_column:
            test_type = testgen.select(
                options=run_columns_df.groupby("test_type").first().reset_index().sort_values("test_name_short"),
                value_column="test_type",
                display_column="test_name_short",
                default_value=test_type,
                required=False,
                bind_to_query="test_type",
                label="Test Type",
            )

        with action_filter_column:
            action = testgen.select(
                options=["✓	Confirmed", "✘	Dismissed", "🔇	Muted", "↩︎	No Action"],
                default_value=action,
                bind_to_query="action",
                label="Action",
            )
            action = action.split("	", 1)[1] if action else None

        with sort_column:
            sortable_columns = (
                ("Table", "r.table_name"),
                ("Columns/Focus", "r.column_names"),
                ("Test Type", "r.test_type"),
                ("Unit of Measure", "tt.measure_uom"),
                ("Result Measure", "result_measure"),
                ("Status", "result_status"),
                ("Action", "r.disposition"),
            )
            default = [(sortable_columns[i][1], "ASC") for i in (0, 1, 2)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default)

        with actions_column:
            str_help = "Toggle on to perform actions on multiple results"
            do_multi_select = st.toggle("Multi-Select", help=str_help)

        match status:
            case "Failed + Warning":
                status = ["Failed", "Warning"]
            case "Failed":
                status = ["Failed"]
            case "Warning":
                status = ["Warning"]
            case "Passed":
                status = ["Passed"]
            case "Error":
                status = ["Error"]

        # Display main grid and retrieve selection
        selected = show_result_detail(
            run_id,
            run_date,
            run.test_suite_id,
            export_button_column,
            status,
            test_type,
            table_name,
            column_name,
            action,
            sorting_columns,
            do_multi_select,
        )

        # Need to render toolbar buttons after grid, so selection status is maintained
        affected_cached_functions = [get_test_disposition, test_result_queries.get_test_results]

        disposition_actions = [
            { "icon": "✓", "help": "Confirm this issue as relevant for this run", "status": "Confirmed" },
            { "icon": "✘", "help": "Dismiss this issue as not relevant for this run", "status": "Dismissed" },
            { "icon": "🔇", "help": "Mute this test to deactivate it for future runs", "status": "Inactive" },
            { "icon": "↩︎", "help": "Clear action", "status": "No Decision" },
        ]

        if user_session_service.user_can_disposition():
            disable_all_dispo = not selected or status == "'Passed'" or all(sel["result_status"] == "Passed" for sel in selected)
            disposition_translator =  {"No Decision": None}
            for action in disposition_actions:
                disable_dispo = disable_all_dispo or all(
                    sel["disposition"] == disposition_translator.get(action["status"], action["status"])
                    or sel["result_status"] == "Passed"
                    for sel in selected
                )
                action["button"] = actions_column.button(action["icon"], help=action["help"], disabled=disable_dispo)

            # This has to be done as a second loop - otherwise, the rest of the buttons after the clicked one are not displayed briefly while refreshing
            for action in disposition_actions:
                if action["button"]:
                    fm.reset_post_updates(
                        do_disposition_update(selected, action["status"]),
                        as_toast=True,
                        clear_cache=True,
                        lst_cached_functions=affected_cached_functions,
                    )

        # Needs to be after all data loading/updating
        # Otherwise the database session is lost for any queries after the fragment -_-
        with score_column:
            render_score(run.project_code, run_id)

        # Help Links
        st.markdown(
            "[Help on Test Types](https://docs.datakitchen.io/article/dataops-testgen-help/testgen-test-types)"
        )


@st.fragment
@with_database_session
def render_score(project_code: str, run_id: str):
    run = TestRun.get_minimal(run_id)
    testgen.flex_row_center()
    with st.container():
        testgen.caption("Score", "text-align: center;")
        testgen.text(
            friendly_score(run.dq_score_test_run) or "--",
            "font-size: 28px;",
        )

    with st.container():
        testgen.whitespace(0.6)
        testgen.button(
            type_="icon",
            style="color: var(--secondary-text-color);",
            icon="autorenew",
            icon_size=22,
            tooltip=f"Recalculate scores for run {'and table group' if run.is_latest_run else ''}",
            on_click=partial(
                refresh_score,
                project_code,
                run_id,
                run.table_groups_id if run.is_latest_run else None,
            ),
        )


def refresh_score(project_code: str, run_id: str, table_group_id: str | None) -> None:
    run_test_rollup_scoring_queries(project_code, run_id, table_group_id)
    st.cache_data.clear()


@st.cache_data(show_spinner=False)
def get_test_run_columns(test_run_id: str) -> pd.DataFrame:
    query = """
    SELECT r.table_name as table_name, r.column_names AS column_name, t.test_name_short as test_name_short, t.test_type as test_type
    FROM test_results r
    LEFT JOIN test_types t ON t.test_type = r.test_type
    WHERE test_run_id = :test_run_id
    ORDER BY table_name, column_names;
    """
    return fetch_df_from_db(query, {"test_run_id": test_run_id})


@st.cache_data(show_spinner=False)
def get_test_disposition(test_run_id: str) -> pd.DataFrame:
    query = """
    SELECT id::VARCHAR, disposition
    FROM test_results
    WHERE test_run_id = :test_run_id;
    """
    df = fetch_df_from_db(query, {"test_run_id": test_run_id})
    dct_replace = {"Confirmed": "✓", "Dismissed": "✘", "Inactive": "🔇", "Passed": ""}
    df["action"] = df["disposition"].replace(dct_replace)

    return df[["id", "action"]]


@st.cache_data(show_spinner=False)
def get_test_result_summary(test_run_id: str) -> list[dict]:
    query = """
    SELECT SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Passed' THEN 1
                ELSE 0
            END
        ) as passed_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Warning' THEN 1
                ELSE 0
            END
        ) as warning_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Failed' THEN 1
                ELSE 0
            END
        ) as failed_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Error' THEN 1
                ELSE 0
            END
        ) as error_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                ELSE 0
            END
        ) as dismissed_ct
    FROM test_runs
    LEFT JOIN test_results ON (
        test_runs.id = test_results.test_run_id
    )
    WHERE test_runs.id = :test_run_id;
    """
    result = fetch_one_from_db(query, {"test_run_id": test_run_id})

    return [
        { "label": "Passed", "value": result.passed_ct, "color": "green" },
        { "label": "Warning", "value": result.warning_ct, "color": "yellow" },
        { "label": "Failed", "value": result.failed_ct, "color": "red" },
        { "label": "Error", "value": result.error_ct, "color": "brown" },
        { "label": "Dismissed", "value": result.dismissed_ct, "color": "grey" },
    ]


def show_test_def_detail(test_definition_id: str, test_suite: TestSuite):
    def readable_boolean(v: bool):
        return "Yes" if v else "No"
    
    if not test_definition_id:
        st.warning("Test definition no longer exists.")
        return
    
    test_definition = TestDefinition.get(test_definition_id)

    if test_definition:
        dynamic_attributes_labels_raw = test_definition.default_parm_prompts
        if not dynamic_attributes_labels_raw:
            dynamic_attributes_labels_raw = ""
        dynamic_attributes_labels = dynamic_attributes_labels_raw.split(",")

        dynamic_attributes_raw = test_definition.default_parm_columns
        dynamic_attributes_fields = dynamic_attributes_raw.split(",")
        dynamic_attributes_values = attrgetter(*dynamic_attributes_fields)(test_definition)\
            if len(dynamic_attributes_fields) > 1\
            else (getattr(test_definition, dynamic_attributes_fields[0]),)

        for field_name in dynamic_attributes_fields[len(dynamic_attributes_labels):]:
            dynamic_attributes_labels.append(snake_case_to_title_case(field_name))

        dynamic_attributes_help_raw = test_definition.default_parm_help
        if not dynamic_attributes_help_raw:
            dynamic_attributes_help_raw = ""
        dynamic_attributes_help = dynamic_attributes_help_raw.split("|")

        testgen.testgen_component(
            "test_definition_summary",
            props={
                "test_definition": {
                    "schema": test_definition.schema_name,
                    "test_suite_name": test_suite.test_suite,
                    "table_name": test_definition.table_name,
                    "test_focus": test_definition.column_name,
                    "export_to_observability": readable_boolean(test_definition.export_to_observability)
                        if test_definition.export_to_observability is not None
                        else f"Inherited ({readable_boolean(test_suite.export_to_observability)})",
                    "severity": test_definition.severity or f"Test Default ({test_definition.default_severity})",
                    "locked": readable_boolean(test_definition.lock_refresh),
                    "active": readable_boolean(test_definition.test_active),
                    "usage_notes": test_definition.usage_notes,
                    "last_manual_update": test_definition.last_manual_update.isoformat()
                        if test_definition.last_manual_update
                        else None,
                    "custom_query": test_definition.custom_query
                        if "custom_query" in dynamic_attributes_fields
                        else None,
                    "attributes": [
                        {"label": label, "value": value, "help": help_}
                        for label, value, help_ in zip_longest(
                            dynamic_attributes_labels,
                            dynamic_attributes_values,
                            dynamic_attributes_help,
                        )
                        if label and value
                    ],
                },
            },
        )


def show_result_detail(
    run_id: str,
    run_date: str,
    test_suite_id: UUID,
    export_container: DeltaGenerator,
    test_statuses: list[str] | None = None,
    test_type_id: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    action: typing.Literal["Confirmed", "Dismissed", "Muted", "No Action"] | None = None,
    sorting_columns: list[str] | None = None,
    do_multi_select: bool = False,
):
    with st.container():
        with st.spinner("Loading data ..."):
            # Retrieve test results (always cached, action as null)
            df = test_result_queries.get_test_results(run_id, test_statuses, test_type_id, table_name, column_name, action, sorting_columns)
            # Retrieve disposition action (cache refreshed)
            df_action = get_test_disposition(run_id)
            # Update action from disposition df
            action_map = df_action.set_index("id")["action"].to_dict()
            df["action"] = df["test_result_id"].map(action_map).fillna(df["action"])

            # Update action from disposition df
            action_map = df_action.set_index("id")["action"].to_dict()
            df["action"] = df["test_result_id"].map(action_map).fillna(df["action"])

            test_suite = TestSuite.get_minimal(test_suite_id)

    lst_show_columns = [
        "table_name",
        "column_names",
        "test_name_short",
        "result_measure",
        "measure_uom",
        "result_status",
        "action",
        "result_message",
    ]

    lst_show_headers = [
        "Table",
        "Columns/Focus",
        "Test Type",
        "Result Measure",
        "Unit of Measure",
        "Status",
        "Action",
        "Details",
    ]

    selected_rows = fm.render_grid_select(
        df,
        lst_show_columns,
        do_multi_select=do_multi_select,
        show_column_headers=lst_show_headers,
        bind_to_query_name="selected",
        bind_to_query_prop="test_result_id",
    )

    popover_container = export_container.empty()

    def open_download_dialog(data: pd.DataFrame | None = None) -> None:
        # Hack to programmatically close popover: https://github.com/streamlit/streamlit/issues/8265#issuecomment-3001655849
        with popover_container.container():
            flex_row_end()
            st.button(label="Export", icon=":material/download:", disabled=True)

        download_dialog(
            dialog_title="Download Excel Report",
            file_content_func=get_excel_report_data,
            args=(test_suite.test_suite, run_date, run_id, data),
        )

    with popover_container.container(key="tg--export-popover"):
        flex_row_end()
        with st.popover(label="Export", icon=":material/download:", help="Download test results to Excel"):
            css_class("tg--export-wrapper")
            st.button(label="All tests", type="tertiary", on_click=open_download_dialog)
            st.button(label="Filtered tests", type="tertiary", on_click=partial(open_download_dialog, df))
            if selected_rows:
                st.button(label="Selected tests", type="tertiary", on_click=partial(open_download_dialog, pd.DataFrame(selected_rows)))

    # Display history and detail for selected row
    if not selected_rows:
        st.markdown(":orange[Select a record to see more information.]")
    else:
        selected_row = selected_rows[0]
        dfh = test_result_queries.get_test_result_history(selected_row)
        show_hist_columns = ["test_date", "threshold_value", "result_measure", "result_status"]

        time_columns = ["test_date"]
        date_service.accommodate_dataframe_to_timezone(dfh, st.session_state, time_columns)

        pg_col1, pg_col2 = st.columns([0.5, 0.5])

        with pg_col2:
            v_col1, v_col2, v_col3, v_col4 = st.columns([.25, .25, .25, .25])
        if user_session_service.user_can_edit():
            view_edit_test(v_col1, selected_row["test_definition_id_current"])

        if selected_row["test_scope"] == "column":
            with v_col2:
                view_profiling_button(
                    selected_row["column_names"],
                    selected_row["table_name"],
                    selected_row["table_groups_id"],
                )

        with v_col3:
            if st.button(
                    ":material/visibility: Source Data", help="View current source data for highlighted result",
                    use_container_width=True
            ):
                MixpanelService().send_event(
                    "view-source-data",
                    page=PAGE_PATH,
                    test_type=selected_row["test_name_short"],
                )
                source_data_dialog(selected_row)

        with v_col4:

            report_eligible_rows = [
                row for row in selected_rows
                if row["result_status"] != "Passed" and row["disposition"] in (None, "Confirmed")
            ]

            if do_multi_select:
                report_btn_help = (
                    "Generate PDF reports for the selected results that are not muted or dismissed and are not Passed"
                )
            else:
                report_btn_help = "Generate PDF report for selected result"

            if st.button(
                ":material/download: Issue Report",
                use_container_width=True,
                disabled=not report_eligible_rows,
                help=report_btn_help,
            ):
                MixpanelService().send_event(
                    "download-issue-report",
                    page=PAGE_PATH,
                    issue_count=len(report_eligible_rows),
                )
                dialog_title = "Download Issue Report"
                if len(report_eligible_rows) == 1:
                    download_dialog(
                        dialog_title=dialog_title,
                        file_content_func=get_report_file_data,
                        args=(report_eligible_rows[0],),
                    )
                else:
                    zip_func = zip_multi_file_data(
                        "testgen_test_issue_reports.zip",
                        get_report_file_data,
                        [(arg,) for arg in selected_rows],
                    )
                    download_dialog(dialog_title=dialog_title, file_content_func=zip_func)

        with pg_col1:
            fm.show_subheader(selected_row["test_name_short"])
            st.markdown(f"###### {selected_row['test_description']}")
            st.caption(empty_if_null(selected_row["measure_uom_description"]))
            fm.render_grid_select(dfh, show_hist_columns, selection_mode="disabled")
        with pg_col2:
            ut_tab1, ut_tab2 = st.tabs(["History", "Test Definition"])
            with ut_tab1:
                if dfh.empty:
                    st.write("Test history not available.")
                else:
                    write_history_graph(dfh)
            with ut_tab2:
                show_test_def_detail(selected_row["test_definition_id_current"], test_suite)
        return selected_rows


@with_database_session
def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    test_suite: str,
    run_date: str,
    run_id: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is None:
        data = test_result_queries.get_test_results(run_id)

    columns = {
        "schema_name": {"header": "Schema"},
        "table_name": {"header": "Table"},
        "column_names": {"header": "Columns/Focus"},
        "test_name_short": {"header": "Test type"},
        "test_description": {"header": "Description", "wrap": True},
        "dq_dimension": {"header": "Quality dimension"},
        "measure_uom": {"header": "Unit of measure (UOM)"},
        "measure_uom_description": {"header": "UOM description"},
        "threshold_value": {},
        "severity": {},
        "result_measure": {},
        "result_status": {"header": "Status"},
        "result_message": {"header": "Message"},
        "action": {},
    }
    return get_excel_file_data(
        data,
        "Test Results",
        details={"Test suite": test_suite, "Test run date": run_date},
        columns=columns,
        update_progress=update_progress,
    )


def write_history_graph(dfh):
    y_min = min(dfh["result_measure"].min(), dfh["threshold_value"].min())
    y_max = max(dfh["result_measure"].max(), dfh["threshold_value"].max())
    str_uom = dfh.at[0, "measure_uom"]

    fig = px.line(
        dfh,
        x="test_date",
        y="result_measure",
        title=None,
        labels={"test_date": "Test Date", "result_measure": str_uom},
        line_shape="linear",
    )

    # Add dots at every observation
    fig.add_scatter(x=dfh["test_date"], y=dfh["result_measure"], mode="markers", name="Observations")

    if all(dfh["test_operator"].isin(["<", "<="])):
        # Add shaded region below: exception if under threshold
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=dfh["threshold_value"],
                fill="tozeroy",
                fillcolor="rgba(255,182,193,0.5)",
                line_color="rgba(255,182,193,0.5)",
                mode="none",
                name="Threshold",
            )
        )
    elif all(dfh["test_operator"].isin([">", ">="])):
        # Add shaded region above: exception if over threshold
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=[max(dfh["threshold_value"]) * 1.1] * len(dfh["test_date"]),  # some value above the maximum threshold
                mode="lines",
                line={"width": 0},  # making this line invisible
                showlegend=False,
            )
        )

        # Now, fill between this auxiliary line and the threshold line
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=dfh["threshold_value"],
                fill="tonexty",
                fillcolor="rgba(255,182,193,0.5)",
                line_color="rgba(255,182,193,0.5)",
                mode="none",
                name="Threshold",
            )
        )
    elif all(dfh["test_operator"].isin(["=", "<>"])):
        # Show line instead of shaded region: pink/exception if equal, green/exception if not equal
        str_line_color = "rgba(255,182,193,0.5)" if all(dfh["test_operator"]) == "=" else "rgba(144, 238, 144, 1)"
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=dfh["threshold_value"],
                line_color=str_line_color,
                mode="lines",  # only lines, no markers
                line={"width": 5},
                name="Threshold",
            )
        )
    # Update the Y-Axis to start from the minimum value

    if y_min > 0 and y_max - y_min < 0.1 * y_max:
        fig.update_layout(yaxis={"range": [y_min, y_max]})

    fig.update_layout(legend={"x": 0.5, "y": 1.1, "xanchor": "center", "yanchor": "top", "orientation": "h"})
    fig.update_layout(width=500, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")

    st.plotly_chart(fig)


def do_disposition_update(selected, str_new_status):
    str_result = None
    if selected:
        if len(selected) > 1:
            str_which = f"of {len(selected)} results to {str_new_status}"
        elif len(selected) == 1:
            str_which = f"of one result to {str_new_status}"

        if not update_result_disposition(selected, str_new_status):
            str_result = f":red[**The update {str_which} did not succeed.**]"

    return str_result


@st.dialog(title="Source Data")
@with_database_session
def source_data_dialog(selected_row):
    st.markdown(f"#### {selected_row['test_name_short']}")
    st.caption(selected_row["test_description"])
    fm.show_prompt(f"Column: {selected_row['column_names']}, Table: {selected_row['table_name']}")

    # Show detail
    fm.render_html_list(
        selected_row, ["input_parameters", "result_message"], None, 700, ["Test Parameters", "Result Detail"]
    )

    with st.spinner("Retrieving source data..."):
        if selected_row["test_type"] == "CUSTOM":
            bad_data_status, bad_data_msg, _, df_bad = get_test_issue_source_data_custom(selected_row, limit=500)
        else:
            bad_data_status, bad_data_msg, _, df_bad = get_test_issue_source_data(selected_row, limit=500)
    if bad_data_status in {"ND", "NA"}:
        st.info(bad_data_msg)
    elif bad_data_status == "ERR":
        st.error(bad_data_msg)
    elif df_bad is None:
        st.error("An unknown error was encountered.")
    else:
        if bad_data_msg:
            st.info(bad_data_msg)
        # Pretify the dataframe
        df_bad.columns = [col.replace("_", " ").title() for col in df_bad.columns]
        df_bad.fillna("<null>", inplace=True)
        if len(df_bad) == 500:
            testgen.caption("* Top 500 records displayed", "text-align: right;")
        # Display the dataframe
        st.dataframe(df_bad, height=500, width=1050, hide_index=True)


def view_edit_test(button_container, test_definition_id):
    if test_definition_id:
        with button_container:
            if st.button(":material/edit: Edit Test", help="Edit the Test Definition", use_container_width=True):
                show_test_form_by_id(test_definition_id)


def get_report_file_data(update_progress, tr_data) -> FILE_DATA_TYPE:
    tr_id = tr_data["test_result_id"][:8]
    tr_time = pd.Timestamp(tr_data["test_date"]).strftime("%Y%m%d_%H%M%S")
    file_name = f"testgen_test_issue_report_{tr_id}_{tr_time}.pdf"

    with BytesIO() as buffer:
        create_report(buffer, tr_data)
        update_progress(1.0)
        buffer.seek(0)
        return file_name, "application/pdf", buffer.read()


def update_result_disposition(
    selected: list[dict],
    disposition: typing.Literal["Confirmed", "Dismissed", "Inactive", "No Decision"],
):
    test_result_ids = [row["test_result_id"] for row in selected]

    execute_db_query(
        """
        WITH selects
            AS (SELECT UNNEST(ARRAY [:test_result_ids]) AS selected_id)
        UPDATE test_results
        SET disposition = NULLIF(:disposition, 'No Decision')
        FROM test_results r
        INNER JOIN selects s
            ON (r.id = s.selected_id::UUID)
        WHERE r.id = test_results.id
            AND r.result_status != 'Passed';
        """,
        {
            "test_result_ids": test_result_ids,
            "disposition": disposition,
        },
    )

    execute_db_query(
        """
        WITH selects
            AS (SELECT UNNEST(ARRAY [:test_result_ids]) AS selected_id)
        UPDATE test_definitions
        SET test_active = :test_active,
            last_manual_update = CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
            lock_refresh = :lock_refresh
        FROM test_definitions d
        INNER JOIN test_results r
            ON (d.id = r.test_definition_id)
        INNER JOIN selects s
            ON (r.id = s.selected_id::UUID)
        WHERE d.id = test_definitions.id
            AND r.result_status != 'Passed';
        """,
        {
            "test_result_ids": test_result_ids,
            "test_active": "N" if disposition == "Inactive" else "Y",
            "lock_refresh": "Y" if disposition == "Inactive" else "N",
        },
    )

    return True
