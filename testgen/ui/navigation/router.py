from __future__ import annotations

import logging
import time

import streamlit as st

import testgen.ui.navigation.page
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models.project import Project
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
        self._pending_navigation: dict | None = None

    def run(self) -> None:
        streamlit_pages = [route.streamlit_page for route in self._routes.values()]

        current_page = st.navigation(streamlit_pages, position="hidden")

        # This hack is needed because the auth cookie is not set if navigation happens immediately after login
        # We have to navigate on the next run
        if session.logging_in:
            session.logging_in = False

            pending_route = session.page_pending_login or session.user_default_page or ""
            pending_args = (
                (session.page_args_pending_login or {})
                if session.page_pending_login
                else {"project_code": session.sidebar_project}
            )
            session.page_pending_login = None
            session.page_args_pending_login = None

            self.navigate(to=pending_route, with_args=pending_args)

        if session.cookies_ready:
            current_page = session.page_pending_cookies or current_page
            session.page_pending_cookies = None

            if session.page_args_pending_router is not None:
                st.query_params.from_dict(session.page_args_pending_router)
                session.page_args_pending_router = None

            session.current_page = current_page.url_path
            current_page.run()
        else:
            # This hack is needed because the auth cookie is not retrieved on the first run
            # We have to store the page and wait until cookies are ready
            session.page_pending_cookies = current_page

            # Don't use st.rerun() here!
            # It will work fine locally, but cause a long initial load on deployed instances
            # The time.sleep somehow causes the cookie to be detected quicker
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
            if is_different_page:
                MixpanelService().send_event(f"nav-{to}")
            if is_different_page or query_params_changed:
                route = self._routes[to]
                session.page_args_pending_router = {
                    name: value for name, value in final_args.items() if value and value not in [None, "None", ""]
                }
                if not session.current_page.startswith("quality-dashboard") and not to.startswith("quality-dashboard"):
                    st.cache_data.clear()

                session.current_page = to
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
        session.sidebar_project = session.sidebar_project or Project.select_where()[0].project_code
        self.navigate(to, {"project_code": session.sidebar_project, **with_args})

    def set_query_params(self, with_args: dict) -> None:
        params = st.query_params
        params.update(with_args)
        params = {
            k: values_list if len(values_list) > 1 else v for k, v in params.items()
            if (values_list := params.get_all(k)) and v not in [None, "None", ""]
        }
        st.query_params.from_dict(params)
