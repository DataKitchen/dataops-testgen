import time
import typing

import streamlit as st

import testgen.ui.services.authentication_service as authentication_service
import testgen.ui.services.form_service as fm
import testgen.ui.services.test_suite_service as test_suite_service
import testgen.ui.services.toolbar_service as tb
from testgen.commands.run_execute_tests import run_execution_steps_in_background
from testgen.commands.run_generate_tests import run_test_gen_queries
from testgen.commands.run_observability_exporter import export_test_results
from testgen.ui.navigation.page import Page
from testgen.ui.services import connection_service, table_group_service
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.session import session


class TestSuitesPage(Page):
    path = "connections:test-suites"
    can_activate: typing.ClassVar = [
        lambda: authentication_service.current_user_has_admin_role() or "overview",
        lambda: session.authentication_status,
    ]

    def render(self, connection_id: str | None = None, table_group_id: str | None = None) -> None:
        fm.render_page_header(
            "Test Suites",
            "https://docs.datakitchen.io/article/dataops-testgen-help/create-a-test-suite",
            lst_breadcrumbs=[
                {"label": "Overview", "path": "overview"},
                {"label": "Connections", "path": "connections"},
                {"label": "Table Groups", "path": "connections:table-groups"},
                {"label": "Test Suites", "path": None},
            ],
        )

        # Get page parameters from session
        project_code = st.session_state["project"]
        connection = connection_service.get_by_id(connection_id) if connection_id else st.session_state["connection"]

        table_group = st.session_state.get("table_group")
        if table_group_id:
            table_group = table_group_service.get_by_id(table_group_id)
            table_group = table_group.iloc[0]

        connection_id = connection["connection_id"]
        table_group_id = table_group["id"]

        tool_bar = tb.ToolBar(2, 5, 0, None)

        with tool_bar.long_slots[0]:
            st.selectbox("Connection", [connection["connection_name"]], disabled=True)

        with tool_bar.long_slots[1]:
            st.selectbox("Table Group", [table_group["table_groups_name"]], disabled=True)

        df = test_suite_service.get_by_table_group(project_code, table_group_id)

        show_columns = [
            "test_suite",
            "test_suite_description",
            "severity",
            "export_to_observability",
            "component_key",
            "component_type",
            "component_name",
        ]

        selected = fm.render_grid_select(df, show_columns)

        if tool_bar.short_slots[1].button("➕ Add", help="Add a new Test Run", use_container_width=True):  # NOQA RUF001
            add_test_suite_dialog(project_code, connection, table_group)

        disable_buttons = selected is None
        if tool_bar.short_slots[2].button(
            "🖊️ Edit", help="Edit the selected Test Run", disabled=disable_buttons, use_container_width=True
        ):
            edit_test_suite_dialog(project_code, connection, table_group, selected)

        if tool_bar.short_slots[3].button(
            "❌ Delete", help="Delete the selected Test Run", disabled=disable_buttons, use_container_width=True
        ):
            delete_test_suite_dialog(selected)

        if tool_bar.short_slots[4].button(
            f":{'gray' if disable_buttons else 'green'}[Tests　→]",
            help="View and edit Test Definitions for selected Test Suite",
            disabled=disable_buttons,
            use_container_width=True,
        ):
            st.session_state["test_suite"] = selected[0]

            self.router.navigate(
                "connections:test-definitions",
                {
                    "connection_id": connection["connection_id"],
                    "table_group_id": table_group_id,
                    "test_suite_id": selected[0]["id"],
                },
            )

        if not selected:
            st.markdown(":orange[Select a row to see Test Suite details.]")
        else:
            show_record_detail(project_code, selected[0])


def show_record_detail(project_code, selected):
    left_column, right_column = st.columns([0.5, 0.5])

    with left_column:
        fm.render_html_list(
            selected,
            [
                "id",
                "project_code",
                "test_suite",
                "connection_id",
                "table_groups_id",
                "test_suite_description",
                "severity",
                "export_to_observability",
                "component_key",
                "component_name",
                "component_type",
            ],
            "Test Suite Information",
            int_data_width=700,
        )

    with right_column:
        # st.write("<br/><br/>", unsafe_allow_html=True)
        _, button_column = st.columns([0.2, 0.8])
        with button_column:
            run_now_commands_tab, cli_commands_tab = st.tabs(["Test Suite Actions", "View CLI Commands"])

            with cli_commands_tab:
                if st.button(
                    "Test Generation Command",
                    help="Shows the run-test-generation CLI command",
                    use_container_width=True,
                ):
                    generate_tests_cli_dialog(selected)

                if st.button(
                    "Test Execution Command",
                    help="Shows the run-tests CLI command",
                    use_container_width=True,
                ):
                    run_tests_cli_dialog(project_code, selected)

                if st.button(
                    "Observability Export Command",
                    help="Shows the export-observability CLI command",
                    use_container_width=True,
                ):
                    observability_export_cli_dialog(selected)

            with run_now_commands_tab:
                if st.button("Run Test Generation", help="Run Test Generation", use_container_width=True):
                    generate_tests_dialog(selected)

                if st.button("Run Test Execution", help="Run the tests", use_container_width=True):
                    run_tests_dialog(project_code, selected)

                if st.button(
                    "Run Observability Export",
                    help="Exports test results to Observability for the current Test Suite",
                    use_container_width=True,
                ):
                    observability_export_dialog(selected)


