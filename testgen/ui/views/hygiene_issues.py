import typing
from io import BytesIO

import pandas as pd
import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
from testgen.commands.run_rollup_scores import run_profile_rollup_scoring_queries
from testgen.common import date_service
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.pii_masking import get_pii_columns, mask_hygiene_detail, mask_profiling_pii
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
from testgen.ui.pdf.hygiene_issue_report import create_report
from testgen.ui.queries.profiling_queries import get_profiling_anomalies
from testgen.ui.queries.source_data_queries import get_hygiene_issue_source_data, get_hygiene_issue_source_query
from testgen.ui.services.database_service import execute_db_query
from testgen.ui.session import session
from testgen.utils import friendly_score, make_json_safe

PAGE_SIZE = 500

SOURCE_DATA_KEY = "hi:source_data"
PROFILING_KEY = "hi:profiling"
EXPORT_FILTERS_KEY = "hi:export_filters"

# Maps JS column names to SQL ORDER BY expressions
SORT_FIELD_MAP = {
    "table_name": "LOWER(r.table_name)",
    "column_name": "LOWER(r.column_name)",
    "issue_likelihood": """CASE t.issue_likelihood
        WHEN 'Definite' THEN 1 WHEN 'Likely' THEN 2
        WHEN 'Possible' THEN 3 WHEN 'Potential PII' THEN 4 ELSE 99 END""",
    "action": "r.disposition",
    "anomaly_name": "LOWER(t.anomaly_name)",
}


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
            sorting_columns.append([sql_expr, order])
            sort_state.append({"field": field, "order": order})

    return sorting_columns if sorting_columns else None, sort_state


