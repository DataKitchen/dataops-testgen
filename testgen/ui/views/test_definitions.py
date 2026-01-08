import logging
import time
import typing
from datetime import datetime
from functools import partial

import pandas as pd
import streamlit as st
from sqlalchemy import and_, asc, desc, func, or_, tuple_
from streamlit.delta_generator import DeltaGenerator
from streamlit_extras.no_default_selectbox import selectbox

import testgen.ui.services.form_service as fm
from testgen.common import date_service
from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_definition import TestDefinition, TestDefinitionMinimal, TestDefinitionSummary
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
)
from testgen.ui.components.widgets.page import css_class, flex_row_end
from testgen.ui.navigation.page import Page
from testgen.ui.services.database_service import fetch_all_from_db, fetch_df_from_db, fetch_from_target_db
from testgen.ui.services.string_service import empty_if_null, snake_case_to_title_case
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.profiling_results_dialog import view_profiling_button
from testgen.ui.views.dialogs.run_tests_dialog import run_tests_dialog
from testgen.utils import to_dataframe

LOG = logging.getLogger("testgen")


class TestDefinitionsPage(Page):
    path = "test-suites:definitions"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "test_suite_id" in st.query_params or "test-suites",
    ]

    def render(
        self,
        test_suite_id: str,
        table_name: str | None = None,
        column_name: str | None = None,
        test_type: str | None = None,
        **_kwargs,
    ) -> None:
        test_suite = TestSuite.get(test_suite_id)
        if not test_suite:
            self.router.navigate_with_warning(
                f"Test suite with ID '{test_suite_id}' does not exist. Redirecting to list of Test Suites ...",
                "test-suites",
            )

        table_group = TableGroup.get_minimal(test_suite.table_groups_id)
        project_code = table_group.project_code
        session.set_sidebar_project(project_code)
        user_can_edit = session.auth.user_has_permission("edit")
        user_can_disposition = session.auth.user_has_permission("disposition")

        testgen.page_header(
            "Test Definitions",
            "testgen-test-types",
            breadcrumbs=[
                { "label": "Test Suites", "path": "test-suites", "params": { "project_code": project_code } },
                { "label": test_suite.test_suite },
            ],
        )

        table_filter_column, column_filter_column, test_filter_column, sort_column, table_actions_column = st.columns([.2, .2, .2, .1, .25], vertical_alignment="bottom")
        testgen.flex_row_end(table_actions_column)

        actions_column, disposition_column = st.columns([.5, .5])
        testgen.flex_row_start(actions_column)
        testgen.flex_row_end(disposition_column)

        filters_changed = False
        current_filters = (table_name, column_name, test_type)
        if (query_filters := st.session_state.get("test_definitions:filters")) != current_filters:
            if query_filters:
                filters_changed = True
            st.session_state["test_definitions:filters"] = current_filters

        with table_filter_column:
            columns_df = get_test_suite_columns(test_suite_id)
            table_options = list(columns_df["table_name"].unique())
            table_name = testgen.select(
                options=table_options,
                value_column="table_name",
                default_value=table_name,
                bind_to_query="table_name",
                label="Table",
            )
        with column_filter_column:
            if table_name:
                column_options = columns_df.loc[
                    columns_df["table_name"] == table_name
                    ]["column_name"].dropna().unique().tolist()
            else:
                column_options = columns_df.groupby("column_name").first().reset_index().sort_values("column_name", key=lambda x: x.str.lower())
            column_name = testgen.select(
                options=column_options,
                default_value=column_name,
                bind_to_query="column_name",
                label="Column",
                accept_new_options=True,
            )
        with test_filter_column:
            test_options = columns_df.groupby("test_type").first().reset_index().sort_values("test_name_short")
            test_type = testgen.select(
                options=test_options,
                value_column="test_type",
                display_column="test_name_short",
                default_value=test_type,
                bind_to_query="test_type",
                label="Test Type",
            )

        with sort_column:
            sortable_columns = (
                ("Table", "table_name"),
                ("Column", "column_name"),
                ("Test Type", "test_type"),
            )
            default = [(sortable_columns[i][1], "ASC") for i in (0, 1, 2)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default)

        if user_can_disposition:
            with disposition_column:
                multi_select = st.toggle("Multi-Select", help="Toggle on to perform actions on multiple test definitions")

        if user_can_edit:
            if actions_column.button(
                ":material/add: Add",
                help="Add a new Test Definition",
            ):
                add_test_dialog(table_group, test_suite, table_name, column_name)

            if table_actions_column.button(
                ":material/play_arrow: Run Tests",
                help="Run test suite's tests",
            ):
                run_tests_dialog(project_code, test_suite)

        with st.container():
            with st.spinner("Loading data ..."):
                df = get_test_definitions(test_suite, table_name, column_name, test_type, sorting_columns)

        selected, selected_test_def = render_grid(df, multi_select, filters_changed)

        popover_container = table_actions_column.empty()

        def open_download_dialog(data: pd.DataFrame | None = None) -> None:
            # Hack to programmatically close popover: https://github.com/streamlit/streamlit/issues/8265#issuecomment-3001655849
            with popover_container.container():
                flex_row_end()
                st.button(label="Export", icon=":material/download:", disabled=True)

            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(test_suite, table_group.table_group_schema, data),
            )

        with popover_container.container(key="tg--export-popover"):
            flex_row_end()
            with st.popover(label="Export", icon=":material/download:", help="Download test definitions to Excel"):
                css_class("tg--export-wrapper")
                st.button(label="All tests", type="tertiary", on_click=open_download_dialog)
                st.button(label="Filtered tests", type="tertiary", on_click=partial(open_download_dialog, df))
                if selected:
                    st.button(label="Selected tests", type="tertiary", on_click=partial(open_download_dialog, pd.DataFrame(selected)))

        fm.render_refresh_button(table_actions_column)

        if user_can_disposition:
            disposition_actions = [
                { "icon": "✓", "help": "Activate for future runs", "attribute": "test_active", "value": True, "message": "Activated" },
                { "icon": "🔇", "help": "Deactivate Test for future runs", "attribute": "test_active", "value": False, "message": "Deactivated" },
            ]

            if user_can_edit:
                disposition_actions.extend([
                    { "icon": "🔒", "help": "Protect from future test generation", "attribute": "lock_refresh", "value": True, "message": "Locked" },
                    { "icon": "🔐", "help": "Unlock for future test generation", "attribute": "lock_refresh", "value": False, "message": "Unlocked" },
                ])

            for action in disposition_actions:
                action_disabled = not selected or all(sel[action["attribute"]] == action["value"] for sel in selected)
                action["button"] = disposition_column.button(action["icon"], help=action["help"], disabled=action_disabled)

            # This has to be done as a second loop - otherwise, the rest of the buttons after the clicked one are not displayed briefly while refreshing
            for action in disposition_actions:
                if action["button"]:
                    is_unlocking = action["attribute"] == "lock_refresh" and not action["value"]
                    if is_unlocking:
                        confirm_unlocking_test_definition(selected)
                    else:
                        fm.reset_post_updates(
                            update_test_definition(selected, action["attribute"], action["value"], action["message"]),
                            as_toast=True,
                            clear_cache=True,
                            lst_cached_functions=[],
                        )

        if user_can_edit:
            if actions_column.button(
                ":material/edit: Edit",
                disabled=not selected,
            ):
                edit_test_dialog(table_group, test_suite, table_name, column_name, selected_test_def)

            if actions_column.button(
                ":material/file_copy: Copy/Move",
                disabled=not selected,
            ):
                copy_move_test_dialog(project_code, table_group, test_suite, selected)

            if actions_column.button(
                ":material/delete: Delete",
                disabled=not selected,
            ):
                delete_test_dialog(selected)

        if selected_test_def:
            render_selected_details(selected_test_def, table_group)


