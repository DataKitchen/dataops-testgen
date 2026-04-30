import json
import typing
from io import BytesIO
from itertools import zip_longest
from operator import attrgetter

import pandas as pd
import streamlit as st

from testgen.commands.run_rollup_scores import run_test_rollup_scoring_queries
from testgen.common import date_service
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition, TestDefinitionNote, TestDefinitionSummary
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.common.pii_masking import get_pii_columns, mask_profiling_pii
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
    zip_multi_file_data,
)
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.pdf.test_result_report import create_report
from testgen.ui.queries import test_result_queries
from testgen.ui.queries.source_data_queries import (
    get_test_issue_source_data,
    get_test_issue_source_data_custom,
    get_test_issue_source_query,
    get_test_issue_source_query_custom,
)
from testgen.ui.services.database_service import execute_db_query, fetch_df_from_db, fetch_one_from_db
from testgen.ui.services.string_service import snake_case_to_title_case
from testgen.ui.session import session
from testgen.utils import friendly_score, make_json_safe

PAGE_PATH = "test-runs:results"
PAGE_SIZE = 500

SELECTED_ITEM_KEY = "tr:selected_item"
EXPORT_FILTERS_KEY = "tr:export_filters"
SOURCE_DATA_KEY = "tr:source_data"
PROFILING_KEY = "tr:profiling"
EDIT_TEST_KEY = "tr:edit_test"
VALIDATE_RESULT_KEY = "tr:validate_result"
ISSUE_REPORT_KEY = "tr:issue_report"
NOTES_DIALOG_KEY = "tr:notes_dialog"

DISPOSITION_MAP = {"Confirmed": "✓", "Dismissed": "✘", "Inactive": "🔇", "Passed": ""}

# Maps JS column names to SQL ORDER BY expressions
SORT_FIELD_MAP = {
    "table_name": "LOWER(r.table_name)",
    "column_names": "LOWER(r.column_names)",
    "test_name_short": "tt.test_name_short",
    "result_measure_display": "result_measure",
    "status_display": "result_status",
    "flagged": "CASE WHEN td.flagged THEN 0 ELSE 1 END",
}


def _parse_status_filter(status: str | None) -> list[str] | None:
    if not status:
        return None
    if status == "Failed + Warning":
        return ["Failed", "Warning"]
    return [status]


def _map_action_filter(action: str | None) -> str | None:
    if not action:
        return None
    if action == "Inactive":
        return "Muted"
    if action == "No Action":
        return "No Action"
    return action


def _parse_sort_param(sort: str | None) -> tuple[list | None, list[dict]]:
    """Parse sort URL param into (sorting_columns for SQL, sort_state for JS).

    Returns (sorting_columns, sort_state) where sorting_columns is a list of
    [sql_expr, order] pairs for the query, and sort_state is the JS-friendly
    list of {field, order} dicts.
    """
    if not sort:
        return None, []

    sorting_columns = []
    sort_state = []
    for part in sort.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(":")
        field = tokens[0]
        order = tokens[1] if len(tokens) > 1 else "asc"
        if order not in ("asc", "desc"):
            order = "asc"

        sql_expr = SORT_FIELD_MAP.get(field)
        if sql_expr:
            sorting_columns.append([sql_expr, order])
            sort_state.append({"field": field, "order": order})

    return sorting_columns if sorting_columns else None, sort_state


