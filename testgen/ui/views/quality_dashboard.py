from typing import ClassVar

import streamlit as st

from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import project_queries
from testgen.ui.queries.scoring_queries import ScoreCard, get_table_groups_score_cards
from testgen.ui.session import session
from testgen.utils import friendly_score

SORTED_BY_SESSION_KEY: str = "score-dashboard:sorted_by"
FILTER_TERM_SESSION_KEY: str = "score-dashboard:name_filter"
PAGE_TITLE = "Quality Dashboard"


class QualityDashboardPage(Page):
    path = "quality-dashboard"
    can_activate: ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="readiness_score", label=PAGE_TITLE, order=1)

    def render(self, *, project_code: str, **_kwargs) -> None:
        sorted_by: str = st.session_state.get(SORTED_BY_SESSION_KEY, "name")
        filter_term: str = st.session_state.get(FILTER_TERM_SESSION_KEY, None)
        project_summary = project_queries.get_summary_by_code(project_code)

        testgen.page_header(PAGE_TITLE)
        testgen.testgen_component(
            "quality_dashboard",
            props={
                "project_summary": {
                    "connections_count": int(project_summary["connections_ct"]),
                    "default_connection_id": str(project_summary["default_connection_id"]),
                    "table_groups_count": int(project_summary["table_groups_ct"]),
                    "profiling_runs_count": int(project_summary["profiling_runs_ct"]),
                },
                "scores": [
                    format_all_scores(score) for score in get_table_groups_score_cards(
                        project_code,
                        sorted_by=sorted_by,
                        filter_term=filter_term,
                    )
                ],
                "sorted_by": sorted_by,
                "filter_term": filter_term,
            },
            on_change_handlers={
                "ScoresSorted": apply_sort,
                "ScoresFiltered": apply_filter,
            },
        )


def format_all_scores(table_group_score_card: ScoreCard) -> ScoreCard:
    return {
        **table_group_score_card,
        "score": friendly_score(table_group_score_card["score"]),
        "profiling_score": friendly_score(table_group_score_card["profiling_score"]),
        "testing_score": friendly_score(table_group_score_card["testing_score"]),
        "cde_score": friendly_score(table_group_score_card["cde_score"])
            if table_group_score_card["cde_score"] else None,
        "dimensions": [
            {**dimension, "score": friendly_score(dimension["score"])}
            for dimension in table_group_score_card["dimensions"]
        ],
    }


def apply_sort(sorted_by: str) -> None:
    st.session_state[SORTED_BY_SESSION_KEY] = sorted_by


def apply_filter(term: str) -> None:
    st.session_state[FILTER_TERM_SESSION_KEY] = term
