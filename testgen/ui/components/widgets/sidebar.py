import logging
import time
from collections.abc import Iterable

from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.common.version_service import Version
from testgen.ui.navigation.menu import Menu
from testgen.ui.navigation.router import Router
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
    version: Version | None = None,
    support_email: str | None = None,
    global_context: bool = False,
    is_global_admin: bool = False,
) -> None:
    """
    Testgen custom component to display a styled menu over streamlit's
    sidebar.

    # Parameters
    :param key: unique key to give the component a persisting state
    :param username: username to display at the bottom of the menu
    :param menu: menu object with all root pages
    :param current_page: page address to highlight the selected item
    :param global_context: when True, renders admin-only sidebar (no project nav)
    """
    from testgen.ui.components.widgets import sidebar_widget

    sidebar_widget(
        key=key,
        data={
            "projects": [{"code": item.project_code, "name": item.project_name} for item in projects],
            "current_project": current_project,
            "menu": menu.filter_for_current_user().sort_items().unflatten().asdict(),
            "current_page": current_page,
            "username": session.auth.user_display,
            "role": "" if global_context else (session.auth.role or "-"),
            "logout_path": LOGOUT_PATH,
            "version": version.__dict__,
            "support_email": support_email,
            "global_context": global_context,
            "is_global_admin": is_global_admin,
        },
        on_Navigate_change=_on_navigate,
    )


@with_database_session
def _on_navigate(payload: dict | None) -> None:
    if not payload:
        return

    if payload.get("path") == LOGOUT_PATH:
        session.auth.end_user_session()
        # This hack is needed because the auth cookie does not immediately get cleared
        # We don't want to try to load the session again on the next run
        session.auth.logging_out = True
        # streamlit_authenticator sets authentication_status implicitly
        # So we need to clear it
        session.authentication_status = None

        Router().queue_navigation(to="")
        # Without the time.sleep, cookies sometimes don't get cleared on deployed instances
        # (even though it works fine locally)
        time.sleep(0.3)
    else:
        query_params = payload.get("params", {})
        Router().queue_navigation(
            to=payload.get("path") or session.auth.get_default_page(project_code=query_params.get("project_code")),
            with_args=query_params,
        )
