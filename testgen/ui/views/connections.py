import logging
import typing

import streamlit as st

from testgen.ui.components import widgets as testgen
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

    def render(self, project_code: str, **_kwargs) -> None:
        dataframe = connection_service.get_connections(project_code)
        connection = dataframe.iloc[0]

        testgen.page_header(
            "Connection",
            "https://docs.datakitchen.io/article/dataops-testgen-help/connect-your-database",
        )

        _, actions_column = st.columns([.1, .9])
        testgen.flex_row_end(actions_column)

        enable_table_groups = connection["project_host"] and connection["project_db"] and connection["project_qc_schema"]

        form_container = st.expander("", expanded=True)
        with form_container:
            mode = "edit"
            show_connection_form(connection, mode, project_code)

        if actions_column.button(
            "Configure QC Utility Schema",
            help="Creates the required Utility schema and related functions in the target database",
        ):
            create_qc_schema_dialog(connection)

        if actions_column.button(
            f":{'gray' if not enable_table_groups else 'green'}[Table Groups　→]",
            help="Create or edit Table Groups for the Connection",
        ):
            self.router.navigate(
                "connections:table-groups",
                {"connection_id": connection["connection_id"]},
            )