def render_grid(df: pd.DataFrame, multi_select: bool, filters_changed: bool) -> list[dict]:
    columns = [
        "table_name",
        "column_name",
        "test_name_short",
        "test_active_display",
        "lock_refresh_display",
        "urgency",
        "export_to_observability_display",
        "profiling_as_of_date",
        "last_manual_update",
    ]
    # Multiselect checkboxes do not display correctly if the dataframe column order does not start with the first displayed column -_-
    df = df.reindex(columns=[columns[0]] + [ col for col in df.columns.to_list() if col != columns[0] ])

    selected, selected_row = fm.render_grid_select(
        df,
        columns,
        [
            "Table",
            "Columns / Focus",
            "Test Type",
            "Active",
            "Locked",
            "Urgency",
            "Export to Observabilty",
            "Based on Profiling",
            "Last Manual Update",
        ],
        id_column="id",
        selection_mode="multiple" if multi_select else "single",
        reset_pagination=filters_changed,
        bind_to_query=True,
        render_highlights=False,
    )

    return selected, selected_row


def render_selected_details(selected_test: dict, table_group: TableGroupMinimal) -> None:
    columns = [
        "schema_name",
        "table_name",
        "column_name",
        "test_type",
        "test_active_display",
        "test_definition_status",
        "lock_refresh_display",
        "urgency",
        "export_to_observability",
    ]

    labels = [
        "schema_name",
        "table_name",
        "column_name",
        "test_type",
        "test_active",
        "test_definition_status",
        "lock_refresh",
        "urgency",
        "export_to_observability",
    ]

    additional_columns = [val.strip() for val in selected_test["default_parm_columns"].split(",")] if selected_test["default_parm_columns"] else []
    columns = columns + additional_columns
    labels = labels + additional_columns
    labels = list(map(snake_case_to_title_case, labels))

    left_column, right_column = st.columns([0.5, 0.5])

    with left_column:
        fm.render_html_list(
            selected_test,
            columns,
            "Test Definition Information",
            int_data_width=700,
            lst_labels=labels,
        )

    _, col_profile_button = right_column.columns([0.7, 0.3])
    if selected_test["test_scope"] == "column" and selected_test["profile_run_id"]:
        with col_profile_button:
            view_profiling_button(
                selected_test["column_name"],
                selected_test["table_name"],
                str(table_group.id),
            )

    with right_column:
        st.write(generate_test_defs_help(selected_test["test_type"]))


@st.dialog("Delete Tests")
@with_database_session
def delete_test_dialog(test_definitions: list[dict]):
    delete_clicked, set_delete_clicked = temp_value("test-definitions:confirm-delete-tests-val")
    st.html(f"""
        Are you sure you want to delete
        {f"<b>{len(test_definitions)}</b> selected test definitions?"
        if len(test_definitions) > 1
        else "the selected test definition?"}
    """)

    _, button_column = st.columns([.85, .15])
    with button_column:
        testgen.button(
            label="Delete",
            type_="flat",
            color="warn",
            key="test-definitions:confirm-delete-tests-btn",
            on_click=lambda: set_delete_clicked(True),
        )

    if delete_clicked():
        TestDefinition.delete_where(TestDefinition.id.in_([ item["id"] for item in test_definitions ]))
        st.success("Test definitions have been deleted.")
        time.sleep(1)
        st.rerun()


def show_test_form_by_id(test_definition_id):
    test_definition = TestDefinition.get(test_definition_id)
    table_group = TableGroup.get_minimal(test_definition.table_groups_id)
    test_suite = TestSuite.get(test_definition.test_suite_id)
    if test_suite:
        edit_test_dialog(
            table_group,
            test_suite,
            test_definition.table_name,
            test_definition.column_name,
            test_definition.to_dict(),
        )


