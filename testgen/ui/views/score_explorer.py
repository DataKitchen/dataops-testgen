from io import BytesIO
from typing import ClassVar

import pandas as pd
import streamlit as st

from testgen.commands.run_refresh_score_cards_results import (
    run_recalculate_score_card,
    run_refresh_score_cards_results,
)
from testgen.common.models.scores import ScoreCategory, ScoreDefinition, ScoreDefinitionFilter, SelectedIssue
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import FILE_DATA_TYPE, download_dialog, zip_multi_file_data
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.pdf import hygiene_issue_report, test_result_report
from testgen.ui.queries import profiling_queries, test_run_queries
from testgen.ui.queries.scoring_queries import (
    get_all_score_cards,
    get_score_card_issue_reports,
    get_score_category_values,
)
from testgen.ui.services import user_session_service
from testgen.ui.session import session
from testgen.utils import format_score_card, format_score_card_breakdown, format_score_card_issues


class ScoreExplorerPage(Page):
    path = "quality-dashboard:explorer"
    can_activate: ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
    ]

    def render(
        self,
        name: str | None = None,
        total_score: str | None = None,
        cde_score: str | None = None,
        category: str | None = None,
        filters: list[str] | None = None,
        breakdown_category: str | None = "table_name",
        breakdown_score_type: str | None = "score",
        drilldown: str | None = None,
        definition_id: str | None = None,
        **_kwargs
    ):
        project_code: str = session.project
        page_title: str = "Score Explorer"
        last_breadcrumb: str = page_title
        if definition_id:
            original_score_definition = ScoreDefinition.get(definition_id)
            page_title = "Edit Scorecard"
            last_breadcrumb = original_score_definition.name
        testgen.page_header(page_title, breadcrumbs=[
            {"path": "quality-dashboard", "label": "Quality Dashboard", "params": {"project_code": project_code}},
            {"label": last_breadcrumb},
        ])

        score_breakdown = None
        issues = None
        filter_values = {}
        with st.spinner(text="Loading data ..."):
            user_can_edit = user_session_service.user_can_edit()
            filter_values = get_score_category_values(project_code)

            score_definition: ScoreDefinition = ScoreDefinition(
                id=definition_id,
                project_code=project_code,
                total_score=True,
                cde_score=True,
            )
            if definition_id and not (name or total_score or category or filters):
                score_definition = ScoreDefinition.get(definition_id)
                set_score_definition(score_definition.to_dict())

            if name or total_score or cde_score or category or filters:
                score_definition.name = name
                score_definition.total_score = total_score and total_score.lower() == "true"
                score_definition.cde_score = cde_score and cde_score.lower() == "true"
                score_definition.category = ScoreCategory(category) if category else None

                if filters:
                    applied_filters = filters
                    if not isinstance(applied_filters, list):
                        applied_filters = [filters]

                    score_definition.filters = [
                        ScoreDefinitionFilter(field=field_value[0], value=field_value[1])
                        for f in applied_filters if (field_value := f.split("="))
                    ]

            score_card = None
            if score_definition:
                score_card = score_definition.as_score_card()

            if len(score_definition.filters) > 0 and not drilldown:
                score_breakdown = format_score_card_breakdown(
                    score_definition.get_score_card_breakdown(
                        score_type=breakdown_score_type,
                        group_by=breakdown_category,
                    ),
                    breakdown_category,
                )
            if score_card and drilldown:
                issues = format_score_card_issues(
                    score_definition.get_score_card_issues(breakdown_score_type, breakdown_category, drilldown),
                    breakdown_category,
                )
            score_definition_dict = score_definition.to_dict()

        testgen.testgen_component(
            "score_explorer",
            props={
                "filter_values": filter_values,
                "definition": score_definition_dict,
                "score_card": format_score_card(score_card),
                "breakdown_category": breakdown_category,
                "breakdown_score_type": breakdown_score_type,
                "breakdown": score_breakdown,
                "drilldown": drilldown,
                "issues": issues,
                "is_new": not definition_id,
                "permissions": {
                    "can_edit": user_can_edit,
                },
            },
            on_change_handlers={
                "ScoreUpdated": set_score_definition,
                "CategoryChanged": set_breakdown_category,
                "ScoreTypeChanged": set_breakdown_score_type,
                "DrilldownChanged": set_breakdown_drilldown,
                "IssueReportsExported": export_issue_reports,
                "ScoreDefinitionSaved": save_score_definition,
            },
        )


