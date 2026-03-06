import logging
from typing import Literal

import extra_streamlit_components as stx
import streamlit as st

from testgen.common.auth import decode_jwt_token, get_jwt_signing_key
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models.project_membership import ProjectMembership, RoleType
from testgen.common.models.user import User
from testgen.ui.services.javascript_service import execute_javascript
from testgen.ui.session import session

LOG = logging.getLogger("testgen")

Permission = Literal["catalog", "view", "disposition", "edit", "administer", "global_admin"]


class Authentication:

    jwt_cookie_name = "dk_cookie_name"
    jwt_cookie_expiry_days = 1

    user: User | None = None
    role: RoleType | None = None

    # Intermediate state holders because auth cookie changes are not immediate
    cookies_ready: bool = False
    logging_in: bool = False
    logging_out: bool = False

    @property
    def is_logged_in(self) -> bool:
        return bool(self.user)

    @property
    def user_display(self) -> str | None:
        return (self.user.name or self.user.username) if self.user else None

    @property
    def current_project(self) -> str | None:
        return session.sidebar_project

    def get_default_page(self, project_code: str | None = None) -> str:  # noqa: ARG002
        return "project-dashboard" if self.user else ""

    def user_has_permission(self, permission: Permission, /, project_code: str | None = None) -> bool:  # noqa: ARG002
        return True

    def user_has_project_access(self, project_code: str) -> bool:  # noqa: ARG002
        return True

    def get_jwt_hashing_key(self) -> bytes:
        try:
            return get_jwt_signing_key()
        except Exception:
            st.error(
                "Error reading the JWT signing key from settings.\n\n Make sure you have a valid "
                "base64 string assigned to the TG_JWT_HASHING_KEY environment variable."
            )
            st.stop()

    def get_credentials(self):
        users = User.select_where()
        usernames = {}
        for item in users:
            usernames[item.username.lower()] = {
                "name": item.name,
                "password": item.password,
            }
        return {"usernames": usernames}

    def login_user(self, username: str) -> None:
        self.user = User.get(username)
        self.user.save(update_latest_login=True)
        self.load_user_role()
        MixpanelService().send_event("login", include_usage=True, role=self.role)

    def load_user_session(self) -> None:
        cookies = self._load_cookies()
        token = cookies.get(self.jwt_cookie_name)
        if token is not None:
            try:
                payload = decode_jwt_token(token)
                self.user = User.get(payload["username"])
                self.load_user_role()
            except Exception:
                LOG.debug("Invalid auth token found on cookies", exc_info=True, stack_info=True)

    def load_user_role(self) -> None:
        if self.user and self.current_project:
            membership = ProjectMembership.get_by_user_and_project(self.user.id, self.current_project)
            self.role = membership.role if membership else None
        else:
            self.role = None

    def end_user_session(self) -> None:
        self._clear_jwt_cookie()
        self.user = None
        self.role = None

    def _clear_jwt_cookie(self) -> None:
        execute_javascript(
            f"""await (async function () {{
                window.parent.postMessage({{ type: 'TestgenLogout', cookie: '{self.jwt_cookie_name}' }}, '*');
                return 0;
            }})()
            """
        )

    def _load_cookies(self) -> dict:
        # Replacing this with st.context.cookies does not work
        # Because it does not update when cookies are deleted on logout
        cookie_manager = stx.CookieManager(key="testgen.cookies.get")
        if cookie_manager.cookies:
            self.cookies_ready = True
        return cookie_manager.cookies
