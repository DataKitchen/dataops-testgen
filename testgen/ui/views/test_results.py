import json
import typing
from datetime import datetime, timedelta
from functools import partial
from io import BytesIO
from itertools import zip_longest
from operator import attrgetter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import testgen.ui.services.form_service as fm
from testgen.commands.run_rollup_scores import run_test_rollup_scoring_queries
from testgen.common import date_service
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.common.pii_masking import get_pii_columns, mask_dataframe_pii
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
from testgen.ui.queries.source_data_queries import (
    get_test_issue_source_data,
    get_test_issue_source_data_custom,
    get_test_issue_source_query,
    get_test_issue_source_query_custom,
)
from testgen.ui.services.database_service import execute_db_query, fetch_df_from_db, fetch_one_from_db
from testgen.ui.services.string_service import snake_case_to_title_case
from testgen.ui.session import session
from testgen.ui.views.dialogs.profiling_results_dialog import profiling_results_dialog
from testgen.ui.views.dialogs.test_definition_notes_dialog import test_definition_notes_dialog
from testgen.ui.views.test_definitions import show_test_form_by_id
from testgen.utils import friendly_score, str_to_timestamp

PAGE_PATH = "test-runs:results"


class TestResultsPage(Page):
    path = PAGE_PATH
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "run_id" in st.query_params or "test-runs",
    ]

    def render(
        self,
        run_id: str,
        status: str | None = None,
        table_name: str | None = None,
        column_name: str | None = None,
        test_type: str | None = None,
        action: str | None = None,
        flagged: str | None = None,
        **_kwargs,
    ) -> None:
        run = TestRun.get_minimal(run_id)
        if not run:
            self.router.navigate_with_warning(
                f"Test run with ID '{run_id}' does not exist. Redirecting to list of Test Runs ...",
                "test-runs",
            )
            return

        if not session.auth.user_has_project_access(run.project_code):
            self.router.navigate_with_warning(
                "You don't have access to view this resource. Redirecting ...",
                "test-runs",
            )
            return

        run_date = date_service.get_timezoned_timestamp(st.session_state, run.test_starttime)
        session.set_sidebar_project(run.project_code)

        testgen.page_header(
            "Test Results",
            "data-quality-testing/investigate-test-results/",
            breadcrumbs=[
                { "label": "Test Runs", "path": "test-runs", "params": { "project_code": run.project_code } },
                { "label": f"{run.test_suite} | {run_date}" },
            ],
        )

        summary_column, score_column, export_button_column = st.columns([.35, .15, .5], vertical_alignment="bottom")
        status_filter_column, table_filter_column, column_filter_column, test_type_filter_column, flagged_filter_column, action_filter_column, sort_column = st.columns(
            [.15, .175, .175, .15, .1, .15, .1], vertical_alignment="bottom"
        )

        testgen.flex_row_end(export_button_column)

        filters_changed = False
        current_filters = (status, table_name, column_name, test_type, flagged, action)
        if (query_filters := st.session_state.get("test_results:filters")) != current_filters:
            if query_filters:
                filters_changed = True
            st.session_state["test_results:filters"] = current_filters

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
                "Log",
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
                column_options = run_columns_df.groupby("column_name").first().reset_index().sort_values("column_name", key=lambda x: x.str.lower())
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

        with flagged_filter_column:
            flagged = testgen.select(
                options=["Flagged", "Not Flagged"],
                default_value=flagged,
                bind_to_query="flagged",
                label="Flagged",
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
                ("Flagged", "CASE WHEN td.flagged THEN 0 ELSE 1 END"),
                ("Has Notes", "CASE WHEN (SELECT COUNT(*) FROM test_definition_notes tdn WHERE tdn.test_definition_id = td.id) > 0 THEN 0 ELSE 1 END"),
                ("Table", "LOWER(r.table_name)"),
                ("Columns/Focus", "LOWER(r.column_names)"),
                ("Test Type", "r.test_type"),
                ("Unit of Measure", "tt.measure_uom"),
                ("Result Measure", "result_measure"),
                ("Status", "result_status"),
                ("Action", "r.disposition"),
            )
            default = [(sortable_columns[i][1], "ASC") for i in (2, 3, 4)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default)

        actions_column, disposition_column = st.columns([.5, .5])
        testgen.flex_row_start(actions_column)
        testgen.flex_row_end(disposition_column)

        user_can_edit = session.auth.user_has_permission("edit")

        with disposition_column:
            multi_select = st.toggle(
                "Multi-Select",
                help="Toggle on to perform actions on multiple results",
            )

        match status:
            case None:
                status = []
            case "Failed + Warning":
                status = ["Failed", "Warning"]
            case _:
                status = [status]

        with st.container():
            with st.spinner("Loading data ..."):
                # Retrieve test results (always cached, action as null)
                flagged_bool = True if flagged == "Flagged" else False if flagged == "Not Flagged" else None
                df = test_result_queries.get_test_results(
                    run_id, status, test_type, table_name, column_name, action, sorting_columns, flagged_bool
                )
                # Retrieve disposition action (cache refreshed)
                df_action = get_test_disposition(run_id)
                # Update action from disposition df
                action_map = df_action.set_index("id")["action"].to_dict()
                df["action"] = df["test_result_id"].map(action_map).fillna(df["action"])

                # Update action from disposition df
                action_map = df_action.set_index("id")["action"].to_dict()
                df["action"] = df["test_result_id"].map(action_map).fillna(df["action"])

                def build_review_column(row):
                    parts = []
                    if row["action"]:
                        parts.append(row["action"])
                    if row["flagged"]:
                        parts.append("🚩")
                    if row.get("notes_count", 0) > 0:
                        parts.append(f"📝 {row['notes_count']}")
                    return "  ·  ".join(parts)

                df["review"] = df.apply(build_review_column, axis=1) if not df.empty else ""

                test_suite = TestSuite.get_minimal(run.test_suite_id)
                table_group = TableGroup.get_minimal(test_suite.table_groups_id)

        selected, selected_row = fm.render_grid_select(
            df,
            [
                "table_name",
                "column_names",
                "test_name_short",
                "result_measure",
                "measure_uom",
                "result_status",
                "review",
                "result_message",
            ],
            [
                "Table",
                "Columns/Focus",
                "Test Type",
                "Result Measure",
                "Unit of Measure",
                "Status",
                "Review",
                "Details",
            ],
            id_column="test_result_id",
            selection_mode="multiple" if multi_select else "single",
            reset_pagination=filters_changed,
            bind_to_query=True,
            column_styles={"review": {"textAlign": "center", "fontSize": "1.1em"}},
        )

        popover_container = export_button_column.empty()

        def open_download_dialog(data: pd.DataFrame | None = None) -> None:
            # Hack to programmatically close popover: https://github.com/streamlit/streamlit/issues/8265#issuecomment-3001655849
            with popover_container.container():
                flex_row_end()
                st.button(label="Export", icon=":material/download:", disabled=True)

            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(test_suite.test_suite, table_group.table_group_schema, run_date, run_id, data),
            )

        with popover_container.container(key="tg--export-popover"):
            flex_row_end()
            with st.popover(label="Export", icon=":material/download:", help="Download test results to Excel"):
                css_class("tg--export-wrapper")
                st.button(label="All tests", type="tertiary", on_click=open_download_dialog)
                st.button(label="Filtered tests", type="tertiary", on_click=partial(open_download_dialog, df))
                if selected:
                    st.button(
                        label="Selected tests",
                        type="tertiary",
                        on_click=partial(open_download_dialog, pd.DataFrame(selected)),
                    )

        # Need to render toolbar buttons after grid, so selection status is maintained
        # === Action buttons (left side, near the grid) ===

        if actions_column.button(
            ":material/sticky_note_2: Notes",
            disabled=not selected or len(selected) != 1,
            help="View and add notes for this test definition",
        ):
            row = selected[0]
            test_definition_notes_dialog(
                str(row["test_definition_id"]),
                {"table": row["table_name"], "column": row["column_names"], "test": row["test_name_short"]},
            )

        if actions_column.button(
            ":material/edit: Edit Test",
            disabled=not selected_row or not user_can_edit,
            help="Edit the Test Definition",
        ):
            show_test_form_by_id(selected_row["test_definition_id"])

        if actions_column.button(
            ":material/visibility: Source Data",
            disabled=not selected_row,
            help="View current source data for highlighted result",
        ):
            MixpanelService().send_event(
                "view-source-data",
                page=PAGE_PATH,
                test_type=selected_row["test_name_short"],
            )
            source_data_dialog(selected_row)

        can_view_profiling = (
            selected_row
            and selected_row.get("test_scope") == "column"
            and selected_row.get("column_names") not in (None, "(multi-column)", "N/A")
            and selected_row.get("table_name") not in (None, "(multi-table)")
        )
        if actions_column.button(
            ":material/insert_chart: Profiling",
            disabled=not can_view_profiling,
            help="View profiling for highlighted column",
        ):
            profiling_results_dialog(
                selected_row["column_names"],
                selected_row["table_name"],
                selected_row["table_groups_id"],
            )

        report_eligible_rows = [
            row for row in selected
            if row["result_status"] != "Passed" and row["disposition"] in (None, "Confirmed")
        ] if selected else []
        report_btn_help = (
            "Generate PDF reports for the selected results that are not muted or dismissed and are not Passed"
            if multi_select
            else "Generate PDF report for selected result"
        )
        if actions_column.button(
            ":material/download: Issue Report",
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
                    [(arg,) for arg in selected],
                )
                download_dialog(dialog_title=dialog_title, file_content_func=zip_func)

        # === Disposition buttons (right side) ===

        disposition_actions = [
            { "icon": "✓", "help": "Confirm this issue as relevant for this run", "status": "Confirmed" },
            { "icon": "✘", "help": "Dismiss this issue as not relevant for this run", "status": "Dismissed" },
            { "icon": "🔇", "help": "Mute this test to deactivate it for future runs", "status": "Inactive" },
            { "icon": "↩︎", "help": "Clear action", "status": "No Decision" },
        ]

        if session.auth.user_has_permission("disposition"):
            disable_all_dispo = not selected or status == "'Passed'" or all(sel["result_status"] == "Passed" for sel in selected)
            disposition_translator =  {"No Decision": None}
            for action in disposition_actions:
                disable_dispo = disable_all_dispo or all(
                    sel["disposition"] == disposition_translator.get(action["status"], action["status"])
                    or sel["result_status"] == "Passed"
                    for sel in selected
                )
                action["button"] = disposition_column.button(action["icon"], help=action["help"], disabled=disable_dispo)

            # This has to be done as a second loop - otherwise, the rest of the buttons after the clicked one are not displayed briefly while refreshing
            for action in disposition_actions:
                if action["button"]:
                    fm.reset_post_updates(
                        do_disposition_update(selected, action["status"]),
                        as_toast=True,
                    )

        if session.auth.user_has_permission("disposition"):
            flag_actions = [
                { "icon": "🚩", "help": "Flag test for attention", "value": True, "message": "Flagged" },
                { "icon": "⌀", "help": "Clear flag", "value": False, "message": "Flag cleared" },
            ]
            for flag_action in flag_actions:
                flag_disabled = not selected or all(sel["flagged"] == flag_action["value"] for sel in selected)
                flag_action["button"] = disposition_column.button(flag_action["icon"], help=flag_action["help"], disabled=flag_disabled)

            for flag_action in flag_actions:
                if flag_action["button"]:
                    test_definition_ids = list({row["test_definition_id"] for row in selected})
                    TestDefinition.set_status_attribute("flagged", test_definition_ids, flag_action["value"])
                    fm.reset_post_updates(
                        None,
                        as_toast=True,
                    )

        # Needs to be after all data loading/updating
        # Otherwise the database session is lost for any queries after the fragment -_-
        with score_column:
            render_score(run.project_code, run_id)

        if selected_row:
            render_selected_details(selected_row, test_suite)


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
    ORDER BY LOWER(r.table_name), LOWER(r.column_names);
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
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Log' THEN 1
                ELSE 0
            END
        ) as log_ct,
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
        { "label": "Log", "value": result.log_ct, "color": "blue" },
        { "label": "Dismissed", "value": result.dismissed_ct, "color": "grey" },
    ]