def show_test_form(
    mode: typing.Literal["add", "edit"],
    table_group: TableGroupMinimal,
    test_suite: TestSuite,
    table_name: str,
    column_name: str,
    selected_test_def: dict | None = None,
):
    # test_type logic
    if mode == "add":
        selected_test_type, selected_test_type_row = prompt_for_test_type()
        test_type = selected_test_type
    else:
        test_type = selected_test_def["test_type"]
        df = run_test_type_lookup_query()
        selected_test_type_row = df[df["test_type"] == test_type].iloc[0]
        test_type_display = selected_test_type_row["test_name_short"]

    if selected_test_type_row is None:
        return

    # run type
    run_type = selected_test_type_row["run_type"]  # Can be "QUERY" or "CAT"
    test_scope = selected_test_type_row["test_scope"]  # Can be "column", "table", "referential", "custom", "tablegroup"

    # test_description
    test_description = empty_if_null(selected_test_def["test_description"]) if mode == "edit" else ""
    test_type_test_description = selected_test_type_row["test_description"]
    test_description_help = (
        "You may enter a description here to override the default description above for the Test Type."
    )
    test_description_placeholder = f"Inherited ({test_type_test_description})"

    # severity
    test_suite_severity = test_suite.severity
    test_types_severity = selected_test_type_row["default_severity"]
    inherited_severity = test_suite_severity if test_suite_severity else test_types_severity

    severity_options = [
        f"Inherited ({inherited_severity})",
        "Log",
        "Warning",
        "Fail",
    ]
    if mode == "add" or selected_test_def["severity"] is None:
        severity_index = 0
    else:
        severity_index = severity_options.index(selected_test_def["severity"])

    # general value parsing
    table_groups_id = selected_test_def["table_groups_id"] if mode == "edit" else table_group.id
    test_suite_id = test_suite.id
    schema_name = selected_test_def["schema_name"] if mode == "edit" else table_group.table_group_schema
    table_name = empty_if_null(selected_test_def["table_name"]) if mode == "edit" else empty_if_null(table_name)
    skip_errors = selected_test_def["skip_errors"] or 0 if mode == "edit" else 0
    test_active = bool(selected_test_def["test_active"]) if mode == "edit" else True
    lock_refresh = bool(selected_test_def["lock_refresh"]) if mode == "edit" else False
    test_definition_status = selected_test_def["test_definition_status"] if mode == "edit" else ""
    column_name = empty_if_null(selected_test_def["column_name"]) if mode == "edit" else empty_if_null(column_name)
    last_auto_gen_date = empty_if_null(selected_test_def["last_auto_gen_date"]) if mode == "edit" else ""
    profiling_as_of_date = empty_if_null(selected_test_def["profiling_as_of_date"]) if mode == "edit" else ""
    profile_run_id = empty_if_null(selected_test_def["profile_run_id"]) if mode == "edit" else ""


    # dynamic attributes
    custom_query = empty_if_null(selected_test_def["custom_query"]) if mode == "edit" else ""
    baseline_ct = empty_if_null(selected_test_def["baseline_ct"]) if mode == "edit" else ""
    baseline_unique_ct = empty_if_null(selected_test_def["baseline_unique_ct"]) if mode == "edit" else ""
    baseline_value = empty_if_null(selected_test_def["baseline_value"]) if mode == "edit" else ""
    baseline_value_ct = empty_if_null(selected_test_def["baseline_value_ct"]) if mode == "edit" else ""
    threshold_value = selected_test_def["threshold_value"] or 0 if mode == "edit" else 0
    baseline_sum = empty_if_null(selected_test_def["baseline_sum"]) if mode == "edit" else ""
    baseline_avg = empty_if_null(selected_test_def["baseline_avg"]) if mode == "edit" else ""
    baseline_sd = empty_if_null(selected_test_def["baseline_sd"]) if mode == "edit" else ""
    lower_tolerance = selected_test_def["lower_tolerance"] or 0 if mode == "edit" else 0
    upper_tolerance = selected_test_def["upper_tolerance"] or 0 if mode == "edit" else 0
    subset_condition = empty_if_null(selected_test_def["subset_condition"]) if mode == "edit" else ""
    groupby_names = empty_if_null(selected_test_def["groupby_names"]) if mode == "edit" else ""
    having_condition = empty_if_null(selected_test_def["having_condition"]) if mode == "edit" else ""
    window_date_column = empty_if_null(selected_test_def["window_date_column"]) if mode == "edit" else ""
    match_schema_name = empty_if_null(selected_test_def["match_schema_name"]) if mode == "edit" else ""
    match_table_name = empty_if_null(selected_test_def["match_table_name"]) if mode == "edit" else ""
    match_column_names = empty_if_null(selected_test_def["match_column_names"]) if mode == "edit" else ""
    match_subset_condition = empty_if_null(selected_test_def["match_subset_condition"]) if mode == "edit" else ""
    match_groupby_names = empty_if_null(selected_test_def["match_groupby_names"]) if mode == "edit" else ""
    match_having_condition = empty_if_null(selected_test_def["match_having_condition"]) if mode == "edit" else ""
    window_days = selected_test_def["window_days"] or 0 if mode == "edit" else 0
    history_calculation = empty_if_null(selected_test_def["history_calculation"]) if mode == "edit" else ""
    history_lookback = empty_if_null(selected_test_def["history_lookback"]) if mode == "edit" else ""

    # export_to_observability
    inherited_export_to_observability = "Yes" if test_suite.export_to_observability else "No"
    inherited_legend = f"Inherited ({inherited_export_to_observability})"
    export_to_observability_options = [inherited_legend, "Yes", "No"]
    if mode == "edit":
        match selected_test_def["export_to_observability"]:
            case False:
                export_to_observability = "No"
            case True:
                export_to_observability = "Yes"
            case _:
                export_to_observability = inherited_legend
    else:
        export_to_observability = inherited_legend
    export_to_observability_index = export_to_observability_options.index(export_to_observability)

    # dynamic attributes
    dynamic_attributes_raw = selected_test_type_row["default_parm_columns"] or ""
    dynamic_attributes = dynamic_attributes_raw.split(",")

    dynamic_attributes_labels_raw = selected_test_type_row["default_parm_prompts"]
    dynamic_attributes_labels = ""
    if dynamic_attributes_labels_raw:
        dynamic_attributes_labels = dynamic_attributes_labels_raw.split(",")

    # Split on pipe -- could contain commas
    dynamic_attributes_help = (
        selected_test_type_row["default_parm_help"].split("|")
        if selected_test_type_row["default_parm_help"]
        else None
    )

    if mode == "edit":
        st.text_input(label="Test Type", value=test_type_display, disabled=True),

    # Using the test_type, display the default description and usage_notes
    if selected_test_type_row["test_description"]:
        st.html(
            f"""
                <div style="border: 1px solid #e6e6e6; border-radius: 5px; padding: 10px;">
                    {selected_test_type_row['test_description']}
                </div><br/>
            """
        )

    if selected_test_type_row["usage_notes"]:
        st.info(f"**Usage Notes:**\n\n{selected_test_type_row['usage_notes']}")

    left_column, right_column = st.columns([0.5, 0.5])
    left_column.text_input(
        label="Test Suite Name", max_chars=200, value=test_suite.test_suite, disabled=True
    )

    test_definition = {
        "table_groups_id": table_groups_id,
        "test_type": test_type,
        "test_suite_id": test_suite_id,
        "test_description": left_column.text_area(
            label="Test Description Override",
            max_chars=1000,
            height=114,
            placeholder=test_description_placeholder,
            value=test_description,
            help=test_description_help,
        ),
        "lock_refresh": left_column.toggle(
            label="Lock Refresh",
            value=lock_refresh,
            help="Protects test parameters from being overwritten when tests in this Test Suite are regenerated.",
        ),
        "test_active": left_column.toggle(label="Test Active", value=test_active),
        "custom_query": custom_query,
        "baseline_ct": baseline_ct,
        "baseline_unique_ct": baseline_unique_ct,
        "baseline_value": baseline_value,
        "baseline_value_ct": baseline_value_ct,
        "threshold_value": threshold_value,
        "baseline_sum": baseline_sum,
        "baseline_avg": baseline_avg,
        "baseline_sd": baseline_sd,
        "lower_tolerance": lower_tolerance,
        "upper_tolerance": upper_tolerance,
        "subset_condition": subset_condition,
        "groupby_names": groupby_names,
        "having_condition": having_condition,
        "window_date_column": window_date_column,
        "match_schema_name": match_schema_name,
        "match_table_name": match_table_name,
        "column_name": column_name,
        "match_column_names": match_column_names,
        "match_subset_condition": match_subset_condition,
        "match_groupby_names": match_groupby_names,
        "match_having_condition": match_having_condition,
        "window_days": window_days,
        "history_calculation": history_calculation,
        "history_lookback": history_lookback,
    }

    # test_definition_status
    test_definition["test_definition_status"] = test_definition_status
    if mode == "edit":
        test_definition_status_display = test_definition_status if test_definition_status else "OK"
        left_column.text_input(
            label="Validation Status", max_chars=200, value=test_definition_status_display, disabled=True
        )

    # export_to_observability
    export_to_observability_help = "Send results to DataKitchen Observability - overrides Test Suite toggle"
    export_to_observability_select = right_column.selectbox(
        label="Send to Observability - Override",
        options=export_to_observability_options,
        index=export_to_observability_index,
        help=export_to_observability_help,
    )
    test_definition["export_to_observability"] = (
        True if export_to_observability_select == "Yes" else (False if export_to_observability_select == "No" else None)
    )

    # severity
    severity_help = "Urgency is defined by default for the Test Type, but can be overridden for all tests in the Test Suite, and ultimately here for each individual test."
    severity_select = right_column.selectbox(
        label="Urgency Override",
        options=severity_options,
        index=severity_index,
        help=severity_help,
    )
    test_definition["severity"] = None if severity_select.startswith("Inherited") else severity_select

    if mode == "edit":
        columns = st.columns([0.5, 0.5])
        if profiling_as_of_date and profile_run_id and (container := columns.pop()):
            if isinstance(profiling_as_of_date, str):
                formatted_time = datetime.strptime(profiling_as_of_date, "%Y-%m-%d %H:%M:%S").strftime("%b %d, %I:%M %p")
            else:
                formatted_time = profiling_as_of_date.strftime("%b %d, %I:%M %p")
            testgen.caption("Based on Profiling", container=container)
            with container:
                testgen.link(
                    href="profiling-runs:results",
                    params={"run_id": str(profile_run_id)},
                    label=formatted_time,
                    open_new=True,
                )

        if last_auto_gen_date and (container := columns.pop()):
            if isinstance(last_auto_gen_date, str):
                formatted_time = datetime.strptime(last_auto_gen_date, "%Y-%m-%d %H:%M:%S").strftime("%b %d, %I:%M %p")
            else:
                formatted_time = last_auto_gen_date.strftime("%b %d, %I:%M %p")
            testgen.caption("Auto-generated at", container=container)
            testgen.text(
                formatted_time,
                container=container,
            )

    st.divider()

    has_match_attributes = any(attribute.startswith("match_") for attribute in dynamic_attributes)
    left_column, right_column = st.columns([0.5, 0.5]) if has_match_attributes else (st.container(), None)

    test_definition["schema_name"] = left_column.text_input(
            label="Schema", max_chars=100, value=schema_name, disabled=True
        )

    # table_name
    table_column_list = get_columns(table_groups_id)
    if test_scope == "tablegroup":
        test_definition["table_name"] = None
    elif test_scope == "custom":
        test_definition["table_name"] = left_column.text_input(
            label="Table", max_chars=100, value=table_name, disabled=False
        )
    else:
        table_name_options = { item["table_name"] for item in table_column_list }
        if table_name not in table_name_options:
            table_name_options.add(table_name)
        table_name_options = list(table_name_options)
        table_name_options.sort(key=lambda x: x.lower())
        test_definition["table_name"] = st.selectbox(
            label="Table",
            options=table_name_options,
            index=table_name_options.index(table_name) if table_name else 0,
            disabled=mode == "edit",
            key="table-name-form",
        )

    column_name_label = None
    if test_scope in ("table", "tablegroup"):
        test_definition["column_name"] = None
    elif test_scope in ("referential", "custom"):
        column_name_label = selected_test_type_row["column_name_prompt"] if selected_test_type_row["column_name_prompt"] else "Test Focus"
        test_definition["column_name"] = left_column.text_input(
            label=column_name_label,
            value=column_name,
            max_chars=500,
            help=selected_test_type_row["column_name_help"] if selected_test_type_row["column_name_help"] else None,
        )
    elif test_scope == "column":  # CAT column test
        column_name_label = "Column"
        column_name_options = { item["column_name"] for item in table_column_list if item["table_name"] == test_definition["table_name"]}
        if column_name not in column_name_options:
            column_name_options.add(column_name)
        column_name_options = list(column_name_options)
        column_name_options.sort(key=lambda x: x.lower())
        test_definition["column_name"] = st.selectbox(
            label=column_name_label,
            options=column_name_options,
            index=column_name_options.index(column_name) if column_name else 0,
            key="column-name-form",
        )

    leftover_attributes = dynamic_attributes.copy()

    def render_dynamic_attribute(attribute: str, container: DeltaGenerator):
        if not attribute in dynamic_attributes or not attribute:
            return

        choice_fields = {
            "history_calculation": ["Value", "Minimum", "Maximum", "Sum", "Average"],
        }
        float_numeric_attributes = ["lower_tolerance", "upper_tolerance"]
        if test_type != "LOV_All":
            float_numeric_attributes.append("threshold_value")
        int_numeric_attributes = ["history_lookback"]

        default_value = 0 if attribute in [*float_numeric_attributes, *int_numeric_attributes] else ""
        value = (
            selected_test_def[attribute]
            if mode == "edit" and selected_test_def[attribute] is not None
            else default_value
        )

        index = dynamic_attributes.index(attribute)
        leftover_attributes.remove(attribute)

        label_text = (
            dynamic_attributes_labels[index]
            if dynamic_attributes_labels and len(dynamic_attributes_labels) > index
            else snake_case_to_title_case(attribute)
        )
        help_text = (
            dynamic_attributes_help[index]
            if dynamic_attributes_help and len(dynamic_attributes_help) > index
            else None
        )

        if attribute == "custom_query":
            custom_query_placeholder = None
            if test_type == "Condition_Flag":
                custom_query_placeholder = "EXAMPLE:  status = 'SHIPPED' and qty_shipped = 0"
            elif test_type == "CUSTOM":
                custom_query_placeholder = "EXAMPLE:  SELECT product, SUM(qty_sold) as sum_sold, SUM(qty_shipped) as qty_shipped \n FROM {DATA_SCHEMA}.sales_history \n GROUP BY product \n HAVING SUM(qty_shipped) > SUM(qty_sold)"

            test_definition[attribute] = container.text_area(
                label=label_text,
                value=custom_query,
                placeholder=custom_query_placeholder,
                height=150 if test_type == "CUSTOM" else 75,
                help=help_text,
            )
        elif attribute in float_numeric_attributes:
            test_definition[attribute] = container.number_input(
                label=label_text,
                value=float(value),
                step=1.0,
                help=help_text,
            )
        elif attribute in int_numeric_attributes:
            max_value = None
            if (
                attribute == "history_lookback"
                and int(value) <= 1
                and (
                    not test_definition.get("history_calculation")
                    or test_definition.get("history_calculation") == "Value"
                )
            ):
                max_value = 1
            test_definition[attribute] = container.number_input(
                label=label_text,
                step=1,
                value=int(value),
                max_value=max_value,
                min_value=0,
                help=help_text,
            )
        elif attribute in choice_fields:
            with container:
                test_definition[attribute] = testgen.select(
                    label_text,
                    choice_fields[attribute],
                    required=True,
                    default_value=value,
                )
        else:
            test_definition[attribute] = container.text_input(
                label=label_text,
                max_chars=4000 if attribute in ["match_column_names", "match_groupby_names", "groupby_names"] else 1000,
                value=value,
                help=help_text,
            )

    if has_match_attributes:
        for attribute in ["match_schema_name", "match_table_name", "match_column_names"]:
            render_dynamic_attribute(attribute, right_column)

    if test_scope != "tablegroup":
        st.divider()

    mid_container = st.container()
    mid_left_column, mid_right_column = st.columns([0.5, 0.5])

    if has_match_attributes:
        for attribute in ["subset_condition", "groupby_names", "having_condition"]:
            if attribute in dynamic_attributes and f"match_{attribute}" in dynamic_attributes:
                render_dynamic_attribute(attribute, mid_left_column)
                render_dynamic_attribute(f"match_{attribute}", mid_right_column)

    if "custom_query" in dynamic_attributes:
        render_dynamic_attribute("custom_query", mid_container)

    total_length = len(leftover_attributes)
    half_length = round(total_length / 2)
    for index, attribute in enumerate(leftover_attributes.copy()):
        render_dynamic_attribute(
            attribute,
            mid_left_column if index == 0 or index < half_length else mid_right_column,
        )

    # skip_errors
    if run_type == "QUERY":
        container = mid_right_column if total_length % 2 else mid_left_column
        test_definition["skip_errors"] = container.number_input(
            label="Threshold Error Count",
            value=skip_errors,
            step=1,
        )
    else:
        test_definition["skip_errors"] = skip_errors

    # submit logic
    bottom_left_column, bottom_right_column = st.columns([0.5, 0.5])

    # Add Validate button
    if test_type in ("Condition_Flag", "CUSTOM"):
        validate = bottom_left_column.button(
            "Validate",
        )
        if validate:
            try:
                validate_test(test_definition, table_group)
                bottom_right_column.success("Validation is successful.")
            except Exception as e:
                bottom_right_column.error(f"Test validation failed with error: {e}")
        else:
            # This is needed to fix a strange bug in Streamlit when using dialog + input fields + button
            # If an input field is changed and the button is clicked immediately (without unfocusing the input first),
            # two fragment reruns happen successively, one for unfocusing the input and the other for clicking the button
            # Some or all (it seems random) of the input fields disappear when this happens
            time.sleep(0.1)

    submit = bottom_left_column.button("Save")

    if submit:
        if validate_form(test_scope, test_definition, column_name_label):
            if mode == "edit":
                test_definition["id"] = selected_test_def["id"]
            TestDefinition(**test_definition).save()
            get_test_suite_columns.clear()
            st.rerun()


