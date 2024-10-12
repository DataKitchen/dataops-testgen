import time
import typing
from functools import partial

import pandas as pd
import streamlit as st

import testgen.ui.services.authentication_service as authentication_service
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
import testgen.ui.services.test_suite_service as test_suite_service
from testgen.commands.run_execute_tests import run_execution_steps_in_background
from testgen.commands.run_generate_tests import run_test_gen_queries
from testgen.commands.run_observability_exporter import export_test_results
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.session import session
from testgen.utils import to_int


class TestSuitesPage(Page):
    path = "test-suites"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="list_alt", label="Test Suites", order=3)

    def render(self, project_code: str | None = None, table_group_id: str | None = None, **_kwargs) -> None:
        project_code = st.session_state["project"]

        testgen.page_header(
            "Test Suites",
            "https://docs.datakitchen.io/article/dataops-testgen-help/create-a-test-suite",
        )

        group_filter_column, actions_column = st.columns([.2, .8], vertical_alignment="bottom")
        testgen.flex_row_end(actions_column)

        with group_filter_column:
            df_tg = get_db_table_group_choices(project_code)
            table_group_id = testgen.toolbar_select(
                options=df_tg,
                value_column="id",
                display_column="table_groups_name",
                default_value=table_group_id,
                label="Table Group",
                bind_to_query="table_group_id",
            )

        df = test_suite_service.get_by_project(project_code, table_group_id)
        user_can_edit = authentication_service.current_user_has_edit_role()

        if user_can_edit:
            with actions_column:
                st.button(
                    ":material/add: Add Test Suite",
                    key="test_suite:keys:add",
                    help="Add a new test suite",
                    on_click=lambda: add_test_suite_dialog(project_code, df_tg),
                )

        for _, test_suite in df.iterrows():
            subtitle = f"{test_suite['connection_name']} > {test_suite['table_groups_name']}"
            with testgen.card(title=test_suite["test_suite"], subtitle=subtitle) as test_suite_card:
                if user_can_edit:
                    with test_suite_card.actions:
                        testgen.button(
                            type_="icon",
                            icon="output",
                            tooltip="Export results to Observability",
                            tooltip_position="right",
                            on_click=partial(observability_export_dialog, test_suite),
                            key=f"test_suite:keys:export:{test_suite['id']}",
                        )
                        testgen.button(
                            type_="icon",
                            icon="edit",
                            tooltip="Edit test suite",
                            tooltip_position="right",
                            on_click=partial(edit_test_suite_dialog, project_code, df_tg, test_suite),
                            key=f"test_suite:keys:edit:{test_suite['id']}",
                        )
                        testgen.button(
                            type_="icon",
                            icon="delete",
                            tooltip="Delete test suite",
                            tooltip_position="right",
                            on_click=partial(delete_test_suite_dialog, test_suite),
                            key=f"test_suite:keys:delete:{test_suite['id']}",
                        )

                main_section, latest_run_section, actions_section = st.columns([.4, .4, .2])

                with main_section:
                    testgen.no_flex_gap()
                    testgen.link(
                        label=f"{to_int(test_suite['last_run_test_ct'])} tests definitions",
                        href="test-suites:definitions",
                        params={ "test_suite_id": test_suite["id"] },
                        right_icon="chevron_right",
                        key=f"test_suite:keys:go-to-definitions:{test_suite['id']}",
                    )

                    testgen.caption("Description")
                    st.markdown(test_suite["test_suite_description"] or "--")

                with latest_run_section:
                    testgen.no_flex_gap()
                    st.caption("Latest Run")

                    if (latest_run_start := test_suite["latest_run_start"]) and pd.notnull(latest_run_start):
                        testgen.link(
                            label=date_service.get_timezoned_timestamp(st.session_state, latest_run_start),
                            href="test-runs:results",
                            params={ "run_id": str(test_suite["latest_run_id"]) },
                            style="margin-bottom: 8px;",
                            height=29,
                            key=f"test_suite:keys:go-to-runs:{test_suite['id']}",
                        )
                        if to_int(test_suite["last_run_test_ct"]):
                            testgen.summary_bar(
                                items=[
                                    { "label": "Passed", "value": to_int(test_suite["last_run_passed_ct"]), "color": "green" },
                                    { "label": "Warning", "value": to_int(test_suite["last_run_warning_ct"]), "color": "yellow" },
                                    { "label": "Failed", "value": to_int(test_suite["last_run_failed_ct"]), "color": "red" },
                                    { "label": "Error", "value": to_int(test_suite["last_run_error_ct"]), "color": "brown" },
                                    { "label": "Dismissed", "value": to_int(test_suite["last_run_dismissed_ct"]), "color": "grey" },
                                ],
                                height=20,
                                width=350,
                            )
                    else:
                        st.markdown("--")

                if user_can_edit:
                    with actions_section:
                        testgen.button(
                            type_="stroked",
                            label="Run Tests",
                            on_click=partial(run_tests_dialog, project_code, test_suite),
                            key=f"test_suite:keys:runtests:{test_suite['id']}",
                        )
                        testgen.button(
                            type_="stroked",
                            label="Generate Tests",
                            on_click=partial(generate_tests_dialog, test_suite),
                            key=f"test_suite:keys:generatetests:{test_suite['id']}",
                        )