class TestResultsPage(Page):
    path = PAGE_PATH
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "run_id" in st.query_params or "test-runs",
    ]

    def render(
        self,
        run_id: str,
        status: str | None = None,
        table_name: str | None = None,
        column_name: str | None = None,
        test_type: str | None = None,
        action: str | None = None,
        flagged: str | None = None,
        selected: str | None = None,
        page: str | None = None,
        page_size: str | None = None,
        sort: str | None = None,
        **_kwargs,
    ) -> None:
        run = TestRun.get_minimal(run_id)
        if not run:
            self.router.navigate_with_warning(
                f"Test run with ID '{run_id}' does not exist. Redirecting to list of Test Runs ...",
                "test-runs",
            )
            return

        if not session.auth.user_has_project_access(run.project_code):
            self.router.navigate_with_warning(
                "You don't have access to view this resource. Redirecting ...",
                "test-runs",
            )
            return

        run_id = str(run.id)

        run_date = date_service.get_timezoned_timestamp(st.session_state, run.test_starttime)
        session.set_sidebar_project(run.project_code)

        testgen.page_header(
            "Test Results",
            "investigate-test-results",
            breadcrumbs=[
                {"label": "Test Runs", "path": "test-runs", "params": {"project_code": run.project_code}},
                {"label": f"{run.test_suite} | {run_date}"},
            ],
        )

        # Handle deferred export/issue report (still use st.dialog for file downloads)
        export_filters = st.session_state.pop(EXPORT_FILTERS_KEY, None)
        if export_filters is not None:
            test_suite = TestSuite.get_minimal(run.test_suite_id)
            _handle_export(export_filters, run_id, run_date, test_suite)

        issue_report_data = st.session_state.pop(ISSUE_REPORT_KEY, None)
        if issue_report_data is not None:
            _handle_issue_report(issue_report_data)

        # Parse pagination and sorting params
        current_page = int(page) if page else 0
        current_page_size = int(page_size) if page_size else PAGE_SIZE
        sorting_columns, sort_state = _parse_sort_param(sort)

        # Map filters to query params
        # "all" means explicitly cleared; None means first load (default to "Failed + Warning")
        status_cleared = status == "all"
        effective_status = None if status_cleared else (status or "Failed + Warning")
        test_statuses = _parse_status_filter(effective_status)
        action_mapped = _map_action_filter(action)
        flagged_bool = True if flagged == "Flagged" else False if flagged == "Not Flagged" else None

        # Load data with server-side filtering, sorting, and pagination
        with st.spinner("Loading data ..."):
            df = test_result_queries.get_test_results(
                run_id,
                test_statuses=test_statuses,
                test_type_id=test_type,
                table_name=table_name,
                column_name=column_name,
                action=action_mapped,
                sorting_columns=sorting_columns,
                flagged=flagged_bool,
                page=current_page,
                page_size=current_page_size,
            )
            df_action = get_test_disposition(run_id)
            action_map = df_action.set_index("id")["action"].to_dict()
            df["action"] = df["test_result_id"].map(action_map).fillna(df["action"])

            total_count = test_result_queries.get_test_results_count(
                run_id,
                test_statuses=test_statuses,
                test_type_id=test_type,
                table_name=table_name,
                column_name=column_name,
                action=action_mapped,
                flagged=flagged_bool,
            )

            filter_options = test_result_queries.get_filter_options(run_id)

            test_suite = TestSuite.get_minimal(run.test_suite_id)

        items = json.loads(df.to_json(orient="records", date_unit="s"))
        summary = get_test_result_summary(run_id)
        score = friendly_score(run.dq_score_test_run) or "--"

        # Handle selected item
        selected_item = st.session_state.get(SELECTED_ITEM_KEY)
        if selected and (selected_item is None or selected_item.get("test_result_id") != selected):
            row_df = df[df["test_result_id"] == selected]
            if not row_df.empty:
                row = json.loads(row_df.to_json(orient="records", date_unit="s"))[0]
                selected_item = build_selected_item_data(row, test_suite)
                st.session_state[SELECTED_ITEM_KEY] = selected_item
        elif not selected:
            st.session_state.pop(SELECTED_ITEM_KEY, None)
            selected_item = None

        # Build dialog data from session state
        profiling_column = st.session_state.get(PROFILING_KEY)
        source_data = st.session_state.get(SOURCE_DATA_KEY)
        edit_test = st.session_state.get(EDIT_TEST_KEY)

        notes_dialog = None
        if notes_state := st.session_state.get(NOTES_DIALOG_KEY):
            notes_dialog = _load_notes_dialog_data(notes_state.get("id") or notes_state, df)

        # Event handlers
        @with_database_session
        def on_row_selected(item_id: str) -> None:
            row_df = df[df["test_result_id"] == item_id]
            if row_df.empty:
                return
            row = json.loads(row_df.to_json(orient="records", date_unit="s"))[0]
            item_data = build_selected_item_data(row, test_suite)
            st.session_state[SELECTED_ITEM_KEY] = item_data
            Router().set_query_params({"selected": item_id})

        def on_filter_changed(filters: dict) -> None:
            st.session_state.pop(SELECTED_ITEM_KEY, None)
            Router().set_query_params({
                "selected": None,
                "page": "0",
                "status": filters.get("status") or "all",
                "table_name": filters.get("table_name"),
                "column_name": filters.get("column_name"),
                "test_type": filters.get("test_type"),
                "action": filters.get("action"),
                "flagged": filters.get("flagged"),
            })

        @with_database_session
        def on_disposition_changed(payload: dict) -> None:
            test_result_ids = payload.get("test_result_ids", [])
            disposition = payload.get("status", "No Decision")
            if test_result_ids:
                update_result_disposition(test_result_ids, disposition)
                st.cache_data.clear()

        @with_database_session
        def on_disposition_all(payload: dict) -> None:
            filters = payload.get("filters", {})
            disposition = payload.get("status", "No Decision")
            filter_status = filters.get("status")
            filter_test_statuses = _parse_status_filter(filter_status)
            filter_action = _map_action_filter(filters.get("action"))
            filter_flagged_str = filters.get("flagged")
            filter_flagged = True if filter_flagged_str == "Flagged" else False if filter_flagged_str == "Not Flagged" else None

            all_ids = test_result_queries.get_test_result_ids(
                run_id,
                test_statuses=filter_test_statuses,
                test_type_id=filters.get("test_type"),
                table_name=filters.get("table_name"),
                column_name=filters.get("column_name"),
                action=filter_action,
                flagged=filter_flagged,
            )
            if all_ids:
                update_result_disposition(all_ids, disposition)
                st.cache_data.clear()

        @with_database_session
        def on_flag_changed(payload: dict) -> None:
            value = payload.get("value", False)
            test_definition_ids = payload.get("test_definition_ids", [])
            if not test_definition_ids:
                # Multi-select: resolve test_result_ids to definition IDs
                test_result_ids = payload.get("test_result_ids", [])
                test_definition_ids = test_result_queries.get_test_definition_ids_for_results(test_result_ids)
            if test_definition_ids:
                TestDefinition.set_status_attribute("flagged", test_definition_ids, value)
                st.cache_data.clear()

        @with_database_session
        def on_flag_all(payload: dict) -> None:
            value = payload.get("value", False)
            filters = payload.get("filters", {})
            filter_status = filters.get("status")
            filter_test_statuses = _parse_status_filter(filter_status)
            filter_action = _map_action_filter(filters.get("action"))
            filter_flagged_str = filters.get("flagged")
            filter_flagged = True if filter_flagged_str == "Flagged" else False if filter_flagged_str == "Not Flagged" else None

            all_def_ids = test_result_queries.get_test_definition_ids_for_run(
                run_id,
                test_statuses=filter_test_statuses,
                test_type_id=filters.get("test_type"),
                table_name=filters.get("table_name"),
                column_name=filters.get("column_name"),
                action=filter_action,
                flagged=filter_flagged,
            )
            if all_def_ids:
                TestDefinition.set_status_attribute("flagged", all_def_ids, value)
                st.cache_data.clear()

        def on_notes_clicked(payload: dict) -> None:
            st.session_state[NOTES_DIALOG_KEY] = payload

        @with_database_session
        def on_note_added(payload: dict) -> None:
            td_id = payload["test_definition_id"]
            current_user = session.auth.user.username if session.auth.user else "unknown"
            TestDefinitionNote.add_note(td_id, payload["text"], current_user)
            st.session_state[NOTES_DIALOG_KEY] = _load_notes_dialog_data(td_id, df)
            st.cache_data.clear()

        @with_database_session
        def on_note_updated(payload: dict) -> None:
            TestDefinitionNote.update_note(payload["id"], payload["text"])
            td_id = payload["test_definition_id"]
            st.session_state[NOTES_DIALOG_KEY] = _load_notes_dialog_data(td_id, df)

        @with_database_session
        def on_note_deleted(payload: dict) -> None:
            TestDefinitionNote.delete_note(payload["id"])
            td_id = payload["test_definition_id"]
            st.session_state[NOTES_DIALOG_KEY] = _load_notes_dialog_data(td_id, df)
            st.cache_data.clear()

        def on_notes_dialog_closed(*_) -> None:
            st.session_state.pop(NOTES_DIALOG_KEY, None)

        @with_database_session
        def on_source_data_clicked(item_id: str) -> None:
            result_df = test_result_queries.get_test_results_by_ids([item_id])
            if not result_df.empty:
                row = json.loads(result_df.to_json(orient="records", date_unit="s"))[0]
                MixpanelService().send_event("view-source-data", page=PAGE_PATH, test_type=row.get("test_name_short"))
                mask_pii = not session.auth.user_has_permission("view_pii")
                st.session_state[SOURCE_DATA_KEY] = _build_source_data(row, mask_pii=mask_pii)

        @with_database_session
        def on_profiling_clicked(test_result_id: str) -> None:
            import testgen.ui.queries.profiling_queries as profiling_queries
            lookup = test_result_queries.get_test_result_lookup(test_result_id)
            if not lookup:
                return
            column = profiling_queries.get_column_by_name(
                lookup["column_names"], lookup["table_name"], lookup["table_groups_id"],
            )
            if column:
                if not session.auth.user_has_permission("view_pii"):
                    mask_profiling_pii(column, get_pii_columns(lookup["table_groups_id"], table_name=lookup["table_name"]))
                st.session_state[PROFILING_KEY] = make_json_safe(column)

        def on_profiling_closed(*_) -> None:
            st.session_state.pop(PROFILING_KEY, None)

        def on_source_data_closed(*_) -> None:
            st.session_state.pop(SOURCE_DATA_KEY, None)

        @with_database_session
        def on_edit_test_clicked(payload: dict) -> None:
            test_result_id = payload.get("test_result_id")
            if test_result_id:
                lookup = test_result_queries.get_test_result_lookup(test_result_id)
                td_id = lookup["test_definition_id"] if lookup else None
            else:
                td_id = payload.get("test_definition_id")
            st.session_state[EDIT_TEST_KEY] = _build_edit_test_dialog_data(td_id, test_suite)

        @with_database_session
        def on_edit_test_saved(test_def: dict) -> None:
            valid_columns = {c.key for c in TestDefinition.__table__.columns}
            filtered = {k: v for k, v in test_def.items() if k in valid_columns}
            TestDefinition(**filtered).save()
            st.session_state.pop(EDIT_TEST_KEY, None)
            st.session_state.pop(VALIDATE_RESULT_KEY, None)
            st.cache_data.clear()

        @with_database_session
        def on_validate_test(test_def: dict) -> None:
            from testgen.ui.views.test_definitions import validate_test

            table_group = TableGroup.get_minimal(test_suite.table_groups_id)
            try:
                validate_test(test_def, table_group)
                st.session_state[VALIDATE_RESULT_KEY] = {"success": True, "message": "Validation is successful."}
            except Exception as e:
                st.session_state[VALIDATE_RESULT_KEY] = {
                    "success": False,
                    "message": f"Test validation failed with error: {e}",
                }

        def on_edit_test_closed(*_) -> None:
            st.session_state.pop(EDIT_TEST_KEY, None)
            st.session_state.pop(VALIDATE_RESULT_KEY, None)

        @with_database_session
        def on_issue_report_clicked(payload: dict) -> None:
            ids = payload.get("ids", [])
            if not ids:
                return
            result_df = test_result_queries.get_test_results_by_ids(ids)
            if result_df.empty:
                return
            rows = json.loads(result_df.to_json(orient="records", date_unit="s"))
            MixpanelService().send_event("download-issue-report", page=PAGE_PATH, issue_count=len(rows))
            st.session_state[ISSUE_REPORT_KEY] = rows

        @with_database_session
        def on_score_refresh(*_) -> None:
            run_test_rollup_scoring_queries(
                run.project_code,
                run_id,
                run.table_groups_id if run.is_latest_run else None,
            )
            st.cache_data.clear()

        def on_export_all(*_) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "all"}

        def on_export_filtered(filters: dict) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "filtered", **filters}

        def on_export_selected(payload: dict) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "selected", "ids": payload.get("ids", [])}

        def on_page_changed(payload: dict) -> None:
            new_page = payload.get("page", 0)
            new_page_size = payload.get("page_size")
            st.session_state.pop(SELECTED_ITEM_KEY, None)
            params = {"page": str(new_page), "selected": None}
            if new_page_size is not None:
                params["page_size"] = str(int(new_page_size))
            Router().set_query_params(params)

        def on_sort_changed(payload: dict) -> None:
            columns = payload.get("columns", [])
            sort_parts = []
            for col in columns:
                field = col.get("field", "")
                order = col.get("order", "asc")
                sort_parts.append(f"{field}:{order}")
            sort_value = ",".join(sort_parts) if sort_parts else None
            st.session_state.pop(SELECTED_ITEM_KEY, None)
            Router().set_query_params({"sort": sort_value, "page": "0", "selected": None})

        testgen.test_results_widget(
            key="test_results",
            data={
                "items": items,
                "summary": summary,
                "score": score,
                "filters": {
                    "status": None if status_cleared else effective_status,
                    "table_name": table_name,
                    "column_name": column_name,
                    "test_type": test_type,
                    "action": action,
                    "flagged": flagged,
                },
                "selected_id": selected,
                "selected_item": make_json_safe(selected_item) if selected_item else None,
                "permissions": {
                    "can_disposition": session.auth.user_has_permission("disposition"),
                    "can_edit": session.auth.user_has_permission("edit"),
                },
                "run_info": {
                    "test_suite": run.test_suite,
                    "test_suite_id": str(run.test_suite_id),
                    "run_date": run_date,
                    "project_code": run.project_code,
                    "is_latest_run": run.is_latest_run,
                },
                "profiling_column": make_json_safe(profiling_column) if profiling_column else None,
                "source_data": make_json_safe(source_data) if source_data else None,
                "edit_test": make_json_safe(edit_test) if edit_test else None,
                "validate_result": st.session_state.pop(VALIDATE_RESULT_KEY, None),
                "notes_dialog": notes_dialog,
                "page": current_page,
                "total_count": total_count,
                "page_size": current_page_size,
                "sort_state": sort_state,
                "filter_options": filter_options,
            },
            on_RowSelected_change=on_row_selected,
            on_FilterChanged_change=on_filter_changed,
            on_DispositionChanged_change=on_disposition_changed,
            on_DispositionAll_change=on_disposition_all,
            on_FlagChanged_change=on_flag_changed,
            on_FlagAll_change=on_flag_all,
            on_NotesClicked_change=on_notes_clicked,
            on_NoteAdded_change=on_note_added,
            on_NoteUpdated_change=on_note_updated,
            on_NoteDeleted_change=on_note_deleted,
            on_NotesDialogClosed_change=on_notes_dialog_closed,
            on_SourceDataClicked_change=on_source_data_clicked,
            on_ProfilingClicked_change=on_profiling_clicked,
            on_ProfilingClosed_change=on_profiling_closed,
            on_SourceDataClosed_change=on_source_data_closed,
            on_EditTestClicked_change=on_edit_test_clicked,
            on_EditTestSaved_change=on_edit_test_saved,
            on_EditTestClosed_change=on_edit_test_closed,
            on_ValidateTest_change=on_validate_test,
            on_IssueReportClicked_change=on_issue_report_clicked,
            on_ScoreRefreshClicked_change=on_score_refresh,
            on_ExportAll_change=on_export_all,
            on_ExportFiltered_change=on_export_filtered,
            on_ExportSelected_change=on_export_selected,
            on_PageChanged_change=on_page_changed,
            on_SortChanged_change=on_sort_changed,
        )