@st.dialog(title="Add Test")
@with_database_session
def add_test_dialog(table_group, test_suite, str_table_name, str_column_name):
    show_test_form("add", table_group, test_suite, str_table_name, str_column_name)


@st.dialog(title="Edit Test")
@with_database_session
def edit_test_dialog(table_group, test_suite, str_table_name, str_column_name, selected_test_def):
    show_test_form("edit", table_group, test_suite, str_table_name, str_column_name, selected_test_def)


@st.dialog(title="Copy/Move Tests")
@with_database_session
def copy_move_test_dialog(
    project_code: str,
    origin_table_group: TableGroup,
    origin_test_suite: TestSuite,
    selected_test_definitions: list[dict],
):
    st.text(f"Selected tests: {len(selected_test_definitions)}")

    group_filter_column, suite_filter_column, table_filter_column = st.columns([.33, .33, .33], vertical_alignment="bottom")

    with group_filter_column:
        table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
        table_groups_df = to_dataframe(table_groups, TableGroupMinimal.columns())
        target_table_group_id = testgen.select(
            options=table_groups_df,
            value_column="id",
            display_column="table_groups_name",
            default_value=origin_table_group.id,
            required=True,
            label="Target Table Group",
        )

    with suite_filter_column:
        test_suites = TestSuite.select_minimal_where(TestSuite.table_groups_id == target_table_group_id)
        test_suites_df = to_dataframe(test_suites, TestSuiteMinimal.columns())
        target_test_suite_id = testgen.select(
            options=test_suites_df,
            value_column="id",
            display_column="test_suite",
            default_value=None,
            required=True,
            label="Target Test Suite",
        )

    target_table_name = None
    target_column_name = None
    if target_test_suite_id == origin_test_suite.id:
        with table_filter_column:
            columns_df = get_test_suite_columns(origin_test_suite.id)
            target_table_name = testgen.select(
                options=list(columns_df["table_name"].unique()),
                value_column="table_name",
                default_value=None,
                required=True,
                label="Target Table Name",
            )
            column_options = list(columns_df.loc[columns_df["table_name"] == target_table_name]["column_name"].unique())
            target_column_name = testgen.select(
                options=column_options,
                default_value=None,
                required=True,
                label="Column Name",
                disabled=not target_table_name,
            )

    movable_test_definitions = []
    if target_table_group_id and target_test_suite_id:
        collision_test_definitions = get_test_definitions_collision(selected_test_definitions, target_table_group_id, target_test_suite_id)
        if not collision_test_definitions.empty:
            unlocked = collision_test_definitions[collision_test_definitions["lock_refresh"] == False]
            locked = collision_test_definitions[collision_test_definitions["lock_refresh"] == True]
            locked_tuples = [ (test["table_name"], test["column_name"], test["test_type"]) for test in locked.iterrows() ]
            movable_test_definitions = [ test for test in selected_test_definitions if (test["table_name"], test["column_name"], test["test_type"]) not in locked_tuples ]

            warning_message = f"""Auto-generated tests are present in the target test suite for the same column-test type combinations as the selected tests.
            \nUnlocked tests that will be overwritten: {len(unlocked)}
            \nLocked tests that will not be overwritten: {len(locked)}
            """
            st.warning(warning_message, icon=":material/warning:")
        else:
            movable_test_definitions = selected_test_definitions

    testgen.whitespace(1)
    _, copy_column, move_column = st.columns([.6, .2, .2])
    copy = copy_column.button(
        "Copy",
        use_container_width=True,
        disabled=not len(movable_test_definitions)>0,
    )

    move = move_column.button(
        "Move",
        disabled=not len(movable_test_definitions)>0,
        use_container_width=True,
    )

    test_definition_ids = [item["id"] for item in movable_test_definitions]
    if move:
        TestDefinition.move(test_definition_ids, target_table_group_id, target_test_suite_id, target_table_name, target_column_name)
        success_message = "Test Definitions have been moved."
        st.success(success_message)
        get_test_suite_columns.clear()
        time.sleep(1)
        st.rerun()
    elif copy:
        TestDefinition.copy(test_definition_ids, target_table_group_id, target_test_suite_id, target_table_name, target_column_name)
        success_message = "Test Definitions have been copied."
        st.success(success_message)
        get_test_suite_columns.clear()
        time.sleep(1)
        st.rerun()

