import json
from datetime import datetime
from functools import partial
from io import BytesIO
from typing import ClassVar

import pandas as pd
import streamlit as st

from testgen.commands.run_refresh_score_cards_results import (
    run_recalculate_score_card,
    run_refresh_score_cards_results,
)
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.scores import ScoreCategory, ScoreDefinition, ScoreDefinitionCriteria, SelectedIssue
from testgen.common.models.test_run import TestRun
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import FILE_DATA_TYPE, download_dialog, zip_multi_file_data
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.pdf import hygiene_issue_report, test_result_report
from testgen.ui.queries.scoring_queries import (
    get_all_score_cards,
    get_column_filters,
    get_score_card_issue_reports,
    get_score_category_values,
)
from testgen.ui.services import user_session_service
from testgen.ui.session import session, temp_value
from testgen.utils import format_score_card, format_score_card_breakdown, format_score_card_issues, try_json

PAGE_PATH = "quality-dashboard:explorer"

class ScoreExplorerPage(Page):
    path = PAGE_PATH
    can_activate: ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "definition_id" in st.query_params or "project_code" in st.query_params or "quality-dashboard",
    ]

    def render(
        self,
        name: str | None = None,
        total_score: str | None = None,
        cde_score: str | None = None,
        category: str | None = None,
        filters: str | None = None,
        breakdown_category: str | None = None,
        breakdown_score_type: str | None = "score",
        drilldown: str | None = None,
        definition_id: str | None = None,
        project_code: str | None = None,
        filter_by_columns: str | None = None,
        **_kwargs
    ):
        page_title: str = "Score Explorer"
        last_breadcrumb: str = page_title
        if definition_id:
            original_score_definition = ScoreDefinition.get(definition_id)

            if not original_score_definition:
                self.router.navigate_with_warning(
                    f"Scorecard with ID '{definition_id}' does not exist. Redirecting to Quality Dashboard ...",
                    "quality-dashboard",
                )
                return

            if not breakdown_category and original_score_definition.category:
                breakdown_category = original_score_definition.category.value

            project_code = original_score_definition.project_code
            page_title = "Edit Scorecard"
            last_breadcrumb = original_score_definition.name
        testgen.page_header(page_title, breadcrumbs=[
            {"path": "quality-dashboard", "label": "Quality Dashboard", "params": {"project_code": project_code}},
            {"label": last_breadcrumb},
        ])

        if not breakdown_category:
            breakdown_category = ScoreCategory.dq_dimension.value

        score_breakdown = None
        issues = None
        filter_values = {}
        with st.spinner(text="Loading data :gray[:small[(This might take a few minutes)]] ..."):
            user_can_edit = user_session_service.user_can_edit()
            filter_values = get_score_category_values(project_code)

            score_definition: ScoreDefinition = ScoreDefinition(
                id=definition_id,
                project_code=project_code,
                total_score=True,
                cde_score=True,
                criteria=ScoreDefinitionCriteria(
                    group_by_field=filter_by_columns != "true" if filter_by_columns else None,
                ),
            )
            if definition_id and not (name or total_score or category or filters):
                score_definition = ScoreDefinition.get(definition_id)
                set_score_definition(score_definition.to_dict())

            if name or total_score or cde_score or category or filters:
                score_definition.name = name
                score_definition.total_score = total_score and total_score.lower() == "true"
                score_definition.cde_score = cde_score and cde_score.lower() == "true"
                score_definition.category = ScoreCategory(category) if category in [cat.value for cat in ScoreCategory] else None

                if filters:
                    applied_filters: list[dict] = try_json(filters, default=[])
                    applied_filters = [
                        {"field": f["field"], "value": f["value"], "others": f.get("others", [])}
                        for f in applied_filters
                        if f.get("field") and f.get("value")
                    ]
                    score_definition.criteria = ScoreDefinitionCriteria.from_filters(
                        applied_filters,
                        group_by_field=filter_by_columns != "true",
                    )

            score_card = None
            if score_definition:
                score_card = score_definition.as_score_card()

            if score_definition.criteria.has_filters() and not drilldown:
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
                "ColumnSelectorOpened": partial(column_selector_dialog, project_code, score_definition_dict),
                "FilterModeChanged": change_score_definition_filter_mode,
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
            "filters": json.dumps(definition["filters"], separators=(",", ":")),
            "definition_id": str(definition_id) if definition_id else None,
            "filter_by_columns": str(definition.get("filter_by_columns", False)).lower(),
        })


def set_breakdown_category(category: str) -> None:
    Router().set_query_params({"breakdown_category": category})


def set_breakdown_score_type(score_type: str) -> None:
    Router().set_query_params({"breakdown_score_type": score_type})


def set_breakdown_drilldown(drilldown: str | None) -> None:
    Router().set_query_params({"drilldown": drilldown})


