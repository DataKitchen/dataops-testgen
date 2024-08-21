import logging
import typing

import streamlit as st

import testgen.ui.services.form_service as fm
import testgen.ui.services.toolbar_service as tb
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import connection_service
from testgen.ui.session import session
from testgen.ui.views.connections_base import create_qc_schema_dialog, show_connection_form

LOG = logging.getLogger("testgen")


class ConnectionsPage(Page):
    path = "connections"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="database", label="Data Configuration", order=3)

    def render(self) -> None:
        fm.render_page_header(
            "Connection",
            "https://docs.datakitchen.io/article/dataops-testgen-help/connect-your-database",
            lst_breadcrumbs=[
                {"label": "Overview", "path": "overview"},
                {"label": "Connection", "path": None},
            ],
        )

        project_code = session.project
        dataframe = connection_service.get_connections(project_code)
        connection = dataframe.iloc[0]

        tool_bar = tb.ToolBar(long_slot_count=6, short_slot_count=0, button_slot_count=0, prompt=None)

        enable_table_groups = connection["project_host"] and connection["project_db"] and connection["project_qc_schema"]

        form_container = st.expander("", expanded=True)
        with form_container:
            mode = "edit"
            show_connection_form(connection, mode, project_code)

        if tool_bar.long_slots[-1].button(
            f":{'gray' if not enable_table_groups else 'green'}[Table Groups　→]",
            help="Create or edit Table Groups for the Connection",
            use_container_width=True,
        ):
            st.session_state["connection"] = connection.to_dict()

            self.router.navigate(
                "connections:table-groups",
                {"connection_id": connection["connection_id"]},
            )

        _, col2 = st.columns([70, 30])

        if col2.button(
            "Configure QC Utility Schema",
            help="Creates the required Utility schema and related functions in the target database",
            use_container_width=True,
        ):
            create_qc_schema_dialog(connection)
