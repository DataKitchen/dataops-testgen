import logging
import typing
from collections.abc import Iterable

import streamlit as st

RUN_PROFILING_DIALOG_KEY = "pr:run_profiling_dialog"
RUN_SCHEDULES_DIALOG_KEY = "pr:run_schedules_dialog"
RUN_NOTIFICATIONS_DIALOG_KEY = "pr:run_notifications_dialog"
RUN_PROFILING_RESULT_KEY = "pr:run_profiling_result"
RUN_PROFILING_DIALOG_OPEN_COUNT_KEY = "pr:run_profiling_dialog_open_count"
RUN_SCHEDULES_DIALOG_OPEN_COUNT_KEY = "pr:run_schedules_dialog_open_count"
RUN_NOTIFICATIONS_DIALOG_OPEN_COUNT_KEY = "pr:run_notifications_dialog_open_count"

import testgen.ui.services.form_service as fm
from testgen.common.models import database_session, get_current_session, with_database_session
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.common.models.notification_settings import (
    ProfilingRunNotificationSettings,
    ProfilingRunNotificationTrigger,
)
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.scheduler import RUN_PROFILE_JOB_KEY
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services.query_cache import get_profiling_run_summaries, get_project_summary, get_table_group_stats
from testgen.ui.session import session
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.ui.views.dialogs.manage_schedules import ScheduleDialog
from testgen.utils import friendly_score

LOG = logging.getLogger("testgen")
PAGE_ICON = "data_thresholding"
PAGE_TITLE = "Profiling Runs"


