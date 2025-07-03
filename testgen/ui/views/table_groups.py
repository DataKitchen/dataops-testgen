import typing
from dataclasses import asdict
from functools import partial

import streamlit as st
from sqlalchemy.exc import IntegrityError

import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.table_group_service as table_group_service
from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.common.models import with_database_session
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import user_session_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.connections import FLAVOR_OPTIONS, format_connection

PAGE_TITLE = "Table Groups"


class TableGroupsPage(Page):
    path = "table-groups"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
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
        if connection_id:
            table_groups = table_group_service.get_by_connection(project_code, connection_id)
        else:
            table_groups = table_group_service.get_all(project_code)

        return testgen.testgen_component(
            "table_group_list",
            props={
                "project_code": project_code,
                "connection_id": connection_id,
                "permissions": {
                    "can_edit": user_can_edit,
                },
                "connections": self._get_connections(project_code),
                "table_groups": self._format_table_group_list([
                    table_group.to_dict() for _, table_group in table_groups.iterrows()
                ]),
            },
            on_change_handlers={
                "AddTableGroupClicked": partial(self.add_table_group_dialog, project_code),
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
    def add_table_group_dialog(self, project_code, *_args):
        def on_preview_table_group_clicked(table_group: dict):
            mark_for_preview(True)
            set_table_group(table_group)

        def on_save_table_group_clicked(table_group: dict):
            set_save(True)
            set_table_group(table_group)

        should_preview, mark_for_preview = temp_value("table_groups:preview:new", default=False)
        should_save, set_save = temp_value("table_groups:save:new", default=False)
        get_table_group, set_table_group = temp_value("table_groups:updated:new", default={})

        connections = self._get_connections(project_code)
        table_group = {
            "project_code": project_code,
            **get_table_group(),
        }
        table_group_preview = {}
        result = None

        if len(connections) == 1:
            table_group["connection_id"] = connections[0]["connection_id"]

        if should_save():
            try:
                table_group_service.add(table_group)
                st.rerun()
            except IntegrityError:
                result = {"success": False, "message": "A Table Group with the same name already exists."}

        if should_preview():
            table_group_preview = self._get_table_group_preview(project_code, table_group["connection_id"], {"id": "temp", **table_group})

        return testgen.testgen_component(
            "table_group",
            props={
                "project_code": project_code,
                "connections": connections,
                "table_group": table_group,
                "table_group_preview": table_group_preview,
                "result": result,
            },
            on_change_handlers={
                "PreviewTableGroupClicked": on_preview_table_group_clicked,
                "TableGroupSaveClicked": on_save_table_group_clicked,
            },
        )

    @st.dialog(title="Edit Table Group")
    def edit_table_group_dialog(self, project_code: str, table_group_id: str):
        def on_preview_table_group_clicked(table_group: dict):
            mark_for_preview(True)
            set_updated_table_group(table_group)

        def on_save_table_group_clicked(table_group: dict):
            set_update(True)
            set_updated_table_group(table_group)

        should_preview, mark_for_preview = temp_value(
            f"table_groups:preview:{table_group_id}",
            default=False,
        )
        should_update, set_update = temp_value(
            f"table_groups:save:{table_group_id}",
            default=False,
        )
        get_updated_table_group, set_updated_table_group = temp_value(
            f"table_groups:updated:{table_group_id}",
            default={},
        )

        table_group = {
            **table_group_service.get_by_id(table_group_id=table_group_id).to_dict(),
            **get_updated_table_group(),
        }
        table_group_preview = {
            "schema": table_group["table_group_schema"],
        }
        result = None

        if should_update():
            try:
                table_group_service.edit(table_group)
                st.rerun()
            except IntegrityError:
                result = {"success": False, "message": "A Table Group with the same name already exists."}

        if should_preview():
            table_group_preview = self._get_table_group_preview(project_code, table_group["connection_id"], table_group)

        return testgen.testgen_component(
            "table_group",
            props={
                "project_code": project_code,
                "connections": self._get_connections(project_code, connection_id=table_group["connection_id"]),
                "table_group": table_group,
                "table_group_preview": table_group_preview,
                "result": result,
            },
            on_change_handlers={
                "PreviewTableGroupClicked": on_preview_table_group_clicked,
                "TableGroupSaveClicked": on_save_table_group_clicked,
            },
        )

    def _get_connections(self, project_code: str, connection_id: str | None = None) -> list[dict]:
        if connection_id:
            connections = [connection_service.get_by_id(connection_id, hide_passwords=True)]
        else:
            connections = [
                connection for _, connection in connection_service.get_connections(
                    project_code, hide_passwords=True
                ).iterrows()
            ]
        return [ format_connection(connection) for connection in connections ]

    def _format_table_group_list(self, table_groups: list[dict]) -> list[dict]:
        for table_group in table_groups:
            flavors = [f for f in FLAVOR_OPTIONS if f.value == table_group["sql_flavor_code"]]
            if flavors and (flavor := flavors[0]):
                table_group["connection"] = {
                    "name": table_group["connection_name"],
                    "flavor": asdict(flavor),
                }
        return table_groups

    def _get_table_group_preview(self, project_code: str, connection_id: str | None, table_group: dict) -> dict:
        table_group_preview = {
            "schema": table_group["table_group_schema"],
            "tables": set(),
            "column_count": 0,
            "success": True,
            "message": None,
        }
        if connection_id:
            try:
                table_group_results = table_group_service.test_table_group(table_group, connection_id, project_code)

                for column in table_group_results:
                    table_group_preview["schema"] = column["table_schema"]
                    table_group_preview["tables"].add(column["table_name"])
                    table_group_preview["column_count"] += 1

                if len(table_group_results) <= 0:
                    table_group_preview["success"] = False
                    table_group_preview["message"] = (
                        "No tables found matching the criteria. Please check the Table Group configuration."
                    )
            except Exception as error:
                table_group_preview["success"] = False
                table_group_preview["message"] = error.args[0]
        else:
            table_group_preview["success"] = False
            table_group_preview["message"] = "No connection selected. Please select a connection to preview the Table Group."

        table_group_preview["tables"] = list(table_group_preview["tables"])
        return table_group_preview

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

        table_group = table_group_service.get_by_id(table_group_id).to_dict()
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
                "table_group": table_group,
                "result": result,
            },
            on_change_handlers={
                "GoToProfilingRunsClicked": on_go_to_profiling_runs_clicked,
                "RunProfilingConfirmed": on_run_profiling_confirmed,
            },
        )

    @st.dialog(title="Delete Table Group")
    def delete_table_group_dialog(self, project_code: str, table_group_id: str):
        def on_delete_confirmed(*_args):
            confirm_deletion(True)

        table_group = table_group_service.get_by_id(table_group_id=table_group_id)
        table_group_name = table_group["table_groups_name"]
        can_be_deleted = table_group_service.cascade_delete([table_group_name], dry_run=True)
        is_deletion_confirmed, confirm_deletion = temp_value(
            f"table_groups:confirm_delete:{table_group_id}",
            default=False,
        )
        success = False
        message = None

        result = None
        if is_deletion_confirmed():
            if not table_group_service.are_table_groups_in_use([table_group_name]):
                table_group_service.cascade_delete([table_group_name])
                message = f"Table Group {table_group_name} has been deleted. "
                st.rerun()
            else:
                message = "This Table Group is in use by a running process and cannot be deleted."
            result = {"success": success, "message": message},

        testgen.testgen_component(
            "table_group_delete",
            props={
                "project_code": project_code,
                "table_group": table_group.to_dict(),
                "can_be_deleted": can_be_deleted,
                "result": result,
            },
            on_change_handlers={
                "DeleteTableGroupConfirmed": on_delete_confirmed,
            },
        )
