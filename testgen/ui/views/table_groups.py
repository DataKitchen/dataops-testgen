import logging
import typing
from collections.abc import Iterable
from dataclasses import asdict
from functools import partial

import streamlit as st
from sqlalchemy.exc import IntegrityError

from testgen.commands.run_profiling import run_profiling_in_background
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.project import Project
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, RUN_TESTS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import table_group_queries
from testgen.ui.session import session, temp_value
from testgen.ui.utils import get_cron_sample_handler
from testgen.ui.views.connections import FLAVOR_OPTIONS, format_connection
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog
from testgen.ui.views.profiling_runs import ProfilingScheduleDialog, manage_notifications

LOG = logging.getLogger("testgen")
PAGE_TITLE = "Table Groups"


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
        testgen.page_header(PAGE_TITLE, "create-a-table-group")

        user_can_edit = session.auth.user_has_permission("edit")
        project_summary = Project.get_summary(project_code)
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

        def on_add_table_group_clicked(*_args) -> None:
            table_group_queries.reset_table_group_preview()
            self.add_table_group_dialog(project_code, connection_id)

        def on_edit_table_group_clicked(table_group_id: str) -> None:
            table_group_queries.reset_table_group_preview()
            self.edit_table_group_dialog(project_code, table_group_id)

        return testgen.testgen_component(
            "table_group_list",
            props={
                "project_summary": project_summary.to_dict(json_safe=True),
                "connection_id": connection_id,
                "table_group_name": table_group_name,
                "permissions": {
                    "can_edit": user_can_edit,
                },
                "connections": connections,
                "table_groups": self._format_table_group_list(table_groups, connections),
            },
            on_change_handlers={
                "RunSchedulesClicked": lambda *_: ProfilingScheduleDialog().open(project_code),
                "RunNotificationsClicked": manage_notifications(project_code),
                "AddTableGroupClicked": on_add_table_group_clicked,
                "EditTableGroupClicked": on_edit_table_group_clicked,
                "DeleteTableGroupClicked": partial(self.delete_table_group_dialog, project_code),
                "RunProfilingClicked": partial(run_profiling_dialog, project_code),
                "TableGroupsFiltered": lambda params: self.router.queue_navigation(
                    to="table-groups",
                    with_args={"project_code": project_code, **params},
                ),
            },
        )

    @st.dialog(title="Add Table Group")
    @with_database_session
    def add_table_group_dialog(self, project_code: str, connection_id: str | None):
        return self._table_group_wizard(
            project_code,
            connection_id=connection_id,
            steps=[
                "tableGroup",
                "testTableGroup",
                "runProfiling",
                "testSuite",
                "monitorSuite",
            ],
        )

    @st.dialog(title="Edit Table Group")
    @with_database_session
    def edit_table_group_dialog(self, project_code: str, table_group_id: str):
        return self._table_group_wizard(
            project_code,
            table_group_id=table_group_id,
            steps=[
                "tableGroup",
                "testTableGroup",
            ],
        )

    def _table_group_wizard(
        self,
        project_code: str,
        *,
        steps: list[str] | None = None,
        connection_id: str | None = None,
        table_group_id: str | None = None,
    ):
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
            set_close_dialog(True)

        get_close_dialog, set_close_dialog = temp_value("table_groups:close:new", default=False)
        if (get_close_dialog()):
            st.rerun()

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
        connections = self._get_connections(project_code)
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

        if len(connections) == 1:
            table_group.connection_id = connections[0]["connection_id"]

        if not table_group.connection_id:
            if connection_id:
                table_group.connection_id = int(connection_id)
            elif len(connections) == 1:
                table_group.connection_id = connections[0]["connection_id"]
        elif table_group.id:
            connections = [
                conn for conn in connections
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
                            predict_min_lookback=monitor_test_suite_data.get("predict_min_lookback") or 30,
                            predict_sensitivity=monitor_test_suite_data.get("predict_sensitivity") or "medium",
                            predict_exclude_weekends=monitor_test_suite_data.get("predict_exclude_weekends") or False,
                            predict_holiday_codes=monitor_test_suite_data.get("predict_holiday_codes") or None,
                        )
                        monitor_test_suite.save()

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
                            run_profiling_in_background(table_group.id)
                            message = f"Profiling run started for table group {table_group.table_groups_name}."
                        except Exception:
                            success = False
                            message = "Profiling run encountered errors"
                            LOG.exception(message)

                except IntegrityError:
                    success = False
                    message = "A Table Group with the same name already exists."
            else:
                success = False
                message = "Verify the table group before saving"

        return testgen.table_group_wizard(
            key="add_tg_wizard",
            data={
                "project_code": project_code,
                "connections": connections,
                "table_group": table_group.to_dict(json_safe=True),
                "is_in_use": is_table_group_used,
                "table_group_preview": table_group_preview,
                "steps": steps,
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
            },
            on_PreviewTableGroupClicked_change=on_preview_table_group_clicked,
            on_GetCronSample_change=on_get_monitor_cron_sample,
            on_GetCronSampleAux_change=on_get_standard_cron_sample,
            on_SaveTableGroupClicked_change=on_save_table_group_clicked,
            on_CloseClicked_change=on_close_clicked,
        )

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

    @st.dialog(title="Delete Table Group")
    @with_database_session
    def delete_table_group_dialog(self, project_code: str, table_group_id: str):
        def on_delete_confirmed(*_args):
            confirm_deletion(True)

        table_group = TableGroup.get_minimal(table_group_id)
        can_be_deleted = not TableGroup.is_in_use([table_group_id])
        is_deletion_confirmed, confirm_deletion = temp_value(
            f"table_groups:confirm_delete:{table_group_id}",
            default=False,
        )
        success = False
        message = None

        result = None
        if is_deletion_confirmed():
            if not TableGroup.has_running_process([table_group_id]):
                TableGroup.cascade_delete([table_group_id])
                message = f"Table Group {table_group.table_groups_name} has been deleted. "
                st.rerun()
            else:
                message = "This Table Group is in use by a running process and cannot be deleted."
            result = {"success": success, "message": message}

        testgen.testgen_component(
            "table_group_delete",
            props={
                "project_code": project_code,
                "table_group": table_group.to_dict(json_safe=True),
                "can_be_deleted": can_be_deleted,
                "result": result,
            },
            on_change_handlers={
                "DeleteTableGroupConfirmed": on_delete_confirmed,
            },
        )