class HygieneIssuesPage(Page):
    path = "profiling-runs:hygiene"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "run_id" in st.query_params or "profiling-runs",
    ]

    def render(
        self,
        run_id: str,
        likelihood: str | None = None,
        table_name: str | None = None,
        column_name: str | None = None,
        issue_type: str | None = None,
        action: str | None = None,
        selected: str | None = None,
        page: str | None = None,
        page_size: str | None = None,
        sort: str | None = None,
        **_kwargs,
    ) -> None:
        run = ProfilingRun.get_minimal(run_id)
        if not run:
            self.router.navigate_with_warning(
                f"Profiling run with ID '{run_id}' does not exist. Redirecting to list of Profiling Runs ...",
                "profiling-runs",
            )
            return

        if not session.auth.user_has_project_access(run.project_code):
            self.router.navigate_with_warning(
                "You don't have access to view this resource. Redirecting ...",
                "profiling-runs",
            )
            return

        run_date = date_service.get_timezoned_timestamp(st.session_state, run.profiling_starttime)
        session.set_sidebar_project(run.project_code)

        testgen.page_header(
            "Hygiene Issues",
            "data-hygiene-issues",
            breadcrumbs=[
                { "label": "Profiling Runs", "path": "profiling-runs", "params": { "project_code": run.project_code } },
                { "label": f"{run.table_groups_name} | {run_date}" },
            ],
        )

        # Handle pending export
        export_filters = st.session_state.pop(EXPORT_FILTERS_KEY, None)
        if export_filters is not None:
            with st.spinner("Loading data ..."):
                export_type = export_filters.get("type", "all")
                if export_type == "selected":
                    export_df = get_profiling_anomalies(run_id)
                    selected_ids = set(export_filters.get("ids", []))
                    export_df = export_df[export_df["id"].isin(selected_ids)]
                elif export_type == "filtered":
                    filters = export_filters.get("filters", {})
                    export_df = get_profiling_anomalies(
                        run_id,
                        likelihood=filters.get("likelihood"),
                        issue_type_id=filters.get("issue_type"),
                        table_name=filters.get("table_name"),
                        column_name=filters.get("column_name"),
                        action=_map_action_filter(filters.get("action")),
                    )
                else:
                    export_df = get_profiling_anomalies(run_id)
            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(run.table_groups_name, run.table_group_schema, run_date, run_id, export_df),
            )

        # Parse pagination and sorting params
        current_page = int(page) if page else 0
        current_page_size = int(page_size) if page_size else PAGE_SIZE
        sorting_columns, sort_state = _parse_sort_param(sort)

        # Map action filter
        action_mapped = _map_action_filter(action)

        # Load data with server-side filtering, sorting, and pagination
        with st.spinner("Loading data ..."):
            df_pa = get_profiling_anomalies(
                run_id,
                likelihood=likelihood,
                issue_type_id=issue_type,
                table_name=table_name,
                column_name=column_name,
                action=action_mapped,
                sorting_columns=sorting_columns,
                page=current_page,
                page_size=current_page_size,
            )

            # Mask detail for PII columns with redactable details
            if not session.auth.user_has_permission("view_pii"):
                mask_hygiene_detail(df_pa)

            # Merge disposition actions
            df_action = _get_anomaly_disposition(run_id)
            action_map = df_action.set_index("id")
            df_pa["action"] = df_pa["id"].map(action_map["action"]).fillna("")
            df_pa["disposition"] = df_pa["id"].map(action_map["disposition"])

            total_count = profiling_queries.get_profiling_anomalies_count(
                run_id,
                likelihood=likelihood,
                issue_type_id=issue_type,
                table_name=table_name,
                column_name=column_name,
                action=action_mapped,
            )

            filter_options = profiling_queries.get_hygiene_filter_options(run_id)

        summaries = _get_profiling_anomaly_summary(run_id)
        items = [
            make_json_safe(record)
            for record in df_pa.where(df_pa.notna(), None).to_dict(orient="records")
        ]

        # Build dialog props
        profiling_column = st.session_state.get(PROFILING_KEY)
        source_data = st.session_state.get(SOURCE_DATA_KEY)

        def on_row_selected(item_id: str) -> None:
            Router().set_query_params({"selected": item_id})

        @with_database_session
        def on_disposition_changed(payload: dict) -> None:
            ids = payload.get("ids", [])
            status = payload.get("status", "No Decision")
            if ids:
                _update_anomaly_disposition(ids, status)
                _get_anomaly_disposition.clear()
                _get_profiling_anomaly_summary.clear()

        @with_database_session
        def on_disposition_all(payload: dict) -> None:
            filters = payload.get("filters", {})
            disposition = payload.get("status", "No Decision")
            filter_action = _map_action_filter(filters.get("action"))
            all_ids = profiling_queries.get_profiling_anomaly_ids(
                run_id,
                likelihood=filters.get("likelihood"),
                issue_type_id=filters.get("issue_type"),
                table_name=filters.get("table_name"),
                column_name=filters.get("column_name"),
                action=filter_action,
            )
            if all_ids:
                _update_anomaly_disposition(all_ids, disposition)
                _get_anomaly_disposition.clear()
                _get_profiling_anomaly_summary.clear()

        def on_filter_changed(payload: dict) -> None:
            Router().set_query_params({
                "likelihood": payload.get("likelihood"),
                "table_name": payload.get("table_name"),
                "column_name": payload.get("column_name"),
                "issue_type": payload.get("issue_type"),
                "action": payload.get("action"),
                "page": "0",
            })

        def on_export_all(*_) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "all"}

        def on_export_filtered(payload: dict) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "filtered", "filters": payload}

        def on_export_selected(payload: dict) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "selected", "ids": payload.get("ids", [])}

        @with_database_session
        def on_view_source_data(row_id: str) -> None:
            anomaly_df = profiling_queries.get_profiling_anomalies_by_ids([row_id])
            if anomaly_df.empty:
                return
            row = make_json_safe(anomaly_df.where(anomaly_df.notna(), None).to_dict(orient="records")[0])

            MixpanelService().send_event(
                "view-source-data",
                page=self.path,
                issue_type=row.get("anomaly_name"),
            )

            mask_pii = not session.auth.user_has_permission("view_pii")
            bad_data_status, bad_data_msg, _, df_bad = get_hygiene_issue_source_data(row, limit=500, mask_pii=mask_pii)

            rows = None
            columns = None
            truncated = False
            if bad_data_status == "OK" and df_bad is not None:
                df_bad.columns = [col.replace("_", " ").title() for col in df_bad.columns]
                df_bad.fillna("<null>", inplace=True)
                truncated = len(df_bad) == 500
                columns = list(df_bad.columns)
                rows = df_bad.values.tolist()

            st.session_state[SOURCE_DATA_KEY] = {
                "header": {
                    "table_name": row.get("table_name", ""),
                    "column_name": row.get("column_name", ""),
                    "anomaly_name": row.get("anomaly_name", ""),
                    "anomaly_description": row.get("anomaly_description", ""),
                    "detail": row.get("detail", ""),
                },
                "status": bad_data_status,
                "message": bad_data_msg,
                "rows": rows,
                "columns": columns,
                "sql_query": get_hygiene_issue_source_query(row),
                "truncated": truncated,
            }

        def on_source_data_closed(*_) -> None:
            st.session_state.pop(SOURCE_DATA_KEY, None)

        @with_database_session
        def on_view_profiling(anomaly_id: str) -> None:
            lookup = profiling_queries.get_profiling_anomaly_lookup(anomaly_id)
            if not lookup:
                return

            column = profiling_queries.get_column_by_name(
                lookup["column_name"], lookup["table_name"], lookup["table_groups_id"],
            )
            if column:
                mask_profiling_pii(column, get_pii_columns(lookup["table_groups_id"], table_name=lookup["table_name"]))
                st.session_state[PROFILING_KEY] = make_json_safe(column)

        def on_profiling_closed(*_) -> None:
            st.session_state.pop(PROFILING_KEY, None)

        @with_database_session
        def on_refresh_score(*_) -> None:
            run_profile_rollup_scoring_queries(
                run.project_code,
                run_id,
                run.table_groups_id if run.is_latest_run else None,
            )
            st.cache_data.clear()

        @with_database_session
        def on_download_report(payload: dict) -> None:
            ids = payload.get("ids", [])
            if not ids:
                return

            anomaly_df = profiling_queries.get_profiling_anomalies_by_ids(ids)
            if anomaly_df.empty:
                return
            selected_items = [
                make_json_safe(record)
                for record in anomaly_df.where(anomaly_df.notna(), None).to_dict(orient="records")
            ]

            MixpanelService().send_event(
                "download-issue-report",
                page=self.path,
                issue_count=len(selected_items),
            )

            dialog_title = "Download Issue Report"
            if len(selected_items) == 1:
                download_dialog(
                    dialog_title=dialog_title,
                    file_content_func=get_report_file_data,
                    args=(selected_items[0],),
                )
            else:
                zip_func = zip_multi_file_data(
                    "testgen_hygiene_issue_reports.zip",
                    get_report_file_data,
                    [(item,) for item in selected_items],
                )
                download_dialog(dialog_title=dialog_title, file_content_func=zip_func)

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

        testgen.hygiene_issues_widget(
            key="hygiene_issues",
            data={
                "run_id": run_id,
                "items": items,
                "summaries": summaries,
                "score": friendly_score(run.dq_score_profiling) or "--",
                "is_latest_run": run.is_latest_run,
                "filters": {
                    "likelihood": likelihood,
                    "table_name": table_name,
                    "column_name": column_name,
                    "issue_type": issue_type,
                    "action": action,
                },
                "permissions": {
                    "can_disposition": session.auth.user_has_permission("disposition"),
                },
                "profiling_column": make_json_safe(profiling_column) if profiling_column else None,
                "source_data": make_json_safe(source_data) if source_data else None,
                "page": current_page,
                "total_count": total_count,
                "page_size": current_page_size,
                "sort_state": sort_state,
                "selected_id": selected,
                "filter_options": filter_options,
            },
            on_RowSelected_change=on_row_selected,
            on_DispositionChanged_change=on_disposition_changed,
            on_DispositionAll_change=on_disposition_all,
            on_FilterChanged_change=on_filter_changed,
            on_ExportAll_change=on_export_all,
            on_ExportFiltered_change=on_export_filtered,
            on_ExportSelected_change=on_export_selected,
            on_ViewSourceData_change=on_view_source_data,
            on_SourceDataClosed_change=on_source_data_closed,
            on_ViewProfiling_change=on_view_profiling,
            on_ProfilingClosed_change=on_profiling_closed,
            on_RefreshScore_change=on_refresh_score,
            on_DownloadReport_change=on_download_report,
            on_PageChanged_change=on_page_changed,
            on_SortChanged_change=on_sort_changed,
        )


