import logging
from typing import Literal

from testgen.ui.components.utils.component import component
from testgen.ui.navigation.menu import Menu
from testgen.ui.navigation.router import Router
from testgen.ui.services import javascript_service, project_service, user_session_service
from testgen.ui.session import session
from testgen.ui.views.dialogs.application_logs_dialog import application_logs_dialog

LOG = logging.getLogger("testgen")

SIDEBAR_KEY = "testgen:sidebar"
LOGOUT_PATH = "logout"


def sidebar(
    key: str = SIDEBAR_KEY,
    projects: list[dict[Literal["name", "codde"], str]] | None = None,
    current_project: str | None = None,
    username: str | None = None,
    menu: Menu = None,
    current_page: str | None = None,
) -> None:
    """
    Testgen custom component to display a styled menu over streamlit's
    sidebar.

    # Parameters
    :param key: unique key to give the component a persisting state
    :param username: username to display at the bottom of the menu
    :param menu: menu object with all root pages
    :param current_page: page address to highlight the selected item
    """
    component(
        id_="sidebar",
        props={
            "projects": projects,
            "current_project": current_project,
            "username": username,
            "menu": menu.filter_for_current_user().sort_items().unflatten().asdict(),
            "current_page": current_page,
            "logout_path": LOGOUT_PATH,
            "permissions": {
                "can_edit": user_session_service.user_can_edit(),
            },
        },
        key=key,
        on_change=on_change,
    )

def on_change():
    # We cannot navigate directly here
    # because st.switch_page uses st.rerun under the hood
    # and we get a "Calling st.rerun() within a callback is a noop" error
    # So we store the path and navigate on the next run

    event_data = getattr(session, SIDEBAR_KEY)
    project = event_data.get("project")
    path = event_data.get("path")
    view_logs = event_data.get("view_logs")

    if project:
        project_service.set_current_project(project)
        Router().queue_navigation(to="")

    if path:
        if path == LOGOUT_PATH:
            javascript_service.clear_component_states()
            user_session_service.end_user_session()
            Router().queue_navigation(to="", with_args={ "project_code": session.project })
        else:
            Router().queue_navigation(to=path, with_args={ "project_code": session.project })

    if view_logs:
        application_logs_dialog()