def _build_edit_test_dialog_data(test_definition_id: str | None, test_suite_minimal: TestSuiteMinimal) -> dict | None:
    """Build the data payload for the Edit Test dialog, matching the test_definitions page format."""
    if not test_definition_id:
        return None

    from testgen.ui.views.test_definitions import get_columns, run_test_type_lookup_query

    test_def = TestDefinition.select_where(TestDefinition.id == test_definition_id)
    if not test_def:
        return None

    full_test_suite = TestSuite.get(test_suite_minimal.id)
    table_group = TableGroup.get_minimal(test_suite_minimal.table_groups_id)
    test_def_row = test_def[0]
    test_def_dict = {col: getattr(test_def_row, col) for col in TestDefinitionSummary.columns()}
    for key in ["id", "table_groups_id", "profile_run_id", "test_suite_id"]:
        if test_def_dict.get(key) is not None:
            test_def_dict[key] = str(test_def_dict[key])
    for key, val in test_def_dict.items():
        if isinstance(val, pd.Timestamp) or hasattr(val, "isoformat"):
            test_def_dict[key] = val.isoformat() if val and str(val) != "NaT" else ""

    test_types = run_test_type_lookup_query().to_dict("records")
    table_columns = get_columns(str(table_group.id))

    test_suite_info = {
        "id": str(full_test_suite.id),
        "test_suite": full_test_suite.test_suite,
        "severity": full_test_suite.severity,
        "export_to_observability": bool(full_test_suite.export_to_observability),
    }

    return {
        "open": True,
        "test_definition": make_json_safe(test_def_dict),
        "test_types": make_json_safe(test_types),
        "table_columns": table_columns,
        "table_group_schema": table_group.table_group_schema,
        "test_suite": test_suite_info,
    }


