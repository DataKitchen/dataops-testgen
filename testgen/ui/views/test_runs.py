import json
import logging
import typing
from collections.abc import Iterable
from functools import partial

import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.form_service as fm
from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import user_session_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.manage_schedules import ScheduleDialog
from testgen.ui.views.dialogs.run_tests_dialog import run_tests_dialog
from testgen.utils import friendly_score, to_dataframe, to_int

PAGE_SIZE = 50
PAGE_ICON = "labs"
PAGE_TITLE = "Test Runs"
LOG = logging.getLogger("testgen")


class TestRunsPage(Page):
    path = "test-runs"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=0,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str, table_group_id: str | None = None, test_suite_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "test-results",
        )

        user_can_run = user_session_service.user_can_edit()
        if render_empty_state(project_code, user_can_run):
            return

        group_filter_column, suite_filter_column, actions_column = st.columns([.3, .3, .4], vertical_alignment="bottom")

        with group_filter_column:
            table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
            table_groups_df = to_dataframe(table_groups, TableGroupMinimal.columns())
            table_groups_df["id"] = table_groups_df["id"].apply(lambda x: str(x))
            table_group_id = testgen.select(
                options=table_groups_df,
                value_column="id",
                display_column="table_groups_name",
                default_value=table_group_id,
                bind_to_query="table_group_id",
                label="Table Group",
                placeholder="---",
            )

        with suite_filter_column:
            clauses = [TestSuite.project_code == project_code]
            if table_group_id:
                clauses.append(TestSuite.table_groups_id == table_group_id)
            test_suites = TestSuite.select_where(*clauses)
            test_suites_df = to_dataframe(test_suites, TestSuite.columns())
            test_suites_df["id"] = test_suites_df["id"].apply(lambda x: str(x))
            test_suite_id = testgen.select(
                options=test_suites_df,
                value_column="id",
                display_column="test_suite",
                default_value=test_suite_id,
                bind_to_query="test_suite_id",
                label="Test Suite",
                placeholder="---",
            )

        with actions_column:
            testgen.flex_row_end(actions_column)

            st.button(
                ":material/today: Test Run Schedules",
                help="Manage when test suites should run",
                on_click=partial(TestRunScheduleDialog().open, project_code)
            )

            if user_can_run:
                st.button(
                    ":material/play_arrow: Run Tests",
                    help="Run tests for a test suite",
                    on_click=partial(run_tests_dialog, project_code, None, test_suite_id)
                )

        fm.render_refresh_button(actions_column)

        testgen.whitespace(0.5)
        list_container = st.container()

        with st.spinner("Loading data ..."):
            test_runs = TestRun.select_summary(project_code, table_group_id, test_suite_id)

        paginated = []
        if run_count := len(test_runs):
            page_index = testgen.paginator(count=run_count, page_size=PAGE_SIZE)
            test_runs = [
                {
                    **row.to_dict(json_safe=True),
                    "dq_score_testing": friendly_score(row.dq_score_testing),
                } for row in test_runs
            ]
            paginated = test_runs[PAGE_SIZE * page_index : PAGE_SIZE * (page_index + 1)]

        with list_container:
            testgen_component(
                "test_runs",
                props={
                    "items": json.dumps(paginated),
                    "permissions": {
                        "can_run": user_can_run,
                        "can_edit": user_can_run,
                    },
                },
                event_handlers={
                    "RunCanceled": on_cancel_run,
                    "RunsDeleted": partial(on_delete_runs, project_code, table_group_id, test_suite_id),
                }
            )


class TestRunScheduleDialog(ScheduleDialog):

    title = "Test Run Schedules"
    arg_label = "Test Suite"
    job_key = "run-tests"
    test_suites: Iterable[TestSuiteMinimal] | None = None

    def init(self) -> None:
        self.test_suites = TestSuite.select_minimal_where(TestSuite.project_code == self.project_code)

    def get_arg_value(self, job):
        return job.kwargs["test_suite_key"]

    def arg_value_input(self) -> tuple[bool, list[typing.Any], dict[str, typing.Any]]:
        test_suites_df = to_dataframe(self.test_suites, TestSuiteMinimal.columns())
        ts_name = testgen.select(
            label="Test Suite",
            options=test_suites_df,
            value_column="test_suite",
            display_column="test_suite",
            required=True,
            placeholder="Select test suite",
        )
        return bool(ts_name), [], {"project_key": self.project_code, "test_suite_key": ts_name}


def render_empty_state(project_code: str, user_can_run: bool) -> bool:
    project_summary = Project.get_summary(project_code)
    if project_summary.test_run_count:
        return False

    label="No test runs yet"
    testgen.whitespace(5)
    if not project_summary.connection_count:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.Connection,
            action_label="Go to Connections",
            link_href="connections",
            link_params={ "project_code": project_code },
        )
    elif not project_summary.table_group_count:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.TableGroup,
            action_label="Go to Table Groups",
            link_href="table-groups",
            link_params={
                "project_code": project_code,
                "connection_id": str(project_summary.default_connection_id),
            }
        )
    elif not project_summary.test_suite_count or not project_summary.test_definition_count:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.TestSuite,
            action_label="Go to Test Suites",
            link_href="test-suites",
            link_params={ "project_code": project_code },
        )
    else:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.TestExecution,
            action_label="Run Tests",
            action_disabled=not user_can_run,
            button_onclick=partial(run_tests_dialog, project_code),
            button_icon="play_arrow",
        )
    return True


def on_cancel_run(test_run: dict) -> None:
    process_status, process_message = process_service.kill_test_run(to_int(test_run["process_id"]))
    if process_status:
        TestRun.update_status(test_run["test_run_id"], "Cancelled")

    fm.reset_post_updates(str_message=f":{'green' if process_status else 'red'}[{process_message}]", as_toast=True)


@st.dialog(title="Delete Test Runs")
@with_database_session
def on_delete_runs(project_code: str, table_group_id: str, test_suite_id: str, test_run_ids: list[str]) -> None:
    def on_delete_confirmed(*_args) -> None:
        set_delete_confirmed(True)

    message = f"Are you sure you want to delete the {len(test_run_ids)} selected test runs?"
    constraint = {
        "warning": "Any running processes will be canceled.",
        "confirmation": "Yes, cancel and delete the test runs.",
    }
    if len(test_run_ids) == 1:
        message = "Are you sure you want to delete the selected test run?"
        constraint["confirmation"] = "Yes, cancel and delete the test run."

    if not TestRun.has_running_process(test_run_ids):
        constraint = None

    result = None
    delete_confirmed, set_delete_confirmed = temp_value("test-runs:confirm-delete", default=False)
    testgen.testgen_component(
        "confirm_dialog",
        props={
            "project_code": project_code,
            "message": message,
            "constraint": constraint,
            "button_label": "Delete",
            "button_color": "warn",
            "result": result,
        },
        on_change_handlers={
            "ActionConfirmed": on_delete_confirmed,
        },
    )

    if delete_confirmed():
        try:
            with st.spinner("Deleting runs ..."):
                test_runs = TestRun.select_summary(project_code, table_group_id, test_suite_id, test_run_ids)
                for test_run in test_runs:
                    if test_run.status == "Running":
                        process_status, _ = process_service.kill_test_run(to_int(test_run.process_id))
                        if process_status:
                            TestRun.update_status(test_run.test_run_id, "Cancelled")
                TestRun.cascade_delete(test_run_ids)
            st.rerun()
        except Exception:
            LOG.exception("Failed to delete test run")
            result = {"success": False, "message": "Unable to delete the test run, try again."}
            st.rerun(scope="fragment")
            