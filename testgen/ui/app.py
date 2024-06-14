import logging
import sys

import streamlit as st

from testgen import settings
from testgen.common.docker_service import check_basic_configuration
from testgen.ui import bootstrap
from testgen.ui.components import widgets as testgen
from testgen.ui.queries import project_queries
from testgen.ui.services import authentication_service, javascript_service
from testgen.ui.services import database_service as db
from testgen.ui.session import session


def render(log_level: int = logging.INFO):
    st.set_page_config(
        page_title="TestGen",
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

    projects = get_projects()
    if not session.project and len(projects) > 0:
        set_current_project(projects[0]["code"])

    if session.renders is None:
        session.renders = 0

    if not session.logging_out and session.authentication_status is None:
        authentication_service.load_user_session()
    testgen.location(on_change=set_current_location)

    if session.authentication_status and not session.logging_out:
        with st.sidebar:
            testgen.sidebar(
                menu=application.menu.update_version(application.get_version()),
                username=session.username,
                current_page=session.current_page,
                current_project=session.project,
                on_logout=authentication_service.end_user_session,
            )

    if session.renders is not None:
        session.renders += 1

    if session.renders > 0 and session.current_page:
        application.router.navigate(to=session.current_page, with_args=session.current_page_args)

    application.logger.debug(f"location status: {session.current_page} {session.current_page_args}")


@st.cache_resource(validate=lambda _: not settings.IS_DEBUG, show_spinner=False)
def get_application(log_level: int = logging.INFO):
    return bootstrap.run(log_level=log_level)


def set_locale():
    timezone = javascript_service.get_browser_locale_timezone()
    if timezone is not None and timezone != 0:
        st.session_state["browser_timezone"] = timezone


@st.cache_data(show_spinner=False)
def get_projects():
    projects = project_queries.get_projects()
    projects = [
        {"code": project["project_code"], "name": project["project_name"]} for project in projects.to_dict("records")
    ]

    return projects


def set_current_location(change: testgen.LocationChanged) -> None:
    session.current_page = change.page
    session.current_page_args = change.args


def set_current_project(project_code: str) -> None:
    session.project = project_code


if __name__ == "__main__":
    log_level = logging.INFO
    if settings.IS_DEBUG_LOG_LEVEL or "--debug" in sys.argv:
        log_level = logging.DEBUG
    render(log_level=log_level)