def _load_notes_dialog_data(td_id_or_state: dict | str, df: pd.DataFrame) -> dict:
    """Build notes dialog data from a test definition ID or existing state dict."""
    if isinstance(td_id_or_state, dict):
        td_id = td_id_or_state.get("id")
        test_label = {
            "table": td_id_or_state.get("table_name", ""),
            "column": td_id_or_state.get("column_name", ""),
            "test": td_id_or_state.get("test_name_short", ""),
        }
    else:
        td_id = td_id_or_state
        row_df = df[df["test_definition_id"] == str(td_id)]
        if row_df.empty:
            test_label = {"table": "", "column": "", "test": ""}
        else:
            row = row_df.iloc[0]
            test_label = {"table": row["table_name"], "column": row["column_names"], "test": row["test_name_short"]}

    current_user = session.auth.user.username if session.auth.user else "unknown"
    notes = TestDefinitionNote.get_notes(td_id)
    return {
        "id": str(td_id),
        "test_label": test_label,
        "notes": notes,
        "current_user": current_user,
    }


@with_database_session
def _build_source_data(row: dict, mask_pii: bool = False) -> dict:
    """Fetch source data for a test result row and return a JSON-safe dict for JS rendering."""
    if row["test_type"] == "CUSTOM":
        bad_data_status, bad_data_msg, _, df_bad = get_test_issue_source_data_custom(row, limit=500, mask_pii=mask_pii)
        query = get_test_issue_source_query_custom(row)
    else:
        bad_data_status, bad_data_msg, _, df_bad = get_test_issue_source_data(row, limit=500, mask_pii=mask_pii)
        query = get_test_issue_source_query(row)

    rows = []
    columns = []
    truncated = False
    if bad_data_status not in {"ND", "NA", "ERR"} and df_bad is not None:
        df_bad.columns = [col.replace("_", " ").title() for col in df_bad.columns]
        df_bad.fillna("<null>", inplace=True)
        truncated = len(df_bad) == 500
        columns = list(df_bad.columns)
        rows = df_bad.values.tolist()

    return {
        "table_name": row.get("table_name", ""),
        "column_names": row.get("column_names", ""),
        "test_name_short": row.get("test_name_short", ""),
        "test_description": row.get("test_description", ""),
        "input_parameters": row.get("input_parameters", ""),
        "result_message": row.get("result_message", ""),
        "status": bad_data_status,
        "message": bad_data_msg or "",
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
        "sql_query": query or "",
    }


