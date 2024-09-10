import logging
import sys
from pathlib import Path

import streamlit as st

from testgen import settings
from testgen.common.docker_service import check_basic_configuration
from testgen.ui import bootstrap
from testgen.ui.components import widgets as testgen
from testgen.ui.services import database_service as db
from testgen.ui.services import javascript_service, project_service, user_session_service
from testgen.ui.session import session


def render(log_level: int = logging.INFO):
    st.set_page_config(
        page_title="TestGen",
        page_icon=get_image_path("assets/favicon.ico"),
        layout="wide",
    )

    application = get_application(log_level=log_level)
    application.logger.debug("Starting Streamlit re-run")

    status_ok, message = check_basic_configuration()
    if not status_ok:
        st.markdown(f":red[{message}]")
        return

    set_locale()

    session.dbschema = db.get_schema()

    projects = project_service.get_projects()
    if not session.project and len(projects) > 0:
        project_service.set_current_project(projects[0]["code"])

    if session.authentication_status is None and not session.logging_out:
        user_session_service.load_user_session()
    
    st.logo(
        image=get_image_path("assets/dk_logo.svg"),
        icon_image=get_image_path("assets/dk_icon.svg")
    )

    hide_sidebar = not session.authentication_status or session.logging_in
    if not hide_sidebar:
        with st.sidebar:
            testgen.sidebar(
                menu=application.menu.update_version(application.get_version()),
                username=session.username,
                current_page=session.current_page,
            )
            
    application.router.run(hide_sidebar)


@st.cache_resource(validate=lambda _: not settings.IS_DEBUG, show_spinner=False)
def get_application(log_level: int = logging.INFO):
    return bootstrap.run(log_level=log_level)


def set_locale():
    timezone = javascript_service.get_browser_locale_timezone()
    if timezone is not None and timezone != 0:
        st.session_state["browser_timezone"] = timezone


def get_image_path(path: str) -> str:
    return str(Path(__file__).parent / path)


if __name__ == "__main__":
    log_level = logging.INFO
    if settings.IS_DEBUG_LOG_LEVEL or "--debug" in sys.argv:
        log_level = logging.DEBUG
    render(log_level=log_level)
