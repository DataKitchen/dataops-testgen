from typing import ClassVar

import streamlit as st

from testgen.common.models.project import Project
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries.scoring_queries import get_all_score_cards
from testgen.ui.session import session
from testgen.utils import format_score_card

PAGE_TITLE = "Quality Dashboard"


class QualityDashboardPage(Page):
    path = "quality-dashboard"
    can_activate: ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="readiness_score",
        label=PAGE_TITLE,
        order=1,
    )

    def render(self, *, project_code: str, **_kwargs) -> None:
        project_summary = Project.get_summary(project_code)

        testgen.page_header(PAGE_TITLE)
        testgen.testgen_component(
            "quality_dashboard",
            props={
                "project_summary": project_summary.to_dict(json_safe=True),
                "scores": [
                    format_score_card(score)
                    for score in get_all_score_cards(project_code)
                    if score.get("score") or score.get("cde_score") or score.get("categories")
                ],
            },
            on_change_handlers={
                "RefreshData": refresh_data,
            },
        )


def refresh_data(*_, **__):
    get_all_score_cards.clear()