def validate_form(test_scope, test_definition, column_name_label):
    if test_scope in ["column", "referential", "custom"] and not test_definition["column_name"]:
        st.error(f"{column_name_label} is a required field.")
        return False
    return True


def prompt_for_test_type():

    col0, col1, col2, col3, col4 = st.columns([0.2, 0.2, 0.2, 0.2, 0.2])
    col0.write("Show Types")

    include_referential=col1.checkbox(":green[⧉] Referential", True)
    include_table=col2.checkbox(":green[⊞] Table", True)
    include_column=col3.checkbox(":green[≣] Column", True)
    include_custom=col4.checkbox(":green[⛭] Custom", True)
    # always exclude tablegroup scopes from showing
    include_all = not any([include_referential, include_table, include_column, include_custom])

    df = run_test_type_lookup_query(
        include_referential=include_referential or include_all,
        include_table=include_table or include_all,
        include_column=include_column or include_all,
        include_custom=include_custom or include_all,
        include_tablegroup=False,
    )
    lst_choices = df["select_name"].tolist()

    str_selected = selectbox("Test Type", lst_choices)
    if str_selected:
        row_selected = df[df["test_name_short"] == str_selected.split(":", 1)[0][2:]].iloc[0]
        str_value = row_selected["test_type"]
    else:
        str_value = None
        row_selected = None
    return str_value, row_selected


