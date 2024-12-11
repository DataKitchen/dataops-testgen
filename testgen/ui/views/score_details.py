from typing import ClassVar, TypedDict

import streamlit as st 

from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.session import session


class ScoreDetailsPage(Page):
    path = "score-dashboard:details"
    can_activate: ClassVar = [
        lambda: session.authentication_status,
    ]

    def render(
        self,
        *,
        table_group: str,
        category: str = "column_name",
        score_type: str = "score",
        drilldown: str | None = None,
        **kwargs
    ):
        project_code: str = session.project

        testgen.page_header(
            "Score Details",
            breadcrumbs=[
                {"path": "score-dashboard", "label": "Score Dashboard", "params": {"project_code": project_code}},
                {"label": table_group},
            ],
        )

        breakdown: ResultSet | None = None
        issues: ResultSet | None = None

        if drilldown:
            issues = get_issues(project_code, table_group, score_type, category, drilldown)
        else:
            breakdown = get_score_breakdown(project_code, table_group, score_type, category)

        testgen.testgen_component(
            "score_details",
            props={
                "category": category,
                "score_type": score_type,
                "drilldown": drilldown,
                "score": get_score(project_code, table_group),
                "breakdown": breakdown,
                "issues": issues,
            },
            on_change_handlers={
                "CategoryChanged": select_category,
                "ScoreTypeChanged": select_score_type,
            },
        )


def get_score(project_code: str, table_group_name: str) -> dict:
    return {
        "project_code": project_code,
        "table_group": table_group_name,
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
    }


def get_score_breakdown(project_code: str, table_group_name: str, score_type: str, category: str) -> "ResultSet":
    example = {category: "value", "impact": 1.1, "score": 91, "issue_ct": 10}
    if category == "column_name":
        example = {"table_name": "my_table", **example}

    return {
        "columns": list(example.keys()),
        "items": [example] * 10
    }


def get_issues(project_code: str, table_group_name: str, score_type: str, category: str, value: str) -> "ResultSet":
    example1 = {"type": "Non-Standard Blank", "status": "Definite", "detail": "Risk: MODERATE, PII Type: CONTACT/Address", "time": 9872110000}
    example2 = {"type": "Percent Missing", "status": "Potential PII", "detail": "Pct records over limit: 0.6, Threashold: 0.5", "time": 9872110000}


    # select anomaly_name, issue_likelihood, detail, profiling_starttime from profile_anomaly_results as results inner join profile_anomaly_types as types on (types.id = results.anomaly_id) inner join profiling_runs as runs on (runs.id = results.profile_run_id);

    return {
        "columns": list(example1.keys()),
        "items": [example1, example2] * 2,
    }


def select_category(category: str) -> None:
    Router().set_query_params({"category": category})


def select_score_type(score_type: str) -> None:
    Router().set_query_params({"score_type": score_type})


class ResultSet(TypedDict):
    columns: list[str]
    items: list[dict]