@st.cache_data(show_spinner=False)
def get_db_table_group_choices(project_code):
    schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(schema, project_code)


@st.dialog(title="Add Test Suite")
def add_test_suite_dialog(project_code, table_groups_df):
    show_test_suite("add", project_code, table_groups_df)


@st.dialog(title="Edit Test Suite")
def edit_test_suite_dialog(project_code, table_groups_df, selected):
    show_test_suite("edit", project_code, table_groups_df, selected)


def show_test_suite(mode, project_code, table_groups_df, selected=None):
    severity_options = ["Inherit", "Failed", "Warning"]
    selected_test_suite = selected if mode == "edit" else None

    if mode == "edit" and not selected_test_suite["severity"]:
        selected_test_suite["severity"] = severity_options[0]

    # establish default values
    test_suite_id = selected_test_suite["id"] if mode == "edit" else None
    test_suite = empty_if_null(selected_test_suite["test_suite"]) if mode == "edit" else ""
    connection_id = selected_test_suite["connection_id"] if mode == "edit" else None
    table_groups_id = selected_test_suite["table_groups_id"] if mode == "edit" else None
    test_suite_description = empty_if_null(selected_test_suite["test_suite_description"]) if mode == "edit" else ""
    test_action = empty_if_null(selected_test_suite["test_action"]) if mode == "edit" else ""
    severity_index = severity_options.index(selected_test_suite["severity"]) if mode == "edit" else 0
    export_to_observability = selected_test_suite["export_to_observability"] == "Y" if mode == "edit" else False
    test_suite_schema = empty_if_null(selected_test_suite["test_suite_schema"]) if mode == "edit" else ""
    component_key = empty_if_null(selected_test_suite["component_key"]) if mode == "edit" else ""
    component_type = empty_if_null(selected_test_suite["component_type"]) if mode == "edit" else "dataset"
    component_name = empty_if_null(selected_test_suite["component_name"]) if mode == "edit" else ""

    left_column, right_column = st.columns([0.50, 0.50])
    expander = st.expander("", expanded=True)
    with expander:
        expander_left_column, expander_right_column = st.columns([0.50, 0.50])

    with st.form("Test Suite Add / Edit", clear_on_submit=True, border=False):
        entity = {
            "id": test_suite_id,
            "project_code": project_code,
            "test_suite": left_column.text_input(
                label="Test Suite Name", max_chars=40, value=test_suite, disabled=(mode != "add")
            ),
            "connection_id": connection_id,
            "table_groups_id": table_groups_id,
            "table_groups_name": right_column.selectbox(
                label="Table Group",
                options=table_groups_df["table_groups_name"],
                index=int(table_groups_df[table_groups_df["id"] == table_groups_id].index[0]) if table_groups_id else 0,
                disabled=(mode != "add"),
            ),
            "test_suite_description": left_column.text_input(
                label="Test Suite Description", max_chars=40, value=test_suite_description
            ),
            "test_action": test_action,
            "severity": right_column.selectbox(
                label="Severity",
                options=severity_options,
                index=severity_index,
                help="Overrides the default severity in 'Test Definition' and/or 'Test Run'.",
            ),
            "test_suite_schema": test_suite_schema,
            "export_to_observability": left_column.toggle(
                "Export to Observability",
                value=export_to_observability,
                help="Fields below are only required when overriding the Table Group defaults.",
            ),
            "component_key": expander_left_column.text_input(
                label="Component Key",
                max_chars=40,
                value=component_key,
                placeholder="Optional Field",
                help="Overrides the default component key mapping, which is set at Table Group level.",
            ),
            "component_type": expander_right_column.text_input(
                label="Component Type", max_chars=40, value=component_type, disabled=True
            ),
            "component_name": expander_left_column.text_input(
                label="Component Name",
                max_chars=40,
                value=component_name,
                placeholder="Optional Field",
                help="Overrides the default component name mapping, which is set at the Table Group level.",
            ),
        }

        _, button_column = st.columns([.85, .15])
        with button_column:
            submit = st.form_submit_button(
                "Save" if mode == "edit" else "Add",
                use_container_width=True,
                disabled=authentication_service.current_user_has_read_role(),
            )

        if submit:
            if " " in entity["test_suite"]:
                proposed_test_suite = entity["test_suite"].replace(" ", "-")
                st.error(
                    f"Blank spaces not allowed in field 'Test Suite Name'. Use dash or underscore instead. i.e.: {proposed_test_suite}"
                )
            else:
                if mode == "edit":
                    test_suite_service.edit(entity)
                else:
                    selected_table_group_name = entity["table_groups_name"]
                    selected_table_group = table_groups_df[table_groups_df["table_groups_name"] == selected_table_group_name].iloc[0]
                    entity["connection_id"] = selected_table_group["connection_id"]
                    entity["table_groups_id"] = selected_table_group["id"]
                    test_suite_service.add(entity)
                success_message = (
                    "Changes have been saved successfully. "
                    if mode == "edit"
                    else "New TestSuite added successfully. "
                )
                st.success(success_message)
                time.sleep(1)
                st.rerun()