def _map_action_filter(action: str | None) -> str | None:
    if not action:
        return None
    if action == "Inactive":
        return "Muted"
    return action


@st.cache_data(show_spinner=False)
def _get_anomaly_disposition(profile_run_id: str) -> pd.DataFrame:
    from testgen.ui.services.database_service import fetch_df_from_db

    query = """
    SELECT id::VARCHAR, disposition
    FROM profile_anomaly_results s
    WHERE s.profile_run_id = :profile_run_id;
    """
    df = fetch_df_from_db(query, {"profile_run_id": profile_run_id})
    dct_replace = {"Confirmed": "\u2713", "Dismissed": "\u2718", "Inactive": "\U0001F507", "Passed": ""}
    df["action"] = df["disposition"].replace(dct_replace)
    return df[["id", "action", "disposition"]]


@st.cache_data(show_spinner=False)
def _get_profiling_anomaly_summary(profile_run_id: str) -> list[dict]:
    count_by_priority = HygieneIssue.select_count_by_priority(profile_run_id)

    return [
        {"label": "Definite", "value": count_by_priority["Definite"].active, "color": "red"},
        {"label": "Likely", "value": count_by_priority["Likely"].active, "color": "orange"},
        {"label": "Possible", "value": count_by_priority["Possible"].active, "color": "yellow"},
        {
            "label": "Dismissed",
            "value": sum(count_by_priority[p].inactive for p in ("Definite", "Likely", "Possible")),
            "color": "grey",
        },
        {"label": "High", "value": count_by_priority["High"].active, "color": "red", "type": "PII"},
        {"label": "Moderate", "value": count_by_priority["Moderate"].active, "color": "orange", "type": "PII"},
        {
            "label": "Dismissed",
            "value": sum(count_by_priority[p].inactive for p in ("High", "Moderate")),
            "color": "grey",
            "type": "PII",
        },
    ]