def show_test_def_detail(test_definition_id: str, test_suite: TestSuiteMinimal):
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

        dynamic_attributes_raw = test_definition.default_parm_columns or ""
        if not dynamic_attributes_raw:
            dynamic_attributes_fields = []
            dynamic_attributes_values = []
        else:
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


@with_database_session
def render_selected_details(
    selected_item: dict,
    test_suite: TestSuiteMinimal,
) -> None:
    dfh = test_result_queries.get_test_result_history(selected_item)
    show_hist_columns = ["test_date", "threshold_value", "result_measure", "result_status"]

    time_columns = ["test_date"]
    date_service.accommodate_dataframe_to_timezone(dfh, st.session_state, time_columns)

    pg_col1, pg_col2 = st.columns([0.5, 0.5])

    with pg_col1:
        fm.show_subheader(selected_item["test_name_short"])
        st.markdown(f"###### {selected_item['test_description']}")
        if selected_item["measure_uom_description"]:
            st.caption(selected_item["measure_uom_description"])
        if selected_item["result_message"]:
            st.caption(selected_item["result_message"].replace("*", "\\*"))
        fm.render_grid_select(dfh, show_hist_columns, selection_mode="disabled", key="test_history")
    with pg_col2:
        ut_tab1, ut_tab2 = st.tabs(["History", "Test Definition"])
        with ut_tab1:
            if dfh.empty:
                st.write("Test history not available.")
            else:
                write_history_chart_v2(dfh)
        with ut_tab2:
            show_test_def_detail(selected_item["test_definition_id"], test_suite)


