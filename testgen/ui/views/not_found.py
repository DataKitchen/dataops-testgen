import typing

import streamlit as st

from testgen.ui.navigation.page import Page
from testgen.ui.session import session


class NotFoundPage(Page):
    path = "404"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status or "login",
    ]

    def render(self, **_) -> None:
        st.write("Page not found")
