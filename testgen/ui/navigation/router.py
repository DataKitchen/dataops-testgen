from __future__ import annotations

import logging
import time

import streamlit as st

import testgen.ui.navigation.page
from testgen.ui.session import session
from testgen.utils.singleton import Singleton

LOG = logging.getLogger("testgen")
COOKIES_READY_RERUNS = 2


class Router(Singleton):
    _routes: dict[str, testgen.ui.navigation.page.Page]

    def __init__(
        self,
        /,
        routes: list[type[testgen.ui.navigation.page.Page]] | None = None,
    ) -> None:
        self._routes = {route.path: route(self) for route in routes} if routes else {}
        self._pending_navigation: dict | None = None

    def run(self, hide_sidebar=False) -> None:
        streamlit_pages = [route.streamlit_page for route in self._routes.values()]

        # Don't use position="hidden" when our custom sidebar needs to be displayed
        # The default [data-testid="stSidebarNav"] element seems to be needed to keep the sidebar DOM stable
        # Otherwise anything custom in the sidebar randomly flickers on page navigation
        current_page = st.navigation(streamlit_pages, position="hidden" if hide_sidebar else "sidebar")
        session.current_page_args = st.query_params

        # This hack is needed because the auth cookie is not retrieved on the first run
        # We have to store the page and wait for the second or third run
        if not session.cookies_ready:
            session.cookies_ready = 1
            session.page_pending_cookies = current_page
            # Set this anyway so that sidebar displays initial selection correctly
            session.current_page = current_page.url_path
            st.rerun()

        # Sometimes the cookie is ready on the second rerun and other times only on the third -_-
        # so we have to make sure the page renders correctly in both cases
        # and also handle the login page!
        elif session.cookies_ready == COOKIES_READY_RERUNS or session.authentication_status or (session.page_pending_cookies and not session.page_pending_cookies.url_path):
            session.cookies_ready = COOKIES_READY_RERUNS
            current_page = session.page_pending_cookies or current_page
            session.page_pending_cookies = None

            if session.page_args_pending_router is not None:
                session.current_page_args = session.page_args_pending_router
                st.query_params.from_dict(session.page_args_pending_router)
                session.page_args_pending_router = None

            session.current_page = current_page.url_path
            current_page.run()
        else:
            session.cookies_ready += 1
            time.sleep(0.3)

    def queue_navigation(self, /, to: str, with_args: dict | None = None) -> None:
        self._pending_navigation = {"to": to, "with_args": with_args or {}}

    def navigate_to_pending(self) -> None:
        """
        Navigate to the last queued navigation. No-op if no navigation
        queued.
        """
        if self._has_pending_navigation():
            navigation, self._pending_navigation = self._pending_navigation, None
            return self.navigate(**navigation)

    def _has_pending_navigation(self) -> bool:
        return isinstance(self._pending_navigation, dict) and "to" in self._pending_navigation

    def navigate(self, /, to: str, with_args: dict = {}) -> None:  # noqa: B006
        try:
            final_args = with_args or {}
            is_different_page = to != session.current_page
            query_params_changed = (
                len((st.query_params or {}).keys()) != len(final_args.keys())
                or any(st.query_params.get(name) != value for name, value in final_args.items())
            )
            if is_different_page or query_params_changed:
                route = self._routes[to]
                session.page_args_pending_router = {
                    name: value for name, value in final_args.items() if value and value not in [None, "None", ""]
                }
                if not session.current_page.startswith("quality-dashboard") and not to.startswith("quality-dashboard"):
                    st.cache_data.clear()
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
        params = {
            k: values_list if len(values_list) > 1 else v for k, v in params.items()
            if (values_list := params.get_all(k)) and v not in [None, "None", ""]
        }
        st.query_params.from_dict(params)
