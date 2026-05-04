import typing

import streamlit as st

from testgen.commands.run_observability_exporter import export_test_results
from testgen.commands.test_generation import run_test_generation
from testgen.common.models import database_session, with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.notification_settings import TestRunNotificationSettings
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services.query_cache import get_project_summary, get_test_suite_summaries
from testgen.ui.session import session
from testgen.ui.views.dialogs.generate_tests_dialog import (
    get_generation_set_choices,
    get_test_suite_refresh_warning,
    lock_edited_tests,
)
from testgen.ui.views.test_runs import TestRunNotificationSettingsDialog, TestRunScheduleDialog

PAGE_ICON = "rule"
PAGE_TITLE = "Test Suites"

ADD_DIALOG_KEY = "ts:add_dialog"
EDIT_DIALOG_KEY = "ts:edit_dialog"
RUN_TESTS_DIALOG_KEY = "ts:run_tests_dialog"
RUN_TESTS_RESULT_KEY = "ts:run_tests_result"
GENERATE_TESTS_DIALOG_KEY = "ts:generate_tests_dialog"
GENERATE_TESTS_RESULT_KEY = "ts:generate_tests_result"
GENERATE_TESTS_LOCK_RESULT_KEY = "ts:generate_tests_lock_result"
RUN_SCHEDULES_DIALOG_KEY = "ts:run_schedules_dialog"
RUN_NOTIFICATIONS_DIALOG_KEY = "ts:run_notifications_dialog"
PAGE_RESULT_KEY = "ts:page_result"

