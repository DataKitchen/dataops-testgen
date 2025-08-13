import time
import typing
from collections.abc import Iterable
from functools import partial

import streamlit as st

from testgen.commands.run_observability_exporter import export_test_results
from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services import user_session_service
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.session import session
from testgen.ui.views.dialogs.generate_tests_dialog import generate_tests_dialog
from testgen.ui.views.dialogs.run_tests_dialog import run_tests_dialog
from testgen.ui.views.test_runs import TestRunScheduleDialog
from testgen.utils import to_dataframe

PAGE_ICON = "rule"
PAGE_TITLE = "Test Suites"

class TestSuitesPage(Page):
    path = "test-suites"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=1,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str, table_group_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "create-a-test-suite",
        )

        table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
        user_can_edit = user_session_service.user_can_edit()
        test_suites = TestSuite.select_summary(project_code, table_group_id)
        project_summary = Project.get_summary(project_code)
        
        testgen.testgen_component(
            "test_suites",
            props={
                "project_summary": project_summary.to_dict(json_safe=True),
                "test_suites": [test_suite.to_dict(json_safe=True) for test_suite in test_suites],
                "table_group_filter_options": [
                    {
                        "value": str(table_group.id),
                        "label": table_group.table_groups_name,
                        "selected": str(table_group_id) == str(table_group.id),
                    } for table_group in table_groups
                ],
                "permissions": {
                    "can_edit": user_can_edit,
                }
            },
            on_change_handlers={
                "FilterApplied": on_test_suites_filtered,
                "RunSchedulesClicked": lambda *_: TestRunScheduleDialog().open(project_code),
                "AddTestSuiteClicked": lambda *_: add_test_suite_dialog(project_code, table_groups),
                "ExportActionClicked": observability_export_dialog,
                "EditActionClicked": partial(edit_test_suite_dialog, project_code, table_groups),
                "DeleteActionClicked": delete_test_suite_dialog,
                "RunTestsClicked": lambda test_suite_id: run_tests_dialog(project_code, TestSuite.get_minimal(test_suite_id)),
                "GenerateTestsClicked": lambda test_suite_id: generate_tests_dialog(TestSuite.get_minimal(test_suite_id)),
            },
        )


def on_test_suites_filtered(table_group_id: str | None = None) -> None:
    Router().set_query_params({ "table_group_id": table_group_id })


@st.dialog(title="Add Test Suite")
@with_database_session
def add_test_suite_dialog(project_code, table_groups):
    show_test_suite("add", project_code, table_groups)


@st.dialog(title="Edit Test Suite")
@with_database_session
def edit_test_suite_dialog(project_code, table_groups, test_suite_id: str) -> None:
    selected = TestSuite.get(test_suite_id)
    show_test_suite("edit", project_code, table_groups, selected)