@st.dialog(title="Generate Tests")
def generate_tests_dialog(selected_test_suite):
    container = st.empty()
    with container:
        st.markdown(":green[**Execute Test Generation for the Test Suite**]")

    warning_container = st.container()
    options_container = st.container()
    button_container = st.empty()
    status_container = st.empty()

    test_ct, unlocked_test_ct, unlocked_edits_ct = test_suite_service.get_test_suite_refresh_warning(
        selected_test_suite["table_groups_id"], selected_test_suite["test_suite"]
    )
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
                    edits_locked = test_suite_service.lock_edited_tests(selected_test_suite["test_suite"])
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

    with button_container:
        start_process_button_message = "Start"
        test_generation_button = st.button(start_process_button_message)

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


@st.dialog(title="Delete Test Suite")
def delete_test_suite_dialog(selected):
    selected_test_suite = selected[0]
    test_suite_name = selected_test_suite["test_suite"]
    can_be_deleted = test_suite_service.cascade_delete([test_suite_name], dry_run=True)

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

    with st.form("Delete Test Suite", clear_on_submit=True):
        disable_delete_button = authentication_service.current_user_has_read_role() or (
            not can_be_deleted and not accept_cascade_delete
        )
        delete = st.form_submit_button("Delete", disabled=disable_delete_button, type="primary")

        if delete:
            if test_suite_service.are_test_suites_in_use([test_suite_name]):
                st.error("This Test Suite is in use by a running process and cannot be deleted.")
            else:
                test_suite_service.cascade_delete([test_suite_name])
                success_message = f"Test Suite {test_suite_name} has been deleted. "
                st.success(success_message)
                time.sleep(1)
                st.rerun()


def show_test_suite(mode, project_code, connection, table_group, selected=None):
    connection_id = connection["connection_id"]
    table_group_id = table_group["id"]
    severity_options = ["Inherit", "Failed", "Warning"]

    selected_test_suite = selected[0] if mode == "edit" else None

    if mode == "edit" and not selected_test_suite["severity"]:
        selected_test_suite["severity"] = severity_options[0]

    # establish default values
    test_suite_id = selected_test_suite["id"] if mode == "edit" else None
    test_suite = empty_if_null(selected_test_suite["test_suite"]) if mode == "edit" else ""
    connection_id = selected_test_suite["connection_id"] if mode == "edit" else connection_id
    table_groups_id = selected_test_suite["table_groups_id"] if mode == "edit" else table_group_id
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

    with st.form("Test Suite Add / Edit", clear_on_submit=True):
        entity = {
            "id": test_suite_id,
            "project_code": project_code,
            "test_suite": left_column.text_input(
                label="Test Suite Name", max_chars=40, value=test_suite, disabled=(mode != "add")
            ),
            "connection_id": connection_id,
            "table_groups_id": table_groups_id,
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

        submit_button_text = "Save" if mode == "edit" else "Add"
        submit = st.form_submit_button(
            submit_button_text, disabled=authentication_service.current_user_has_read_role()
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
                    test_suite_service.add(entity)
                success_message = (
                    "Changes have been saved successfully. "
                    if mode == "edit"
                    else "New TestSuite added successfully. "
                )
                st.success(success_message)
                time.sleep(1)
                st.rerun()


@st.dialog(title="Add Test Suite")
def add_test_suite_dialog(project_code, connection, table_group):
    show_test_suite("add", project_code, connection, table_group)


@st.dialog(title="Edit Test Suite")
def edit_test_suite_dialog(project_code, connection, table_group, selected):
    show_test_suite("edit", project_code, connection, table_group, selected)


@st.dialog(title="Run Tests")
def run_tests_dialog(project_code, selected_test_suite):
    container = st.empty()
    with container:
        st.markdown(":green[**Run Tests for the Test Suite**]")

    button_container = st.empty()
    status_container = st.empty()

    with button_container:
        start_process_button_message = "Start"
        run_test_button = st.button(start_process_button_message)

    if run_test_button:
        button_container.empty()

        test_suite_key = selected_test_suite["test_suite"]
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


@st.dialog(title="Run Tests CLI Command")
def run_tests_cli_dialog(project_code, selected_test_suite):
    test_suite_name = selected_test_suite["test_suite"]
    command = f"testgen run-tests --project-key {project_code} --test-suite-key {test_suite_name}"
    st.code(command, language="shellSession")


@st.dialog(title="Generate Tests CLI Command")
def generate_tests_cli_dialog(selected_test_suite):
    test_suite_key = selected_test_suite["test_suite"]
    table_group_id = selected_test_suite["table_groups_id"]
    command = f"testgen run-test-generation --table-group-id {table_group_id} --test-suite-key {test_suite_key}"
    st.code(command, language="shellSession")


@st.dialog(title="Observability Export CLI Command")
def observability_export_cli_dialog(selected_test_suite):
    test_suite_key = selected_test_suite["test_suite"]
    project_key = selected_test_suite["project_code"]
    command = f"testgen export-observability --project-key {project_key} --test-suite-key {test_suite_key}"
    st.code(command, language="shellSession")


@st.dialog(title="Export to Observability")
def observability_export_dialog(selected_test_suite):
    container = st.empty()
    with container:
        st.markdown(":green[**Execute the test export for the current Test Suite**]")

    button_container = st.empty()
    status_container = st.empty()

    with button_container:
        start_process_button_message = "Start"
        test_generation_button = st.button(start_process_button_message)

    if test_generation_button:
        button_container.empty()

        test_suite_key = selected_test_suite["test_suite"]
        project_key = selected_test_suite["project_code"]
        status_container.info("Executing Export ...")

        try:
            qty_of_exported_events = export_test_results(project_key, test_suite_key)
            status_container.empty()
            status_container.success(
                f"Process has successfully finished, {qty_of_exported_events} events have been exported."
            )
        except Exception as e:
            status_container.empty()
            status_container.error(f"Process has finished with errors: {e!s}.")
