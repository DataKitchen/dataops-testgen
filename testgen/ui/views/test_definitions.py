import logging
import time
import typing

import streamlit as st
from streamlit_extras.no_default_selectbox import selectbox

import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
import testgen.ui.services.table_group_service as table_group_service
import testgen.ui.services.test_definition_service as test_definition_service
import testgen.ui.services.test_suite_service as test_suite_service
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.services import authentication_service, project_service
from testgen.ui.services.string_service import empty_if_null, snake_case_to_title_case
from testgen.ui.session import session
from testgen.ui.views.profiling_modal import view_profiling_button

LOG = logging.getLogger("testgen")


class TestDefinitionsPage(Page):
    path = "test-suites:definitions"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: "test_suite_id" in session.current_page_args or "test-suites",
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
        project_service.set_current_project(project_code)
        user_can_edit = authentication_service.current_user_has_edit_role()

        testgen.page_header(
            "Test Definitions",
            "https://docs.datakitchen.io/article/dataops-testgen-help/testgen-test-types",
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
            table_options = run_table_lookup_query(table_group["id"])
            table_name = testgen.toolbar_select(
                options=table_options,
                value_column="table_name",
                default_value=table_name,
                bind_to_query="table_name",
                required=True,
                label="Table Name",
            )
        with column_filter_column:
            column_options = get_column_names(table_group["id"], table_name)
            column_name = testgen.toolbar_select(
                options=column_options,
                default_value=column_name,
                bind_to_query="column_name",
                label="Column Name",
                disabled=not table_name,
            )

        with disposition_column:
            str_help = "Toggle on to perform actions on multiple test definitions"
            do_multi_select = st.toggle("Multi-Select", help=str_help)

        if user_can_edit and actions_column.button(
            ":material/add: Add", help="Add a new Test Definition"
        ):
            add_test_dialog(project_code, table_group, test_suite, table_name, column_name)

        selected = show_test_defs_grid(
            session.project, test_suite["test_suite"], table_name, column_name, do_multi_select, table_actions_column,
            table_group["id"]
        )
        fm.render_refresh_button(table_actions_column)

        disposition_actions = [
            { "icon": "✓", "help": "Activate for future runs", "attribute": "test_active", "value": True, "message": "Activated" },
            { "icon": "✘", "help": "Inactivate Test for future runs", "attribute": "test_active", "value": False, "message": "Inactivated" },
            { "icon": "🔒", "help": "Protect from future test generation", "attribute": "lock_refresh", "value": True, "message": "Locked" },
            { "icon": "🔐", "help": "Unlock for future test generation", "attribute": "lock_refresh", "value": False, "message": "Unlocked" },
        ]

        for action in disposition_actions:
            action["button"] = disposition_column.button(action["icon"], help=action["help"], disabled=not selected)

        # This has to be done as a second loop - otherwise, the rest of the buttons after the clicked one are not displayed briefly while refreshing
        for action in disposition_actions:
            if action["button"]:
                fm.reset_post_updates(
                    update_test_definition(selected, action["attribute"], action["value"], action["message"]),
                    as_toast=True,
                    clear_cache=True,
                    lst_cached_functions=[],
                )

        if selected:
            selected_test_def = selected[0]

        if user_can_edit and actions_column.button(
            ":material/edit: Edit",
            help="Edit the Test Definition",
            disabled=not selected,
        ):
            edit_test_dialog(project_code, table_group, test_suite, table_name, column_name, selected_test_def)

        if user_can_edit and actions_column.button(
            ":material/delete: Delete",
            help="Delete the selected Test Definition",
            disabled=not selected,
        ):
            delete_test_dialog(selected_test_def)          


@st.dialog("Delete Test")
def delete_test_dialog(selected_test_definition):
    test_definition_id = selected_test_definition["id"]
    test_name_short = selected_test_definition["test_name_short"]

    can_be_deleted = test_definition_service.delete([test_definition_id], dry_run=True)

    fm.render_html_list(
        selected_test_definition,
        [
            "id",
            "project_code",
            "schema_name",
            "table_name",
            "column_name",
            "test_name_short",
            "table_groups_id",
            "test_suite",
            "test_active_display",
            "test_description",
            "last_manual_update",
        ],
        "Test Definition Information",
        int_data_width=700,
    )

    with st.form("Delete Test Definition", clear_on_submit=True):
        disable_delete_button = authentication_service.current_user_has_read_role() or not can_be_deleted
        delete = st.form_submit_button("Delete", disabled=disable_delete_button, type="primary")

        if delete:
            test_definition_service.delete([test_definition_id])
            success_message = f"Test Definition {test_name_short} has been deleted. "
            st.success(success_message)
            time.sleep(1)
            st.rerun()

    if not can_be_deleted:
        st.markdown(":orange[This Test Definition cannot be deleted because it is being used in existing tests.]")


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
        st.markdown(
            f"""
                <div style="border: 1px solid #e6e6e6; border-radius: 5px; padding: 10px;">
                    {selected_test_type_row['test_description']}
                </div><br/>
                """,
            unsafe_allow_html=True,
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
            height=3,
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
        "schema_name": right_column.text_input(
            label="Schema Name", max_chars=100, value=schema_name, disabled=True
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

    st.divider()

    # table_name
    test_definition["table_name"] = st.text_input(
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
        test_definition["column_name"] = st.text_input(
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

        test_definition["column_name"] = st.text_input(
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

    st.divider()

    # dynamic attributes
    mid_left_column, mid_right_column = st.columns([0.5, 0.5])

    current_column = mid_left_column
    show_custom_query = False
    dynamic_attributes_length = len(dynamic_attributes)
    dynamic_attributes_half_length = max(round((dynamic_attributes_length + 0.5) / 2), 1)
    for i, dynamic_attribute in enumerate(dynamic_attributes):
        if i >= dynamic_attributes_half_length:
            current_column = mid_right_column

        default_value = "" if dynamic_attribute != "threshold_value" else 0
        value = empty_if_null(selected_test_def[dynamic_attribute]) if mode == "edit" else default_value

        actual_dynamic_attributes_labels = (
            dynamic_attributes_labels[i]
            if dynamic_attributes_labels and len(dynamic_attributes_labels) > i
            else "Help text is not available."
        )

        actual_dynamic_attributes_help = (
            dynamic_attributes_help[i]
            if dynamic_attributes_help and len(dynamic_attributes_help) > i
            else snake_case_to_title_case(dynamic_attribute)
        )

        if dynamic_attribute in ["custom_query"]:
            show_custom_query = True
        else:
            test_definition[dynamic_attribute] = current_column.text_input(
                label=actual_dynamic_attributes_labels,
                max_chars=4000 if dynamic_attribute in ["match_column_names", "match_groupby_names", "groupby_names"] else 1000,
                value=value,
                help=actual_dynamic_attributes_help,
            )

    # Custom Query
    if show_custom_query:
        if test_type == "Condition_Flag":
            custom_query_default = "EXAMPLE:  status = 'SHIPPED' and qty_shipped = 0"
            custom_query_height = 75
        elif test_type == "CUSTOM":
            custom_query_default = "EXAMPLE:  SELECT product, SUM(qty_sold) as sum_sold, SUM(qty_shipped) as qty_shipped \n FROM {DATA_SCHEMA}.sales_history \n GROUP BY product \n HAVING SUM(qty_shipped) > SUM(qty_sold)"
            custom_query_height = 150
        else:
            custom_query_default = None
            custom_query_height = 75
        test_definition["custom_query"] = st.text_area(
            label=actual_dynamic_attributes_labels,
            value=custom_query,
            placeholder=custom_query_default,
            height=custom_query_height,
            help=actual_dynamic_attributes_help,
        )

    # skip_errors
    if run_type == "QUERY":
        test_definition["skip_errors"] = left_column.number_input(label="Threshold Error Count", value=skip_errors)
    else:
        test_definition["skip_errors"] = skip_errors

    # submit logic
    bottom_left_column, bottom_right_column = st.columns([0.5, 0.5])

    # Add Validate button
    if test_type in ("Condition_Flag", "CUSTOM"):
        validate = bottom_left_column.button(
            "Validate", disabled=authentication_service.current_user_has_read_role()
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

    submit = bottom_left_column.button("Save", disabled=authentication_service.current_user_has_read_role())

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
    )

    with export_container:
        lst_export_columns = [
            "schema_name",
            "table_name",
            "column_name",
            "test_name_short",
            "final_test_description",
            "threshold_value",
            "export_uom",
            "test_active_display",
            "lock_refresh_display",
            "urgency",
            "profiling_as_of_date",
            "last_manual_update",
        ]
        lst_wrap_columns = ["final_test_description"]
        lst_export_headers = [
            "Schema",
            "Table Name",
            "Column/Test Focus",
            "Test Type",
            "Description",
            "Test Threshold",
            "Unit of Measure",
            "Active",
            "Locked",
            "Urgency",
            "From Profiling As-Of",
            "Last Manual Update",
        ]
        fm.render_excel_export(
            df,
            lst_export_columns,
            f"Test Definitions for Test Suite {str_test_suite}",
            "{TIMESTAMP}",
            lst_wrap_columns,
            lst_export_headers,
        )

    if dct_selected_row:
        st.markdown("</p>&nbsp;</br>", unsafe_allow_html=True)
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
        if selected_row["test_scope"] == "column":
            view_profiling_button(
                col_profile_button, selected_row["table_name"], selected_row["column_name"],
                str_table_groups_id=str_table_groups_id
            )

        with right_column:
            st.write(generate_test_defs_help(row_selected["test_type"]))

    return dct_selected_row


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
def run_table_lookup_query(str_table_groups_id):
    str_schema = st.session_state["dbschema"]
    return dq.run_table_lookup_query(str_schema, str_table_groups_id)


@st.cache_data(show_spinner=False)
def run_column_lookup_query(str_table_groups_id, str_table_name):
    str_schema = st.session_state["dbschema"]
    return dq.run_column_lookup_query(str_schema, str_table_groups_id, str_table_name)


@st.cache_data(show_spinner=False)
def run_test_suite_lookup_query(str_table_groups_id, test_suite_name=None):
    str_schema = st.session_state["dbschema"]
    return dq.run_test_suite_lookup_by_tgroup_query(str_schema, str_table_groups_id, test_suite_name)


def get_column_names(str_table_groups_id, str_table_name):
    df = run_column_lookup_query(str_table_groups_id, str_table_name)
    lst_choices = df["column_name"].tolist()
    return lst_choices