def show_test_suite(mode, project_code, table_groups: Iterable[TableGroupMinimal], selected: TestSuite | None = None):
    severity_options = ["Inherit", "Failed", "Warning"]
    selected_test_suite = selected if mode == "edit" else None
    table_groups_df = to_dataframe(table_groups, TableGroupMinimal.columns())

    # establish default values
    test_suite_id = selected_test_suite.id if mode == "edit" else None
    test_suite_name = empty_if_null(selected_test_suite.test_suite) if mode == "edit" else ""
    connection_id = selected_test_suite.connection_id if mode == "edit" else None
    table_groups_id = selected_test_suite.table_groups_id if mode == "edit" else None
    test_suite_description = empty_if_null(selected_test_suite.test_suite_description) if mode == "edit" else ""
    test_action = empty_if_null(selected_test_suite.test_action) if mode == "edit" else ""
    try:
        severity_index = severity_options.index(selected_test_suite.severity) if mode == "edit" else 0
    except ValueError:
        severity_index = 0
    export_to_observability = selected_test_suite.export_to_observability if mode == "edit" else False
    dq_score_exclude = selected_test_suite.dq_score_exclude if mode == "edit" else False
    test_suite_schema = empty_if_null(selected_test_suite.test_suite_schema) if mode == "edit" else ""
    component_key = empty_if_null(selected_test_suite.component_key) if mode == "edit" else ""
    component_type = empty_if_null(selected_test_suite.component_type) if mode == "edit" else "dataset"
    component_name = empty_if_null(selected_test_suite.component_name) if mode == "edit" else ""

    left_column, right_column = st.columns([0.50, 0.50])
    expander = st.expander("", expanded=True)
    with expander:
        expander_left_column, expander_right_column = st.columns([0.50, 0.50])

    with st.form("Test Suite Add / Edit", clear_on_submit=True, border=False):
        entity = {
            "id": test_suite_id,
            "project_code": project_code,
            "test_suite": left_column.text_input(
                label="Test Suite Name", max_chars=40, value=test_suite_name, disabled=(mode != "add")
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
            "export_to_observability": left_column.checkbox(
                "Export to Observability",
                value=export_to_observability,
                help="Fields below are only required when overriding the Table Group defaults.",
            ),
            "dq_score_exclude": right_column.checkbox(
                "Exclude from quality scoring",
                value=dq_score_exclude,
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
            )

        if submit:
            if " " in entity["test_suite"]:
                proposed_test_suite = entity["test_suite"].replace(" ", "-")
                st.error(
                    f"Blank spaces not allowed in field 'Test Suite Name'. Use dash or underscore instead. i.e.: {proposed_test_suite}"
                )
            else:
                test_suite = selected or TestSuite()
                for key, value in entity.items():
                    setattr(test_suite, key, value)

                if mode == "edit":
                    test_suite.save()
                else:
                    selected_table_group_name = entity["table_groups_name"]
                    selected_table_group = table_groups_df[table_groups_df["table_groups_name"] == selected_table_group_name].iloc[0]
                    test_suite.connection_id = int(selected_table_group["connection_id"])
                    test_suite.table_groups_id = selected_table_group["id"]
                    test_suite.save()
                success_message = (
                    "Changes have been saved successfully. "
                    if mode == "edit"
                    else "New test suite added successfully. "
                )
                st.success(success_message)
                time.sleep(1)
                st.rerun()


@st.dialog(title="Delete Test Suite")
@with_database_session
def delete_test_suite_dialog(test_suite_id: str) -> None:
    selected_test_suite = TestSuite.get_minimal(test_suite_id)
    test_suite_id = selected_test_suite.id
    test_suite_name = selected_test_suite.test_suite
    is_in_use = TestSuite.is_in_use([test_suite_id])

    st.markdown(f"Are you sure you want to delete the test suite **{test_suite_name}**?")

    if is_in_use:
        st.warning(
            """This Test Suite has related data, which may include test definitions and test results.
            \nIf you proceed, all related data will be permanently deleted."""
        )
        accept_cascade_delete = st.toggle(f"Yes, delete the test suite **{test_suite_name}** and related TestGen data.")

    with st.form("Delete Test Suite", clear_on_submit=True, border=False):
        delete = False
        _, button_column = st.columns([.85, .15])
        with button_column:
            delete = st.form_submit_button(
                "Delete",
                type="primary",
                disabled=is_in_use and not accept_cascade_delete,
                use_container_width=True,
            )

        if delete:
            if TestSuite.has_running_process([test_suite_id]):
                st.error("This Test Suite is in use by a running process and cannot be deleted.")
            else:
                TestSuite.cascade_delete([test_suite_id])
                success_message = f"Test Suite {test_suite_name} has been deleted. "
                st.success(success_message)
                time.sleep(1)
                st.rerun()


@st.dialog(title="Export to Observability")
def observability_export_dialog(test_suite_id: str) -> None:
    selected_test_suite = TestSuite.get_minimal(test_suite_id)
    project_key = selected_test_suite.project_code
    test_suite_key = selected_test_suite.test_suite
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
            qty_of_exported_events = export_test_results(selected_test_suite.id)
            status_container.empty()
            status_container.success(
                f"Process has successfully finished, {qty_of_exported_events} events have been exported."
            )
        except Exception as e:
            status_container.empty()
            status_container.error(f"Process has finished with errors: {e!s}.")
