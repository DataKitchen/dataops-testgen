import logging
import typing

import streamlit as st

import testgen.ui.services.form_service as fm
import testgen.ui.services.toolbar_service as tb
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import connection_service
from testgen.ui.session import session
from testgen.ui.views.connections_base import show_connection, show_create_qc_schema_modal

LOG = logging.getLogger("testgen")


class ConnectionsPage(Page):
    path = "connections"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status or "login",
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
            connection_modal = None
            mode = "edit"
            show_connection(connection_modal, connection, mode, project_code, show_header=False)

        if tool_bar.long_slots[-1].button(
            f":{'gray' if not enable_table_groups else 'green'}[Table Groups　→]",
            help="Create or edit Table Groups for the Connection",
            use_container_width=True,
        ):
            st.session_state["connection"] = connection.to_dict()

            session.current_page = "connections/table-groups"
            session.current_page_args = {"connection_id": connection["connection_id"]}
            st.experimental_rerun()

        create_qc_schema_modal = testgen.Modal(title=None, key="dk-create-qc-schema-modal", max_width=1100)

        _, col2 = st.columns([70, 30])

        if col2.button(
            "Configure QC Utility Schema",
            help="Creates the required Utility schema and related functions in the target database",
            use_container_width=True,
        ):
            create_qc_schema_modal.open()

        if create_qc_schema_modal.is_open():
            show_create_qc_schema_modal(create_qc_schema_modal, connection)
