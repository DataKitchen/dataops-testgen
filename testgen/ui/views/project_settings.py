import time
import typing
from functools import partial

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from testgen.commands.run_observability_exporter import test_observability_exporter
from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import user_session_service
from testgen.ui.session import session

PAGE_TITLE = "Project Settings"


class ProjectSettingsPage(Page):
    path = "settings"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: user_session_service.user_is_admin(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="settings",
        label=PAGE_TITLE,
        section="Settings",
        order=0,
        roles=[ "admin" ],
    )

    project: Project | None = None
    existing_names: list[str] | None = None

    def render(self, project_code: str | None = None, **_kwargs) -> None:
        self.project = Project.get(project_code)

        testgen.page_header(
            PAGE_TITLE,
            "tg-project-settings",
        )

        testgen.whitespace(1)
        self.show_edit_form()

    def show_edit_form(self) -> None:
        form_container = st.container()
        status_container = st.container()

        with form_container:
            with testgen.card():
                name_input = st.text_input(
                    label="Project Name",
                    value=self.project.project_name,
                    max_chars=30,
                    key="project_settings:keys:project_name",
                )
                st.text_input(
                    label="Observability API URL",
                    value=self.project.observability_api_url,
                    key="project_settings:keys:observability_api_url",
                )
                st.text_input(
                    label="Observability API Key",
                    value=self.project.observability_api_key,
                    key="project_settings:keys:observability_api_key",
                )

                testgen.whitespace(1)
                test_button_column, warning_column, save_button_column = st.columns([.4, .3, .3])
                testgen.flex_row_start(test_button_column)
                testgen.flex_row_end(save_button_column)

                with test_button_column:
                    testgen.button(
                        type_="stroked",
                        color="basic",
                        label="Test Observability Connection",
                        width=250,
                        on_click=partial(self._display_connection_status, status_container),
                        key="project-settings:keys:test-connection",
                    )

                with warning_column:
                    if not name_input:
                        testgen.text("Project name is required", "color: var(--red)")
                    elif self.existing_names and name_input in self.existing_names:
                        testgen.text("Project name in use", "color: var(--red)")

                with save_button_column:
                    testgen.button(
                        type_="flat",
                        label="Save",
                        width=100,
                        on_click=self.edit_project,
                        key="project-settings:keys:edit",
                    )

    @with_database_session
    def edit_project(self) -> None:
        edited_project = self._get_edited_project()
        if edited_project["project_name"] and (not self.existing_names or edited_project["project_name"] not in self.existing_names):
            self.project.project_name = edited_project["project_name"]
            self.project.observability_api_url = edited_project["observability_api_url"]
            self.project.observability_api_key = edited_project["observability_api_key"]
            self.project.save()
            st.toast("Changes have been saved.")

    def _get_edited_project(self) -> None:
        edited_project = {
            "id": self.project.id,
            "project_code": self.project.project_code,
        }
        # We have to get the input widget values from the session state
        # The return values for st.text_input do not reflect the latest user input if the button is clicked without unfocusing the input
        # https://discuss.streamlit.io/t/issue-with-modifying-text-using-st-text-input-and-st-button/56619/5
        for key in [ "project_name", "observability_api_url", "observability_api_key" ]:
            value = st.session_state.get(f"project_settings:keys:{key}")
            edited_project[key] = value.strip() if value else None
        return edited_project

    def _display_connection_status(self, status_container: DeltaGenerator) -> None:
        single_element_container = status_container.empty()
        single_element_container.info("Connecting ...")

        try:
            project = self._get_edited_project()
            test_observability_exporter(
                project["project_code"],
                project["observability_api_url"],
                project["observability_api_key"],
            )
            single_element_container.success("The connection was successful.")
        except Exception as e:
            with single_element_container.container():
                st.error("Error attempting the connection.")
                error_message = e.args[0]
                st.caption("Connection Error Details")
                with st.container(border=True):
                    st.markdown(error_message)

        time.sleep(0.1)
