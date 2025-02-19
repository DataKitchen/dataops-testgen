import logging

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
    project: str | None = None,
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
            "project": project,
            "username": username,
            "menu": menu.filter_for_current_user().sort_items().unflatten().asdict(),
            "current_page": current_page,
            "logout_path": LOGOUT_PATH,
        },
        key=key,
        on_change=on_change,
    )

def on_change():
    # We cannot navigate directly here
    # because st.switch_page uses st.rerun under the hood
    # and we get a "Calling st.rerun() within a callback is a noop" error
    # So we store the path and navigate on the next run

    path = getattr(session, SIDEBAR_KEY)
    if path == LOGOUT_PATH:
        javascript_service.clear_component_states()
        user_session_service.end_user_session()
        Router().queue_navigation(to="", with_args={ "project_code": session.project })
    else:
        Router().queue_navigation(to=path, with_args={ "project_code": session.project })
