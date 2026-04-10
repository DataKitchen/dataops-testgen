import logging
import typing
from collections.abc import Iterable
from dataclasses import asdict

import streamlit as st
from sqlalchemy.exc import IntegrityError

from testgen.commands.test_generation import run_monitor_generation
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.notification_settings import ProfilingRunNotificationSettings
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, RUN_TESTS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries import table_group_queries
from testgen.ui.services.query_cache import get_profiling_run_summaries, get_project_summary, get_table_group_stats
from testgen.ui.session import session, temp_value
from testgen.ui.utils import get_cron_sample_handler
from testgen.ui.views.connections import FLAVOR_OPTIONS, format_connection
from testgen.ui.views.profiling_runs import ProfilingRunNotificationSettingsDialog, ProfilingScheduleDialog

LOG = logging.getLogger("testgen")
PAGE_TITLE = "Table Groups"

TG_RUN_PROFILING_DIALOG_KEY = "tg:run_profiling_dialog"
TG_RUN_PROFILING_RESULT_KEY = "tg:run_profiling_result"
TG_RUN_SCHEDULES_DIALOG_KEY = "tg:run_schedules_dialog"
TG_RUN_NOTIFICATIONS_DIALOG_KEY = "tg:run_notifications_dialog"


class TableGroupsPage(Page):
    path = "table-groups"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="table_view",
        label=PAGE_TITLE,
        section="Data Configuration",
        order=0,
    )

    def render(
        self,
        project_code: str,
        connection_id: str | None = None,
        table_group_name: str | None = None,
        **_kwargs,
    ) -> None:
        testgen.page_header(PAGE_TITLE, "manage-table-groups")

        user_can_edit = session.auth.user_has_permission("edit")
        project_summary = get_project_summary(project_code)
        if connection_id and not connection_id.isdigit():
            connection_id = None

        table_group_filters = [
            TableGroup.project_code == project_code,
        ]
        if connection_id:
            table_group_filters.append(TableGroup.connection_id == connection_id)

        if table_group_name:
            table_group_filters.append(TableGroup.table_groups_name.ilike(f"%{table_group_name}%"))

        table_groups = TableGroup.select_minimal_where(*table_group_filters)
        connections = self._get_connections(project_code)

        wizard_mode = st.session_state.get("tg_wizard_mode")
        delete_dialog = st.session_state.get("tg_delete_dialog")

        def on_add_table_group_clicked(*_args) -> None:
            table_group_queries.reset_table_group_preview()
            st.session_state["tg_wizard_mode"] = "add"
            st.session_state["tg_wizard_connection_id"] = connection_id

        def on_edit_table_group_clicked(table_group_id: str) -> None:
            table_group_queries.reset_table_group_preview()
            st.session_state["tg_wizard_mode"] = "edit"
            st.session_state["tg_wizard_table_group_id"] = table_group_id

        def on_run_profiling_clicked(table_group_id: str) -> None:
            st.session_state[TG_RUN_PROFILING_DIALOG_KEY] = table_group_id

        def on_run_schedules_clicked(*_) -> None:
            st.session_state[TG_RUN_SCHEDULES_DIALOG_KEY] = True

        def on_run_notifications_clicked(*_) -> None:
            st.session_state[TG_RUN_NOTIFICATIONS_DIALOG_KEY] = True

        schedule_obj = ProfilingScheduleDialog(project_code)
        ns_obj = ProfilingRunNotificationSettingsDialog(
            ProfilingRunNotificationSettings, {"project_code": project_code}
        )

        run_profiling_data = None
        if run_profiling_tg_id := st.session_state.get(TG_RUN_PROFILING_DIALOG_KEY):
            table_groups_stats = get_table_group_stats(
                project_code=project_code,
                table_group_id=run_profiling_tg_id,
            )
            run_profiling_data = {
                "title": "Run Profiling",
                "table_groups": [tg.to_dict(json_safe=True) for tg in table_groups_stats],
                "selected_id": str(run_profiling_tg_id),
                "allow_selection": False,
                "result": st.session_state.get(TG_RUN_PROFILING_RESULT_KEY),
            }

        schedule_data = None
        if st.session_state.get(TG_RUN_SCHEDULES_DIALOG_KEY):
            schedule_data = schedule_obj.build_data()
            schedule_data["open"] = True

        notifications_data = None
        if st.session_state.get(TG_RUN_NOTIFICATIONS_DIALOG_KEY):
            notifications_data = ns_obj.build_data()
            notifications_data["open"] = True

        def on_run_profiling_confirmed(table_group: dict) -> None:
            success = True
            message = f"Profiling run started for table group '{table_group['table_groups_name']}'."
            show_link = session.current_page != "profiling-runs"
            try:
                run_profiling_in_background(table_group["id"])
            except Exception as error:
                success = False
                message = f"Profiling run could not be started: {error!s}."
                show_link = False
            st.session_state[TG_RUN_PROFILING_RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
            if success and not show_link:
                get_profiling_run_summaries.clear()
                st.session_state.pop(TG_RUN_PROFILING_DIALOG_KEY, None)
                st.session_state.pop(TG_RUN_PROFILING_RESULT_KEY, None)

        def on_go_to_profiling_runs_clicked(tg_id: str) -> None:
            st.session_state.pop(TG_RUN_PROFILING_RESULT_KEY, None)
            Router().queue_navigation(to="profiling-runs", with_args={"project_code": project_code, "table_group_id": tg_id})

        def on_run_profiling_dialog_closed(*_) -> None:
            st.session_state.pop(TG_RUN_PROFILING_DIALOG_KEY, None)
            st.session_state.pop(TG_RUN_PROFILING_RESULT_KEY, None)

        def on_schedule_dialog_closed(*_) -> None:
            schedule_obj.clear_state()
            st.session_state.pop(TG_RUN_SCHEDULES_DIALOG_KEY, None)

        def on_notifications_dialog_closed(*_) -> None:
            ns_obj.clear_state()
            st.session_state.pop(TG_RUN_NOTIFICATIONS_DIALOG_KEY, None)

        # --- Wizard data (add mode only) ---
        wizard_data = None
        wizard_handlers = {}
        wizard_cron_handler = None
        if wizard_mode == "add":
            wizard_data, wizard_handlers, wizard_cron_handler = self._build_wizard_data(
                project_code,
                connections,
                connection_id=connection_id,
            )

        # --- Edit dialog data ---
        edit_dialog_data = None
        edit_dialog_handlers = {}
        if wizard_mode == "edit":
            edit_dialog_data, edit_dialog_handlers = self._build_edit_data(
                project_code,
                connections,
            )

        def on_get_cron_sample(payload):
            schedule_obj.on_cron_sample(payload)
            if wizard_cron_handler:
                wizard_cron_handler(payload)

        testgen.table_group_list_widget(
            key="table_group_list",
            data={
                "project_summary": project_summary.to_dict(json_safe=True),
                "connection_id": connection_id,
                "table_group_name": table_group_name,
                "permissions": {
                    "can_edit": user_can_edit,
                    "can_view_pii": session.auth.user_has_permission("view_pii"),
                },
                "connections": connections,
                "table_groups": self._format_table_group_list(table_groups, connections),
                "delete_dialog": delete_dialog,
                "run_profiling_dialog": run_profiling_data,
                "schedule_dialog": schedule_data,
                "notifications_dialog": notifications_data,
                "wizard": wizard_data,
                "edit_dialog": edit_dialog_data,
            },
            on_RunSchedulesClicked_change=on_run_schedules_clicked,
            on_RunNotificationsClicked_change=on_run_notifications_clicked,
            on_AddTableGroupClicked_change=on_add_table_group_clicked,
            on_EditTableGroupClicked_change=on_edit_table_group_clicked,
            on_DeleteTableGroupClicked_change=self._prepare_delete_dialog,
            on_DeleteTableGroupConfirmed_change=self._execute_delete,
            on_DeleteDialogDismissed_change=lambda *_: st.session_state.pop("tg_delete_dialog", None),
            on_RunProfilingClicked_change=on_run_profiling_clicked,
            on_TableGroupsFiltered_change=lambda params: self.router.queue_navigation(
                to="table-groups",
                with_args={"project_code": project_code, **params},
            ),
            # RunProfilingDialog events
            on_RunProfilingConfirmed_change=on_run_profiling_confirmed,
            on_GoToProfilingRunsClicked_change=on_go_to_profiling_runs_clicked,
            on_RunProfilingDialogClosed_change=on_run_profiling_dialog_closed,
            # ScheduleList events
            on_PauseSchedule_change=schedule_obj.on_pause,
            on_ResumeSchedule_change=schedule_obj.on_resume,
            on_DeleteSchedule_change=schedule_obj.on_delete,
            on_GetCronSample_change=on_get_cron_sample,
            on_AddSchedule_change=schedule_obj.on_add,
            on_ScheduleDialogClosed_change=on_schedule_dialog_closed,
            # NotificationSettings events
            on_AddNotification_change=ns_obj.on_add_item,
            on_UpdateNotification_change=ns_obj.on_update_item,
            on_DeleteNotification_change=ns_obj.on_delete_item,
            on_PauseNotification_change=ns_obj.on_pause_item,
            on_ResumeNotification_change=ns_obj.on_resume_item,
            on_NotificationsDialogClosed_change=on_notifications_dialog_closed,
            # Wizard events (add mode)
            **wizard_handlers,
            # Edit dialog events
            **edit_dialog_handlers,
        )

    def _build_wizard_data(
        self,
        project_code: str,
        connections: list[dict],
        *,
        connection_id: str | None = None,
    ) -> tuple[dict, dict, typing.Callable]:
        steps = ["tableGroup", "testTableGroup", "runProfiling", "testSuite", "monitorSuite"]
        dialog = {"open": True, "title": "Add Table Group"}
        table_group_id = None

        def on_preview_table_group_clicked(payload: dict):
            table_group = payload["table_group"]
            verify_table_access = payload.get("verify_access") or False

            mark_for_preview(True)
            mark_for_access_preview(verify_table_access)
            set_table_group(table_group)

        def on_save_table_group_clicked(payload: dict):
            table_group: dict = payload["table_group"]
            table_group_verified: bool = payload.get("table_group_verified", False)
            run_profiling: bool = payload.get("run_profiling", False)
            standard_test_suite: dict | None = payload.get("standard_test_suite", None)
            monitor_test_suite: dict | None = payload.get("monitor_test_suite", None)

            mark_for_preview(True)
            set_save(True)
            set_table_group(table_group)
            set_standard_test_suite_data(standard_test_suite)
            set_monitor_test_suite_data(monitor_test_suite)
            set_table_group_verified(table_group_verified)
            set_run_profiling(run_profiling)

        def on_close_clicked(_params: dict) -> None:
            TableGroup.select_minimal_where.clear()
            for key in ["tg_wizard_mode", "tg_wizard_connection_id", "tg_wizard_table_group_id"]:
                st.session_state.pop(key, None)

        should_preview, mark_for_preview = temp_value("table_groups:preview:new", default=False)
        should_verify_access, mark_for_access_preview = temp_value("table_groups:preview_access:new", default=False)
        should_save, set_save = temp_value("table_groups:save:new", default=False)
        get_table_group, set_table_group = temp_value("table_groups:updated:new", default={})
        get_standard_test_suite_data, set_standard_test_suite_data = temp_value(
            "table_groups:test_suite_data:new",
            default={
                "generate": False,
                "name": "",
                "schedule": "",
                "timezone": "",
            },
        )
        get_monitor_test_suite_data, set_monitor_test_suite_data = temp_value(
            "table_groups:monitor_suite_data:new",
            default={
                "generate": False,
                "monitor_lookback": 0,
                "schedule": "",
                "timezone": "",
                "predict_sensitivity": 0,
                "predict_min_lookback": 0,
                "predict_exclude_weekends": False,
                "predict_holiday_codes": None,
            },
        )
        is_table_group_verified, set_table_group_verified = temp_value(
            "table_groups:new:verified",
            default=False,
        )
        should_run_profiling, set_run_profiling = temp_value(
            "table_groups:new:run_profiling",
            default=False,
        )
        standard_cron_sample_result, on_get_standard_cron_sample = get_cron_sample_handler("table_groups:new:standard_cron_expr_validation")
        monitor_cron_sample_result, on_get_monitor_cron_sample = get_cron_sample_handler("table_groups:new:monitor_cron_expr_validation")

        is_table_group_used = False
        wizard_connections = connections
        table_group = TableGroup(project_code=project_code)
        original_table_group_schema = None
        if table_group_id:
            table_group = TableGroup.get(table_group_id)
            original_table_group_schema = table_group.table_group_schema
            is_table_group_used = TableGroup.is_in_use([table_group_id])

        add_scorecard_definition = False
        for key, value in get_table_group().items():
            if key == "add_scorecard_definition":
                add_scorecard_definition = value
            else:
                setattr(table_group, key, value)

        table_group_preview = None
        save_data_chars = None

        if is_table_group_used:
            table_group.table_group_schema = original_table_group_schema

        if len(wizard_connections) == 1:
            table_group.connection_id = wizard_connections[0]["connection_id"]

        if not table_group.connection_id:
            if connection_id:
                table_group.connection_id = int(connection_id)
            elif len(wizard_connections) == 1:
                table_group.connection_id = wizard_connections[0]["connection_id"]
        elif table_group.id:
            wizard_connections = [
                conn for conn in wizard_connections
                if int(conn["connection_id"]) == int(table_group.connection_id)
            ]

        if should_preview():
            table_group_preview, save_data_chars = table_group_queries.get_table_group_preview(
                table_group,
                verify_table_access=should_verify_access(),
            )

        success = None
        message = ""
        run_profiling = False
        generate_test_suite = False
        generate_monitor_suite = False
        standard_test_suite = None
        monitor_test_suite = None
        if should_save():
            success = True
            if is_table_group_verified():
                try:
                    table_group.save(add_scorecard_definition)
                    if save_data_chars:
                        try:
                            save_data_chars(table_group.id)
                        except Exception:
                            LOG.exception("Data characteristics refresh encountered errors")

                    standard_test_suite_data = get_standard_test_suite_data() or {}
                    if standard_test_suite_data.get("generate"):
                        generate_test_suite = True
                        standard_test_suite = TestSuite(
                            project_code=project_code,
                            test_suite=standard_test_suite_data["name"],
                            connection_id=table_group.connection_id,
                            table_groups_id=table_group.id,
                            export_to_observability=False,
                            dq_score_exclude=False,
                            is_monitor=False,
                            monitor_lookback=0,
                            predict_min_lookback=0,
                        )
                        standard_test_suite.save()

                        JobSchedule(
                            project_code=project_code,
                            key=RUN_TESTS_JOB_KEY,
                            cron_expr=standard_test_suite_data["schedule"],
                            cron_tz=standard_test_suite_data["timezone"],
                            args=[],
                            kwargs={"test_suite_id": str(standard_test_suite.id)},
                        ).save()

                    monitor_test_suite_data = get_monitor_test_suite_data() or {}
                    if monitor_test_suite_data.get("generate"):
                        generate_monitor_suite = True
                        monitor_test_suite = TestSuite(
                            project_code=project_code,
                            test_suite=f"{table_group.table_groups_name} Monitors",
                            connection_id=table_group.connection_id,
                            table_groups_id=table_group.id,
                            export_to_observability=False,
                            dq_score_exclude=True,
                            is_monitor=True,
                            monitor_lookback=monitor_test_suite_data.get("monitor_lookback") or 14,
                            monitor_regenerate_freshness=monitor_test_suite_data.get("monitor_regenerate_freshness") or True,
                            predict_min_lookback=monitor_test_suite_data.get("predict_min_lookback") or 30,
                            predict_sensitivity=monitor_test_suite_data.get("predict_sensitivity") or "medium",
                            predict_exclude_weekends=monitor_test_suite_data.get("predict_exclude_weekends") or False,
                            predict_holiday_codes=monitor_test_suite_data.get("predict_holiday_codes") or None,
                        )
                        monitor_test_suite.save()
                        # Commit needed to make test suite visible to run_monitor_generation's separate DB connection
                        get_current_session().commit()
                        run_monitor_generation(monitor_test_suite.id, ["Volume_Trend", "Schema_Drift"])

                        JobSchedule(
                            project_code=project_code,
                            key=RUN_MONITORS_JOB_KEY,
                            cron_expr=monitor_test_suite_data.get("schedule"),
                            cron_tz=monitor_test_suite_data.get("timezone"),
                            args=[],
                            kwargs={"test_suite_id": str(monitor_test_suite.id)},
                        ).save()

                    if standard_test_suite or monitor_test_suite:
                        table_group.default_test_suite_id = standard_test_suite.id if standard_test_suite else None
                        table_group.monitor_test_suite_id = monitor_test_suite.id if monitor_test_suite else None
                        table_group.save()

                    if should_run_profiling():
                        run_profiling = True
                        try:
                            JobExecution.submit(
                                job_key="run-profile",
                                kwargs={"table_group_id": str(table_group.id)},
                                source="ui",
                                project_code=table_group.project_code,
                            )
                            message = f"Profiling run started for table group {table_group.table_groups_name}."
                        except Exception:
                            success = False
                            message = "Profiling run encountered errors"
                            LOG.exception(message)

                except IntegrityError as error:
                    get_current_session().rollback()
                    success = False
                    if "table_groups_name_unique" in str(error.orig):
                        message = "A Table Group with the same name already exists."
                    else:
                        message = "Something went wrong while creating the table group."
                        LOG.exception(message)
            else:
                success = False
                message = "Verify the table group before saving"

        data = {
            "project_code": project_code,
            "connections": wizard_connections,
            "table_group": table_group.to_dict(json_safe=True),
            "is_in_use": is_table_group_used,
            "table_group_preview": table_group_preview,
            "steps": steps,
            "dialog": dialog,
            "results": {
                "success": success,
                "message": message,
                "run_profiling": run_profiling,
                "generate_test_suite": generate_test_suite,
                "generate_monitor_suite": generate_monitor_suite,
                "test_suite_name": standard_test_suite.test_suite if standard_test_suite else None,
            } if success is not None else None,
            "standard_cron_sample": standard_cron_sample_result(),
            "monitor_cron_sample": monitor_cron_sample_result(),
        }

        handlers = {
            "on_PreviewTableGroupClicked_change": on_preview_table_group_clicked,
            "on_GetCronSampleAux_change": on_get_standard_cron_sample,
            "on_SaveTableGroupClicked_change": on_save_table_group_clicked,
            "on_CloseClicked_change": on_close_clicked,
        }

        return data, handlers, on_get_monitor_cron_sample

    def _build_edit_data(
        self,
        _project_code: str,
        connections: list[dict],
    ) -> tuple[dict, dict]:
        table_group_id = st.session_state.get("tg_wizard_table_group_id")

        should_preview, mark_for_preview = temp_value("table_groups:edit:preview", default=False)
        should_verify_access, mark_for_verify_access = temp_value("table_groups:edit:verify_access", default=False)
        should_save, mark_for_save = temp_value("table_groups:edit:save", default=False)
        get_edit_tg, set_edit_tg = temp_value("table_groups:edit:tg_data", default={})

        def on_preview_edit(payload: dict) -> None:
            set_edit_tg(payload["table_group"])
            mark_for_preview(True)
            mark_for_verify_access(payload.get("verify_access") or False)

        def on_save_edit(payload: dict) -> None:
            set_edit_tg(payload["table_group"])
            mark_for_preview(True)
            mark_for_save(True)

        def on_close_edit(_params: dict) -> None:
            for key in ["tg_wizard_mode", "tg_wizard_table_group_id"]:
                st.session_state.pop(key, None)

        table_group = TableGroup.get(table_group_id)
        original_schema = table_group.table_group_schema
        is_in_use = TableGroup.is_in_use([table_group_id])

        edit_tg_data = get_edit_tg()
        add_scorecard_definition = False
        for key, value in edit_tg_data.items():
            if key == "add_scorecard_definition":
                add_scorecard_definition = value
            else:
                setattr(table_group, key, value)

        if is_in_use:
            table_group.table_group_schema = original_schema

        edit_connections = connections
        if table_group.connection_id and table_group.id:
            edit_connections = [
                c for c in connections
                if int(c["connection_id"]) == int(table_group.connection_id)
            ]

        table_group_preview = None
        save_data_chars = None
        if should_preview():
            table_group_preview, save_data_chars = table_group_queries.get_table_group_preview(
                table_group,
                verify_table_access=should_verify_access(),
            )

        result = None
        if should_save():
            if table_group_preview and table_group_preview.get("success"):
                try:
                    table_group.save(add_scorecard_definition)
                except IntegrityError:
                    result = {"success": False, "message": "A Table Group with the same name already exists."}
                else:
                    if save_data_chars:
                        try:
                            save_data_chars(table_group.id)
                        except Exception:
                            LOG.exception("Data characteristics refresh encountered errors")
                    TableGroup.select_minimal_where.clear()
                    st.toast(f"Table group '{table_group.table_groups_name}' saved.", icon=":material/check:")
                    for key in ["tg_wizard_mode", "tg_wizard_table_group_id"]:
                        st.session_state.pop(key, None)
                    return None, {}
            else:
                result = {"success": False, "message": "Verify the table group before saving."}

        data = {
            "dialog": {"open": True, "title": "Edit Table Group"},
            "connections": edit_connections,
            "table_group": table_group.to_dict(json_safe=True),
            "is_in_use": is_in_use,
            "table_group_preview": table_group_preview,
            "result": result,
        }
        handlers = {
            "on_PreviewEditTableGroupClicked_change": on_preview_edit,
            "on_SaveEditTableGroupClicked_change": on_save_edit,
            "on_CloseEditClicked_change": on_close_edit,
        }
        return data, handlers

    def _get_connections(self, project_code: str, connection_id: str | None = None) -> list[dict]:
        if connection_id:
            connections = [Connection.get_minimal(connection_id)]
        else:
            connections = Connection.select_minimal_where(Connection.project_code == project_code)
        return [ format_connection(connection) for connection in connections ]

    def _format_table_group_list(
        self,
        table_groups: Iterable[TableGroupMinimal],
        connections: list[dict],
    ) -> list[dict]:
        connections_by_id = { con["connection_id"]: con for con in connections }
        formatted_list = []

        for table_group in table_groups:
            formatted_table_group = table_group.to_dict(json_safe=True)
            connection = connections_by_id[table_group.connection_id]

            flavors = [f for f in FLAVOR_OPTIONS if f.value == connection["sql_flavor_code"]]
            if flavors and (flavor := flavors[0]):
                formatted_table_group["connection"] = {
                    "name": connection["connection_name"],
                    "flavor": asdict(flavor),
                }

            formatted_list.append(formatted_table_group)

        return formatted_list

    @with_database_session
    def _prepare_delete_dialog(self, table_group_id: str) -> None:
        table_group = TableGroup.get_minimal(table_group_id)
        can_be_deleted = not TableGroup.is_in_use([table_group_id])
        st.session_state["tg_delete_dialog"] = {
            "open": True,
            "table_group": table_group.to_dict(json_safe=True),
            "can_be_deleted": can_be_deleted,
        }

    @with_database_session
    def _execute_delete(self, table_group_id: str) -> None:
        table_group_name = st.session_state.get("tg_delete_dialog", {}).get("table_group", {}).get("table_groups_name", "")
        if not (ProfilingRun.has_active_job_for(TableGroup, table_group_id) or TestRun.has_active_job_for(TableGroup, table_group_id)):
            TableGroup.cascade_delete([table_group_id])
            TableGroup.select_minimal_where.clear()
            st.toast(f"Table Group {table_group_name} has been deleted.", icon=":material/check:")
        else:
            st.toast("This Table Group is in use by a running process and cannot be deleted.", icon=":material/error:")
        st.session_state.pop("tg_delete_dialog", None)
