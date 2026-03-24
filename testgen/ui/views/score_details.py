import logging
import typing
from decimal import Decimal
from io import BytesIO
from typing import Any, ClassVar

import pandas as pd
import streamlit as st

from testgen.commands.run_refresh_score_cards_results import run_recalculate_score_card
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    NotificationEvent,
    NotificationSettings,
    ScoreDropNotificationSettings,
)
from testgen.common.models.scores import (
    Categories,
    ScoreCategory,
    ScoreDefinition,
    ScoreDefinitionBreakdownItem,
    ScoreTypes,
    SelectedIssue,
)
from testgen.common.pii_masking import mask_hygiene_detail
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import FILE_DATA_TYPE, download_dialog, zip_multi_file_data
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.pdf import hygiene_issue_report, test_result_report
from testgen.ui.queries.scoring_queries import get_all_score_cards, get_score_card_issue_reports
from testgen.ui.session import session
from testgen.ui.views.dialogs.manage_notifications import NotificationSettingsDialogBase
from testgen.ui.views.dialogs.profiling_results_dialog import profiling_results_dialog
from testgen.utils import format_score_card, format_score_card_breakdown, format_score_card_issues

LOG = logging.getLogger("testgen")
PAGE_PATH = "quality-dashboard:score-details"

SD_EDIT_NOTIFICATIONS_DIALOG_KEY = "sd:edit_notifications_open"
SD_COLUMN_PROFILING_DIALOG_KEY = "sd:column_profiling_payload"


class ScoreDetailsPage(Page):
    path = PAGE_PATH
    can_activate: ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "definition_id" in st.query_params or "quality-dashboard",
    ]

    def render(
        self,
        *,
        definition_id: str,
        category: str | None = None,
        score_type: str | None = None,
        drilldown: str | None = None,
        **_kwargs
    ):
        score_definition: ScoreDefinition = ScoreDefinition.get(definition_id)

        if not score_definition:
            self.router.navigate_with_warning(
                f"Scorecard with ID '{definition_id}' does not exist. Redirecting to Quality Dashboard ...",
                "quality-dashboard",
            )
            return

        if not session.auth.user_has_project_access(score_definition.project_code):
            self.router.navigate_with_warning(
                "You don't have access to view this resource. Redirecting ...",
                "quality-dashboard",
            )
            return

        session.set_sidebar_project(score_definition.project_code)

        testgen.page_header(
            "Score Details",
            "view-score-details",
            breadcrumbs=[
                {"path": "quality-dashboard", "label": "Quality Dashboard", "params": {"project_code": score_definition.project_code}},
                {"label": score_definition.name},
            ],
        )

        if not category or category not in typing.get_args(Categories):
            category = (
                score_definition.category.value
                if score_definition.category
                else ScoreCategory.dq_dimension.value
            )

        if not score_type or score_type not in typing.get_args(ScoreTypes):
            score_type = (
                "cde_score"
                if score_definition.cde_score and not score_definition.total_score
                else "score"
            )

        score_breakdown = None
        issues = None
        with st.spinner(text="Loading data :gray[:small[(This might take a few minutes)]] ..."):
            user_can_edit = session.auth.user_has_permission("edit")
            score_card = format_score_card(score_definition.as_cached_score_card(include_definition=True))
            if not drilldown:
                score_breakdown = ScoreDefinitionBreakdownItem.filter(
                    definition_id=definition_id,
                    category=category,
                    score_type=score_type,
                )
                score_breakdown = format_score_card_breakdown([item.to_dict() for item in score_breakdown], category)
            else:
                raw_issues = score_definition.get_score_card_issues(score_type, category, drilldown)
                if not session.auth.user_has_permission("view_pii"):
                    mask_hygiene_detail(raw_issues)
                issues = format_score_card_issues(raw_issues, category)

        def on_edit_notifications(*_) -> None:
            st.session_state[SD_EDIT_NOTIFICATIONS_DIALOG_KEY] = True

        ns_obj = ScoreDropNotificationSettingsDialog(
            ScoreDropNotificationSettings,
            ns_attrs={"project_code": score_definition.project_code, "score_definition_id": score_definition.id},
            component_props={"cde_enabled": score_definition.cde_score, "total_enabled": score_definition.total_score},
        )

        notifications_data = None
        if st.session_state.get(SD_EDIT_NOTIFICATIONS_DIALOG_KEY):
            notifications_data = ns_obj.build_data()
            notifications_data["open"] = True

        def on_notifications_dialog_closed(*_) -> None:
            ns_obj.clear_state()
            st.session_state.pop(SD_EDIT_NOTIFICATIONS_DIALOG_KEY, None)

        def on_column_profiling_clicked(payload: dict) -> None:
            st.session_state[SD_COLUMN_PROFILING_DIALOG_KEY] = payload

        testgen.score_details_widget(
            key="score_details",
            data={
                "category": category,
                "score_type": score_type,
                "drilldown": drilldown,
                "score": score_card,
                "breakdown": score_breakdown,
                "issues": issues,
                "permissions": {
                    "can_edit": user_can_edit,
                },
                "notifications_dialog": notifications_data,
            },
            on_DeleteScoreConfirmed_change=delete_score_card,
            on_EditNotifications_change=on_edit_notifications,
            on_CategoryChanged_change=select_category,
            on_ScoreTypeChanged_change=select_score_type,
            on_IssueReportsExported_change=export_issue_reports,
            on_ColumnProflingClicked_change=on_column_profiling_clicked,
            on_RecalculateHistory_change=recalculate_score_history,
            # NotificationSettings events
            on_AddNotification_change=ns_obj.on_add_item,
            on_UpdateNotification_change=ns_obj.on_update_item,
            on_DeleteNotification_change=ns_obj.on_delete_item,
            on_PauseNotification_change=ns_obj.on_pause_item,
            on_ResumeNotification_change=ns_obj.on_resume_item,
            on_NotificationsDialogClosed_change=on_notifications_dialog_closed,
        )

        if column_profiling_payload := st.session_state.pop(SD_COLUMN_PROFILING_DIALOG_KEY, None):
            profiling_results_dialog(
                column_profiling_payload["column_name"],
                column_profiling_payload["table_name"],
                column_profiling_payload["table_group_id"],
            )


