import logging
import time
from collections.abc import Iterable

from testgen.common.models.project import Project
from testgen.common.version_service import Version
from testgen.ui.components.utils.component import component
from testgen.ui.navigation.menu import Menu
from testgen.ui.navigation.router import Router
from testgen.ui.services import javascript_service, user_session_service
from testgen.ui.session import session

LOG = logging.getLogger("testgen")

SIDEBAR_KEY = "testgen:sidebar"
LOGOUT_PATH = "logout"


def sidebar(
    key: str = SIDEBAR_KEY,
    projects: Iterable[Project] | None = None,
    current_project: str | None = None,
    menu: Menu = None,
    current_page: str | None = None,
    username: str | None = None,
    role: str | None = None,
    version: Version | None = None,
    support_email: str | None = None,
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
            "projects": [ {"code": item.project_code, "name": item.project_name} for item in projects ],
            "current_project": current_project,
            "menu": menu.filter_for_current_user().sort_items().unflatten().asdict(),
            "current_page": current_page,
            "username": username,
            "role": role,
            "logout_path": LOGOUT_PATH,
            "version": version.__dict__,
            "support_email": support_email,
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

    # Prevent handling the same event multiple times
    event_id = event_data.get("_id")
    if event_id == session.sidebar_event_id:
        return
    session.sidebar_event_id = event_id

    if event_data.get("path") == LOGOUT_PATH:
        javascript_service.clear_component_states()
        user_session_service.end_user_session()
        Router().queue_navigation(to="")
        # Without the time.sleep, cookies sometimes don't get cleared on deployed instances 
        # (even though it works fine locally)
        time.sleep(0.3)
    else:
        Router().queue_navigation(
            to=event_data.get("path") or session.user_default_page,
            with_args=event_data.get("params", {}),
        )