@with_database_session
def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    test_suite: str,
    schema: str,
    run_date: str,
    run_id: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is None:
        data = test_result_queries.get_test_results(run_id)

    columns = {
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
        "flagged_display": {"header": "Flagged"},
    }
    return get_excel_file_data(
        data,
        "Test Results",
        details={"Test suite": test_suite, "Schema": schema, "Test run date": run_date},
        columns=columns,
        update_progress=update_progress,
    )


def write_history_graph(data: pd.DataFrame):
    chart_type = data.at[0, "result_visualization"]
    chart_params = json.loads(data.at[0, "result_visualization_params"] or "{}")

    match chart_type:
        case "binary_chart":
            render_binary_chart(data, **chart_params)
        case _: render_line_chart(data, **chart_params)


def write_history_chart_v2(data: pd.DataFrame):
    data["test_date"] = data["test_date"].apply(str_to_timestamp)
    return testgen.testgen_component(
        "test_results_chart",
        props={
            # Fix NaN values
            "data": json.loads(data.to_json(orient="records")),
        },
    )


def render_line_chart(dfh: pd.DataFrame, **_params: dict) -> None:
    str_uom = dfh.at[0, "measure_uom"]

    y_min = min(dfh["result_measure"].min(), dfh["threshold_value"].min())
    y_max = max(dfh["result_measure"].max(), dfh["threshold_value"].max())

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