class DataProfilingPage(Page):
    path = "profiling-runs"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Profiling",
        order=1,
    )

    def render(self, project_code: str, table_group_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "data-profiling",
        )

        page = int(st.query_params.get("page", 1))

        with st.spinner("Loading data ..."):
            project_summary = get_project_summary(project_code)
            profiling_runs, total_count = get_profiling_run_summaries(project_code, table_group_id, page=page)
            table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)

        schedule_obj = ProfilingScheduleDialog(project_code)
        ns_obj = ProfilingRunNotificationSettingsDialog(
            ProfilingRunNotificationSettings, {"project_code": project_code}
        )

        def on_run_profiling_clicked(*_) -> None:
            st.session_state[RUN_PROFILING_DIALOG_KEY] = True
            st.session_state[RUN_PROFILING_DIALOG_OPEN_COUNT_KEY] = st.session_state.get(RUN_PROFILING_DIALOG_OPEN_COUNT_KEY, 0) + 1

        def on_run_schedules_clicked(*_) -> None:
            st.session_state[RUN_SCHEDULES_DIALOG_KEY] = True
            st.session_state[RUN_SCHEDULES_DIALOG_OPEN_COUNT_KEY] = st.session_state.get(RUN_SCHEDULES_DIALOG_OPEN_COUNT_KEY, 0) + 1

        def on_run_notifications_clicked(*_) -> None:
            st.session_state[RUN_NOTIFICATIONS_DIALOG_KEY] = True
            st.session_state[RUN_NOTIFICATIONS_DIALOG_OPEN_COUNT_KEY] = st.session_state.get(RUN_NOTIFICATIONS_DIALOG_OPEN_COUNT_KEY, 0) + 1

        # Build run profiling dialog data
        run_profiling_data = None
        if st.session_state.get(RUN_PROFILING_DIALOG_KEY):
            table_groups_stats = get_table_group_stats(project_code=project_code)
            run_profiling_data = {
                "open": st.session_state[RUN_PROFILING_DIALOG_OPEN_COUNT_KEY],
                "title": "Run Profiling",
                "table_groups": [tg.to_dict(json_safe=True) for tg in table_groups_stats],
                "selected_id": str(table_group_id) if table_group_id else None,
                "allow_selection": True,
                "result": st.session_state.get(RUN_PROFILING_RESULT_KEY),
            }

        # Build schedule dialog data
        schedule_data = None
        if st.session_state.get(RUN_SCHEDULES_DIALOG_KEY):
            schedule_data = schedule_obj.build_data()
            schedule_data["open"] = st.session_state[RUN_SCHEDULES_DIALOG_OPEN_COUNT_KEY]

        # Build notifications dialog data
        notifications_data = None
        if st.session_state.get(RUN_NOTIFICATIONS_DIALOG_KEY):
            notifications_data = ns_obj.build_data()
            notifications_data["open"] = st.session_state[RUN_NOTIFICATIONS_DIALOG_OPEN_COUNT_KEY]

        def on_run_profiling_confirmed(table_group: dict) -> None:
            success = True
            message = f"Profiling run started for table group '{table_group['table_groups_name']}'."
            show_link = session.current_page != "profiling-runs"
            try:
                with database_session():
                    JobExecution.submit(
                        job_key="run-profile",
                        kwargs={"table_group_id": str(table_group["id"])},
                        source="ui",
                        project_code=project_code,
                    )
            except Exception as error:
                success = False
                message = f"Profiling run could not be started: {error!s}."
                show_link = False
            st.session_state[RUN_PROFILING_RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
            if success and not show_link:
                get_profiling_run_summaries.clear()
                Router().set_query_params({"page": 1})
                st.session_state.pop(RUN_PROFILING_DIALOG_KEY, None)
                st.session_state.pop(RUN_PROFILING_RESULT_KEY, None)

        def on_go_to_profiling_runs_clicked(tg_id: str) -> None:
            st.session_state.pop(RUN_PROFILING_DIALOG_KEY, None)
            st.session_state.pop(RUN_PROFILING_RESULT_KEY, None)
            Router().queue_navigation(to="profiling-runs", with_args={"project_code": project_code, "table_group_id": tg_id})

        def on_run_profiling_dialog_closed(*_) -> None:
            st.session_state.pop(RUN_PROFILING_DIALOG_KEY, None)
            st.session_state.pop(RUN_PROFILING_RESULT_KEY, None)

        def on_schedule_dialog_closed(*_) -> None:
            schedule_obj.clear_state()
            st.session_state.pop(RUN_SCHEDULES_DIALOG_KEY, None)

        def on_notifications_dialog_closed(*_) -> None:
            ns_obj.clear_state()
            st.session_state.pop(RUN_NOTIFICATIONS_DIALOG_KEY, None)

        def on_page_changed(new_page: int) -> None:
            Router().set_query_params({"page": new_page})

        testgen.profiling_runs_widget(
            key="profiling_runs",
            data={
                "project_summary": project_summary.to_dict(json_safe=True),
                "profiling_runs": [
                    {
                        **run.to_dict(json_safe=True),
                        "status_label": run.status_label,
                        "dq_score_profiling": friendly_score(run.dq_score_profiling),
                    } for run in profiling_runs
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
                "permissions": {
                    "can_edit": session.auth.user_has_permission("edit"),
                },
                "run_profiling_dialog": run_profiling_data,
                "schedule_dialog": schedule_data,
                "notifications_dialog": notifications_data,
            },
            on_PageChanged_change=on_page_changed,
            on_FilterApplied_change=on_profiling_runs_filtered,
            on_RunNotificationsClicked_change=on_run_notifications_clicked,
            on_RunSchedulesClicked_change=on_run_schedules_clicked,
            on_RunProfilingClicked_change=on_run_profiling_clicked,
            on_RefreshData_change=refresh_data,
            on_RunsDeleted_change=on_delete_runs,
            on_RunCanceled_change=on_cancel_run,
            # RunProfilingDialog events
            on_RunProfilingConfirmed_change=on_run_profiling_confirmed,
            on_GoToProfilingRunsClicked_change=on_go_to_profiling_runs_clicked,
            on_RunProfilingDialogClosed_change=on_run_profiling_dialog_closed,
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


class ProfilingRunFilters(typing.TypedDict):
    table_group_id: str

def on_profiling_runs_filtered(filters: ProfilingRunFilters) -> None:
    Router().set_query_params({**filters, "page": 1})


def refresh_data(*_) -> None:
    get_profiling_run_summaries.clear()


class ProfilingScheduleDialog(ScheduleDialog):

    title = "Profiling Schedules"
    arg_label = "Table Group"
    job_key = RUN_PROFILE_JOB_KEY
    table_groups: Iterable[TableGroupMinimal] | None = None

    def init(self) -> None:
        self.table_groups = TableGroup.select_minimal_where(TableGroup.project_code == self.project_code)

    def get_arg_value(self, job):
        return next(item.table_groups_name for item in self.table_groups if str(item.id) == job.kwargs["table_group_id"])

    def get_arg_value_options(self) -> list[dict[str, str]]:
        return [
            {"value": str(table_group.id), "label": table_group.table_groups_name}
            for table_group in self.table_groups
        ]

    def get_job_arguments(self, arg_value: str) -> tuple[list[typing.Any], dict[str, typing.Any]]:
        return [], {"table_group_id": str(arg_value)}


class ProfilingRunNotificationSettingsDialog(NotificationSettingsDialogBase):

    title = "Profiling Notifications"

    def _item_to_model_attrs(self, item: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return {
            "trigger": ProfilingRunNotificationTrigger(item["trigger"]),
            "table_group_id": item["scope"],
        }

    def _model_to_item_attrs(self, model: ProfilingRunNotificationSettings) -> dict[str, typing.Any]:
        return {
            "trigger": model.trigger.value if model.trigger else None,
            "scope": str(model.table_group_id) if model.table_group_id else None,
        }

    def _get_component_props(self) -> dict[str, typing.Any]:
        table_group_options = [
            (str(tg.id), tg.table_groups_name)
            for tg in TableGroup.select_minimal_where(TableGroup.project_code == self.ns_attrs["project_code"])
        ]
        table_group_options.insert(0, (None, "All Table Groups"))
        trigger_labels = {
            ProfilingRunNotificationTrigger.always.value: "Always",
            ProfilingRunNotificationTrigger.on_changes.value: "On new hygiene issues",
        }
        trigger_options = [(t.value, trigger_labels[t.value]) for t in ProfilingRunNotificationTrigger]
        return {
            "scope_label": "Table Group",
            "scope_options": table_group_options,
            "trigger_options": trigger_options,
        }


@with_database_session
def on_cancel_run(payload: dict) -> None:
    job_execution_id = payload.get("job_execution_id")
    if not job_execution_id:
        fm.reset_post_updates(str_message=":red[This run cannot be canceled.]", as_toast=True)
        return

    job_exec = JobExecution.get(job_execution_id)
    if job_exec and job_exec.request_cancel():
        # Stopgap: also update the run status so the UI reflects cancellation immediately.
        if profiling_run_id := payload.get("profiling_run_id"):
            ProfilingRun.cancel_run(profiling_run_id)
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
            profiling_run = next(iter(ProfilingRun.select_where(ProfilingRun.job_execution_id == je_id)), None)
            if profiling_run:
                ProfilingRun.cascade_delete([str(profiling_run.id)])
            get_current_session().delete(job_exec)
        get_profiling_run_summaries.clear()
        Router().set_query_params({"page": 1})
    except Exception:
        LOG.exception("Failed to delete profiling runs")
        st.toast("Unable to delete the selected profiling runs, try again.", icon=":material/error:")
