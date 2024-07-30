import dataclasses
import logging
import typing

import streamlit as st

from testgen.ui.components.utils.callbacks import register_callback
from testgen.ui.components.utils.component import component
from testgen.ui.navigation.menu import Menu
from testgen.ui.services import authentication_service

LOG = logging.getLogger("testgen")


def sidebar(
    key: str = "testgen:sidebar",
    username: str | None = None,
    menu: Menu = None,
    current_page: str | None = None,
    current_project: str | None = None,
    on_logout: typing.Callable[[], None] | None = None,
) -> None:
    """
    Testgen custom component to display a styled menu over streamlit's
    sidebar.

    # Parameters
    :param key: unique key to give the component a persisting state
    :param username: username to display at the bottom of the menu
    :param menu: menu object with all root pages
    :param current_page: page address to highlight the selected item
    :param on_logout: callback for when user clicks logout
    :param on_project_changed: callback for when user switches projects
    """
    register_callback(key, _handle_callbacks, key, on_logout)

    component(
        id_="sidebar",
        props={
            "username": username,
            "menu": menu.filter_for_current_user().sort_items().asdict(),
            "current_page": current_page,
            "current_project": current_project,
            "auth_cookie_name": authentication_service.AUTH_TOKEN_COOKIE_NAME,
        },
        key=key,
        default={},
    )


def _handle_callbacks(
    key: str,
    on_logout: typing.Callable[[], None] | None = None,
):
    action = st.session_state[key]
    action = MenuAction(**action)

    if action.logout and on_logout:
        return on_logout()


class Project(typing.TypedDict):
    code: str
    name: str


@dataclasses.dataclass
class MenuAction:
    logout: bool | None = None