@st.dialog(title="Unlock Test Definition")
@with_database_session
def confirm_unlocking_test_definition(test_definitions: list[dict]):
    unlock_confirmed, set_unlock_confirmed = temp_value("test-definitions:confirm-unlock-tests")

    st.warning(
        """Unlocked tests subject to auto-generation will be overwritten during the next test generation run."""
    )

    st.html(f"""
        Are you sure you want to unlock
        {f"<b>{len(test_definitions)}</b> selected test definitions?"
        if len(test_definitions) > 1
        else "the selected test definition?"}
    """)

    if unlock_confirmed():
        update_test_definition(test_definitions, "lock_refresh", False, "Test definitions have been unlocked.")
        time.sleep(1)
        st.rerun()

    _, button_column = st.columns([.85, .15])
    with button_column:
        testgen.button(
            label="Unlock",
            type_="stroked",
            color="basic",
            key="test-definitions:confirm-unlock-tests-btn",
            on_click=lambda: set_unlock_confirmed(True),
        )


def update_test_definition(selected, attribute, value, message):
    result = None
    test_definition_ids = [row["id"] for row in selected if "id" in row]
    TestDefinition.set_status_attribute(attribute, test_definition_ids, value)
    st.success(message)
    return result


@with_database_session
def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    test_suite: TestSuite,
    schema: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is not None:
        data = data.copy()
    else:
        data = get_test_definitions(test_suite)

    for key in ["test_active_display", "lock_refresh_display"]:
        data[key] = data[key].apply(lambda val: val if val == "Yes" else None)

    for key in ["profiling_as_of_date", "last_manual_update"]:
        data[key] = data[key].apply(
            lambda val: datetime.strptime(val, "%Y-%m-%d %H:%M:%S").strftime("%b %-d %Y, %-I:%M %p") if not pd.isna(val) else None
        )

    columns = {
        "table_name": {"header": "Table"},
        "column_name": {"header": "Column/Focus"},
        "test_name_short": {"header": "Test type"},
        "final_test_description": {"header": "Description", "wrap": True},
        "threshold_value": {},
        "export_uom": {"header": "Unit of measure"},
        "test_active_display": {"header": "Active"},
        "lock_refresh_display": {"header": "Locked"},
        "urgency": {"header": "Severity"},
        "profiling_as_of_date": {"header": "From profiling as-of (UTC)"},
        "last_manual_update": {"header": "Last manual update (UTC)"},
    }
    return get_excel_file_data(
        data,
        "Test Definitions",
        details={"Test suite": test_suite.test_suite, "Schema": schema},
        columns=columns,
        update_progress=update_progress,
    )


