import logging

import streamlit as st

from testgen import settings
from testgen.common import version_service
from testgen.common.docker_service import check_basic_configuration
from testgen.common.models import with_database_session
from testgen.common.models.project import Project
from testgen.ui import bootstrap
from testgen.ui.assets import get_asset_path
from testgen.ui.components import widgets as testgen
from testgen.ui.services import javascript_service, user_session_service
from testgen.ui.session import session


@with_database_session
def render(log_level: int = logging.INFO):
    st.set_page_config(
        page_title="TestGen",
        page_icon=get_asset_path("favicon.ico"),
        layout="wide",
        # Collapse when logging out because the sidebar takes some time to be removed from the DOM
        # Collapse for Catalog role since they only have access to one page
        initial_sidebar_state="collapsed"
        if session.logging_out or user_session_service.user_has_catalog_role()
        else "auto",
    )

    application = get_application(log_level=log_level)
    application.logger.debug("Starting Streamlit re-run")

    status_ok, message = check_basic_configuration()
    if not status_ok:
        st.markdown(f":red[{message}]")
        return

    set_locale()

    session.sidebar_project = (
        session.page_args_pending_router and session.page_args_pending_router.get("project_code")
    ) or st.query_params.get("project_code", session.sidebar_project)

    if session.authentication_status is None and not session.logging_out:
        user_session_service.load_user_session()

    application.logo.render()

    if session.authentication_status and not session.logging_in:
        with st.sidebar:
            testgen.sidebar(
                projects=Project.select_where(),
                current_project=session.sidebar_project,
                menu=application.menu,
                current_page=session.current_page,
                username=session.username,
                role=session.auth_role,
                version=version_service.get_version(),
                support_email=settings.SUPPORT_EMAIL,
            )

    application.router.run()


@st.cache_resource(validate=lambda _: not settings.IS_DEBUG, show_spinner=False)
def get_application(log_level: int = logging.INFO):
    return bootstrap.run(log_level=log_level)


def set_locale():
    timezone = javascript_service.get_browser_locale_timezone()
    if timezone is not None and timezone != 0:
        st.session_state["browser_timezone"] = timezone


if __name__ == "__main__":
    render(log_level=logging.DEBUG if settings.IS_DEBUG_LOG_LEVEL else logging.INFO)