def export_issue_reports(selected_issues: list[SelectedIssue]) -> None:
    MixpanelService().send_event(
        "download-issue-report",
        page=PAGE_PATH,
        issue_count=len(selected_issues),
    )
    
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
            timestamp = pd.Timestamp(issue["test_date"]).strftime("%Y%m%d_%H%M%S")
            test_result_report.create_report(buffer, issue)

        update_progress(1.0)
        buffer.seek(0)

        file_name = f"testgen_{issue["issue_type"]}_issue_report_{issue_id}_{timestamp}.pdf"
        return file_name, "application/pdf", buffer.read()


def column_selector_dialog(project_code: str, score_definition_dict: dict, _) -> None:
    is_column_selector_opened, set_column_selector_opened = temp_value("explorer-column-selector", default=False)

    def dialog_content() -> None:
        if not is_column_selector_opened():
            st.rerun()

        selected_filters = set()
        if score_definition_dict.get("filter_by_columns"):
            selected_filters = _get_selected_filters(score_definition_dict.get("filters", []))

        column_filters = get_column_filters(project_code)
        for column in column_filters:
            table_group_selected = (f"table_groups_name={column["table_group"]}",) in selected_filters
            table_selected = (
                f"table_groups_name={column["table_group"]}",
                f"table_name={column["table"]}",
            ) in selected_filters
            column_selected = (
                f"table_groups_name={column["table_group"]}",
                f"table_name={column["table"]}",
                f"column_name={column["name"]}",
            ) in selected_filters
            column["selected"] = table_group_selected or table_selected or column_selected

        testgen.testgen_component(
            "column_selector",
            props={"columns": column_filters},
            on_change_handlers={
                "ColumnFiltersUpdated": set_score_definition_column_filters,
            }
        )

    def set_score_definition_column_filters(filters: list[dict]) -> None:
        set_score_definition({
            **score_definition_dict,
            "filters": filters,
            "filter_by_columns": bool(filters),
        })
        set_column_selector_opened(False)

    set_column_selector_opened(True)
    return st.dialog(title="Select Columns for the Scorecard", width="small")(dialog_content)()


def _get_selected_filters(filters: list[dict]) -> set[tuple[str]]:
    selected_filters = set()
    for filter_ in filters:
        filter_values = {
            filter_["field"]: filter_["value"],
        }
        for linked_filter in filter_.get("others", []):
            filter_values[linked_filter["field"]] = linked_filter["value"]

        parts = []
        for key in ["table_groups_name", "table_name", "column_name"]:
            if key in filter_values:
                parts.append(f"{key}={filter_values[key]}")

        selected_filters.add(tuple(parts))
    return selected_filters


def change_score_definition_filter_mode(filter_by_columns: bool) -> None:
    Router().set_query_params({
        "filters": None,
        "filter_by_columns": str(filter_by_columns).lower(),
    })


def save_score_definition(_) -> None:
    project_code = st.query_params.get("project_code")
    definition_id = st.query_params.get("definition_id")
    name = st.query_params.get("name")
    total_score = st.query_params.get("total_score")
    cde_score = st.query_params.get("cde_score")
    category = st.query_params.get("category")
    filters: list[dict] = try_json(st.query_params.get("filters"), default=[])
    filter_by_columns: bool = (st.query_params.get("filter_by_columns") or "false") == "true"

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
        project_code = score_definition.project_code

    if is_new:
        latest_run = max(
            ProfilingRun.get_latest_run(project_code),
            TestRun.get_latest_run(project_code),
            key=lambda run: getattr(run, "run_time", datetime.min),
        )

        refresh_kwargs = {
            "add_history_entry": True,
            "refresh_date": latest_run.run_time if latest_run else None,
        }

    score_definition.project_code = project_code
    score_definition.name = name
    score_definition.total_score = total_score and total_score.lower() == "true"
    score_definition.cde_score = cde_score and cde_score.lower() == "true"
    score_definition.category = ScoreCategory(category) if category else None
    score_definition.criteria = ScoreDefinitionCriteria.from_filters(
        [
            {"field": f["field"], "value": f["value"], "others": f.get("others", [])} for f in filters
            if f.get("field") and f.get("value")
        ],
        group_by_field=not filter_by_columns,
    )
    score_definition.save()
    run_refresh_score_cards_results(definition_id=score_definition.id, **refresh_kwargs)
    get_all_score_cards.clear()

    if not is_new:
        run_recalculate_score_card(project_code=project_code, definition_id=score_definition.id)

    Router().set_query_params({
        "name": None,
        "total_score": None,
        "cde_score": None,
        "category": None,
        "filters": None,
        "filter_by_columns": None,
        "definition_id": str(score_definition.id) if score_definition.id else None,
    })

    st.toast("Scorecard saved", icon=":material/task_alt:")
