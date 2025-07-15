import logging
import time
import typing
from datetime import datetime
from functools import partial

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator
from streamlit_extras.no_default_selectbox import selectbox

import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
import testgen.ui.services.table_group_service as table_group_service
import testgen.ui.services.test_definition_service as test_definition_service
import testgen.ui.services.test_suite_service as test_suite_service
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
)
from testgen.ui.components.widgets.page import css_class, flex_row_end
from testgen.ui.navigation.page import Page
from testgen.ui.services import project_service, user_session_service
from testgen.ui.services.string_service import empty_if_null, snake_case_to_title_case
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.profiling_results_dialog import view_profiling_button

LOG = logging.getLogger("testgen")


class TestDefinitionsPage(Page):
    path = "test-suites:definitions"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "test_suite_id" in st.query_params or "test-suites",
    ]

    def render(self, test_suite_id: str, table_name: str | None = None, column_name: str | None = None, **_kwargs) -> None:
        test_suite = test_suite_service.get_by_id(test_suite_id)
        if test_suite.empty:
            self.router.navigate_with_warning(
                f"Test suite with ID '{test_suite_id}' does not exist. Redirecting to list of Test Suites ...",
                "test-suites",
            )

        table_group = table_group_service.get_by_id(test_suite["table_groups_id"])
        project_code = table_group["project_code"]
        project_service.set_sidebar_project(project_code)
        user_can_edit = user_session_service.user_can_edit()
        user_can_disposition = user_session_service.user_can_disposition()

        testgen.page_header(
            "Test Definitions",
            "testgen-test-types",
            breadcrumbs=[
                { "label": "Test Suites", "path": "test-suites", "params": { "project_code": project_code } },
                { "label": test_suite["test_suite"] },
            ],
        )

        table_filter_column, column_filter_column, table_actions_column = st.columns([.3, .3, .4], vertical_alignment="bottom")
        testgen.flex_row_end(table_actions_column)

        actions_column, disposition_column = st.columns([.5, .5])
        testgen.flex_row_start(actions_column)
        testgen.flex_row_end(disposition_column)

        with table_filter_column:
            columns_df = get_test_suite_columns(test_suite_id)
            table_options = list(columns_df["table_name"].unique())
            table_name = testgen.select(
                options=table_options,
                value_column="table_name",
                default_value=table_name or (table_options[0] if table_options else None),
                bind_to_query="table_name",
                required=True,
                label="Table Name",
            )
        with column_filter_column:
            column_options = columns_df.loc[columns_df["table_name"] == table_name]["column_name"].dropna().unique().tolist()
            column_name = testgen.select(
                options=column_options,
                default_value=column_name,
                bind_to_query="column_name",
                label="Column Name",
                disabled=not table_name,
                accept_new_options=True,
            )

        with disposition_column:
            str_help = "Toggle on to perform actions on multiple test definitions"
            do_multi_select = user_can_disposition and st.toggle("Multi-Select", help=str_help)

        if user_can_edit and actions_column.button(
            ":material/add: Add", help="Add a new Test Definition"
        ):
            add_test_dialog(project_code, table_group, test_suite, table_name, column_name)

        selected = show_test_defs_grid(
            project_code, test_suite["test_suite"], table_name, column_name, do_multi_select, table_actions_column,
            table_group["id"]
        )
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
                action["button"] = disposition_column.button(action["icon"], help=action["help"], disabled=not selected)

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

        if selected:
            selected_test_def = selected[0]

        if user_can_edit:
            if actions_column.button(
                ":material/edit: Edit",
                disabled=not selected,
            ):
                edit_test_dialog(project_code, table_group, test_suite, table_name, column_name, selected_test_def)

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


@st.dialog("Delete Tests")
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
        test_definition_service.delete([ item["id"] for item in test_definitions ])
        st.success("Test definitions have been deleted.")
        time.sleep(1)
        st.rerun()