@with_database_session
def build_selected_item_data(row: dict, test_suite: TestSuiteMinimal) -> dict:
    dfh = test_result_queries.get_test_result_history(row)
    time_columns = ["test_date"]
    date_service.accommodate_dataframe_to_timezone(dfh, st.session_state, time_columns)
    history = json.loads(dfh.to_json(orient="records", date_unit="s"))

    test_definition = _build_test_definition_data(row.get("test_definition_id"), test_suite)

    return {
        "test_result_id": row["test_result_id"],
        "history": history,
        "test_definition": test_definition,
    }


def _build_test_definition_data(test_definition_id: str | None, test_suite: TestSuiteMinimal) -> dict | None:
    def readable_boolean(v: bool) -> str:
        return "Yes" if v else "No"

    if not test_definition_id:
        return None

    test_definition = TestDefinition.get(test_definition_id)
    if not test_definition:
        return None

    dynamic_attributes_labels_raw = test_definition.default_parm_prompts or ""
    dynamic_attributes_labels = dynamic_attributes_labels_raw.split(",") if dynamic_attributes_labels_raw else []

    dynamic_attributes_raw = test_definition.default_parm_columns or ""
    if not dynamic_attributes_raw:
        dynamic_attributes_fields = []
        dynamic_attributes_values = []
    else:
        dynamic_attributes_fields = dynamic_attributes_raw.split(",")
        dynamic_attributes_values = (
            attrgetter(*dynamic_attributes_fields)(test_definition)
            if len(dynamic_attributes_fields) > 1
            else (getattr(test_definition, dynamic_attributes_fields[0]),)
        )

    for field_name in dynamic_attributes_fields[len(dynamic_attributes_labels):]:
        dynamic_attributes_labels.append(snake_case_to_title_case(field_name))

    dynamic_attributes_help_raw = test_definition.default_parm_help or ""
    dynamic_attributes_help = dynamic_attributes_help_raw.split("|") if dynamic_attributes_help_raw else []

    return {
        "schema": test_definition.schema_name,
        "test_suite_name": test_suite.test_suite,
        "table_name": test_definition.table_name,
        "test_focus": test_definition.column_name,
        "export_to_observability": (
            readable_boolean(test_definition.export_to_observability)
            if test_definition.export_to_observability is not None
            else f"Inherited ({readable_boolean(test_suite.export_to_observability)})"
        ),
        "severity": test_definition.severity or f"Test Default ({test_definition.default_severity})",
        "locked": readable_boolean(test_definition.lock_refresh),
        "active": readable_boolean(test_definition.test_active),
        "usage_notes": test_definition.usage_notes,
        "last_manual_update": (
            test_definition.last_manual_update.isoformat() if test_definition.last_manual_update else None
        ),
        "custom_query": (
            test_definition.custom_query if "custom_query" in dynamic_attributes_fields else None
        ),
        "attributes": [
            {"label": label, "value": value, "help": help_}
            for label, value, help_ in zip_longest(
                dynamic_attributes_labels,
                dynamic_attributes_values,
                dynamic_attributes_help,
            )
            if label and value
        ],
    }