class TestSuitesPage(Page):
    path = "test-suites"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=2,
    )

    def render(self, project_code: str, table_group_id: str | None = None, test_suite_name: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "manage-test-suites",
        )

        table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
        user_can_edit = session.auth.user_has_permission("edit")
        test_suites = get_test_suite_summaries(project_code, table_group_id, test_suite_name)
        project_summary = get_project_summary(project_code)
        delete_dialog = st.session_state.get("ts_delete_dialog")
        page_result = st.session_state.pop(PAGE_RESULT_KEY, None)

        # Build form_dialog prop from session state
        table_group_options = [{"value": str(tg.id), "label": tg.table_groups_name} for tg in table_groups]
        form_dialog = None
        if st.session_state.get(ADD_DIALOG_KEY):
            form_dialog = {
                "open": True,
                "mode": "add",
                "title": "Add Test Suite",
                "table_groups": table_group_options,
                "initial_values": None,
                "result": st.session_state.get("ts_form_dialog:result"),
            }
        elif edit_ts_id := st.session_state.get(EDIT_DIALOG_KEY):
            selected = TestSuite.get(edit_ts_id)
            form_dialog = {
                "open": True,
                "mode": "edit",
                "title": "Edit Test Suite",
                "test_suite_id": str(selected.id),
                "table_groups": table_group_options,
                "initial_values": {
                    "test_suite": selected.test_suite,
                    "table_groups_id": str(selected.table_groups_id) if selected.table_groups_id else None,
                    "test_suite_description": selected.test_suite_description or "",
                    "severity": selected.severity,
                    "export_to_observability": bool(selected.export_to_observability),
                    "dq_score_exclude": bool(selected.dq_score_exclude),
                    "component_key": selected.component_key or "",
                    "component_type": selected.component_type or "dataset",
                    "component_name": selected.component_name or "",
                },
                "result": st.session_state.get("ts_form_dialog:result"),
            }

        def on_add_ts_clicked(*_) -> None:
            st.session_state[ADD_DIALOG_KEY] = True

        def on_edit_ts_clicked(test_suite_id: str) -> None:
            st.session_state[EDIT_DIALOG_KEY] = test_suite_id

        def on_run_tests_clicked(test_suite_id: str) -> None:
            st.session_state[RUN_TESTS_DIALOG_KEY] = test_suite_id

        def on_generate_tests_clicked(test_suite_id: str) -> None:
            st.session_state[GENERATE_TESTS_DIALOG_KEY] = test_suite_id

        def on_run_schedules_clicked(*_) -> None:
            st.session_state[RUN_SCHEDULES_DIALOG_KEY] = True

        def on_run_notifications_clicked(*_) -> None:
            st.session_state[RUN_NOTIFICATIONS_DIALOG_KEY] = True

        schedule_obj = TestRunScheduleDialog(project_code)
        ns_obj = TestRunNotificationSettingsDialog(
            TestRunNotificationSettings, {"project_code": project_code}
        )

        run_tests_data = None
        if run_tests_ts_id := st.session_state.get(RUN_TESTS_DIALOG_KEY):
            run_tests_data = {
                "title": "Run Tests",
                "project_code": project_code,
                "test_suites": [{"value": str(ts.id), "label": ts.test_suite} for ts in test_suites if str(ts.id) == str(run_tests_ts_id)],
                "default_test_suite_id": str(run_tests_ts_id) if run_tests_ts_id else None,
                "result": st.session_state.get(RUN_TESTS_RESULT_KEY),
            }

        generate_tests_data = None
        if generate_tests_ts_id := st.session_state.get(GENERATE_TESTS_DIALOG_KEY):
            generate_ts = TestSuite.get_minimal(generate_tests_ts_id)
            generation_sets = get_generation_set_choices()
            default_set = "Standard" if "Standard" in generation_sets else (generation_sets[0] if generation_sets else "")
            test_ct, unlocked_test_ct, unlocked_edits_ct = get_test_suite_refresh_warning(str(generate_ts.id))
            refresh_warning = {
                "test_ct": test_ct,
                "unlocked_test_ct": unlocked_test_ct or 0,
                "unlocked_edits_ct": unlocked_edits_ct or 0,
            } if test_ct else None
            generate_tests_data = {
                "title": "Generate Tests",
                "test_suite_id": str(generate_ts.id),
                "test_suite_name": generate_ts.test_suite,
                "generation_sets": generation_sets,
                "default_generation_set": default_set,
                "refresh_warning": refresh_warning,
                "lock_result": st.session_state.get(GENERATE_TESTS_LOCK_RESULT_KEY),
                "result": st.session_state.get(GENERATE_TESTS_RESULT_KEY),
            }

        schedule_data = None
        if st.session_state.get(RUN_SCHEDULES_DIALOG_KEY):
            schedule_data = schedule_obj.build_data()
            schedule_data["open"] = True

        notifications_data = None
        if st.session_state.get(RUN_NOTIFICATIONS_DIALOG_KEY):
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
            st.session_state[RUN_TESTS_RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
            if success and not show_link:
                st.cache_data.clear()
                st.session_state.pop(RUN_TESTS_DIALOG_KEY, None)
                st.session_state.pop(RUN_TESTS_RESULT_KEY, None)

        def on_go_to_test_runs(payload: dict) -> None:
            st.session_state.pop(RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(RUN_TESTS_RESULT_KEY, None)
            st.cache_data.clear()
            Router().queue_navigation(to="test-runs", with_args=payload)

        def on_run_tests_dialog_closed(*_) -> None:
            st.session_state.pop(RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(RUN_TESTS_RESULT_KEY, None)

        def on_lock_edited_tests(*_) -> None:
            if ts_id := st.session_state.get(GENERATE_TESTS_DIALOG_KEY):
                lock_edited_tests(ts_id)
            st.session_state[GENERATE_TESTS_LOCK_RESULT_KEY] = "Edited tests have been successfully locked."

        @with_database_session
        def on_generate_tests_confirmed(data: dict) -> None:
            selected_id = data.get("test_suite_id")
            selected_set = data.get("generation_set", "")
            ts_name = data.get("test_suite_name", "")
            try:
                run_test_generation(selected_id, selected_set)
                st.session_state[GENERATE_TESTS_RESULT_KEY] = {"success": True, "message": f"Test generation completed for test suite '{ts_name}'."}
                st.cache_data.clear()
                st.session_state.pop(GENERATE_TESTS_DIALOG_KEY, None)
                st.session_state.pop(GENERATE_TESTS_RESULT_KEY, None)
                st.session_state.pop(GENERATE_TESTS_LOCK_RESULT_KEY, None)
            except Exception as e:
                st.session_state[GENERATE_TESTS_RESULT_KEY] = {"success": False, "message": f"Test generation encountered errors: {e!s}."}

        def on_generate_tests_dialog_closed(*_) -> None:
            st.session_state.pop(GENERATE_TESTS_DIALOG_KEY, None)
            st.session_state.pop(GENERATE_TESTS_RESULT_KEY, None)
            st.session_state.pop(GENERATE_TESTS_LOCK_RESULT_KEY, None)

        def on_schedule_dialog_closed(*_) -> None:
            schedule_obj.clear_state()
            st.session_state.pop(RUN_SCHEDULES_DIALOG_KEY, None)

        def on_notifications_dialog_closed(*_) -> None:
            ns_obj.clear_state()
            st.session_state.pop(RUN_NOTIFICATIONS_DIALOG_KEY, None)

        def on_close_form_dialog(*_) -> None:
            st.session_state.pop(ADD_DIALOG_KEY, None)
            st.session_state.pop(EDIT_DIALOG_KEY, None)
            st.session_state.pop("ts_form_dialog:result", None)

        testgen.test_suites_widget(
            key="test_suites",
            data={
                "project_summary": project_summary.to_dict(json_safe=True),
                "test_suites": [test_suite.to_dict(json_safe=True) for test_suite in test_suites],
                "table_group_filter_options": [
                    {
                        "value": str(table_group.id),
                        "label": table_group.table_groups_name,
                        "selected": str(table_group_id) == str(table_group.id),
                    } for table_group in table_groups
                ],
                "test_suite_name": test_suite_name,
                "permissions": {
                    "can_edit": user_can_edit,
                },
                "delete_dialog": delete_dialog,
                "form_dialog": form_dialog,
                "run_tests_dialog": run_tests_data,
                "generate_tests_dialog": generate_tests_data,
                "schedule_dialog": schedule_data,
                "notifications_dialog": notifications_data,
                "page_result": page_result,
            },
            on_FilterApplied_change=on_test_suites_filtered,
            on_RunSchedulesClicked_change=on_run_schedules_clicked,
            on_AddTestSuiteClicked_change=on_add_ts_clicked,
            on_ExportActionClicked_change=observability_export_action,
            on_EditActionClicked_change=on_edit_ts_clicked,
            on_DeleteActionClicked_change=prepare_ts_delete_dialog,
            on_DeleteTestSuiteConfirmed_change=execute_ts_delete,
            on_DeleteDialogDismissed_change=lambda *_: st.session_state.pop("ts_delete_dialog", None),
            on_RunTestsClicked_change=on_run_tests_clicked,
            on_RunNotificationsClicked_change=on_run_notifications_clicked,
            on_GenerateTestsClicked_change=on_generate_tests_clicked,
            on_SaveTestSuiteForm_change=save_test_suite_form,
            on_FormDialogClosed_change=on_close_form_dialog,
            # RunTestsDialog events
            on_RunTestsConfirmed_change=on_run_tests_confirmed,
            on_GoToTestRunsClicked_change=on_go_to_test_runs,
            on_RunTestsDialogClosed_change=on_run_tests_dialog_closed,
            # GenerateTestsDialog events
            on_LockEditedTests_change=on_lock_edited_tests,
            on_GenerateTestsConfirmed_change=on_generate_tests_confirmed,
            on_GenerateTestsDialogClosed_change=on_generate_tests_dialog_closed,
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


class TestSuiteFilters(typing.TypedDict):
    table_group_id: str
    test_suite_name: str


def on_test_suites_filtered(filters: TestSuiteFilters) -> None:
    Router().set_query_params(filters)


@with_database_session
def save_test_suite_form(data: dict) -> None:
    mode = data.get("mode")
    if not data.get("test_suite"):
        st.session_state["ts_form_dialog:result"] = {"success": False, "message": "Test Suite Name is required."}
        return

    if mode == "edit":
        test_suite_id = data.get("test_suite_id")
        test_suite = TestSuite.get(test_suite_id)
        test_suite.test_suite_description = data.get("test_suite_description", "")
        test_suite.severity = data.get("severity")
        test_suite.export_to_observability = data.get("export_to_observability", False)
        test_suite.dq_score_exclude = data.get("dq_score_exclude", False)
        test_suite.component_key = data.get("component_key", "")
        test_suite.component_type = data.get("component_type", "dataset")
        test_suite.component_name = data.get("component_name", "")
        test_suite.save()
        st.session_state.pop("ts_form_dialog:result", None)
        st.session_state.pop(EDIT_DIALOG_KEY, None)
        get_test_suite_summaries.clear()
        st.session_state[PAGE_RESULT_KEY] = {"success": True, "message": "Changes have been saved successfully."}
    else:
        table_group = TableGroup.get(data.get("table_groups_id"))
        test_suite = TestSuite()
        test_suite.project_code = table_group.project_code
        test_suite.test_suite = data.get("test_suite")
        test_suite.connection_id = table_group.connection_id
        test_suite.table_groups_id = table_group.id
        test_suite.test_suite_description = data.get("test_suite_description", "")
        test_suite.severity = data.get("severity")
        test_suite.export_to_observability = data.get("export_to_observability", False)
        test_suite.dq_score_exclude = data.get("dq_score_exclude", False)
        test_suite.component_key = data.get("component_key", "")
        test_suite.component_type = data.get("component_type", "dataset")
        test_suite.component_name = data.get("component_name", "")
        test_suite.save()
        st.session_state.pop("ts_form_dialog:result", None)
        st.session_state.pop(ADD_DIALOG_KEY, None)
        get_test_suite_summaries.clear()
        st.session_state[PAGE_RESULT_KEY] = {"success": True, "message": "New test suite added successfully."}


@with_database_session
def prepare_ts_delete_dialog(test_suite_id: str) -> None:
    selected = TestSuite.get_minimal(test_suite_id)
    is_in_use = TestSuite.is_in_use([selected.id])
    st.session_state["ts_delete_dialog"] = {
        "open": True,
        "test_suite_id": str(selected.id),
        "test_suite_name": selected.test_suite,
        "is_in_use": is_in_use,
    }


@with_database_session
def execute_ts_delete(test_suite_id: str) -> None:
    test_suite_name = st.session_state.get("ts_delete_dialog", {}).get("test_suite_name", "")
    if TestRun.has_active_job_for(TestSuite, test_suite_id):
        st.session_state[PAGE_RESULT_KEY] = {"success": False, "message": "This Test Suite is in use by a running process and cannot be deleted."}
    else:
        TestSuite.cascade_delete([test_suite_id])
        st.session_state[PAGE_RESULT_KEY] = {"success": True, "message": f"Test Suite {test_suite_name} has been deleted."}
    st.session_state.pop("ts_delete_dialog", None)
    get_test_suite_summaries.clear()


@with_database_session
def observability_export_action(test_suite_id: str) -> None:
    selected_test_suite = TestSuite.get_minimal(test_suite_id)
    try:
        qty_of_exported_events = export_test_results(selected_test_suite.id)
        st.session_state[PAGE_RESULT_KEY] = {"success": True, "message": f"Export finished: {qty_of_exported_events} events exported."}
    except Exception as e:
        st.session_state[PAGE_RESULT_KEY] = {"success": False, "message": f"Export failed: {e!s}"}
