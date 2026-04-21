import logging
import os
from urllib.parse import urlparse

import streamlit as st

from testgen import settings
from testgen.common import version_service
from testgen.common.docker_service import check_basic_configuration
from testgen.common.standalone_postgres import STANDALONE_URI_ENV_VAR, ensure_standalone_setup, is_standalone_mode
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.project import Project
from testgen.ui import bootstrap
from testgen.ui.assets import get_asset_path
from testgen.ui.components import widgets as testgen
from testgen.ui.services import javascript_service
from testgen.ui.session import session

if is_standalone_mode() and (standalone_uri := os.environ.get(STANDALONE_URI_ENV_VAR)):
    ensure_standalone_setup(standalone_uri)

@with_database_session
def render(log_level: int = logging.INFO):
    try:
        st.set_page_config(
            page_title="TestGen",
            page_icon=get_asset_path("favicon.ico"),
            layout="wide",
            # Collapse when logging out or on the no-project page (no sidebar content on either)
            initial_sidebar_state="collapsed"
                if (session.auth and session.auth.logging_out) or session.current_page == "no-project"
                else "auto",
        )

        application = get_application(log_level=log_level)
        application.logger.debug("Starting Streamlit re-run")
        if not session.auth:
            session.auth = application.auth_class()

        if not is_standalone_mode():
            status_ok, message = check_basic_configuration()
            if not status_ok:
                st.markdown(f":red[{message}]")
                return

        set_locale()

        if session.auth.logging_out:
            session.sidebar_project = None
        else:
            session.sidebar_project = (
                session.page_args_pending_router and session.page_args_pending_router.get("project_code")
            ) or st.query_params.get("project_code", session.sidebar_project)

        if not session.auth.is_logged_in and not session.auth.logging_out:
            session.auth.load_user_session()

        if session.auth.is_logged_in and not session.auth.logging_out:
            session.auth.load_user_role()

        application.logo.render()

        if session.auth.is_logged_in and not session.auth.logging_in and not session.auth.logging_out:
            current_page = session.current_page
            if not current_page:
                try:
                    current_page = urlparse(st.context.url).path.lstrip("/")
                except Exception:
                    current_page = ""
            is_global_context = current_page in application.global_admin_paths
            if current_page != "no-project":
                with st.sidebar:
                    testgen.sidebar(
                        projects=[] if is_global_context else [
                            p for p in Project.select_where() if session.auth.user_has_project_access(p.project_code)
                        ],
                        current_project=None if is_global_context else session.sidebar_project,
                        menu=application.menu,
                        current_page=session.current_page,
                        version=version_service.get_version(),
                        support_email=settings.SUPPORT_EMAIL,
                        global_context=is_global_context,
                        is_global_admin=session.auth.user_has_permission("global_admin") and bool(application.global_admin_paths),
                    )

        application.router.run()
    finally:
        # Safety net: commit any flushed-but-uncommitted work (e.g., PersistedSetting writes)
        # before RerunException propagates and bypasses database_session()'s normal commit.
        db_session = get_current_session()
        if db_session:
            db_session.commit()


@st.cache_resource(validate=lambda _: not settings.IS_DEBUG, show_spinner=False)
def get_application(log_level: int = logging.INFO):
    return bootstrap.run(log_level=log_level)


def set_locale():
    timezone = javascript_service.get_browser_locale_timezone()
    if timezone is not None and timezone != 0:
        st.session_state["browser_timezone"] = timezone


if __name__ == "__main__":
    render(log_level=logging.DEBUG if settings.IS_DEBUG_LOG_LEVEL else logging.INFO)