@with_database_session
def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    table_group: str,
    schema: str,
    run_date: str,
    run_id: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is None:
        data = get_profiling_anomalies(run_id)

    if not session.auth.user_has_permission("view_pii"):
        data = data.copy()
        mask_hygiene_detail(data)

    columns = {
        "table_name": {"header": "Table"},
        "column_name": {"header": "Column"},
        "anomaly_name": {"header": "Issue Type"},
        "issue_likelihood": {"header": "Likelihood"},
        "anomaly_description": {"header": "Description", "wrap": True},
        "action": {},
        "detail": {},
        "suggested_action": {"wrap": True},
    }
    return get_excel_file_data(
        data,
        "Hygiene Issues",
        details={"Table group": table_group, "Schema": schema, "Profiling run date": run_date},
        columns=columns,
        update_progress=update_progress,
    )


def get_report_file_data(update_progress, tr_data) -> FILE_DATA_TYPE:
    hi_id = tr_data["id"][:8]
    profiling_time = pd.Timestamp(tr_data["profiling_starttime"]).strftime("%Y%m%d_%H%M%S")
    file_name = f"testgen_hygiene_issue_report_{hi_id}_{profiling_time}.pdf"

    with BytesIO() as buffer:
        create_report(buffer, tr_data, mask_pii=not session.auth.user_has_permission("view_pii"))
        update_progress(1.0)
        buffer.seek(0)
        return file_name, "application/pdf", buffer.read()


def _update_anomaly_disposition(
    ids: list[str],
    disposition: typing.Literal["Confirmed", "Dismissed", "Inactive", "No Decision"],
) -> None:
    execute_db_query(
        """
        WITH selects
            AS (SELECT UNNEST(ARRAY [:anomaly_result_ids]) AS selected_id)
        UPDATE profile_anomaly_results
        SET disposition = NULLIF(:disposition, 'No Decision')
        FROM profile_anomaly_results r
        INNER JOIN selects s
            ON (r.id = s.selected_id::UUID)
        WHERE r.id = profile_anomaly_results.id;
        """,
        {
            "anomaly_result_ids": ids,
            "disposition": disposition,
        }
    )
