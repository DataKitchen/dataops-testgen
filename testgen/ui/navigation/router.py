from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import streamlit as st

import testgen.ui.navigation.page
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models.settings import PersistedSetting
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

    def _init_session(self, url: str):
        # Clear cache on initial load or page refresh
        st.cache_data.clear()

        try:
            parsed_url = urlparse(st.context.url)
            PersistedSetting.set("BASE_URL", f"{parsed_url.scheme}://{parsed_url.netloc}")
        except Exception as e:
            LOG.exception("Error capturing the base URL")

        source = st.query_params.pop("source", None)
        MixpanelService().send_event(f"nav-{url}", page_load=True, source=source)

    def _evaluate_feedback_popup(self) -> None:
        from datetime import UTC, datetime, timedelta

        from testgen import settings

        if settings.DISABLE_FEEDBACK_POPUP:
            session.show_feedback_popup = False
            return

        user = session.auth.user
        if not user:
            session.show_feedback_popup = False
            return

        last_popup_str = user.preferences.get("last_feedback_popup")
        if last_popup_str:
            try:
                last_popup_dt = datetime.fromisoformat(last_popup_str)
                if datetime.now(UTC) - last_popup_dt < timedelta(days=30):
                    session.show_feedback_popup = False
                    return
            except (ValueError, TypeError):
                pass  # Corrupted value — treat as no prior popup

        # User is eligible: record the timestamp and show the popup
        user.preferences["last_feedback_popup"] = datetime.now(UTC).isoformat()
        user.update_preferences()
        session.show_feedback_popup = True

    def run(self) -> None:
        streamlit_pages = [route.streamlit_page for route in self._routes.values()]

        current_page = st.navigation(streamlit_pages, position="hidden")

        if not session.initialized:
            self._init_session(url=current_page.url_path)
            session.initialized = True

        # This hack is needed because the auth cookie is not set if navigation happens immediately after login
        # We have to navigate on the next run
        if session.auth.logging_in:
            session.auth.logging_in = False

            pending_route = session.page_pending_login or session.auth.get_default_page(project_code=session.sidebar_project)
            pending_args = (
                (session.page_args_pending_login or {})
                if session.page_pending_login
                else {"project_code": session.sidebar_project}
            )
            session.page_pending_login = None
            session.page_args_pending_login = None
            self.navigate(to=pending_route, with_args=pending_args)

        if session.auth.cookies_ready:
            current_page = session.page_pending_cookies or current_page
            session.page_pending_cookies = None

            if session.page_args_pending_router is not None:
                st.query_params.from_dict(session.page_args_pending_router)
                session.page_args_pending_router = None

            if session.show_feedback_popup is None and session.auth.is_logged_in:
                try:
                    self._evaluate_feedback_popup()
                except Exception:
                    LOG.exception("Error evaluating feedback popup eligibility")
                    session.show_feedback_popup = False

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
        sidebar_project = session.sidebar_project
        if session.auth.user and not sidebar_project:
            project_codes = session.auth.user.get_accessible_projects()
            sidebar_project = project_codes[0] if project_codes else None
        session.sidebar_project = sidebar_project
        self.navigate(to, {"project_code": session.sidebar_project, **with_args})

    def set_query_params(self, with_args: dict) -> None:
        params = st.query_params
        params.update(with_args)
        params = {
            k: values_list if len(values_list) > 1 else v for k, v in params.items()
            if (values_list := params.get_all(k)) and v not in [None, "None", ""]
        }
        st.query_params.from_dict(params)