def _handle_export(export_filters: dict, run_id: str, run_date: str, test_suite: TestSuiteMinimal) -> None:
    from testgen.common.models.table_group import TableGroup
    table_group = TableGroup.get_minimal(test_suite.table_groups_id)

    export_type = export_filters.get("type", "all")
    with st.spinner("Loading data ..."):
        if export_type == "selected":
            selected_ids = export_filters.get("ids", [])
            export_df = test_result_queries.get_test_results(run_id)
            if selected_ids:
                export_df = export_df[export_df["test_result_id"].isin(selected_ids)]
        elif export_type == "filtered":
            status_filter = export_filters.get("status")
            test_statuses = _parse_status_filter(status_filter)
            action_filter = export_filters.get("action")
            export_df = test_result_queries.get_test_results(
                run_id,
                test_statuses=test_statuses,
                table_name=export_filters.get("table_name"),
                column_name=export_filters.get("column_name"),
                test_type_id=export_filters.get("test_type"),
                action=_map_action_filter(action_filter),
            )
        else:
            export_df = test_result_queries.get_test_results(run_id)

    download_dialog(
        dialog_title="Download Excel Report",
        file_content_func=get_excel_report_data,
        args=(test_suite.test_suite, table_group.table_group_schema, run_date, run_id, export_df),
    )


