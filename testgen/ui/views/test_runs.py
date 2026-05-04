import logging
import typing
from collections.abc import Iterable
from typing import Any

import streamlit as st

import testgen.ui.services.form_service as fm
from testgen.common.models import database_session, get_current_session, with_database_session
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.common.models.notification_settings import (
    TestRunNotificationSettings,
    TestRunNotificationTrigger,
)
from testgen.common.models.scheduler import RUN_TESTS_JOB_KEY
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services.query_cache import get_project_summary, get_test_run_summaries
from testgen.ui.session import session
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.ui.views.dialogs.manage_schedules import ScheduleDialog
from testgen.utils import friendly_score

PAGE_ICON = "labs"
PAGE_TITLE = "Test Runs"
LOG = logging.getLogger("testgen")

TR_RUN_TESTS_DIALOG_KEY = "tr:run_tests_dialog"
TR_RUN_SCHEDULES_DIALOG_KEY = "tr:run_schedules_dialog"
TR_RUN_NOTIFICATIONS_DIALOG_KEY = "tr:run_notifications_dialog"
TR_RUN_TESTS_RESULT_KEY = "tr:run_tests_result"


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
        order=1,
    )

    def render(self, project_code: str, table_group_id: str | None = None, test_suite_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "data-quality-testing",
        )

        page = int(st.query_params.get("page", 1))

        with st.spinner("Loading data ..."):
            project_summary = get_project_summary(project_code)
            test_runs, total_count = get_test_run_summaries(project_code, table_group_id, test_suite_id, page=page)
            table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
            test_suites = TestSuite.select_minimal_where(TestSuite.project_code == project_code, TestSuite.is_monitor.isnot(True))

        def on_run_tests_clicked(*_) -> None:
            st.session_state[TR_RUN_TESTS_DIALOG_KEY] = True

        def on_run_schedules_clicked(*_) -> None:
            st.session_state[TR_RUN_SCHEDULES_DIALOG_KEY] = True

        def on_run_notifications_clicked(*_) -> None:
            st.session_state[TR_RUN_NOTIFICATIONS_DIALOG_KEY] = True

        schedule_obj = TestRunScheduleDialog(project_code)
        ns_obj = TestRunNotificationSettingsDialog(
            TestRunNotificationSettings, {"project_code": project_code}
        )

        run_tests_data = None
        if st.session_state.get(TR_RUN_TESTS_DIALOG_KEY):
            run_tests_data = {
                "title": "Run Tests",
                "project_code": project_code,
                "test_suites": [{"value": str(ts.id), "label": ts.test_suite} for ts in test_suites],
                "default_test_suite_id": str(test_suite_id) if test_suite_id else None,
                "result": st.session_state.get(TR_RUN_TESTS_RESULT_KEY),
            }

        schedule_data = None
        if st.session_state.get(TR_RUN_SCHEDULES_DIALOG_KEY):
            schedule_data = schedule_obj.build_data()
            schedule_data["open"] = True

        notifications_data = None
        if st.session_state.get(TR_RUN_NOTIFICATIONS_DIALOG_KEY):
            notifications_data = ns_obj.build_data()
            notifications_data["open"] = True

        def on_run_tests_confirmed(data: dict) -> None:
            selected_id = data.get("test_suite_id")
            selected_name = data.get("test_suite_name")
            success = True
            message = f"Test run started for test suite '{selected_name}'."
            show_link = session.current_page != "test-runs"
            try:
                with database_session():
                    JobExecution.submit(
                        job_key="run-tests",
                        kwargs={"test_suite_id": str(selected_id)},
                        source="ui",
                        project_code=project_code,
                    )
            except Exception as error:
                success = False
                message = f"Test run could not be started: {error!s}."
                show_link = False
            st.session_state[TR_RUN_TESTS_RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
            if success and not show_link:
                st.cache_data.clear()
                Router().set_query_params({"page": 1})
                st.session_state.pop(TR_RUN_TESTS_DIALOG_KEY, None)
                st.session_state.pop(TR_RUN_TESTS_RESULT_KEY, None)

        def on_go_to_test_runs(payload: dict) -> None:
            st.session_state.pop(TR_RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(TR_RUN_TESTS_RESULT_KEY, None)
            st.cache_data.clear()
            Router().queue_navigation(to="test-runs", with_args=payload)

        def on_run_tests_dialog_closed(*_) -> None:
            st.session_state.pop(TR_RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(TR_RUN_TESTS_RESULT_KEY, None)

        def on_schedule_dialog_closed(*_) -> None:
            schedule_obj.clear_state()
            st.session_state.pop(TR_RUN_SCHEDULES_DIALOG_KEY, None)

        def on_notifications_dialog_closed(*_) -> None:
            ns_obj.clear_state()
            st.session_state.pop(TR_RUN_NOTIFICATIONS_DIALOG_KEY, None)

        def on_page_changed(new_page: int) -> None:
            Router().set_query_params({"page": new_page})

        testgen.test_runs_widget(
            key="test_runs",
            data={
                "project_summary": project_summary.to_dict(json_safe=True),
                "test_runs": [
                    {
                        **run.to_dict(json_safe=True),
                        "status_label": run.status_label,
                        "dq_score_testing": friendly_score(run.dq_score_testing),
                    } for run in test_runs
                ],
                "total_count": total_count,
                "page": page,
                "page_size": 20,
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
                "run_tests_dialog": run_tests_data,
                "schedule_dialog": schedule_data,
                "notifications_dialog": notifications_data,
            },
            on_PageChanged_change=on_page_changed,
            on_FilterApplied_change=on_test_runs_filtered,
            on_RunSchedulesClicked_change=on_run_schedules_clicked,
            on_RunNotificationsClicked_change=on_run_notifications_clicked,
            on_RunTestsClicked_change=on_run_tests_clicked,
            on_RefreshData_change=refresh_data,
            on_RunsDeleted_change=on_delete_runs,
            on_RunCanceled_change=on_cancel_run,
            # RunTestsDialog events
            on_RunTestsConfirmed_change=on_run_tests_confirmed,
            on_GoToTestRunsClicked_change=on_go_to_test_runs,
            on_RunTestsDialogClosed_change=on_run_tests_dialog_closed,
            # ScheduleList events
            on_PauseSchedule_change=schedule_obj.on_pause,
            on_ResumeSchedule_change=schedule_obj.on_resume,
            on_DeleteSchedule_change=schedule_obj.on_delete,
            on_GetCronSample_change=schedule_obj.on_cron_sample,
            on_AddSchedule_change=schedule_obj.on_add,
            on_ScheduleDialogClosed_change=on_schedule_dialog_closed,
            # NotificationSettings events
            on_AddNotification_change=ns_obj.on_add_item,
            on_UpdateNotification_change=ns_obj.on_update_item,
            on_DeleteNotification_change=ns_obj.on_delete_item,
            on_PauseNotification_change=ns_obj.on_pause_item,
            on_ResumeNotification_change=ns_obj.on_resume_item,
            on_NotificationsDialogClosed_change=on_notifications_dialog_closed,
        )


class TestRunFilters(typing.TypedDict):
    table_group_id: str
    test_suite_id: str

def on_test_runs_filtered(filters: TestRunFilters) -> None:
    Router().set_query_params({**filters, "page": 1})


def refresh_data(*_) -> None:
    get_test_run_summaries.clear()


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
            for ts in TestSuite.select_minimal_where(
                TestSuite.project_code == self.ns_attrs["project_code"],
                TestSuite.is_monitor.isnot(True),
            )
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
        self.test_suites = TestSuite.select_minimal_where(
            TestSuite.project_code == self.project_code,
            TestSuite.is_monitor.isnot(True),
        )

    def get_arg_value(self, job):
        return next(item.test_suite for item in self.test_suites if str(item.id) == job.kwargs["test_suite_id"])

    def get_arg_value_options(self) -> list[dict[str, str]]:
        return [
            {"value": str(test_suite.id), "label": test_suite.test_suite}
            for test_suite in self.test_suites
        ]

    def get_job_arguments(self, arg_value: str) -> tuple[list[typing.Any], dict[str, typing.Any]]:
        return [], {"test_suite_id": str(arg_value)}


@with_database_session
def on_cancel_run(payload: dict) -> None:
    job_execution_id = payload.get("job_execution_id")
    if not job_execution_id:
        fm.reset_post_updates(str_message=":red[This run cannot be canceled.]", as_toast=True)
        return

    job_exec = JobExecution.get(job_execution_id)
    if job_exec and job_exec.request_cancel():
        # Stopgap: also update the run status so the UI reflects cancellation immediately.
        if test_run_id := payload.get("test_run_id"):
            TestRun.cancel_run(test_run_id)
        get_test_run_summaries.clear()
        fm.reset_post_updates(str_message=":green[Cancellation requested.]", as_toast=True)
    else:
        fm.reset_post_updates(str_message=":red[This run cannot be canceled.]", as_toast=True)


@with_database_session
def on_delete_runs(job_execution_ids: list[str]) -> None:
    try:
        for je_id in job_execution_ids:
            job_exec = JobExecution.get(je_id)
            if not job_exec:
                continue
            if job_exec.status in (JobStatus.PENDING, JobStatus.CLAIMED, JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED):
                job_exec.request_cancel()
            test_run = next(iter(TestRun.select_where(TestRun.job_execution_id == je_id)), None)
            if test_run:
                TestRun.cascade_delete([str(test_run.id)])
            get_current_session().delete(job_exec)
        get_test_run_summaries.clear()
        Router().set_query_params({"page": 1})
    except Exception:
        LOG.exception("Failed to delete test run")
        st.toast("Something went wrong while deleting the test run.", icon=":material/error:")
