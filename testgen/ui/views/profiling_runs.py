import json
import logging
import typing
from collections.abc import Iterable
from functools import partial

import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.form_service as fm
from testgen.common.models import with_database_session
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import user_session_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.manage_schedules import ScheduleDialog
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog
from testgen.utils import friendly_score, to_dataframe, to_int

LOG = logging.getLogger("testgen")
FORM_DATA_WIDTH = 400
PAGE_SIZE = 50
PAGE_ICON = "data_thresholding"
PAGE_TITLE = "Profiling Runs"


class DataProfilingPage(Page):
    path = "profiling-runs"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Profiling",
        order=1,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str, table_group_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "investigate-profiling",
        )

        user_can_run = user_session_service.user_can_edit()
        if render_empty_state(project_code, user_can_run):
            return

        group_filter_column, actions_column = st.columns([.3, .7], vertical_alignment="bottom")

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

        with actions_column:
            testgen.flex_row_end()

            st.button(
                ":material/today: Profiling Schedules",
                help="Manage when profiling should run for table groups",
                on_click=partial(ProfilingScheduleDialog().open, project_code)
            )

            if user_can_run:
                st.button(
                    ":material/play_arrow: Run Profiling",
                    help="Run profiling for a table group",
                    on_click=partial(run_profiling_dialog, project_code, None, table_group_id)
                )
        fm.render_refresh_button(actions_column)

        testgen.whitespace(0.5)
        list_container = st.container()

        with st.spinner("Loading data ..."):
            profiling_runs = ProfilingRun.select_summary(project_code, table_group_id)

        paginated = []
        if run_count := len(profiling_runs):
            page_index = testgen.paginator(count=run_count, page_size=PAGE_SIZE)
            profiling_runs = [
                {
                    **row.to_dict(json_safe=True),
                    "dq_score_profiling": friendly_score(row.dq_score_profiling),
                } for row in profiling_runs
            ]
            paginated = profiling_runs[PAGE_SIZE * page_index : PAGE_SIZE * (page_index + 1)]

        with list_container:
            testgen_component(
                "profiling_runs",
                props={
                    "items": json.dumps(paginated),
                    "permissions": {
                        "can_run": user_can_run,
                        "can_edit": user_can_run,
                    },
                },
                event_handlers={
                    "RunCanceled": on_cancel_run,
                    "RunsDeleted": partial(on_delete_runs, project_code, table_group_id),
                }
            )


class ProfilingScheduleDialog(ScheduleDialog):

    title = "Profiling Schedules"
    arg_label = "Table Group"
    job_key = "run-profile"
    table_groups: Iterable[TableGroupMinimal] | None = None

    def init(self) -> None:
        self.table_groups = TableGroup.select_minimal_where(TableGroup.project_code == self.project_code)

    def get_arg_value(self, job):
        return next(item.table_groups_name for item in self.table_groups if str(item.id) == job.kwargs["table_group_id"])

    def arg_value_input(self) -> tuple[bool, list[typing.Any], dict[str, typing.Any]]:
        table_groups_df = to_dataframe(self.table_groups, TableGroupMinimal.columns())
        tg_id = testgen.select(
            label="Table Group",
            options=table_groups_df,
            value_column="id",
            display_column="table_groups_name",
            required=True,
            placeholder="Select table group",
        )
        return bool(tg_id), [], {"table_group_id": str(tg_id)}


def render_empty_state(project_code: str, user_can_run: bool) -> bool:
    project_summary = Project.get_summary(project_code)
    if project_summary.profiling_run_count:
        return False

    label = "No profiling runs yet"
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
            },
        )
    else:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.Profiling,
            action_label="Run Profiling",
            action_disabled=not user_can_run,
            button_onclick=partial(run_profiling_dialog, project_code),
            button_icon="play_arrow",
        )
    return True


def on_cancel_run(profiling_run: dict) -> None:
    process_status, process_message = process_service.kill_profile_run(to_int(profiling_run["process_id"]))
    if process_status:
        ProfilingRun.update_status(profiling_run["profiling_run_id"], "Cancelled")

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
                            ProfilingRun.update_status(profiling_run.profiling_run_id, "Cancelled")
                ProfilingRun.cascade_delete(profiling_run_ids)
            st.rerun()
        except Exception:
            LOG.exception("Failed to delete profiling runs")
            set_result({
                "success": False,
                "message": "Unable to delete the selected profiling runs, try again.",
            })
            st.rerun(scope="fragment")
