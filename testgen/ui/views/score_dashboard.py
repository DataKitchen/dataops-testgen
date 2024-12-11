from typing import ClassVar

import streamlit as st 

from testgen.testgen.ui.services import table_group_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.session import session

SORTED_BY_SESSION_KEY: str = "score-dashboard:sorted_by"
FILTER_TERM_SESSION_KEY: str = "score-dashboard:name_filter"


class ScoreDashboardPage(Page):
    path = "score-dashboard"
    can_activate: ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="readiness_score", label="Score Dashboard", order=1)

    def render(self, *, project_code: str, **kwargs) -> None:
        sorted_by: str = st.session_state.get(SORTED_BY_SESSION_KEY, "table_group")
        filter_term: str = st.session_state.get(FILTER_TERM_SESSION_KEY, None)

        testgen.page_header("Score Dashboard")
        testgen.testgen_component(
            "score_dashboard",
            props={
                "scores": get_table_groups_scores(project_code, sorted_by=sorted_by, filter_term=filter_term),
                "sorted_by": sorted_by,
                "filter_term": filter_term,
            },
            on_change_handlers={
                "ScoresSorted": apply_sort,
                "ScoresFiltered": apply_filter,
            },
        )


def get_table_groups_scores(project_code: str, sorted_by: str, filter_term: str | None = None) -> list[dict]:
    results = [
        {
            "project_code": project_code,
            "table_group": "Another Table Group",
            "score": 94,
            "cde_score": 98,
            "dimensions": [
                {"label": "Accuracy", "score": 93},
                {"label": "Completeness", "score": 99},
                {"label": "Consistency", "score": 98},
                {"label": "Timeliness", "score": 87},
                {"label": "Uniqueness", "score": 97},
                {"label": "Validity", "score": 94},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "Default Table Group",
            "score": 83,
            "cde_score": 90,
            "dimensions": [
                {"label": "Accuracy", "score": 96},
                {"label": "Completeness", "score": 99},
                {"label": "Consistency", "score": 98},
                {"label": "Timeliness", "score": 96},
                {"label": "Uniqueness", "score": 97},
                {"label": "Validity", "score": 96},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "My Table Group",
            "score": 97,
            "cde_score": 100,
            "dimensions": [
                {"label": "Accuracy", "score": 80},
                {"label": "Completeness", "score": 80},
                {"label": "Consistency", "score": 80},
                {"label": "Timeliness", "score": 80},
                {"label": "Uniqueness", "score": 80},
                {"label": "Validity", "score": 91},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "Another Table Group",
            "score": 94,
            "cde_score": 98,
            "dimensions": [
                {"label": "Accuracy", "score": 93},
                {"label": "Completeness", "score": 99},
                {"label": "Consistency", "score": 98},
                {"label": "Timeliness", "score": 87},
                {"label": "Uniqueness", "score": 97},
                {"label": "Validity", "score": 94},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "Default Table Group",
            "score": 83,
            "cde_score": 90,
            "dimensions": [
                {"label": "Accuracy", "score": 96},
                {"label": "Completeness", "score": 99},
                {"label": "Consistency", "score": 98},
                {"label": "Timeliness", "score": 96},
                {"label": "Uniqueness", "score": 97},
                {"label": "Validity", "score": 96},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "My Table Group",
            "score": 97,
            "cde_score": 100,
            "dimensions": [
                {"label": "Accuracy", "score": 80},
                {"label": "Completeness", "score": 80},
                {"label": "Consistency", "score": 80},
                {"label": "Timeliness", "score": 80},
                {"label": "Uniqueness", "score": 80},
                {"label": "Validity", "score": 91},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "Another Table Group",
            "score": 94,
            "cde_score": 98,
            "dimensions": [
                {"label": "Accuracy", "score": 93},
                {"label": "Completeness", "score": 99},
                {"label": "Consistency", "score": 98},
                {"label": "Timeliness", "score": 87},
                {"label": "Uniqueness", "score": 97},
                {"label": "Validity", "score": 94},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "Default Table Group",
            "score": 83,
            "cde_score": 90,
            "dimensions": [
                {"label": "Accuracy", "score": 96},
                {"label": "Completeness", "score": 99},
                {"label": "Consistency", "score": 98},
                {"label": "Timeliness", "score": 96},
                {"label": "Uniqueness", "score": 97},
                {"label": "Validity", "score": 96},
            ],
        },
        {
            "project_code": project_code,
            "table_group": "My Table Group",
            "score": 97,
            "cde_score": 100,
            "dimensions": [
                {"label": "Accuracy", "score": 80},
                {"label": "Completeness", "score": 80},
                {"label": "Consistency", "score": 80},
                {"label": "Timeliness", "score": 80},
                {"label": "Uniqueness", "score": 80},
                {"label": "Validity", "score": 91},
            ],
        },
    ]

    if filter_term:
        results = [item for item in results if not filter_term or filter_term in item["table_group"]]

    try:
        results = sorted(results, key=lambda item: item[sorted_by])
    except:
        pass

    return list(results)


def apply_sort(sorted_by: str) -> None:
    st.session_state[SORTED_BY_SESSION_KEY] = sorted_by


def apply_filter(term: str) -> None:
    st.session_state[FILTER_TERM_SESSION_KEY] = term