def _handle_issue_report(rows: list[dict]) -> None:
    mask_pii = not session.auth.user_has_permission("view_pii")
    if len(rows) == 1:
        download_dialog(
            dialog_title="Download Issue Report",
            file_content_func=get_report_file_data,
            args=(rows[0], mask_pii),
        )
    else:
        zip_func = zip_multi_file_data(
            "testgen_test_issue_reports.zip",
            get_report_file_data,
            [(row, mask_pii) for row in rows],
        )
        download_dialog(dialog_title="Download Issue Report", file_content_func=zip_func)


@st.cache_data(show_spinner=False)
def get_test_disposition(test_run_id: str) -> pd.DataFrame:
    query = """
    SELECT id::VARCHAR, disposition
    FROM test_results
    WHERE test_run_id = :test_run_id;
    """
    df = fetch_df_from_db(query, {"test_run_id": test_run_id})
    df["action"] = df["disposition"].replace(DISPOSITION_MAP)
    return df[["id", "action"]]


@st.cache_data(show_spinner=False)
def get_test_result_summary(test_run_id: str) -> list[dict]:
    query = """
    SELECT SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Passed' THEN 1
                ELSE 0
            END
        ) as passed_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Warning' THEN 1
                ELSE 0
            END
        ) as warning_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Failed' THEN 1
                ELSE 0
            END
        ) as failed_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Error' THEN 1
                ELSE 0
            END
        ) as error_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Log' THEN 1
                ELSE 0
            END
        ) as log_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                ELSE 0
            END
        ) as dismissed_ct
    FROM test_runs
    LEFT JOIN test_results ON (
        test_runs.id = test_results.test_run_id
    )
    WHERE test_runs.id = :test_run_id;
    """
    result = fetch_one_from_db(query, {"test_run_id": test_run_id})

    return [
        {"label": "Passed", "value": result.passed_ct, "color": "green"},
        {"label": "Warning", "value": result.warning_ct, "color": "yellow"},
        {"label": "Failed", "value": result.failed_ct, "color": "red"},
        {"label": "Error", "value": result.error_ct, "color": "brown"},
        {"label": "Log", "value": result.log_ct, "color": "blue"},
        {"label": "Dismissed", "value": result.dismissed_ct, "color": "grey"},
    ]


