from io import BytesIO
from typing import ClassVar

import pandas as pd
import streamlit as st

from testgen.common.models.scores import ScoreDefinition, ScoreDefinitionBreakdownItem, SelectedIssue
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import FILE_DATA_TYPE, download_dialog, zip_multi_file_data
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.pdf import hygiene_issue_report, test_result_report
from testgen.ui.queries.scoring_queries import get_all_score_cards, get_score_card_issue_reports
from testgen.ui.services import authentication_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.profiling_results_dialog import profiling_results_dialog
from testgen.utils import format_score_card, format_score_card_breakdown, format_score_card_issues


class ScoreDetailsPage(Page):
    path = "quality-dashboard:score-details"
    can_activate: ClassVar = [
        lambda: session.authentication_status,
        lambda: "definition_id" in session.current_page_args or "quality-dashboard",
    ]

    def render(
        self,
        *,
        definition_id: str,
        category: str = "table_name",
        score_type: str | None = None,
        drilldown: str | None = None,
        **_kwargs
    ):
        project_code: str = session.project
        score_definition: ScoreDefinition = ScoreDefinition.get(definition_id)

        if not score_definition:
            self.router.navigate_with_warning(
                f"Scorecard with ID '{definition_id}' does not exist. Redirecting to Quality Dashboard ...",
                "quality-dashboard",
            )
            return

        testgen.page_header(
            "Score Details",
            breadcrumbs=[
                {"path": "quality-dashboard", "label": "Quality Dashboard", "params": {"project_code": project_code}},
                {"label": score_definition.name},
            ],
        )

        score_card = None
        score_breakdown = None
        issues = None
        with st.spinner(text="Loading data ..."):
            user_can_edit = authentication_service.current_user_has_edit_role()
            score_card = format_score_card(score_definition.as_score_card())
            if not score_type:
                score_type = "cde_score" if score_card["cde_score"] and not score_card["score"] else "score"
            if not drilldown:
                score_breakdown = ScoreDefinitionBreakdownItem.filter(
                    definition_id=definition_id,
                    category=category,
                    score_type=score_type,
                )
                score_breakdown = format_score_card_breakdown([item.to_dict() for item in score_breakdown], category)
            else:
                issues = format_score_card_issues(
                    score_definition.get_score_card_issues(score_type, category, drilldown),
                    category,
                )

        testgen.testgen_component(
            "score_details",
            props={
                "category": category,
                "score_type": score_type,
                "drilldown": drilldown,
                "score": score_card,
                "breakdown": score_breakdown,
                "issues": issues,
                "permissions": {
                    "can_edit": user_can_edit,
                }
            },
            event_handlers={
                "DeleteScoreRequested": delete_score_card,
            },
            on_change_handlers={
                "CategoryChanged": select_category,
                "ScoreTypeChanged": select_score_type,
                "IssueReportsExported": export_issue_reports,
                "ColumnProflingClicked": lambda payload: profiling_results_dialog(
                    payload["column_name"],
                    payload["table_name"],
                    payload["table_group_id"],
                )
            },
        )


def select_category(category: str) -> None:
    Router().set_query_params({"category": category})


def select_score_type(score_type: str) -> None:
    Router().set_query_params({"score_type": score_type})


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


@st.dialog(title="Delete Scorecard")
def delete_score_card(definition_id: str) -> None:
    score_definition = ScoreDefinition.get(definition_id)

    delete_clicked, set_delelte_clicked = temp_value(
        "score-details:confirm-delete-score-val"
    )
    st.markdown(
        f"Are you sure you want to delete the scorecard <b>{score_definition.name}</b>?",
        unsafe_allow_html=True,
    )

    _, button_column = st.columns([.85, .15])
    with button_column:
        testgen.button(
            label="Delete",
            type_="flat",
            color="warn",
            key="score-details:confirm-delete-score-btn",
            on_click=lambda: set_delelte_clicked(True),
        )

    if delete_clicked():
        score_definition.delete()
        get_all_score_cards.clear()
        Router().navigate("quality-dashboard")