def select_category(category: str) -> None:
    Router().set_query_params({"category": category})


def select_score_type(score_type: str) -> None:
    Router().set_query_params({"score_type": score_type})


@with_database_session
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


@with_database_session
def delete_score_card(definition_id: str) -> None:
    score_definition = ScoreDefinition.get(definition_id)
    score_definition.delete()
    get_all_score_cards.clear()
    Router().queue_navigation("quality-dashboard", {"project_code": score_definition.project_code})


@with_database_session
def recalculate_score_history(definition_id: str) -> None:
    try:
        score_definition = ScoreDefinition.get(definition_id)
        run_recalculate_score_card(project_code=score_definition.project_code, definition_id=score_definition.id)
        st.toast("Scorecard trend recalculated", icon=":material/task_alt:")
    except:
        LOG.exception(f"Failure recalculating history for scorecard id={definition_id}")
        st.toast("Recalculating the trend failed. Try again", icon=":material/error:")


class ScoreDropNotificationSettingsDialog(NotificationSettingsDialogBase):

    title = "Scorecard Notifications"

    def _item_to_model_attrs(self, item: dict[str, Any]) -> dict[str, Any]:
        model_data = {
            attr: Decimal(item[attr])
            for attr in ("total_score_threshold", "cde_score_threshold")
            if attr in item
        }
        return model_data

    def _model_to_item_attrs(self, model: NotificationSettings) -> dict[str, Any]:
        item_data = {
            attr: str(getattr(model, attr))
            for attr in ("total_score_threshold", "cde_score_threshold")
        }
        return item_data

    def _get_component_props(self) -> dict[str, Any]:
        return {
            "event": NotificationEvent.score_drop.value,
        }