@with_database_session
def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    test_suite: str,
    schema: str,
    run_date: str,
    run_id: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is None:
        data = test_result_queries.get_test_results(run_id)

    columns = {
        "table_name": {"header": "Table"},
        "column_names": {"header": "Columns/Focus"},
        "test_name_short": {"header": "Test type"},
        "test_description": {"header": "Description", "wrap": True},
        "dq_dimension": {"header": "Quality dimension"},
        "impact_dimension": {"header": "Impact dimension"},
        "measure_uom": {"header": "Unit of measure (UOM)"},
        "measure_uom_description": {"header": "UOM description"},
        "threshold_value": {},
        "severity": {},
        "result_measure": {},
        "result_status": {"header": "Status"},
        "result_message": {"header": "Message"},
        "action": {},
        "flagged_display": {"header": "Flagged"},
    }
    return get_excel_file_data(
        data,
        "Test Results",
        details={"Test suite": test_suite, "Schema": schema, "Test run date": run_date},
        columns=columns,
        update_progress=update_progress,
    )


def get_report_file_data(update_progress, tr_data, mask_pii: bool = False) -> FILE_DATA_TYPE:
    tr_id = tr_data["test_result_id"][:8]
    tr_time = pd.Timestamp(tr_data["test_date"]).strftime("%Y%m%d_%H%M%S")
    file_name = f"testgen_test_issue_report_{tr_id}_{tr_time}.pdf"

    with BytesIO() as buffer:
        create_report(buffer, tr_data, mask_pii=mask_pii)
        update_progress(1.0)
        buffer.seek(0)
        return file_name, "application/pdf", buffer.read()


def update_result_disposition(
    test_result_ids: list[str],
    disposition: str,
) -> None:
    execute_db_query(
        """
        WITH selects
            AS (SELECT UNNEST(ARRAY [:test_result_ids]) AS selected_id)
        UPDATE test_results
        SET disposition = NULLIF(:disposition, 'No Decision')
        FROM test_results r
        INNER JOIN selects s
            ON (r.id = s.selected_id::UUID)
        WHERE r.id = test_results.id
            AND r.result_status != 'Passed';
        """,
        {
            "test_result_ids": test_result_ids,
            "disposition": disposition,
        },
    )

    execute_db_query(
        """
        WITH selects
            AS (SELECT UNNEST(ARRAY [:test_result_ids]) AS selected_id)
        UPDATE test_definitions
        SET test_active = :test_active,
            last_manual_update = CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
            lock_refresh = :lock_refresh
        FROM test_definitions d
        INNER JOIN test_results r
            ON (d.id = r.test_definition_id)
        INNER JOIN selects s
            ON (r.id = s.selected_id::UUID)
        WHERE d.id = test_definitions.id
            AND r.result_status != 'Passed';
        """,
        {
            "test_result_ids": test_result_ids,
            "test_active": "N" if disposition == "Inactive" else "Y",
            "lock_refresh": "Y" if disposition == "Inactive" else "N",
        },
    )
