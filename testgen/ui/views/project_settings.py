import random
import typing
from dataclasses import asdict, dataclass, field

import streamlit as st

from testgen.commands.run_observability_exporter import test_observability_exporter
from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.session import session, temp_value

PAGE_TITLE = "Project Settings"


class ProjectSettingsPage(Page):
    path = "settings"
    permission = "administer"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="settings",
        label=PAGE_TITLE,
        section="Settings",
        order=0,
    )

    project: Project | None = None
    existing_names: list[str] | None = None

    def render(self, project_code: str | None = None, **_kwargs) -> None:
        self.project = Project.get(project_code)

        testgen.page_header(
            PAGE_TITLE,
            "manage-projects/",
        )

        get_test_results, set_test_results = temp_value(f"project_settings:{project_code}", default=None)

        def on_observability_connection_test(payload: dict) -> None:
            results = self.test_observability_connection(project_code, payload)
            set_test_results(asdict(results))

        return testgen.project_settings(
            key="project_settings",
            data={
                "name": self.project.project_name,
                "observability_api_url": self.project.observability_api_url,
                "observability_api_key": self.project.observability_api_key,
                "observability_test_results": get_test_results(),
            },
            on_TestObservabilityClicked_change=on_observability_connection_test,
            on_SaveClicked_change=lambda payload: self.update_project(project_code, payload),
        )

    @with_database_session
    def update_project(self, project_code: str, edited_project: dict) -> None:
        existing_names = [
            p.project_name.lower() for p in Project.select_where(Project.project_code != project_code)
        ]
        new_project_name = edited_project["name"]
        if new_project_name.lower() in existing_names:
            raise ValueError(f"Another project named {new_project_name} exists")

        self.project.project_name = new_project_name
        self.project.observability_api_url = edited_project.get("observability_api_url")
        self.project.observability_api_key = edited_project.get("observability_api_key")
        self.project.save()
        Project.clear_cache()

    def test_observability_connection(self, project_code: str, edited_project: dict) -> "ObservabilityConnectionStatus":
        try:
            test_observability_exporter(
                project_code,
                edited_project.get("observability_api_url"),
                edited_project.get("observability_api_key"),
            )
            return ObservabilityConnectionStatus(successful=True, message="The connection was successful.")
        except Exception as e:
            error_message = e.args[0]
            return ObservabilityConnectionStatus(
                successful=False,
                message="Error attempting the connection",
                details=error_message,
            )


@dataclass(frozen=True, slots=True)
class ObservabilityConnectionStatus:
    message: str
    successful: bool
    details: str | None = field(default=None)
    _: float = field(default_factory=random.random)
