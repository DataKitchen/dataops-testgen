import logging
import typing
from collections.abc import Iterable
from functools import partial
from typing import Any

import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.form_service as fm
from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    TestRunNotificationSettings,
    TestRunNotificationTrigger,
)
from testgen.common.models.project import Project
from testgen.common.models.scheduler import RUN_TESTS_JOB_KEY
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.common.notifications.test_run import send_test_run_notifications
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.ui.views.dialogs.manage_schedules import ScheduleDialog
from testgen.ui.views.dialogs.run_tests_dialog import run_tests_dialog
from testgen.utils import friendly_score, to_int

PAGE_ICON = "labs"
PAGE_TITLE = "Test Runs"
LOG = logging.getLogger("testgen")


class TestRunsPage(Page):
    path = "test-runs"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=0,
    )

    def render(self, project_code: str, table_group_id: str | None = None, test_suite_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "test-results",
        )

        with st.spinner("Loading data ..."):
            project_summary = Project.get_summary(project_code)
            test_runs = TestRun.select_summary(project_code, table_group_id, test_suite_id)
            table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
            test_suites = TestSuite.select_minimal_where(TestSuite.project_code == project_code)

        testgen_component(
            "test_runs",
            props={
                "project_summary": project_summary.to_dict(json_safe=True),
                "test_runs": [
                    {
                        **run.to_dict(json_safe=True),
                        "dq_score_testing": friendly_score(run.dq_score_testing),
                    } for run in test_runs
                ],
                "table_group_options": [
                    {
                        "value": str(table_group.id),
                        "label": table_group.table_groups_name,
                        "selected": str(table_group_id) == str(table_group.id),
                    } for table_group in table_groups
                ],
                "test_suite_options": [
                    {
                        "value": str(test_suite.id),
                        "label": test_suite.test_suite,
                        "selected": str(test_suite_id) == str(test_suite.id),
                    } for test_suite in test_suites
                    if not table_group_id or str(table_group_id) == str(test_suite.table_groups_id)
                ],
                "permissions": {
                    "can_edit": session.auth.user_has_permission("edit"),
                },
            },
            on_change_handlers={
                "FilterApplied": on_test_runs_filtered,
                "RunSchedulesClicked": lambda *_: TestRunScheduleDialog().open(project_code),
                "RunNotificationsClicked": manage_notifications(project_code),
                "RunTestsClicked": lambda *_: run_tests_dialog(project_code, None, test_suite_id),
                "RefreshData": refresh_data,
                "RunsDeleted": partial(on_delete_runs, project_code, table_group_id, test_suite_id),
            },
            event_handlers={
                "RunCanceled": on_cancel_run,
            },
        )


class TestRunFilters(typing.TypedDict):
    table_group_id: str
    test_suite_id: str

def on_test_runs_filtered(filters: TestRunFilters) -> None:
    Router().set_query_params(filters)


def refresh_data(*_) -> None:
    TestRun.select_summary.clear()


def manage_notifications(project_code):

    def open_dialog(*_):
        TestRunNotificationSettingsDialog(TestRunNotificationSettings, {"project_code": project_code}).open(),

    return open_dialog


class TestRunNotificationSettingsDialog(NotificationSettingsDialogBase):

    title = "Test Run Notifications"

    def _item_to_model_attrs(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "trigger": TestRunNotificationTrigger(item["trigger"]),
            "test_suite_id": item["scope"],
        }

    def _model_to_item_attrs(self, model: TestRunNotificationSettings) -> dict[str, Any]:
        return {
            "trigger": model.trigger.value if model.trigger else None,
            "scope": str(model.test_suite_id) if model.test_suite_id else None,
        }

    def _get_component_props(self) -> dict[str, Any]:
        test_suite_options = [
            (str(ts.id), ts.test_suite)
            for ts in TestSuite.select_minimal_where(TestSuite.project_code == self.ns_attrs["project_code"])
        ]
        test_suite_options.insert(0, (None, "All Test Suites"))
        trigger_labels = {
            TestRunNotificationTrigger.always.value: "Always",
            TestRunNotificationTrigger.on_failures.value: "On test failures",
            TestRunNotificationTrigger.on_warnings.value: "On test failures and warnings",
            TestRunNotificationTrigger.on_changes.value: "On new test failures and warnings",
        }
        trigger_options = [(t.value, trigger_labels[t.value]) for t in TestRunNotificationTrigger]
        return {
            "scope_label": "Test Suite",
            "scope_options": test_suite_options,
            "trigger_options": trigger_options,
        }


class TestRunScheduleDialog(ScheduleDialog):

    title = "Test Run Schedules"
    arg_label = "Test Suite"
    job_key = RUN_TESTS_JOB_KEY
    test_suites: Iterable[TestSuiteMinimal] | None = None

    def init(self) -> None:
        self.test_suites = TestSuite.select_minimal_where(TestSuite.project_code == self.project_code)

    def get_arg_value(self, job):
        return next(item.test_suite for item in self.test_suites if str(item.id) == job.kwargs["test_suite_id"])

    def get_arg_value_options(self) -> list[dict[str, str]]:
        return [
            {"value": str(test_suite.id), "label": test_suite.test_suite}
            for test_suite in self.test_suites
        ]

    def get_job_arguments(self, arg_value: str) -> tuple[list[typing.Any], dict[str, typing.Any]]:
        return [], {"test_suite_id": str(arg_value)}


def on_cancel_run(test_run: dict) -> None:
    process_status, process_message = process_service.kill_test_run(to_int(test_run["process_id"]))
    if process_status:
        TestRun.cancel_run(test_run["test_run_id"])
        send_test_run_notifications(TestRun.get(test_run["test_run_id"]))

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
                            TestRun.cancel_run(test_run.test_run_id)
                            send_test_run_notifications(TestRun.get(test_run.test_run_id))
                TestRun.cascade_delete(test_run_ids)
            st.rerun()
        except Exception:
            LOG.exception("Failed to delete test run")
            result = {"success": False, "message": "Unable to delete the test run, try again."}
            st.rerun(scope="fragment")