@st.dialog(title="Delete Test Suite")
def delete_test_suite_dialog(selected_test_suite):
    test_suite_id = selected_test_suite["id"]
    test_suite_name = selected_test_suite["test_suite"]
    can_be_deleted = test_suite_service.cascade_delete([test_suite_id], dry_run=True)

    fm.render_html_list(
        selected_test_suite,
        [
            "id",
            "test_suite",
            "test_suite_description",
        ],
        "Test Suite Information",
        int_data_width=700,
    )

    if not can_be_deleted:
        st.markdown(
            ":orange[This Test Suite has related data, which includes test definitions and may include test results. If you proceed, all related data will be permanently deleted.<br/>Are you sure you want to proceed?]",
            unsafe_allow_html=True,
        )
        accept_cascade_delete = st.toggle("I accept deletion of this Test Suite and all related TestGen data.")

    with st.form("Delete Test Suite", clear_on_submit=True, border=False):
        disable_delete_button = authentication_service.current_user_has_read_role() or (
            not can_be_deleted and not accept_cascade_delete
        )

        delete = False
        _, button_column = st.columns([.85, .15])
        with button_column:
            delete = st.form_submit_button(
                "Delete",
                type="primary",
                disabled=disable_delete_button,
                use_container_width=True,
            )

        if delete:
            if test_suite_service.are_test_suites_in_use([test_suite_id]):
                st.error("This Test Suite is in use by a running process and cannot be deleted.")
            else:
                test_suite_service.cascade_delete([test_suite_id])
                success_message = f"Test Suite {test_suite_name} has been deleted. "
                st.success(success_message)
                time.sleep(1)
                st.rerun()


@st.dialog(title="Run Tests")
def run_tests_dialog(project_code, selected_test_suite):
    test_suite_key = selected_test_suite["test_suite"]
    start_process_button_message = "Start"

    with st.container():
        st.markdown(f"Run tests for the test suite :green[{test_suite_key}]?")

    if testgen.expander_toggle(expand_label="Show CLI command", key="test_suite:keys:run-tests-show-cli"):
        st.code(
            f"testgen run-tests --project-key {project_code} --test-suite-key {selected_test_suite['test_suite']}",
            language="shellSession"
        )

    button_container = st.empty()
    status_container = st.empty()

    run_test_button = None
    with button_container:
        _, button_column = st.columns([.85, .15])
        with button_column:
            run_test_button = st.button(start_process_button_message, use_container_width=True)

    if run_test_button:
        button_container.empty()

        status_container.info(f"Running tests for test suite {test_suite_key}")

        try:
            run_execution_steps_in_background(project_code, test_suite_key)
        except Exception as e:
            status_container.empty()
            status_container.error(f"Process started with errors: {e!s}.")

        status_container.empty()
        status_container.success(
            "Process has successfully started. Check details in menu item 'Data Quality Testing'."
        )


