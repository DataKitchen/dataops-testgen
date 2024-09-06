import typing

import streamlit as st

from testgen.commands.run_observability_exporter import test_observability_exporter
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import form_service, project_service
from testgen.ui.session import session
from testgen.ui.views.app_log_modal import view_log_file


class ProjectSettingsPage(Page):
    path = "settings"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: session.project is not None or "overview",
    ]
    menu_item = MenuItem(icon="settings", label="Settings", order=100)

    def render(self, project_code: str | None = None, **_kwargs) -> None:
        project = project_service.get_project_by_code(project_code or session.project)

        testgen.page_header(
            "Settings",
            "https://docs.datakitchen.io/article/dataops-testgen-help/configuration",
        )

        testgen.whitespace(1)
        form_service.render_edit_form(
            "",
            project,
            "projects",
            project.keys(),
            ["id"],
            form_unique_key="project-settings",
        )

        _, col2, col3 = st.columns([50, 25, 25])
        if col2.button("Test Observability Connection", use_container_width=False):
            status = st.empty()
            status.info("Testing your connection to DataKitchen Observability...")
            try:
                project_code = project["project_code"]
                api_url = project["observability_api_url"]
                api_key = project["observability_api_key"]
                test_observability_exporter(project_code, api_url, api_key)
                status.empty()
                status.success("The Observability connection test was successful.")
            except Exception as e:
                status.empty()
                status.error("An error occurred during the Observability connection test.")
                error_message = e.args[0]
                st.text_area("Error Details", value=error_message)

        view_log_file(col3)


def set_add_new_project():
    session.add_project = True


def set_edit_current_project():
    session.add_project = False
