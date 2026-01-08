import logging
import typing
from collections.abc import Iterable
from functools import partial

import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.form_service as fm
from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    ProfilingRunNotificationSettings,
    ProfilingRunNotificationTrigger,
)
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.project import Project
from testgen.common.models.scheduler import RUN_PROFILE_JOB_KEY
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.notifications.profiling_run import send_profiling_run_notifications
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.ui.views.dialogs.manage_schedules import ScheduleDialog
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog
from testgen.utils import friendly_score, to_int

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
            "investigate-profiling",
        )

        with st.spinner("Loading data ..."):
            project_summary = Project.get_summary(project_code)
            profiling_runs = ProfilingRun.select_summary(project_code, table_group_id)
            table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)

        testgen_component(
            "profiling_runs",
            props={
                "project_summary": project_summary.to_dict(json_safe=True),
                "profiling_runs": [
                    {
                        **run.to_dict(json_safe=True),
                        "dq_score_profiling": friendly_score(run.dq_score_profiling),
                    } for run in profiling_runs
                ],
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
            },
            on_change_handlers={
                "FilterApplied": on_profiling_runs_filtered,
                "RunNotificationsClicked": manage_notifications(project_code),
                "RunSchedulesClicked": lambda *_: ProfilingScheduleDialog().open(project_code),
                "RunProfilingClicked": lambda *_: run_profiling_dialog(project_code, table_group_id, allow_selection=True),
                "RefreshData": refresh_data,
                "RunsDeleted": partial(on_delete_runs, project_code, table_group_id),
            },
            event_handlers={
                "RunCanceled": on_cancel_run,
            },
        )


class ProfilingRunFilters(typing.TypedDict):
    table_group_id: str

def on_profiling_runs_filtered(filters: ProfilingRunFilters) -> None:
    Router().set_query_params(filters)


def refresh_data(*_) -> None:
    ProfilingRun.select_summary.clear()


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


def manage_notifications(project_code):

    def open_dialog(*_):
        ProfilingRunNotificationSettingsDialog(ProfilingRunNotificationSettings, {"project_code": project_code}).open(),

    return open_dialog


def on_cancel_run(profiling_run: dict) -> None:
    process_status, process_message = process_service.kill_profile_run(to_int(profiling_run["process_id"]))
    if process_status:
        ProfilingRun.cancel_run(profiling_run["id"])
        send_profiling_run_notifications(ProfilingRun.get(profiling_run["id"]))

    fm.reset_post_updates(str_message=f":{'green' if process_status else 'red'}[{process_message}]", as_toast=True)


@st.dialog(title="Delete Profiling Runs")
@with_database_session
def on_delete_runs(project_code: str, table_group_id: str, profiling_run_ids: list[str]) -> None:
    def on_delete_confirmed(*_args) -> None:
        set_delete_confirmed(True)

    message = f"Are you sure you want to delete the {len(profiling_run_ids)} selected profiling runs?"
    constraint = {
        "warning": "Any running processes will be canceled.",
        "confirmation": "Yes, cancel and delete the profiling runs.",
    }
    if len(profiling_run_ids) == 1:
        message = "Are you sure you want to delete the selected profiling run?"
        constraint["confirmation"] = "Yes, cancel and delete the profiling run."

    if not ProfilingRun.has_running_process(profiling_run_ids):
        constraint = None

    result, set_result = temp_value("profiling-runs:result-value", default=None)
    delete_confirmed, set_delete_confirmed = temp_value("profiling-runs:confirm-delete", default=False)

    testgen.testgen_component(
        "confirm_dialog",
        props={
            "project_code": project_code,
            "message": message,
            "constraint": constraint,
            "button_label": "Delete",
            "button_color": "warn",
            "result": result(),
        },
        on_change_handlers={
            "ActionConfirmed": on_delete_confirmed,
        },
    )

    if delete_confirmed():
        try:
            with st.spinner("Deleting runs ..."):
                profiling_runs = ProfilingRun.select_summary(project_code, table_group_id, profiling_run_ids)
                for profiling_run in profiling_runs:
                    if profiling_run.status == "Running":
                        process_status, _ = process_service.kill_profile_run(to_int(profiling_run.process_id))
                        if process_status:
                            ProfilingRun.cancel_run(profiling_run.id)
                            send_profiling_run_notifications(ProfilingRun.get(profiling_run.id))
                ProfilingRun.cascade_delete(profiling_run_ids)
            st.rerun()
        except Exception:
            LOG.exception("Failed to delete profiling runs")
            set_result({
                "success": False,
                "message": "Unable to delete the selected profiling runs, try again.",
            })
            st.rerun(scope="fragment")
