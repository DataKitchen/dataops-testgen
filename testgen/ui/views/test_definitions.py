import json
import logging
import typing
from datetime import UTC, datetime

import pandas as pd
import streamlit as st
from sqlalchemy import and_, asc, case, desc, func, or_, tuple_

from testgen.common import date_service
from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.common.models.test_definition import (
    TestDefinition,
    TestDefinitionMinimal,
    TestDefinitionNote,
    TestDefinitionSummary,
)
from testgen.common.models.test_suite import TestSuite
from testgen.common.pii_masking import get_pii_columns, mask_profiling_pii
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
)
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries import profiling_queries
from testgen.ui.services.database_service import fetch_all_from_db, fetch_df_from_db, fetch_from_target_db
from testgen.ui.session import session
from testgen.utils import make_json_safe, to_dataframe

LOG = logging.getLogger("testgen")

PAGE_SIZE = 500

# Maps JS column names to SQL ORDER BY expressions
SORT_FIELD_MAP = {
    "table_name": "table_name",
    "column_name": "column_name",
    "test_name_short": "test_name_short",
    "flagged": "flagged",
}

TD_ADD_DIALOG_KEY = "td:add_dialog"
TD_EDIT_DIALOG_KEY = "td:edit_dialog"
TD_DELETE_DIALOG_KEY = "td:delete_dialog"
TD_COPY_MOVE_DIALOG_KEY = "td:copy_move_dialog"
TD_UNLOCK_DIALOG_KEY = "td:unlock_dialog"
TD_RUN_TESTS_DIALOG_KEY = "td:run_tests_dialog"
TD_RUN_TESTS_RESULT_KEY = "td:run_tests_result"
TD_VALIDATE_RESULT_KEY = "td:validate_result"
TD_COPY_MOVE_COLLISION_KEY = "td:copy_move_collision"
TD_COPY_MOVE_OVERWRITE_KEY = "td:copy_move_overwrite"
TD_NOTES_DIALOG_KEY = "td:notes_dialog"
TD_PROFILING_KEY = "td:profiling"


def _parse_sort_param(sort: str | None) -> tuple[list | None, list[dict]]:
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
            sorting_columns.append((sql_expr, order.upper()))
            sort_state.append({"field": field, "order": order})

    return sorting_columns if sorting_columns else None, sort_state


