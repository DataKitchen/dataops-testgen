from __future__ import annotations

import logging
import time

import streamlit as st

import testgen.ui.navigation.page
from testgen.ui.session import session
from testgen.utils.singleton import Singleton

LOG = logging.getLogger("testgen")


class Router(Singleton):
    _routes: dict[str, testgen.ui.navigation.page.Page]

    def __init__(
        self,
        /,
        routes: list[type[testgen.ui.navigation.page.Page]] | None = None,
    ) -> None:
        self._routes = {route.path: route(self) for route in routes} if routes else {}

    def run(self, hide_sidebar=False) -> None:
        streamlit_pages = [route.streamlit_page for route in self._routes.values()]

        # Don't use position="hidden" when our custom sidebar needs to be displayed
        # The default [data-testid="stSidebarNav"] element seems to be needed to keep the sidebar DOM stable
        # Otherwise anything custom in the sidebar randomly flickers on page navigation
        current_page = st.navigation(streamlit_pages, position="hidden" if hide_sidebar else "sidebar")
        session.current_page_args = st.query_params

        # This hack is needed because the auth cookie is not retrieved on the first run
        # We have to store the page and wait for the second run

        if not session.cookies_ready:
            session.cookies_ready = True
            session.page_pending_cookies = current_page
        else:
            current_page = session.page_pending_cookies or current_page
            session.page_pending_cookies = None

            if session.page_args_pending_router is not None:
                session.current_page_args = session.page_args_pending_router
                st.query_params.from_dict(session.page_args_pending_router)
                session.page_args_pending_router = None

            session.current_page = current_page.url_path
            current_page.run()


    def navigate(self, /, to: str, with_args: dict = {}) -> None:  # noqa: B006
        try:
            if to != session.current_page:
                route = self._routes[to]
                session.page_args_pending_router = with_args
                st.switch_page(route.streamlit_page)

        except KeyError as k:
            error_message = f"{to}: {k!s}"
            st.error(error_message)
            LOG.exception(error_message)
            return self.navigate(to="", with_args=with_args)
        except Exception as e:
            error_message = f"{to}: {e!s}"
            st.error(error_message)
            LOG.exception(error_message)

    
    def navigate_with_warning(self, warning: str, to: str, with_args: dict = {}) -> None:  # noqa: B006
        st.warning(warning)
        time.sleep(3)
        self.navigate(to, with_args)


    def set_query_params(self, with_args: dict) -> None:
        params = st.query_params
        params.update(with_args)
        params = {k: v for k, v in params.items() if v not in [None, "None", ""]}
        st.query_params.from_dict(params)
