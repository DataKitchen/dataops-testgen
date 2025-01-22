from io import BytesIO
from typing import ClassVar, TypedDict

import pandas as pd

from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import FILE_DATA_TYPE, download_dialog, zip_multi_file_data
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.pdf import hygiene_issue_report, test_result_report
from testgen.ui.queries import table_group_queries
from testgen.ui.queries.scoring_queries import (
    SelectedIssue,
    get_score_card_breakdown,
    get_score_card_issue_reports,
    get_score_card_issues,
    get_table_group_score_card,
)
from testgen.ui.session import session
from testgen.ui.views.quality_dashboard import format_all_scores
from testgen.utils import friendly_score, friendly_score_impact


class ScoreDetailsPage(Page):
    path = "quality-dashboard:score-details"
    can_activate: ClassVar = [
        lambda: session.authentication_status,
    ]

    def render(
        self,
        *,
        name: str,
        category: str = "table_name",
        score_type: str = "score",
        drilldown: str | None = None,
        **_kwargs
    ):
        project_code: str = session.project

        testgen.page_header(
            "Score Details",
            breadcrumbs=[
                {"path": "quality-dashboard", "label": "Quality Dashboard", "params": {"project_code": project_code}},
                {"label": name},
            ],
        )

        table_group_dict = table_group_queries.get_by_name(project_code, name)

        breakdown: ResultSet | None = None
        issues: ResultSet | None = None

        if drilldown:
            issues = get_issues(project_code, table_group_dict["id"], score_type, category, drilldown)
        else:
            breakdown = get_score_breakdown(project_code, table_group_dict["id"], score_type, category)

        testgen.testgen_component(
            "score_details",
            props={
                "category": category,
                "score_type": score_type,
                "drilldown": drilldown,
                "score": format_all_scores(get_table_group_score_card(project_code, table_group_dict["id"])),
                "breakdown": breakdown,
                "issues": issues,
            },
            on_change_handlers={
                "CategoryChanged": select_category,
                "ScoreTypeChanged": select_score_type,
                "IssueReportsExported": export_issue_reports,
            },
        )


def get_score_breakdown(project_code: str, table_group_id: str, score_type: str, category: str) -> "ResultSet":
    results = get_score_card_breakdown(project_code, table_group_id, score_type, category)
    return {
        "columns": [category, "impact", "score", "issue_ct"],
        "items": [{
            **row,
            "score": friendly_score(row["score"]),
            "impact": friendly_score_impact(row["impact"]),
        } for row in results],
    }


def get_issues(project_code: str, table_group_id: str, score_type: str, category: str, value: str) -> "ResultSet":
    issues = get_score_card_issues(project_code, table_group_id, score_type, category, value)
    columns = ["type", "status", "detail", "time"]
    if category != "column_name":
        columns.insert(0, "column")
    return {
        "columns": columns,
        "items": issues,
    }


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
        if issue["report_type"] == "hygiene":
            issue_id = issue["id"][:8]
            timestamp = pd.Timestamp(issue["profiling_starttime"]).strftime("%Y%m%d_%H%M%S")
            hygiene_issue_report.create_report(buffer, issue)
        else:
            issue_id = issue["test_result_id"][:8]
            timestamp = pd.Timestamp(issue["test_time"]).strftime("%Y%m%d_%H%M%S")
            test_result_report.create_report(buffer, issue)

        update_progress(1.0)
        buffer.seek(0)

        file_name = f"testgen_{issue["report_type"]}_issue_report_{issue_id}_{timestamp}.pdf"
        return file_name, "application/pdf", buffer.read()


class ResultSet(TypedDict):
    columns: list[str]
    items: list[dict]