@st.dialog(title="Generate Tests")
def generate_tests_dialog(selected_test_suite):
    test_suite_id = selected_test_suite["id"]
    test_suite_key = selected_test_suite["test_suite"]
    table_group_id = selected_test_suite["table_groups_id"]
    start_process_button_message = "Start"

    with st.container():
        st.markdown(f"Execute the test generation for test suite :green[{test_suite_key}]?")

    warning_container = st.container()
    options_container = st.container()

    if testgen.expander_toggle(expand_label="Show CLI command", key="test_suite:keys:generate-tests-show-cli"):
        st.code(
            f"testgen run-test-generation --table-group-id {table_group_id} --test-suite-key {test_suite_key}",
            language="shellSession",
        )

    button_container = st.empty()
    status_container = st.empty()

    test_ct, unlocked_test_ct, unlocked_edits_ct = test_suite_service.get_test_suite_refresh_warning(test_suite_id)
    if test_ct:
        warning_msg = ""
        counts_msg = f"\n\nAuto-Generated Tests: {test_ct}, Unlocked: {unlocked_test_ct}, Edited Unlocked: {unlocked_edits_ct}"
        if unlocked_edits_ct > 0:
            if unlocked_edits_ct > 1:

                warning_msg = "Manual changes have been made to auto-generated tests in this Test Suite that have not been locked. "
            else:
                warning_msg = "A manual change has been made to an auto-generated test in this Test Suite that has not been locked. "
        elif unlocked_test_ct > 0:
            warning_msg = "Auto-generated tests are present in this Test Suite that have not been locked. "
        warning_msg = f"{warning_msg}Generating tests now will overwrite unlocked tests subject to auto-generation based on the latest profiling.{counts_msg}"
        with warning_container:
            st.warning(warning_msg)
            if unlocked_edits_ct > 0:
                lock_edits_button = st.button("Lock Edited Tests")
                if lock_edits_button:
                    edits_locked = test_suite_service.lock_edited_tests(test_suite_id)
                    if edits_locked:
                        st.info("Edited tests have been successfully locked.")

    with options_container:
        lst_generation_sets = test_suite_service.get_generation_set_choices()
        if lst_generation_sets:
            lst_generation_sets.insert(0, "(All Test Types)")
            str_generation_set = st.selectbox("Generation Set", lst_generation_sets)
            if str_generation_set == "(All Test Types)":
                str_generation_set = ""
        else:
            str_generation_set = ""

    test_generation_button = None
    with button_container:
        _, button_column = st.columns([.85, .15])
        with button_column:
            test_generation_button = st.button(start_process_button_message, use_container_width=True)

    if test_generation_button:
        button_container.empty()

        table_group_id = selected_test_suite["table_groups_id"]
        test_suite_key = selected_test_suite["test_suite"]
        status_container.info("Executing Test Generation...")

        try:
            run_test_gen_queries(table_group_id, test_suite_key, str_generation_set)
        except Exception as e:
            status_container.empty()
            status_container.error(f"Process had errors: {e!s}.")

        status_container.empty()
        status_container.success("Process has successfully finished.")


@st.dialog(title="Export to Observability")
def observability_export_dialog(selected_test_suite):
    project_key = selected_test_suite["project_code"]
    test_suite_key = selected_test_suite["test_suite"]
    start_process_button_message = "Start"

    with st.container():
        st.markdown(f"Execute the test export for test suite :green[{test_suite_key}]?")

    if testgen.expander_toggle(expand_label="Show CLI command", key="test_suite:keys:export-tests-show-cli"):
        st.code(
            f"testgen export-observability --project-key {project_key} --test-suite-key {test_suite_key}",
            language="shellSession"
        )

    button_container = st.empty()
    status_container = st.empty()

    test_generation_button = None
    with button_container:
        _, button_column = st.columns([.85, .15])
        with button_column:
            test_generation_button = st.button(start_process_button_message, use_container_width=True)

    if test_generation_button:
        button_container.empty()

        status_container.info("Executing Export ...")

        try:
            qty_of_exported_events = export_test_results(selected_test_suite["id"])
            status_container.empty()
            status_container.success(
                f"Process has successfully finished, {qty_of_exported_events} events have been exported."
            )
        except Exception as e:
            status_container.empty()
            status_container.error(f"Process has finished with errors: {e!s}.")
