import logging
import typing

import streamlit as st
import streamlit_authenticator as stauth

from testgen.common.mixpanel_service import MixpanelService
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.services import javascript_service, user_session_service
from testgen.ui.session import session

LOG = logging.getLogger("testgen")


class LoginPage(Page):
    path = ""
    can_activate: typing.ClassVar = [
        lambda: not session.authentication_status or session.logging_in,
    ]

    def render(self, **_kwargs) -> None:
        auth_data = user_session_service.get_auth_data()

        authenticator = stauth.Authenticate(
            auth_data["credentials"],
            auth_data["cookie"]["name"],
            auth_data["cookie"]["key"],
            auth_data["cookie"]["expiry_days"],
        )

        _, login_column, links_column = st.columns([0.25, 0.5, 0.25])

        with links_column:
            testgen.help_menu()

        with login_column:
            st.html("""
                        <br><br><br>
                        <h3 style="text-align: center; font-size: 26px; font-weight: 600;">Welcome to DataKitchen DataOps TestGen</h3>
                        """)
            name, authentication_status, username = authenticator.login("Login")

            if authentication_status is False:
                st.error("Username or password is incorrect.")
                MixpanelService().send_event("login-denied", username=username)

            if authentication_status is None:
                javascript_service.clear_component_states()

            session.authentication_status = authentication_status

            if authentication_status:
                user_session_service.start_user_session(name, username)
                session.logging_in = True
                MixpanelService().send_event("login", include_usage=True)
