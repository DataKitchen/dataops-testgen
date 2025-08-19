import logging
import typing

import streamlit as st
import streamlit_authenticator as stauth

from testgen.common.mixpanel_service import MixpanelService
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.session import session

LOG = logging.getLogger("testgen")


class LoginPage(Page):
    path = ""
    permission = None
    can_activate: typing.ClassVar = [
        lambda: not session.auth.is_logged_in or session.auth.logging_in,
    ]

    def render(self, **_kwargs) -> None:
        _, login_column, links_column = st.columns([0.25, 0.5, 0.25])

        with links_column:
            testgen.help_menu()

        with login_column:
            self.render_login_form(**_kwargs)
            
    def render_login_form(self, **_kwargs) -> None:
        st.html("""
        <br><br><br>
        <h3 style="text-align: center; font-size: 26px; font-weight: 600;">Welcome to DataKitchen DataOps TestGen</h3>
        """)
        
        authenticator = stauth.Authenticate(
            session.auth.get_credentials(),
            session.auth.jwt_cookie_name,
            session.auth.get_jwt_hashing_key(),
            session.auth.jwt_cookie_expiry_days,
        )
    
        _name, authentication_status, username = authenticator.login("Login")

        if authentication_status is False:
            st.error("Username or password is incorrect.")
            MixpanelService().send_event("login-denied", username=username)

        if authentication_status is None:
            session.auth.end_user_session()

        if authentication_status:
            session.auth.logging_in = True
            session.auth.logging_out = False
            session.auth.login_user(username)