def generate_test_defs_help(str_test_type):
    df = run_test_type_lookup_query(str_test_type)
    if not df.empty:
        row = df.iloc[0]

        str_help = f"""
##### {row["test_name_short"]}
{row["test_description"]}

**Measure UOM:**  {row["measure_uom"]}

{row["measure_uom_description"]}

**Threshold:**  {row["threshold_description"]}

**Default Test Severity:** {row["default_severity"]}

**Test Run Type:** {row["test_scope"]}
 - COLUMN tests are consolidated into aggregate queries and execute faster.
 - TABLE, REFERENTIAL and CUSTOM tests are executed individually and may take longer to run.

**Data Quality Dimension:** {row["dq_dimension"]}
"""
    else:
        str_help = ""
    return str_help


@st.cache_data(show_spinner=False)
def run_test_type_lookup_query(
    test_type: str | None = None,
    include_referential: bool = True,
    include_table: bool = True,
    include_column: bool = True,
    include_custom: bool = True,
    include_tablegroup: bool = True,
) -> pd.DataFrame:
    scope_map = {
        "referential": include_referential,
        "table": include_table,
        "column": include_column,
        "custom": include_custom,
        "tablegroup": include_tablegroup,
    }
    scopes = [ key for key, include in scope_map.items() if include ]

    query = f"""
    SELECT
        tt.id, tt.test_type, tt.id as cat_test_id,
        tt.test_name_short, tt.test_name_long, tt.test_description,
        tt.measure_uom, COALESCE(tt.measure_uom_description, '') as measure_uom_description,
        tt.default_parm_columns, tt.default_severity,
        tt.run_type, tt.test_scope, tt.dq_dimension, tt.threshold_description,
        tt.column_name_prompt, tt.column_name_help,
        tt.default_parm_prompts, tt.default_parm_help, tt.usage_notes,
        CASE tt.test_scope
            WHEN 'referential' THEN '⧉ '
            WHEN 'custom' THEN '⛭ '
            WHEN 'table' THEN '⊞ '
            WHEN 'column' THEN '≣ '
            WHEN 'tablegroup' THEN '▦ '
            ELSE '? '
        END
        || tt.test_name_short
        || ': '
        || lower(tt.test_name_long)
        || CASE
            WHEN tt.selection_criteria > '' THEN ' [auto-generated]'
            ELSE ''
        END as select_name
    FROM test_types tt
    WHERE tt.active = 'Y'
        {"AND tt.test_type = :test_type" if test_type else ""}
        {"AND tt.test_scope in :scopes" if scopes else ""}
    ORDER BY
        CASE tt.test_scope
            WHEN 'referential' THEN 1
            WHEN 'custom' THEN 2
            WHEN 'table' THEN 3
            WHEN 'column' THEN 4
            WHEN 'tablegroup' THEN 5
            ELSE 6
        END,
        tt.test_name_short;
    """
    params = {
        "test_type": test_type,
        "scopes": tuple(scopes),
    }
    return fetch_df_from_db(query, params)