def show_test_form_by_id(test_definition_id):
    selected_test_raw = test_definition_service.get_test_definitions(test_definition_ids=[test_definition_id])
    test_definition = selected_test_raw.iloc[0].to_dict()

    project_code = test_definition["project_code"]
    table_group_id = test_definition["table_groups_id"]
    test_suite_name = test_definition["test_suite"]
    table_name = test_definition["table_name"]
    column_name = test_definition["column_name"]

    table_group_raw = run_table_groups_lookup_query(project_code, table_group_id=None)
    table_group = table_group_raw.iloc[0].to_dict()

    test_suite_raw = run_test_suite_lookup_query(table_group_id, test_suite_name)
    if not test_suite_raw.empty:
        test_suite = test_suite_raw.iloc[0].to_dict()

        edit_test_dialog(
            project_code, table_group, test_suite, table_name, column_name, test_definition
        )


def show_test_form(
    mode,
    project_code,
    table_group,
    test_suite,
    str_table_name,
    str_column_name,
    selected_test_def=None,
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
    test_scope = selected_test_type_row["test_scope"]  # Can be "column", "table", "referential", "custom"

    # test_description
    test_description = empty_if_null(selected_test_def["test_description"]) if mode == "edit" else ""
    test_type_test_description = selected_test_type_row["test_description"]
    test_description_help = (
        "You may enter a description here to override the default description above for the Test Type."
    )
    test_description_placeholder = f"Inherited ({test_type_test_description})"

    # severity
    test_suite_severity = test_suite["severity"]
    test_types_severity = selected_test_type_row["default_severity"]
    inherited_severity = test_suite_severity if test_suite_severity else test_types_severity

    severity_options = [f"Inherited ({inherited_severity})", "Warning", "Fail"]
    if mode == "add" or selected_test_def["severity"] is None:
        severity_index = 0
    else:
        severity_index = severity_options.index(selected_test_def["severity"])

    # general value parsing
    entity_id = selected_test_def["id"] if mode == "edit" else ""
    cat_test_id = selected_test_def["cat_test_id"] if mode == "edit" else ""
    project_code = selected_test_def["project_code"] if mode == "edit" else project_code
    table_groups_id = selected_test_def["table_groups_id"] if mode == "edit" else table_group["id"]
    profile_run_id = selected_test_def["profile_run_id"] if mode == "edit" else ""
    test_suite_name = selected_test_def["test_suite"] if mode == "edit" else test_suite["test_suite"]
    test_suite_id = test_suite["id"]
    test_action = empty_if_null(selected_test_def["test_action"]) if mode == "edit" else ""
    schema_name = selected_test_def["schema_name"] if mode == "edit" else table_group["table_group_schema"]
    table_name = empty_if_null(selected_test_def["table_name"]) if mode == "edit" else empty_if_null(str_table_name)
    skip_errors = selected_test_def["skip_errors"] if mode == "edit" else 0
    test_active = selected_test_def["test_active"] == "Y" if mode == "edit" else True
    lock_refresh = selected_test_def["lock_refresh"] == "Y" if mode == "edit" else False
    test_definition_status = selected_test_def["test_definition_status"] if mode == "edit" else ""
    check_result = selected_test_def["check_result"] if mode == "edit" else None
    column_name = empty_if_null(selected_test_def["column_name"]) if mode == "edit" else ""
    last_auto_gen_date = empty_if_null(selected_test_def["last_auto_gen_date"]) if mode == "edit" else ""
    profiling_as_of_date = empty_if_null(selected_test_def["profiling_as_of_date"]) if mode == "edit" else ""
    profile_run_id = empty_if_null(selected_test_def["profile_run_id"]) if mode == "edit" else ""

    # dynamic attributes
    custom_query = empty_if_null(selected_test_def["custom_query"]) if mode == "edit" else ""
    baseline_ct = empty_if_null(selected_test_def["baseline_ct"]) if mode == "edit" else ""
    baseline_unique_ct = empty_if_null(selected_test_def["baseline_unique_ct"]) if mode == "edit" else ""
    baseline_value = empty_if_null(selected_test_def["baseline_value"]) if mode == "edit" else ""
    baseline_value_ct = empty_if_null(selected_test_def["baseline_value_ct"]) if mode == "edit" else ""
    threshold_value = empty_if_null(selected_test_def["threshold_value"]) if mode == "edit" else 0
    baseline_sum = empty_if_null(selected_test_def["baseline_sum"]) if mode == "edit" else ""
    baseline_avg = empty_if_null(selected_test_def["baseline_avg"]) if mode == "edit" else ""
    baseline_sd = empty_if_null(selected_test_def["baseline_sd"]) if mode == "edit" else ""
    lower_tolerance = empty_if_null(selected_test_def["lower_tolerance"]) if mode == "edit" else 0
    upper_tolerance = empty_if_null(selected_test_def["upper_tolerance"]) if mode == "edit" else 0
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
    window_days = selected_test_def["window_days"] if mode == "edit" and selected_test_def["window_days"] else 0
    test_mode = empty_if_null(selected_test_def["test_mode"]) if mode == "edit" else ""

    # export_to_observability
    test_suite_export_to_observability = test_suite["export_to_observability"]
    inherited_export_to_observability = "Yes" if test_suite_export_to_observability == "Y" else "No"

    inherited_legend = f"Inherited ({inherited_export_to_observability})"
    export_to_observability_options = [inherited_legend, "Yes", "No"]
    if mode == "edit":
        match selected_test_def["export_to_observability_raw"]:
            case "N":
                export_to_observability = "No"
            case "Y":
                export_to_observability = "Yes"
            case _:
                export_to_observability = inherited_legend
    else:
        export_to_observability = inherited_legend
    export_to_observability_index = export_to_observability_options.index(export_to_observability)

    # watch_level
    watch_level = selected_test_def["watch_level"] if mode == "edit" else "WARN"

    # dynamic attributes
    dynamic_attributes_raw = selected_test_type_row["default_parm_columns"]
    dynamic_attributes = dynamic_attributes_raw.split(",")

    dynamic_attributes_labels_raw = selected_test_type_row["default_parm_prompts"]
    dynamic_attributes_labels = ""
    if dynamic_attributes_labels_raw:
        dynamic_attributes_labels = dynamic_attributes_labels_raw.split(",")

    dynamic_attributes_help_raw = selected_test_type_row["default_parm_help"]
    if not dynamic_attributes_help_raw:
        dynamic_attributes_help_raw = "No help is available"
    # Split on pipe -- could contain commas
    dynamic_attributes_help = dynamic_attributes_help_raw.split("|")

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

    test_definition = {
        "id": entity_id,
        "cat_test_id": cat_test_id,
        "watch_level": watch_level,
        "project_code": project_code,
        "table_groups_id": table_groups_id,
        "profile_run_id": profile_run_id,
        "test_type": test_type,
        "test_suite": left_column.text_input(
            label="Test Suite Name", max_chars=200, value=test_suite_name, disabled=True
        ),
        "test_suite_id": test_suite_id,
        "test_description": left_column.text_area(
            label="Test Description Override",
            max_chars=1000,
            height=114,
            placeholder=test_description_placeholder,
            value=test_description,
            help=test_description_help,
        ),
        "test_action": test_action,
        "test_mode": test_mode,
        "lock_refresh": left_column.toggle(
            label="Lock Refresh",
            value=lock_refresh,
            help="Protects test parameters from being overwritten when tests in this Test Suite are regenerated.",
        ),
        "test_active": left_column.toggle(label="Test Active", value=test_active),
        "check_result": check_result,
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
    test_definition["export_to_observability_raw"] = right_column.selectbox(
        label="Send to Observability - Override",
        options=export_to_observability_options,
        index=export_to_observability_index,
        help=export_to_observability_help,
    )

    # severity
    severity_help = "Urgency is defined by default for the Test Type, but can be overridden for all tests in the Test Suite, and ultimately here for each individual test."
    test_definition["severity"] = right_column.selectbox(
        label="Urgency Override",
        options=severity_options,
        index=severity_index,
        help=severity_help,
    )

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
                    params={"run_id": profile_run_id},
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

    # schema_name
    test_definition["schema_name"] = left_column.text_input(
        label="Schema Name", max_chars=100, value=schema_name, disabled=True
    )

    # table_name
    test_definition["table_name"] = left_column.text_input(
        label="Table Name", max_chars=100, value=table_name, disabled=False
    )

    # column_name
    if selected_test_type_row["column_name_prompt"]:
        column_name_label = selected_test_type_row["column_name_prompt"]
    else:
        column_name_label = "Test Focus"
    if selected_test_type_row["column_name_help"]:
        column_name_help = selected_test_type_row["column_name_help"]
    else:
        column_name_help = "Help is not available"

    if test_scope == "table":
        test_definition["column_name"] = None
        column_name_label = None
    elif test_scope == "referential":
        column_name_disabled = False
        test_definition["column_name"] = left_column.text_input(
            label=column_name_label,
            value=column_name,
            max_chars=500,
            help=column_name_help,
            disabled=column_name_disabled,
        )
    elif test_scope == "custom":
        if str_column_name:
            if mode == "add":  # query add present
                column_name_disabled = False
                column_name = str_column_name
            else:  # query edit present
                column_name_disabled = False
                column_name = str_column_name
        else:
            if mode == "add":  # query add not-present
                column_name_disabled = False
            else:  # query edit not-present
                column_name_disabled = False

        test_definition["column_name"] = left_column.text_input(
            label=column_name_label,
            value=column_name,
            max_chars=100,
            help=column_name_help,
            disabled=column_name_disabled,
        )
    elif test_scope == "column":  # CAT column test
        if str_column_name:
            column_name_disabled = True
            if mode == "add":
                column_name = str_column_name  # CAT add present
            else:
                pass  # CAT edit present
        else:
            column_name_disabled = False
            if mode == "add":
                pass  # CAT add not-present
            else:
                pass  # CAT edit not-present

        column_name_label = "Column Name"
        column_name_options = get_column_names(table_groups_id, test_definition["table_name"])
        column_name_help = "Select the column to test"
        column_name_index = column_name_options.index(column_name) if column_name else 0
        test_definition["column_name"] = st.selectbox(
            label=column_name_label,
            options=column_name_options,
            index=column_name_index,
            help=column_name_help,
            key="column-name-form",
            disabled=column_name_disabled,
        )

    leftover_attributes = dynamic_attributes.copy()

    def render_dynamic_attribute(attribute: str, container: DeltaGenerator):
        if not attribute in dynamic_attributes:
            return
        
        numeric_attributes = ["threshold_value", "lower_tolerance", "upper_tolerance"]

        default_value = 0 if attribute in numeric_attributes else ""
        value = empty_if_null(selected_test_def[attribute]) if mode == "edit" else default_value

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
            else "Help text is not available."
        )

        if attribute == "custom_query":
            custom_query_placeholder = None
            if test_type == "Condition_Flag":
                custom_query_placeholder = "EXAMPLE:  status = 'SHIPPED' and qty_shipped = 0"
            elif test_type == "CUSTOM":
                custom_query_placeholder = "EXAMPLE:  SELECT product, SUM(qty_sold) as sum_sold, SUM(qty_shipped) as qty_shipped \n FROM {DATA_SCHEMA}.sales_history \n GROUP BY product \n HAVING SUM(qty_shipped) > SUM(qty_sold)"
                
            test_definition[attribute] = st.text_area(
                label=label_text,
                value=custom_query,
                placeholder=custom_query_placeholder,
                height=150 if test_type == "CUSTOM" else 75,
                help=help_text,
            )
        elif attribute in numeric_attributes:
            test_definition[attribute] = container.number_input(
                label=label_text,
                value=float(value),
                step=1.0,
                help=help_text,
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

    st.divider()

    mid_left_column, mid_right_column = st.columns([0.5, 0.5])

    if has_match_attributes:
        for attribute in ["subset_condition", "groupby_names", "having_condition"]:
            if attribute in dynamic_attributes and f"match_{attribute}" in dynamic_attributes:
                render_dynamic_attribute(attribute, mid_left_column)
                render_dynamic_attribute(f"match_{attribute}", mid_right_column)

    if "custom_query" in dynamic_attributes:
        render_dynamic_attribute("custom_query", mid_left_column)

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
                test_definition_service.validate_test(test_definition)
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
        if validate_form(test_scope, test_type, test_definition, column_name_label):
            if mode == "edit":
                test_definition_service.update(test_definition)
                st.rerun()
            else:
                test_definition_service.add(test_definition)
                st.rerun()


@st.dialog(title="Add Test")
def add_test_dialog(project_code, table_group, test_suite, str_table_name, str_column_name):
    show_test_form("add", project_code, table_group, test_suite, str_table_name, str_column_name)


@st.dialog(title="Edit Test")
def edit_test_dialog(project_code, table_group, test_suite, str_table_name, str_column_name, selected_test_def):
    show_test_form("edit", project_code, table_group, test_suite, str_table_name, str_column_name, selected_test_def)


@st.dialog(title="Copy/Move Tests")
def copy_move_test_dialog(project_code, origin_table_group, origin_test_suite, selected_test_definitions):
    st.text(f"Selected tests: {len(selected_test_definitions)}")

    group_filter_column, suite_filter_column, table_filter_column = st.columns([.33, .33, .33], vertical_alignment="bottom")

    with group_filter_column:
        table_groups_df = run_table_groups_lookup_query(project_code)
        target_table_group_id = testgen.select(
            options=table_groups_df,
            value_column="id",
            display_column="table_groups_name",
            default_value=origin_table_group["id"],
            required=True,
            label="Target Table Group",
        )

    with suite_filter_column:
        test_suites_df = run_test_suite_lookup_query(target_table_group_id)
        target_test_suite_id = testgen.select(
            options=test_suites_df,
            value_column="id",
            display_column="test_suite",
            default_value=None,
            required=True,
            label="Target Test Suite",
        )

    target_table_column = None
    if target_test_suite_id == origin_test_suite["id"]:
        with table_filter_column:
            columns_df = get_test_suite_columns(origin_test_suite["id"])
            table_name = testgen.select(
                options=list(columns_df["table_name"].unique()),
                value_column="table_name",
                default_value=None,
                required=True,
                label="Target Table Name",
            )
            column_options = list(columns_df.loc[columns_df["table_name"] == table_name]["column_name"].unique())
            column_name = testgen.select(
                options=column_options,
                default_value=None,
                required=True,
                label="Column Name",
                disabled=not table_name,
            )
        target_table_column = {
            "table_name": table_name,
            "column_name":column_name
        }

    movable_test_definitions = []
    if target_table_group_id and target_test_suite_id:
        collision_test_definitions = test_definition_service.get_test_definitions_collision(selected_test_definitions, target_table_group_id, target_test_suite_id)
        if not collision_test_definitions.empty:
            unlocked = collision_test_definitions[collision_test_definitions["lock_refresh"] == "N"]
            locked = collision_test_definitions[collision_test_definitions["lock_refresh"] == "Y"]
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

    if move:
        test_definition_service.move(movable_test_definitions, target_table_group_id, target_test_suite_id, target_table_column)
        success_message = "Test Definitions have been moved."
        st.success(success_message)
        time.sleep(1)
        st.rerun()
    elif copy:
        test_definition_service.copy(movable_test_definitions, target_table_group_id, target_test_suite_id, target_table_column)
        success_message = "Test Definitions have been copied."
        st.success(success_message)
        time.sleep(1)
        st.rerun()

def validate_form(test_scope, test_type, test_definition, column_name_label):
    if test_type == "Condition_Flag" and not test_definition["threshold_value"]:
        st.error("Threshold Error Count is a required field.")
        return False
    if not test_definition["test_type"]:
        st.error("Test Type is a required field.")
        return False
    if test_scope in ["column", "referential", "custom"] and not test_definition["column_name"]:
        st.error(f"{column_name_label} is a required field.")
        return False
    return True


def validate_test_definition_uniqueness(test_definition, test_scope):
    record_count = test_definition_service.check_test_definition_uniqueness(test_definition)
    if record_count > 0:
        match test_scope:
            case "column":
                message_bit = "and Column Name "
            case "referential":
                message_bit = "and Column Names "
            case "custom":
                message_bit = "and Test Focus "
            case "table":
                message_bit = ""
            case _:
                message_bit = ""

        return f"Validation error: the combination of Table Name, Test Type {message_bit}must be unique within a Test Suite"


def prompt_for_test_type():

    col0, col1, col2, col3, col4, col5 = st.columns([0.1, 0.2, 0.2, 0.2, 0.2, 0.1])
    col0.write("Show Types")
    boo_show_referential = col1.checkbox(":green[⧉] Referential", True)
    boo_show_table = col2.checkbox(":green[⊞] Table", True)
    boo_show_column = col3.checkbox(":green[≣] Column", True)
    boo_show_custom = col4.checkbox(":green[⛭] Custom", True)

    df = run_test_type_lookup_query(str_test_type=None, boo_show_referential=boo_show_referential,
                                    boo_show_table=boo_show_table, boo_show_column=boo_show_column,
                                    boo_show_custom=boo_show_custom)
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
    test_definition_service.update_attribute(test_definition_ids, attribute, value)
    st.success(message)
    return result


def show_test_defs_grid(
    str_project_code, str_test_suite, str_table_name, str_column_name, do_multi_select, export_container,
        str_table_groups_id
):
    with st.container():
        with st.spinner("Loading data ..."):
            df = test_definition_service.get_test_definitions(
                str_project_code, str_test_suite, str_table_name, str_column_name
            )
            date_service.accommodate_dataframe_to_timezone(df, st.session_state)

            for col in df.select_dtypes(include=["datetime"]).columns:
                df[col] = df[col].astype(str).replace("NaT", "")

    lst_show_columns = [
        "schema_name",
        "table_name",
        "column_name",
        "test_name_short",
        "test_active_display",
        "lock_refresh_display",
        "urgency",
        "export_to_observability",
        "profiling_as_of_date",
        "last_manual_update",
    ]
    show_column_headers = [
        "Schema",
        "Table",
        "Columns / Focus",
        "Test Name",
        "Active",
        "Locked",
        "Urgency",
        "Export to Observabilty",
        "Based on Profiling",
        "Last Manual Update",
    ]

    # show_column_headers = list(map(snake_case_to_title_case, show_column_headers))

    dct_selected_row = fm.render_grid_select(
        df,
        lst_show_columns,
        do_multi_select=do_multi_select,
        show_column_headers=show_column_headers,
        render_highlights=False,
        bind_to_query_name="selected",
        bind_to_query_prop="id",
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
            args=(str_project_code, str_test_suite, data),
        )

    with popover_container.container(key="tg--export-popover"):
        flex_row_end()
        with st.popover(label="Export", icon=":material/download:", help="Download test definitions to Excel"):
            css_class("tg--export-wrapper")
            st.button(label="All tests", type="tertiary", on_click=open_download_dialog)
            st.button(label="Filtered tests", type="tertiary", on_click=partial(open_download_dialog, df))
            if dct_selected_row:
                st.button(label="Selected tests", type="tertiary", on_click=partial(open_download_dialog, pd.DataFrame(dct_selected_row)))

    if dct_selected_row:
        st.html("</p>&nbsp;</br>")
        selected_row = dct_selected_row[0]
        str_test_id = selected_row["id"]
        row_selected = df[df["id"] == str_test_id].iloc[0]
        str_parm_columns = selected_row["default_parm_columns"]

        # Shared columns to show
        lst_show_columns = [
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

        # Test-specific columns to show
        additional_columns = [val.strip() for val in str_parm_columns.split(",")]
        lst_show_columns = lst_show_columns + additional_columns
        labels = labels + additional_columns

        labels = list(map(snake_case_to_title_case, labels))

        left_column, right_column = st.columns([0.5, 0.5])

        with left_column:
            fm.render_html_list(
                selected_row,
                lst_show_columns,
                "Test Definition Information",
                int_data_width=700,
                lst_labels=labels,
            )

        _, col_profile_button = right_column.columns([0.7, 0.3])
        if selected_row["test_scope"] == "column" and selected_row["profile_run_id"]:
            with col_profile_button:
                view_profiling_button(
                    selected_row["column_name"],
                    selected_row["table_name"],
                    str_table_groups_id,
                )

        with right_column:
            st.write(generate_test_defs_help(row_selected["test_type"]))

    return dct_selected_row


def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    project_code: str,
    test_suite: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is not None:
        data = data.copy()
    else:
        data = test_definition_service.get_test_definitions(project_code, test_suite)
        date_service.accommodate_dataframe_to_timezone(data, st.session_state)

    for key in ["test_active_display", "lock_refresh_display"]:
        data[key] = data[key].apply(lambda val: val if val == "Yes" else None)

    for key in ["profiling_as_of_date", "last_manual_update"]:
        data[key] = data[key].apply(
            lambda val: datetime.strptime(val, "%Y-%m-%d %H:%M:%S").strftime("%b %-d %Y, %-I:%M %p") if not pd.isna(val) else None
        )

    columns = {
        "schema_name": {"header": "Schema"},
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
        details={"Test suite": test_suite},
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
def run_test_type_lookup_query(str_test_type=None, boo_show_referential=True, boo_show_table=True,
                               boo_show_column=True, boo_show_custom=True):
    str_schema = st.session_state["dbschema"]
    return dq.run_test_type_lookup_query(str_schema, str_test_type, boo_show_referential, boo_show_table,
                                         boo_show_column, boo_show_custom)


@st.cache_data(show_spinner=False)
def run_table_groups_lookup_query(str_project_code, str_connection_id=None, table_group_id=None):
    str_schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(str_schema, str_project_code, str_connection_id, table_group_id)


@st.cache_data(show_spinner=False)
def get_test_suite_columns(test_suite_id: str) -> pd.DataFrame:
    schema: str = st.session_state["dbschema"]
    sql = f"""
    SELECT table_name, column_name
    FROM {schema}.test_definitions
    WHERE test_suite_id = '{test_suite_id}'
    ORDER BY table_name, column_name;
    """
    return db.retrieve_data(sql)


@st.cache_data(show_spinner=False)
def run_test_suite_lookup_query(str_table_groups_id, test_suite_name=None):
    str_schema = st.session_state["dbschema"]
    return dq.run_test_suite_lookup_by_tgroup_query(str_schema, str_table_groups_id, test_suite_name)


def get_column_names(table_groups_id: str, table_name: str) -> list:
    schema: str = st.session_state["dbschema"]
    sql = f"""
    SELECT column_name
    FROM {schema}.data_column_chars
    WHERE table_groups_id = '{table_groups_id}'::UUID
        AND table_name = '{table_name}'
        AND drop_date IS NULL
    ORDER BY column_name
    """
    df = db.retrieve_data(sql)
    return df["column_name"].tolist()
