import typing

import streamlit as st
import streamlit_authenticator as stauth

from testgen.ui.navigation.page import Page
from testgen.ui.services import authentication_service, javascript_service
from testgen.ui.session import session


class LoginPage(Page):
    path = "login"
    can_activate: typing.ClassVar = [
        lambda: not session.authentication_status or "overview",
    ]

    def render(self) -> None:
        auth_data = authentication_service.get_auth_data()

        authenticator = stauth.Authenticate(
            auth_data["credentials"],
            auth_data["cookie"]["name"],
            auth_data["cookie"]["key"],
            auth_data["cookie"]["expiry_days"],
            auth_data["preauthorized"],
        )

        name, authentication_status, username = authenticator.login("Login", "main")

        if authentication_status is False:
            st.error("Username or password is incorrect.")

        if authentication_status is None:
            st.warning("Please enter your username and password.")
            javascript_service.clear_component_states()

        session.authentication_status = authentication_status

        if authentication_status:
            authentication_service.start_user_session(name, username)