class TestDefinitionsPage(Page):
    path = "test-suites:definitions"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "test_suite_id" in st.query_params or "test-suites",
    ]

    def render(
        self,
        test_suite_id: str,
        table_name: str | None = None,
        column_name: str | None = None,
        test_type: str | None = None,
        flagged: str | None = None,
        page: str | None = None,
        page_size: str | None = None,
        sort: str | None = None,
        **_kwargs,
    ) -> None:
        test_suite = TestSuite.get(test_suite_id)
        if not test_suite:
            self.router.navigate_with_warning(
                f"Test suite with ID '{test_suite_id}' does not exist. Redirecting to list of Test Suites ...",
                "test-suites",
            )
            return

        table_group = TableGroup.get_minimal(test_suite.table_groups_id)
        project_code = table_group.project_code

        if not session.auth.user_has_project_access(project_code):
            self.router.navigate_with_warning(
                "You don't have access to view this resource. Redirecting ...",
                "test-suites",
            )
            return

        session.set_sidebar_project(project_code)
        testgen.page_header(
            "Test Definitions",
            "test-definitions",
            breadcrumbs=[
                {"label": "Test Suites", "path": "test-suites", "params": {"project_code": project_code}},
                {"label": test_suite.test_suite},
            ],
        )

        # Parse pagination and sorting params
        current_page = int(page) if page else 0
        current_page_size = int(page_size) if page_size else PAGE_SIZE
        sorting_columns, sort_state = _parse_sort_param(sort)

        with st.spinner("Loading data ..."):
            user_can_edit = session.auth.user_has_permission("edit")
            user_can_disposition = session.auth.user_has_permission("disposition")
            df = get_test_definitions(test_suite, table_name, column_name, test_type, sorting_columns,
                                       page=current_page, page_size=current_page_size,
                                       flagged_filter=flagged)
            total_count = get_test_definitions_count(test_suite, table_name, column_name, test_type,
                                                      flagged_filter=flagged)
            test_types = run_test_type_lookup_query().to_dict("records")
            table_columns = get_columns(str(table_group.id))
            filter_columns_df = get_test_suite_columns(test_suite_id)
            table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
            all_test_suites = TestSuite.select_minimal_where(
                TestSuite.table_groups_id.in_([str(tg.id) for tg in table_groups]),
                TestSuite.is_monitor.isnot(True),
            )

        # Build filter options
        table_options = sorted(filter_columns_df["table_name"].dropna().unique().tolist(), key=str.lower)
        columns_raw = (
            filter_columns_df[["table_name", "column_name"]]
            .dropna(subset=["column_name"])
            .drop_duplicates()
            .to_dict("records")
        )
        test_type_options = (
            filter_columns_df[["test_type", "test_name_short"]]
            .dropna(subset=["test_type"])
            .drop_duplicates(subset=["test_type"])
            .sort_values("test_name_short")
            .to_dict("records")
        )

        # Build test suite info dict
        test_suite_info = {
            "id": str(test_suite.id),
            "test_suite": test_suite.test_suite,
            "severity": test_suite.severity,
            "export_to_observability": bool(test_suite.export_to_observability),
        }

        # Build dialog states
        validate_result = st.session_state.pop(TD_VALIDATE_RESULT_KEY, None)

        add_dialog = None
        if st.session_state.get(TD_ADD_DIALOG_KEY):
            add_dialog = {
                "open": True,
                "test_types": test_types,
                "table_columns": table_columns,
                "table_groups_id": str(table_group.id),
                "table_group_schema": table_group.table_group_schema,
                "test_suite": test_suite_info,
            }

        edit_dialog = None
        if selected_def := st.session_state.get(TD_EDIT_DIALOG_KEY):
            edit_dialog = {
                "open": True,
                "test_definition": selected_def,
                "test_types": test_types,
                "table_columns": table_columns,
                "table_group_schema": table_group.table_group_schema,
                "test_suite": test_suite_info,
            }

        delete_dialog = None
        if selected := st.session_state.get(TD_DELETE_DIALOG_KEY):
            delete_dialog = {"open": True, "count": len(selected), "ids": [s["id"] for s in selected]}

        unlock_dialog = None
        if selected := st.session_state.get(TD_UNLOCK_DIALOG_KEY):
            unlock_dialog = {"open": True, "count": len(selected), "ids": [s["id"] for s in selected]}

        copy_move_dialog = None
        if selected := st.session_state.get(TD_COPY_MOVE_DIALOG_KEY):
            suites_by_tg: dict[str, list] = {}
            for ts in all_test_suites:
                suites_by_tg.setdefault(str(ts.table_groups_id), []).append(
                    {"id": str(ts.id), "test_suite": ts.test_suite}
                )
            copy_move_dialog = {
                "open": True,
                "selected": selected,
                "table_groups": [{"id": str(tg.id), "table_groups_name": tg.table_groups_name} for tg in table_groups],
                "current_table_group_id": str(table_group.id),
                "current_test_suite_id": str(test_suite.id),
                "test_suites_by_table_group": suites_by_tg,
                "filter_columns": filter_columns_df[["table_name", "column_name"]].drop_duplicates().to_dict("records"),
                "collision": st.session_state.get(TD_COPY_MOVE_COLLISION_KEY),
            }

        run_tests_data = None
        if st.session_state.get(TD_RUN_TESTS_DIALOG_KEY):
            run_tests_data = {
                "open": True,
                "project_code": project_code,
                "test_suites": [{"value": str(test_suite.id), "label": test_suite.test_suite}],
                "default_test_suite_id": str(test_suite.id),
                "result": st.session_state.get(TD_RUN_TESTS_RESULT_KEY),
            }

        notes_dialog = None
        if notes_state := st.session_state.get(TD_NOTES_DIALOG_KEY):
            notes_dialog = _load_notes_dialog_data(notes_state.get("id") or notes_state, df)

        # --- Event handlers ---

        def on_add_dialog_opened(*_) -> None:
            st.session_state[TD_ADD_DIALOG_KEY] = True

        @with_database_session
        def on_edit_dialog_opened(payload: dict) -> None:
            # Payload is either the full row dict or just { id: ... }
            test_def_id = payload.get("id") if isinstance(payload, dict) else None
            if not test_def_id:
                return
            # Fetch fresh row from the current data
            row_df = df[df["id"] == test_def_id]
            if not row_df.empty:
                test_def = json.loads(row_df.to_json(orient="records", date_unit="s"))[0]
                st.session_state[TD_EDIT_DIALOG_KEY] = test_def

        def on_delete_dialog_opened(selected: list) -> None:
            # Extract just ids from the payload
            if selected and isinstance(selected[0], dict):
                st.session_state[TD_DELETE_DIALOG_KEY] = [{"id": s["id"]} for s in selected]
            else:
                st.session_state[TD_DELETE_DIALOG_KEY] = selected

        @with_database_session
        def on_delete_all_opened(*_) -> None:
            all_ids = get_test_definition_ids(test_suite, table_name, column_name, test_type, flagged_filter=flagged)
            st.session_state[TD_DELETE_DIALOG_KEY] = [{"id": id_} for id_ in all_ids]

        def on_unlock_dialog_opened(selected: list) -> None:
            if selected and isinstance(selected[0], dict):
                st.session_state[TD_UNLOCK_DIALOG_KEY] = [{"id": s["id"]} for s in selected]
            else:
                st.session_state[TD_UNLOCK_DIALOG_KEY] = selected

        @with_database_session
        def on_unlock_all_opened(*_) -> None:
            all_ids = get_test_definition_ids(test_suite, table_name, column_name, test_type, flagged_filter=flagged)
            st.session_state[TD_UNLOCK_DIALOG_KEY] = [{"id": id_} for id_ in all_ids]

        @with_database_session
        def on_copy_move_dialog_opened(selected) -> None:
            if selected == "all":
                all_ids = get_test_definition_ids(test_suite, table_name, column_name, test_type, flagged_filter=flagged)
                results = TestDefinition.select_where(TestDefinition.id.in_(all_ids))
                selected = [
                    {"id": str(r.id), "table_name": r.table_name, "column_name": r.column_name,
                     "test_type": r.test_type, "lock_refresh": r.lock_refresh}
                    for r in results
                ]
            # selected contains minimal row dicts (id, table_name, column_name, test_type, lock_refresh)
            st.session_state[TD_COPY_MOVE_DIALOG_KEY] = selected
            st.session_state.pop(TD_COPY_MOVE_COLLISION_KEY, None)
            st.session_state.pop(TD_COPY_MOVE_OVERWRITE_KEY, None)

        def on_add_dialog_closed(*_) -> None:
            st.session_state.pop(TD_ADD_DIALOG_KEY, None)
            st.session_state.pop(TD_VALIDATE_RESULT_KEY, None)

        def on_edit_dialog_closed(*_) -> None:
            st.session_state.pop(TD_EDIT_DIALOG_KEY, None)
            st.session_state.pop(TD_VALIDATE_RESULT_KEY, None)

        def on_delete_dialog_closed(*_) -> None:
            st.session_state.pop(TD_DELETE_DIALOG_KEY, None)

        def on_unlock_dialog_closed(*_) -> None:
            st.session_state.pop(TD_UNLOCK_DIALOG_KEY, None)

        def on_copy_move_dialog_closed(*_) -> None:
            st.session_state.pop(TD_COPY_MOVE_DIALOG_KEY, None)
            st.session_state.pop(TD_COPY_MOVE_COLLISION_KEY, None)
            st.session_state.pop(TD_COPY_MOVE_OVERWRITE_KEY, None)

        @with_database_session
        def on_add_test_saved(test_def: dict) -> None:
            test_def["last_manual_update"] = datetime.now(UTC)
            td_columns = set(TestDefinition.__table__.columns.keys())
            TestDefinition(**{k: v for k, v in test_def.items() if k in td_columns}).save()
            st.cache_data.clear()
            st.session_state.pop(TD_ADD_DIALOG_KEY, None)
            st.session_state.pop(TD_VALIDATE_RESULT_KEY, None)

        @with_database_session
        def on_edit_test_saved(test_def: dict) -> None:
            test_def["last_manual_update"] = datetime.now(UTC)
            td_columns = set(TestDefinition.__table__.columns.keys())
            TestDefinition(**{k: v for k, v in test_def.items() if k in td_columns}).save()
            st.cache_data.clear()
            st.session_state.pop(TD_EDIT_DIALOG_KEY, None)
            st.session_state.pop(TD_VALIDATE_RESULT_KEY, None)

        @with_database_session
        def on_delete_confirmed(payload: dict) -> None:
            ids = payload.get("ids", [])
            TestDefinition.delete_where(TestDefinition.id.in_(ids))
            st.cache_data.clear()
            st.session_state.pop(TD_DELETE_DIALOG_KEY, None)

        @with_database_session
        def on_unlock_confirmed(payload: dict) -> None:
            ids = payload.get("ids", [])
            TestDefinition.set_status_attribute("lock_refresh", ids, False)
            st.cache_data.clear()
            st.session_state.pop(TD_UNLOCK_DIALOG_KEY, None)

        @with_database_session
        def on_update_attribute(payload: dict) -> None:
            attribute = payload["attribute"]
            ids = payload["ids"]
            value = payload["value"]
            TestDefinition.set_status_attribute(attribute, ids, value)
            st.cache_data.clear()

        @with_database_session
        def on_update_attribute_all(payload: dict) -> None:
            attribute = payload["attribute"]
            value = payload["value"]
            all_ids = get_test_definition_ids(test_suite, table_name, column_name, test_type, flagged_filter=flagged)
            if all_ids:
                TestDefinition.set_status_attribute(attribute, all_ids, value)
                st.cache_data.clear()

        @with_database_session
        def on_copy_confirmed(payload: dict) -> None:
            ids = payload["ids"]
            target_tg_id = payload["target_table_group_id"]
            target_ts_id = payload["target_test_suite_id"]
            target_table = payload.get("target_table_name")
            target_col = payload.get("target_column_name")
            overwrite_ids = st.session_state.pop(TD_COPY_MOVE_OVERWRITE_KEY, [])
            if overwrite_ids:
                TestDefinition.delete_where(TestDefinition.id.in_(overwrite_ids))
            TestDefinition.copy(ids, target_tg_id, target_ts_id, target_table, target_col)
            st.cache_data.clear()
            get_test_suite_columns.clear()
            st.session_state.pop(TD_COPY_MOVE_DIALOG_KEY, None)
            st.session_state.pop(TD_COPY_MOVE_COLLISION_KEY, None)
            st.session_state.pop(TD_COPY_MOVE_OVERWRITE_KEY, None)

        @with_database_session
        def on_move_confirmed(payload: dict) -> None:
            ids = payload["ids"]
            target_tg_id = payload["target_table_group_id"]
            target_ts_id = payload["target_test_suite_id"]
            target_table = payload.get("target_table_name")
            target_col = payload.get("target_column_name")
            overwrite_ids = st.session_state.pop(TD_COPY_MOVE_OVERWRITE_KEY, [])
            if overwrite_ids:
                TestDefinition.delete_where(TestDefinition.id.in_(overwrite_ids))
            TestDefinition.move(ids, target_tg_id, target_ts_id, target_table, target_col)
            st.cache_data.clear()
            get_test_suite_columns.clear()
            st.session_state.pop(TD_COPY_MOVE_DIALOG_KEY, None)
            st.session_state.pop(TD_COPY_MOVE_COLLISION_KEY, None)
            st.session_state.pop(TD_COPY_MOVE_OVERWRITE_KEY, None)

        @with_database_session
        def on_copy_move_target_changed(payload: dict) -> None:
            selected = payload["selected"]
            target_tg_id = payload["target_table_group_id"]
            target_ts_id = payload["target_test_suite_id"]
            target_table = payload.get("target_table_name")
            target_col = payload.get("target_column_name")
            collision_df = get_test_definitions_collision(selected, target_tg_id, target_ts_id, target_table, target_col)
            overwrite_ids = []
            if collision_df.empty:
                st.session_state[TD_COPY_MOVE_COLLISION_KEY] = []
            else:
                unlocked = collision_df[collision_df["lock_refresh"] == False]
                selected_ids = {str(item["id"]) for item in selected}
                overwrite_ids = [id_ for id_ in unlocked["id"].tolist() if str(id_) not in selected_ids]
                # Only send the fields JS needs (lock_refresh, table_name, column_name, test_type)
                cols = ["table_name", "column_name", "test_type", "lock_refresh"]
                st.session_state[TD_COPY_MOVE_COLLISION_KEY] = collision_df[cols].to_dict("records")
            st.session_state[TD_COPY_MOVE_OVERWRITE_KEY] = overwrite_ids

        @with_database_session
        def on_validate_test(test_def: dict) -> None:
            try:
                validate_test(test_def, table_group)
                st.session_state[TD_VALIDATE_RESULT_KEY] = {"success": True, "message": "Validation is successful."}
            except Exception as e:
                st.session_state[TD_VALIDATE_RESULT_KEY] = {
                    "success": False,
                    "message": f"Test validation failed with error: {e}",
                }

        def on_run_tests_clicked(*_) -> None:
            st.session_state[TD_RUN_TESTS_DIALOG_KEY] = True

        @with_database_session
        def on_run_tests_confirmed(data: dict) -> None:
            selected_id = data.get("test_suite_id")
            selected_name = data.get("test_suite_name")
            success = True
            message = f"Test run started for test suite '{selected_name}'."
            show_link = session.current_page != "test-runs"
            try:
                JobExecution.submit(
                    job_key="run-tests",
                    kwargs={"test_suite_id": str(selected_id)},
                    source="ui",
                    project_code=project_code,
                )
            except Exception as error:
                success = False
                message = f"Test run could not be started: {error!s}."
                show_link = False
            st.session_state[TD_RUN_TESTS_RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
            if success and not show_link:
                st.cache_data.clear()
                st.session_state.pop(TD_RUN_TESTS_DIALOG_KEY, None)
                st.session_state.pop(TD_RUN_TESTS_RESULT_KEY, None)

        def on_run_tests_dialog_closed(*_) -> None:
            st.session_state.pop(TD_RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(TD_RUN_TESTS_RESULT_KEY, None)

        def on_go_to_test_runs(payload: dict) -> None:
            st.session_state.pop(TD_RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(TD_RUN_TESTS_RESULT_KEY, None)
            Router().queue_navigation(to="test-runs", with_args=payload)

        def on_notes_clicked(payload: dict) -> None:
            st.session_state[TD_NOTES_DIALOG_KEY] = payload

        @with_database_session
        def on_note_added(payload: dict) -> None:
            td_id = payload["test_definition_id"]
            current_user = session.auth.user.username if session.auth.user else "unknown"
            TestDefinitionNote.add_note(td_id, payload["text"], current_user)
            st.session_state[TD_NOTES_DIALOG_KEY] = _load_notes_dialog_data(td_id, df)
            st.cache_data.clear()

        @with_database_session
        def on_note_updated(payload: dict) -> None:
            TestDefinitionNote.update_note(payload["id"], payload["text"])
            td_id = payload["test_definition_id"]
            st.session_state[TD_NOTES_DIALOG_KEY] = _load_notes_dialog_data(td_id, df)

        @with_database_session
        def on_note_deleted(payload: dict) -> None:
            TestDefinitionNote.delete_note(payload["id"])
            td_id = payload["test_definition_id"]
            st.session_state[TD_NOTES_DIALOG_KEY] = _load_notes_dialog_data(td_id, df)
            st.cache_data.clear()

        def on_notes_dialog_closed(*_) -> None:
            st.session_state.pop(TD_NOTES_DIALOG_KEY, None)

        @with_database_session
        def on_profiling_clicked(payload: dict) -> None:
            column_name = payload.get("column_name")
            table_name = payload.get("table_name")
            table_groups_id = payload.get("table_groups_id")
            if not (column_name and table_name and table_groups_id):
                return
            column = profiling_queries.get_column_by_name(column_name, table_name, table_groups_id)
            if column:
                mask_profiling_pii(column, get_pii_columns(table_groups_id, table_name=table_name))
                st.session_state[TD_PROFILING_KEY] = make_json_safe(column)

        def on_profiling_closed(*_) -> None:
            st.session_state.pop(TD_PROFILING_KEY, None)

        def on_export_all(*_) -> None:
            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(test_suite, table_group.table_group_schema),
            )

        def on_export_filtered(payload: dict) -> None:
            records = payload.get("records", [])
            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(test_suite, table_group.table_group_schema, pd.DataFrame(records)),
            )

        @with_database_session
        def on_export_selected(payload: dict) -> None:
            ids = payload.get("ids", [])
            if ids:
                data = get_test_definitions(test_suite)
                data = data[data["id"].isin(ids)]
                download_dialog(
                    dialog_title="Download Excel Report",
                    file_content_func=get_excel_report_data,
                    args=(test_suite, table_group.table_group_schema, data),
                )

        def on_filter_changed(filters: dict) -> None:
            Router().set_query_params({**filters, "page": "0"})

        def on_page_changed(payload: dict) -> None:
            new_page = payload.get("page", 0)
            new_page_size = payload.get("page_size")
            params: dict = {"page": str(new_page)}
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
            Router().set_query_params({"sort": sort_value, "page": "0"})

        testgen.test_definitions_widget(
            key="test_definitions",
            data={
                "test_suite": {
                    "id": str(test_suite.id),
                    "test_suite": test_suite.test_suite,
                    "project_code": project_code,
                },
                "test_definitions": json.loads(df.to_json(orient="records", date_unit="s")),
                "filter_options": {
                    "tables": table_options,
                    "columns": columns_raw,
                    "test_types": test_type_options,
                },
                "current_filters": {
                    "table_name": table_name,
                    "column_name": column_name,
                    "test_type": test_type,
                    "flagged": flagged,
                },
                "page": current_page,
                "total_count": total_count,
                "page_size": current_page_size,
                "sort_state": sort_state,
                "permissions": {
                    "can_edit": user_can_edit,
                    "can_disposition": user_can_disposition,
                },
                "validate_result": validate_result,
                "add_dialog": add_dialog,
                "edit_dialog": edit_dialog,
                "delete_dialog": delete_dialog,
                "unlock_dialog": unlock_dialog,
                "copy_move_dialog": copy_move_dialog,
                "run_tests_dialog": run_tests_data,
                "notes_dialog": notes_dialog,
                "profiling_column": st.session_state.get(TD_PROFILING_KEY),
            },
            on_AddDialogOpened_change=on_add_dialog_opened,
            on_EditDialogOpened_change=on_edit_dialog_opened,
            on_DeleteDialogOpened_change=on_delete_dialog_opened,
            on_DeleteAllOpened_change=on_delete_all_opened,
            on_UnlockDialogOpened_change=on_unlock_dialog_opened,
            on_UnlockAllOpened_change=on_unlock_all_opened,
            on_CopyMoveDialogOpened_change=on_copy_move_dialog_opened,
            on_AddDialogClosed_change=on_add_dialog_closed,
            on_EditDialogClosed_change=on_edit_dialog_closed,
            on_DeleteDialogClosed_change=on_delete_dialog_closed,
            on_UnlockDialogClosed_change=on_unlock_dialog_closed,
            on_CopyMoveDialogClosed_change=on_copy_move_dialog_closed,
            on_AddTestSaved_change=on_add_test_saved,
            on_EditTestSaved_change=on_edit_test_saved,
            on_DeleteConfirmed_change=on_delete_confirmed,
            on_UnlockConfirmed_change=on_unlock_confirmed,
            on_UpdateAttribute_change=on_update_attribute,
            on_UpdateAttributeAll_change=on_update_attribute_all,
            on_CopyConfirmed_change=on_copy_confirmed,
            on_MoveConfirmed_change=on_move_confirmed,
            on_CopyMoveTargetChanged_change=on_copy_move_target_changed,
            on_ValidateTest_change=on_validate_test,
            on_RunTestsClicked_change=on_run_tests_clicked,
            on_RunTestsConfirmed_change=on_run_tests_confirmed,
            on_RunTestsDialogClosed_change=on_run_tests_dialog_closed,
            on_GoToTestRunsClicked_change=on_go_to_test_runs,
            on_ExportAll_change=on_export_all,
            on_ExportFiltered_change=on_export_filtered,
            on_ExportSelected_change=on_export_selected,
            on_NotesClicked_change=on_notes_clicked,
            on_NoteAdded_change=on_note_added,
            on_NoteUpdated_change=on_note_updated,
            on_NoteDeleted_change=on_note_deleted,
            on_NotesDialogClosed_change=on_notes_dialog_closed,
            on_ProfilingClicked_change=on_profiling_clicked,
            on_ProfilingClosed_change=on_profiling_closed,
            on_FilterChanged_change=on_filter_changed,
            on_PageChanged_change=on_page_changed,
            on_SortChanged_change=on_sort_changed,
        )


def _load_notes_dialog_data(td_id_or_state, df: pd.DataFrame) -> dict:
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
        row_df = df[df["id"] == str(td_id)]
        if row_df.empty:
            test_label = {"table": "", "column": "", "test": ""}
        else:
            row = row_df.iloc[0]
            test_label = {"table": row["table_name"], "column": row["column_name"], "test": row["test_name_short"]}

    current_user = session.auth.user.username if session.auth.user else "unknown"
    notes = TestDefinitionNote.get_notes(td_id)
    return {
        "id": str(td_id),
        "test_label": test_label,
        "notes": notes,
        "current_user": current_user,
    }


@with_database_session
def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    test_suite: TestSuite,
    schema: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    from datetime import datetime

    if data is not None:
        data = data.copy()
    else:
        data = get_test_definitions(test_suite)

    for key in ["test_active_display", "lock_refresh_display", "flagged_display"]:
        data[key] = data[key].apply(lambda val: val if val == "Yes" else None)

    for key in ["profiling_as_of_date", "last_manual_update"]:
        data[key] = data[key].apply(
            lambda val: datetime.strptime(val, "%Y-%m-%d %H:%M:%S").strftime("%b %-d %Y, %-I:%M %p")
            if (val and not pd.isna(val) and val != "NaT")
            else None
        )

    columns = {
        "table_name": {"header": "Table"},
        "column_name": {"header": "Column/Focus"},
        "test_name_short": {"header": "Test type"},
        "final_test_description": {"header": "Description", "wrap": True},
        "threshold_value": {},
        "export_uom": {"header": "Unit of measure"},
        "test_active_display": {"header": "Active"},
        "lock_refresh_display": {"header": "Locked"},
        "flagged_display": {"header": "Flagged"},
        "urgency": {"header": "Severity"},
        "profiling_as_of_date": {"header": "From profiling as-of (UTC)"},
        "last_manual_update": {"header": "Last manual update (UTC)"},
    }
    return get_excel_file_data(
        data,
        "Test Definitions",
        details={"Test suite": test_suite.test_suite, "Schema": schema},
        columns=columns,
        update_progress=update_progress,
    )


@st.cache_data(show_spinner=False)
def run_test_type_lookup_query(test_type: str | None = None) -> pd.DataFrame:
    query = f"""
    SELECT
        tt.id, tt.test_type,
        tt.test_name_short, tt.test_name_long, tt.test_description,
        tt.measure_uom, COALESCE(tt.measure_uom_description, '') as measure_uom_description,
        tt.default_parm_columns, tt.default_severity,
        tt.run_type, tt.test_scope, tt.dq_dimension, tt.threshold_description,
        tt.column_name_prompt, tt.column_name_help,
        tt.default_parm_prompts, tt.default_parm_help, tt.usage_notes,
        CASE tt.test_scope
            WHEN 'referential' THEN '⧉ '
            WHEN 'custom' THEN '⛭ '
            WHEN 'table' THEN '⊞ '
            WHEN 'column' THEN '≣ '
            WHEN 'tablegroup' THEN '▦ '
            ELSE '? '
        END
        || tt.test_name_short
        || ': '
        || lower(tt.test_name_long)
        || CASE
            WHEN tt.selection_criteria > '' THEN ' [auto-generated]'
            ELSE ''
        END as select_name
    FROM test_types tt
    WHERE tt.active = 'Y'
        {"AND tt.test_type = :test_type" if test_type else ""}
    ORDER BY
        CASE tt.test_scope
            WHEN 'referential' THEN 1
            WHEN 'custom' THEN 2
            WHEN 'table' THEN 3
            WHEN 'column' THEN 4
            WHEN 'tablegroup' THEN 5
            ELSE 6
        END,
        tt.test_name_short;
    """
    return fetch_df_from_db(query, {"test_type": test_type})


@st.cache_data(show_spinner=False)
def get_test_suite_columns(test_suite_id: str) -> pd.DataFrame:
    results = TestDefinition.select_minimal_where(
        TestDefinition.test_suite_id == test_suite_id,
        order_by=(asc(func.lower(TestDefinition.table_name)), asc(func.lower(TestDefinition.column_name))),
    )
    return to_dataframe(results, TestDefinitionMinimal.columns())


def get_test_definitions(
    test_suite: TestSuite,
    table_name: str | None = None,
    column_name: str | None = None,
    test_type: str | None = None,
    sorting_columns: list[tuple] | None = None,
    page: int = 0,
    page_size: int = 0,
    flagged_filter: str | None = None,
) -> pd.DataFrame:
    clauses = [TestDefinition.test_suite_id == test_suite.id]
    if table_name:
        clauses.append(TestDefinition.table_name == table_name)
    if column_name:
        clauses.append(TestDefinition.column_name.ilike(column_name))
    if test_type:
        clauses.append(TestDefinition.test_type == test_type)
    if flagged_filter == "Flagged":
        clauses.append(TestDefinition.flagged == True)
    elif flagged_filter == "Not Flagged":
        clauses.append(TestDefinition.flagged == False)

    sort_funcs = {"ASC": asc, "DESC": desc}

    sort_expressions = {
        "flagged": lambda d: sort_funcs[d](case((TestDefinition.flagged == True, 0), else_=1)),
    }

    order_by = []
    if sorting_columns:
        for (attribute, direction) in sorting_columns:
            if attribute in sort_expressions:
                order_by.append(sort_expressions[attribute](direction))
            else:
                order_by.append(sort_funcs[direction](func.lower(getattr(TestDefinition, attribute))))

    # For pagination, we need to bypass the base select_where which doesn't support offset/limit.
    # We'll fetch all matching results and slice in Python.
    test_definitions = TestDefinition.select_where(
        *clauses,
        order_by=tuple(order_by) if order_by else None,
    )

    if page_size > 0:
        offset = page * page_size
        test_definitions = list(test_definitions)[offset:offset + page_size]

    df = to_dataframe(test_definitions, TestDefinitionSummary.columns())
    date_service.accommodate_dataframe_to_timezone(df, st.session_state)
    for key in ["id", "table_groups_id", "profile_run_id", "test_suite_id"]:
        df[key] = df[key].apply(lambda value: str(value))

    df["test_active_display"] = df["test_active"].apply(lambda value: "Yes" if value else "No")
    df["lock_refresh_display"] = df["lock_refresh"].apply(lambda value: "Yes" if value else "No")
    df["flagged_display"] = df["flagged"].apply(lambda value: "Yes" if value else "No")
    if not df.empty:
        notes_counts = TestDefinitionNote.get_notes_count_by_ids([str(td_id) for td_id in df["id"]])
        df["notes_count"] = df["id"].map(notes_counts).fillna(0).astype(int)
    else:
        df["notes_count"] = pd.Series(dtype=int)

    df["urgency"] = df.apply(lambda row: row["severity"] or test_suite.severity or row["default_severity"], axis=1)
    df["final_test_description"] = df.apply(
        lambda row: row["test_description"] or row["default_test_description"], axis=1
    )
    df["export_uom"] = df.apply(lambda row: row["measure_uom_description"] or row["measure_uom"], axis=1)

    def get_export_to_observability_display(value: str) -> str:
        if value is not None:
            return "Yes" if value else "No"
        return f"Inherited ({'Yes' if test_suite.export_to_observability else 'No'})"

    df["export_to_observability_display"] = df["export_to_observability"].apply(get_export_to_observability_display)

    for col in df.select_dtypes(include=["datetime"]).columns:
        df[col] = df[col].astype(str).replace("NaT", "")

    return df


def get_test_definitions_count(
    test_suite: TestSuite,
    table_name: str | None = None,
    column_name: str | None = None,
    test_type: str | None = None,
    flagged_filter: str | None = None,
) -> int:
    from testgen.ui.services.database_service import fetch_one_from_db

    where_parts = ["test_suite_id = :test_suite_id"]
    params: dict = {"test_suite_id": str(test_suite.id)}
    if table_name:
        where_parts.append("table_name = :table_name")
        params["table_name"] = table_name
    if column_name:
        where_parts.append("column_name ILIKE :column_name")
        params["column_name"] = column_name
    if test_type:
        where_parts.append("test_type = :test_type")
        params["test_type"] = test_type
    if flagged_filter == "Flagged":
        where_parts.append("flagged = true")
    elif flagged_filter == "Not Flagged":
        where_parts.append("flagged = false")

    query = f"SELECT COUNT(*) as cnt FROM test_definitions WHERE {' AND '.join(where_parts)};"
    result = fetch_one_from_db(query, params)
    return int(result["cnt"]) if result else 0


def get_test_definition_ids(
    test_suite: TestSuite,
    table_name: str | None = None,
    column_name: str | None = None,
    test_type: str | None = None,
    flagged_filter: str | None = None,
) -> list[str]:
    clauses = [TestDefinition.test_suite_id == test_suite.id]
    if table_name:
        clauses.append(TestDefinition.table_name == table_name)
    if column_name:
        clauses.append(TestDefinition.column_name.ilike(column_name))
    if test_type:
        clauses.append(TestDefinition.test_type == test_type)
    if flagged_filter == "Flagged":
        clauses.append(TestDefinition.flagged == True)
    elif flagged_filter == "Not Flagged":
        clauses.append(TestDefinition.flagged == False)
    results = TestDefinition.select_where(*clauses)
    return [str(r.id) for r in results]


def get_test_definitions_collision(
    test_definitions: list[dict],
    target_table_group_id: str,
    target_test_suite_id: str,
    target_table_name: str | None = None,
    target_column_name: str | None = None,
) -> pd.DataFrame:
    table_tests = [
        (target_table_name or item["table_name"], item["test_type"])
        for item in test_definitions
        if item["column_name"] is None and item["table_name"] is not None
    ]
    column_tests = [
        (target_table_name or item["table_name"], target_column_name or item["column_name"], item["test_type"])
        for item in test_definitions
        if item["column_name"] is not None
    ]
    results = TestDefinition.select_minimal_where(
        TestDefinition.table_groups_id == target_table_group_id,
        TestDefinition.test_suite_id == target_test_suite_id,
        TestDefinition.last_auto_gen_date.isnot(None),
        or_(
            tuple_(TestDefinition.table_name, TestDefinition.column_name, TestDefinition.test_type).in_(column_tests),
            and_(
                tuple_(TestDefinition.table_name, TestDefinition.test_type).in_(table_tests),
                TestDefinition.column_name.is_(None),
            ),
        ),
    )
    return to_dataframe(results, TestDefinitionMinimal.columns())


def get_columns(table_groups_id: str) -> list[dict]:
    results = fetch_all_from_db(
        """
        SELECT table_name, column_name
        FROM data_column_chars
        WHERE table_groups_id = :table_groups_id
            AND drop_date IS NULL
        """,
        {"table_groups_id": table_groups_id},
    )
    return [dict(row) for row in results]


def validate_test(test_definition: dict, table_group: TableGroupMinimal) -> None:
    schema = test_definition["schema_name"]
    table_name = test_definition["table_name"]
    connection = Connection.get(table_group.connection_id)

    if test_definition["test_type"] == "Condition_Flag":
        condition = test_definition["custom_query"]
        flavor_service = get_flavor_service(connection.sql_flavor)
        concat_operator = flavor_service.concat_operator
        quote = flavor_service.quote_character
        query = f"""
        SELECT
            COALESCE(
                CAST(
                    SUM(
                        CASE WHEN {condition} THEN 1 ELSE 0 END
                    ) AS VARCHAR(1000)
                )
                {concat_operator} '|',
                '<NULL>|'
            )
        FROM {quote}{schema}{quote}.{quote}{table_name}{quote};
        """
    else:
        query = replace_params(
            f"""
            SELECT COUNT(*)
            FROM (
                {test_definition["custom_query"]}
            ) TEST
            """,
            {"DATA_SCHEMA": schema},
        )

    fetch_from_target_db(connection, query)