def set_score_definition(definition: dict | None) -> None:
    if definition:
        definition_id = st.query_params.get("definition_id") or definition.get("id")
        Router().set_query_params({
            "name": definition["name"],
            "total_score": definition["total_score"],
            "cde_score": definition["cde_score"],
            "category": definition["category"],
            "filters": [
                f"{f["field"]}={filter_value}"
                for f in definition["filters"]
                if (filter_value := f.get("value"))
            ],
            "definition_id": str(definition_id) if definition_id else None,
        })


def set_breakdown_category(category: str) -> None:
    Router().set_query_params({"breakdown_category": category})


def set_breakdown_score_type(score_type: str) -> None:
    Router().set_query_params({"breakdown_score_type": score_type})


def set_breakdown_drilldown(drilldown: str | None) -> None:
    Router().set_query_params({"drilldown": drilldown})


def export_issue_reports(selected_issues: list[SelectedIssue]) -> None:
    issues_data = get_score_card_issue_reports(selected_issues)
    dialog_title = "Download Issue Reports"
    if len(issues_data) == 1:
        download_dialog(
            dialog_title=dialog_title,
            file_content_func=get_report_file_data,
            args=(issues_data[0],),
        )
    else:
        zip_func = zip_multi_file_data(
            "testgen_issue_reports.zip",
            get_report_file_data,
            [(arg,) for arg in issues_data],
        )
        download_dialog(dialog_title=dialog_title, file_content_func=zip_func)


def get_report_file_data(update_progress, issue) -> FILE_DATA_TYPE:
    with BytesIO() as buffer:
        if issue["issue_type"] == "hygiene":
            issue_id = issue["id"][:8]
            timestamp = pd.Timestamp(issue["profiling_starttime"]).strftime("%Y%m%d_%H%M%S")
            hygiene_issue_report.create_report(buffer, issue)
        else:
            issue_id = issue["test_result_id"][:8]
            timestamp = pd.Timestamp(issue["test_time"]).strftime("%Y%m%d_%H%M%S")
            test_result_report.create_report(buffer, issue)

        update_progress(1.0)
        buffer.seek(0)

        file_name = f"testgen_{issue["issue_type"]}_issue_report_{issue_id}_{timestamp}.pdf"
        return file_name, "application/pdf", buffer.read()


def save_score_definition(_) -> None:
    definition_id = st.query_params.get("definition_id")
    name = st.query_params.get("name")
    total_score = st.query_params.get("total_score")
    cde_score = st.query_params.get("cde_score")
    category = st.query_params.get("category")
    filters = st.query_params.get_all("filters")

    if not name:
        raise ValueError("A name is required to save the scorecard")

    if not filters:
        raise ValueError("At least one filter is required to save the scorecard")

    is_new = True
    score_definition = ScoreDefinition()
    refresh_kwargs = {}
    if definition_id:
        is_new = False
        score_definition = ScoreDefinition.get(definition_id)

    if is_new:
        latest_run = max(
            profiling_queries.get_latest_run_date(session.project),
            test_run_queries.get_latest_run_date(session.project),
            key=lambda run: getattr(run, "run_time", 0),
        )

        refresh_kwargs = {
            "add_history_entry": True,
            "refresh_date": latest_run.run_time if latest_run else None,
        }

    score_definition.project_code = session.project
    score_definition.name = name
    score_definition.total_score = total_score and total_score.lower() == "true"
    score_definition.cde_score = cde_score and cde_score.lower() == "true"
    score_definition.category = ScoreCategory(category) if category else None
    score_definition.filters = [
        ScoreDefinitionFilter(field=field_value[0], value=field_value[1])
        for f in filters if (field_value := f.split("="))
    ]
    score_definition.save()
    run_refresh_score_cards_results(definition_id=score_definition.id, **refresh_kwargs)
    get_all_score_cards.clear()

    if not is_new:
        run_recalculate_score_card(project_code=score_definition.project_code, definition_id=score_definition.id)

    Router().set_query_params({
        "name": None,
        "total_score": None,
        "cde_score": None,
        "category": None,
        "filters": None,
        "definition_id": str(score_definition.id) if score_definition.id else None,
    })

    st.toast("Scorecard saved", icon=":material/task_alt:")
