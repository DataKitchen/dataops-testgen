import logging
import typing

import streamlit as st

from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import form_service
from testgen.ui.session import session

LOG = logging.getLogger("testgen")


class OverviewPage(Page):
    path = "overview"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="home", label="Overview", order=0)

    def render(self):
        form_service.render_page_header(
            "Welcome to DataOps TestGen",
            "https://docs.datakitchen.io/article/dataops-testgen-help/introduction-to-dataops-testgen",
        )

        st.session_state["app_title"] = "TestGen Dashboard"

        st.markdown(
            "###### The easiest way possible to institute comprehensive, agile data quality testing.\n\n"
            " - Start measuring immediately. \n"
            " - Derive actionable information quickly. \n"
            " - Then iterate, using tests and results to refine as you go."
        )