def render_binary_chart(data: pd.DataFrame, **params: dict) -> None:
    history = data.copy(deep=True)
    legend_labels = params.get("legend", {}).get("labels") or {"0": "0", "1": "1"}

    history["test_start"] = history["test_date"].apply(datetime.fromisoformat)
    history["test_end"] = history["test_start"].apply(lambda start: start + timedelta(seconds=60))
    history["formatted_test_date"] = history["test_date"].apply(lambda date_str: datetime.fromisoformat(date_str).strftime("%I:%M:%S %p, %d/%m/%Y"))
    history["result_measure_with_status"] = history.apply(lambda row: f"{legend_labels[str(int(row['result_measure'])) if not pd.isnull(row['result_measure']) else "0"]} ({row['result_status']})", axis=1)

    fig = px.timeline(
        history,
        x_start="test_start",
        x_end="test_end",
        y="measure_uom",
        color="result_measure_with_status",
        color_discrete_map={
            f"{legend_labels['0']} (Failed)": "#EF5350",
            f"{legend_labels['0']} (Warning)": "#FF9800",
            f"{legend_labels['0']} (Log)": "#BDBDBD",
            f"{legend_labels['1']} (Passed)": "#9CCC65",
            f"{legend_labels['1']} (Log)": "#42A5F5",
        },
        hover_name="formatted_test_date",
        hover_data={
            "test_start": False,
            "test_end": False,
            "result_measure": False,
            "result_measure_with_status": False,
            "measure_uom": False,
        },
        labels={
            "result_measure_with_status": "",
        },
    )
    fig.update_layout(
        yaxis_visible=False,
        xaxis_showline=True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend={"x": 0.5, "y": 1.1, "xanchor": "center", "yanchor": "top", "orientation": "h"},
        width=500,
    )

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
    testgen.caption(f"Table > Column: <b>{selected_row['table_name']} > {selected_row['column_names']}</b>")

    st.markdown(f"#### {selected_row['test_name_short']}")
    st.caption(selected_row["test_description"])

    st.markdown("#### Test Parameters")
    testgen.caption(selected_row["input_parameters"], styles="max-height: 75px; overflow: auto;")

    if selected_row["result_message"]:
        st.markdown("#### Result Detail")
        st.caption(selected_row["result_message"].replace("*", "\\*"))

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
        if not session.auth.user_has_permission("view_pii"):
            pii_columns = get_pii_columns(
                selected_row["table_groups_id"],
                table_name=selected_row["table_name"],
            )
            mask_dataframe_pii(df_bad, pii_columns)
        # Pretify the dataframe
        df_bad.columns = [col.replace("_", " ").title() for col in df_bad.columns]
        df_bad.fillna("<null>", inplace=True)
        if len(df_bad) == 500:
            testgen.caption("* Top 500 records displayed", "text-align: right;")
        # Display the dataframe
        st.dataframe(df_bad, width=1050, hide_index=True)

    st.markdown("#### SQL Query")
    if selected_row["test_type"] == "CUSTOM":
        query = get_test_issue_source_query_custom(selected_row)
    else:
        query = get_test_issue_source_query(selected_row)
    if query:
        st.code(query, language="sql", wrap_lines=True, height=100)


def get_report_file_data(update_progress, tr_data) -> FILE_DATA_TYPE:
    tr_id = tr_data["test_result_id"][:8]
    tr_time = pd.Timestamp(tr_data["test_date"]).strftime("%Y%m%d_%H%M%S")
    file_name = f"testgen_test_issue_report_{tr_id}_{tr_time}.pdf"

    with BytesIO() as buffer:
        create_report(buffer, tr_data, mask_pii=not session.auth.user_has_permission("view_pii"))
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