@st.cache_data(show_spinner=False)
def get_test_suite_columns(test_suite_id: str) -> pd.DataFrame:
    results = TestDefinition.select_minimal_where(
        TestDefinition.test_suite_id == test_suite_id,
        order_by = (asc(func.lower(TestDefinition.table_name)), asc(func.lower(TestDefinition.column_name))),
    )
    return to_dataframe(results, TestDefinitionMinimal.columns())


def get_test_definitions(
    test_suite: TestSuite,
    table_name: str | None = None,
    column_name: str | None = None,
    test_type: str | None = None,
    sorting_columns: list[str] | None = None,
) -> pd.DataFrame:
    clauses = [TestDefinition.test_suite_id == test_suite.id]
    if table_name:
        clauses.append(TestDefinition.table_name == table_name)
    if column_name:
        clauses.append(TestDefinition.column_name.ilike(column_name))
    if test_type:
        clauses.append(TestDefinition.test_type == test_type)

    sort_funcs = {"ASC": asc, "DESC": desc}
    test_definitions = TestDefinition.select_where(
        *clauses,
        order_by=tuple([
            sort_funcs[direction](func.lower(getattr(TestDefinition, attribute)))
            for (attribute, direction) in sorting_columns
        ]) if sorting_columns else None,
    )

    df = to_dataframe(test_definitions, TestDefinitionSummary.columns())
    date_service.accommodate_dataframe_to_timezone(df, st.session_state)
    for key in ["id", "table_groups_id", "profile_run_id", "test_suite_id"]:
        df[key] = df[key].apply(lambda value: str(value))

    df["test_active_display"] = df["test_active"].apply(lambda value: "Yes" if value else "No")
    df["lock_refresh_display"] = df["lock_refresh"].apply(lambda value: "Yes" if value else "No")
    df["urgency"] = df.apply(lambda row: row["severity"] or test_suite.severity or row["default_severity"], axis=1)
    df["final_test_description"] = df.apply(lambda row: row["test_description"] or row["default_test_description"], axis=1)
    df["export_uom"] = df.apply(lambda row: row["measure_uom_description"] or row["measure_uom"], axis=1)

    def get_export_to_observability_display(value: str) -> str:
        if value is not None:
            return "Yes" if value else "No"
        return f"Inherited ({'Yes' if test_suite.export_to_observability else 'No'})"
    df["export_to_observability_display"] = df["export_to_observability"].apply(get_export_to_observability_display)

    for col in df.select_dtypes(include=["datetime"]).columns:
        df[col] = df[col].astype(str).replace("NaT", "")

    return df


def get_test_definitions_collision(
    test_definitions: list[dict],
    target_table_group_id: str,
    target_test_suite_id: str,
) -> pd.DataFrame:
    table_tests = [(item["table_name"], item["test_type"]) for item in test_definitions if item["column_name"] is None and item["table_name"] is not None]
    column_tests = [(item["table_name"], item["column_name"], item["test_type"]) for item in test_definitions if item["column_name"] is not None]
    results = TestDefinition.select_minimal_where(
        TestDefinition.table_groups_id == target_table_group_id,
        TestDefinition.test_suite_id == target_test_suite_id,
        TestDefinition.last_auto_gen_date.isnot(None),
        or_(
            tuple_(TestDefinition.table_name, TestDefinition.column_name, TestDefinition.test_type).in_(column_tests),
            and_(tuple_(TestDefinition.table_name, TestDefinition.test_type).in_(table_tests), TestDefinition.column_name.is_(None)),
        )
    )
    return to_dataframe(results, TestDefinitionMinimal.columns())


def get_columns(table_groups_id: str) -> list[dict]:
    results = fetch_all_from_db(
        """
        SELECT table_name, column_name
        FROM data_column_chars
        WHERE table_groups_id = :table_groups_id
            AND drop_date IS NULL
        """,
        {
            "table_groups_id": table_groups_id,
        },
    )
    return [ dict(row) for row in results ]


def validate_test(test_definition, table_group: TableGroupMinimal):
    schema = test_definition["schema_name"]
    table_name = test_definition["table_name"]
    connection = Connection.get(table_group.connection_id)

    if test_definition["test_type"] == "Condition_Flag":
        condition = test_definition["custom_query"]
        flavor_service = get_flavor_service(connection.sql_flavor)
        concat_operator = flavor_service.concat_operator
        quote = flavor_service.quote_character
        query = f"""
        SELECT
            COALESCE(
                CAST(
                    SUM(
                        CASE WHEN {condition} THEN 1 ELSE 0 END
                    ) AS VARCHAR(1000)
                )
                {concat_operator} '|',
                '<NULL>|'
            )
        FROM {quote}{schema}{quote}.{quote}{table_name}{quote};
        """
    else:
        query = replace_params(
            f"""
            SELECT COUNT(*)
            FROM (
                {test_definition["custom_query"]}
            ) TEST
            """,
            {"DATA_SCHEMA": schema},
        )

    fetch_from_target_db(connection, query)
