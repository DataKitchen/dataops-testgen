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

    if session.page_pending_sidebar is not None:
        path = session.page_pending_sidebar
        session.page_pending_sidebar = None
        params = { "project_code": session.project } if path != "" else {}
        Router().navigate(to=path, with_args=params)

    component(
        id_="sidebar",
        props={
            "username": username,
            "menu": menu.filter_for_current_user().sort_items().asdict(),
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
        session.page_pending_sidebar = ""
    else:
        session.page_pending_sidebar = path
