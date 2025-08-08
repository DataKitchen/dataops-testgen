import logging
import typing
from collections.abc import Iterable
from dataclasses import asdict
from functools import partial

import streamlit as st
from sqlalchemy.exc import IntegrityError

from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import table_group_queries
from testgen.ui.services import user_session_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.connections import FLAVOR_OPTIONS, format_connection
from testgen.ui.views.profiling_runs import ProfilingScheduleDialog

LOG = logging.getLogger("testgen")
PAGE_TITLE = "Table Groups"


class TableGroupsPage(Page):
    path = "table-groups"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="table_view",
        label=PAGE_TITLE,
        section="Data Configuration",
        order=0,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str, connection_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(PAGE_TITLE, "create-a-table-group")

        user_can_edit = user_session_service.user_can_edit()
        project_summary = Project.get_summary(project_code)
        if connection_id and not connection_id.isdigit():
            connection_id = None

        if connection_id:
            table_groups = TableGroup.select_minimal_where(
                TableGroup.project_code == project_code,
                TableGroup.connection_id == connection_id,
            )
        else:
            table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)

        connections = self._get_connections(project_code)

        return testgen.testgen_component(
            "table_group_list",
            props={
                "project_summary": project_summary.to_dict(json_safe=True),
                "connection_id": connection_id,
                "permissions": {
                    "can_edit": user_can_edit,
                },
                "connections": connections,
                "table_groups": self._format_table_group_list(table_groups, connections),
            },
            on_change_handlers={
                "RunSchedulesClicked": lambda *_: ProfilingScheduleDialog().open(project_code),
                "AddTableGroupClicked": partial(self.add_table_group_dialog, project_code, connection_id),
                "EditTableGroupClicked": partial(self.edit_table_group_dialog, project_code),
                "DeleteTableGroupClicked": partial(self.delete_table_group_dialog, project_code),
                "RunProfilingClicked": partial(self.run_profiling_dialog, project_code),
                "ConnectionSelected": lambda inner_connection_id: self.router.queue_navigation(
                    to="table-groups",
                    with_args={"project_code": project_code, "connection_id": inner_connection_id},
                ),
            },
        )

    @st.dialog(title="Add Table Group")
    @with_database_session
    def add_table_group_dialog(self, project_code: str, connection_id: str | None, *_args):
        return self._table_group_wizard(
            project_code,
            connection_id=connection_id,
            steps=[
                "tableGroup",
                "testTableGroup",
                "runProfiling",
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

            set_save(True)
            set_table_group(table_group)
            set_table_group_verified(table_group_verified)
            set_run_profiling(run_profiling)

        def on_go_to_profiling_runs(params: dict) -> None:
            set_navigation_params({ **params, "project_code": project_code })

        get_navigation_params, set_navigation_params = temp_value(
            "connections:new_table_group:go_to_profiling_run",
            default=None,
        )
        if (params := get_navigation_params()):
            self.router.navigate(to="profiling-runs", with_args=params)

        should_preview, mark_for_preview = temp_value("table_groups:preview:new", default=False)
        should_verify_access, mark_for_access_preview = temp_value("table_groups:preview_access:new", default=False)
        should_save, set_save = temp_value("table_groups:save:new", default=False)
        get_table_group, set_table_group = temp_value("table_groups:updated:new", default={})
        is_table_group_verified, set_table_group_verified = temp_value(
            "table_groups:new:verified",
            default=False,
        )
        should_run_profiling, set_run_profiling = temp_value(
            "table_groups:new:run_profiling",
            default=False,
        )

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
            table_group_preview = table_group_queries.get_table_group_preview(
                table_group,
                verify_table_access=should_verify_access(),
            )

        success = None
        message = ""
        if should_save():
            success = True
            if is_table_group_verified():
                try:
                    table_group.save(add_scorecard_definition)
                    if should_run_profiling():
                        try:
                            run_profiling_in_background(table_group.id)
                            message = f"Profiling run started for table group {table_group.table_groups_name}."
                        except Exception:
                            success = False
                            message = "Profiling run encountered errors"
                            LOG.exception(message)
                    else:
                        st.rerun()
                except IntegrityError:
                    success = False
                    message = "A Table Group with the same name already exists."
            else:
                success = False
                message = "Verify the table group before saving"

        return testgen.testgen_component(
            "table_group_wizard",
            props={
                "project_code": project_code,
                "connections": connections,
                "table_group": table_group.to_dict(json_safe=True),
                "is_in_use": is_table_group_used,
                "table_group_preview": table_group_preview,
                "steps": steps,
                "results": {
                    "success": success,
                    "message": message,
                    "table_group_id": str(table_group.id),
                } if success is not None else None,
            },
            on_change_handlers={
                "PreviewTableGroupClicked": on_preview_table_group_clicked,
                "SaveTableGroupClicked": on_save_table_group_clicked,
                "GoToProfilingRunsClicked": on_go_to_profiling_runs,
            },
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

    @st.dialog(title="Run Profiling")
    def run_profiling_dialog(self, project_code: str, table_group_id: str) -> None:
        def on_go_to_profiling_runs_clicked(table_group_id: str) -> None:
            set_navigation_params({ "project_code": project_code, "table_group_id": table_group_id })

        def on_run_profiling_confirmed(*_args) -> None:
            set_run_profiling(True)

        get_navigation_params, set_navigation_params = temp_value(
            f"table_groups:{table_group_id}:go_to_profiling_run",
            default=None,
        )
        if (params := get_navigation_params()):
            self.router.navigate(to="profiling-runs", with_args=params)

        should_run_profiling, set_run_profiling = temp_value(
            f"table_groups:{table_group_id}:run_profiling",
            default=False,
        )

        table_group = TableGroup.get_minimal(table_group_id)
        result = None
        if should_run_profiling():
            success = True
            message = "Profiling run started"

            try:
                run_profiling_in_background(table_group_id)
            except Exception as error:
                success = False
                message = f"Profiling run encountered errors: {error!s}."
            result = {"success": success, "message": message}

        return testgen.testgen_component(
            "run_profiling_dialog",
            props={
                "project_code": project_code,
                "table_group": table_group.to_dict(json_safe=True),
                "result": result,
            },
            on_change_handlers={
                "GoToProfilingRunsClicked": on_go_to_profiling_runs_clicked,
                "RunProfilingConfirmed": on_run_profiling_confirmed,
            },
        )

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
