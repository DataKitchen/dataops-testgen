import json
import typing

import pandas as pd
import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
from testgen.common import date_service
from testgen.common.date_service import parse_fuzzy_date
from testgen.common.models import with_database_session
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.pii_masking import PII_REDACTED, get_pii_columns, mask_hygiene_detail, mask_profiling_pii
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
)
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.session import session

PAGE_SIZE = 500

SELECTED_ITEM_KEY = "prf:selected_item"
EXPORT_FILTERS_KEY = "prf:export_filters"

# Maps JS column names to SQL ORDER BY expressions
SORT_FIELD_MAP = {
    "table_name": "LOWER(table_name)",
    "column_name": "LOWER(column_name)",
    "db_data_type": "LOWER(db_data_type)",
    "semantic_data_type": "LOWER(functional_data_type)",
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


class ProfilingResultsPage(Page):
    path = "profiling-runs:results"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "run_id" in st.query_params or "profiling-runs",
    ]

    def render(
        self,
        run_id: str,
        table_name: str | None = None,
        column_name: str | None = None,
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
            "Data Profiling Results",
            "investigate-profiling-results",
            breadcrumbs=[
                { "label": "Profiling Runs", "path": "profiling-runs", "params": { "project_code": run.project_code } },
                { "label": f"{run.table_groups_name} | {run_date}" },
            ],
        )

        export_filters = st.session_state.pop(EXPORT_FILTERS_KEY, None)
        if export_filters is not None:
            with st.spinner("Loading data ..."):
                export_type = export_filters.get("type", "all")
                if export_type == "selected":
                    selected_id = export_filters.get("id")
                    export_df = profiling_queries.get_profiling_results(run_id)
                    export_df = export_df[export_df["id"] == selected_id]
                elif export_type == "filtered":
                    export_df = profiling_queries.get_profiling_results(
                        run_id,
                        table_name=export_filters.get("table_name"),
                        column_name=export_filters.get("column_name"),
                    )
                else:
                    export_df = profiling_queries.get_profiling_results(run_id)
            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(run.table_groups_name, run.table_group_schema, run_date, run_id, export_df),
            )

        # Parse pagination and sorting params
        current_page = int(page) if page else 0
        current_page_size = int(page_size) if page_size else PAGE_SIZE
        sorting_columns, sort_state = _parse_sort_param(sort)

        with st.spinner("Loading data ..."):
            df = profiling_queries.get_profiling_results(
                run_id,
                table_name=table_name,
                column_name=column_name,
                sorting_columns=sorting_columns,
                page=current_page,
                page_size=current_page_size,
            )

            total_count = profiling_queries.get_profiling_results_count(
                run_id, table_name=table_name, column_name=column_name,
            )

            filter_options = profiling_queries.get_profiling_filter_options(run_id)

        if not session.auth.user_has_permission("view_pii"):
            pii_columns = get_pii_columns(str(run.table_groups_id))
            mask_profiling_pii(df, pii_columns)

        # Use pandas JSON serialization to safely handle NaN/NaT -> null, timestamps -> epoch seconds
        items = json.loads(df.to_json(orient="records", date_unit="s"))

        selected_item = st.session_state.get(SELECTED_ITEM_KEY)
        # Load selected item if URL has a selection but session cache is missing or stale
        if selected and (selected_item is None or selected_item.get("id") != selected):
            row_df = df[df["id"] == selected]
            if not row_df.empty:
                row = json.loads(row_df.to_json(orient="records", date_unit="s"))[0]
                row["hygiene_issues"] = profiling_queries.get_hygiene_issues(
                    run_id, row["table_name"], row.get("column_name")
                )
                if not session.auth.user_has_permission("view_pii"):
                    pii_cols = get_pii_columns(row["table_group_id"], table_name=row["table_name"])
                    mask_hygiene_detail(row["hygiene_issues"], pii_cols)
                st.session_state[SELECTED_ITEM_KEY] = row
                selected_item = row
        elif not selected:
            st.session_state.pop(SELECTED_ITEM_KEY, None)
            selected_item = None

        @with_database_session
        def on_row_selected(item_id: str) -> None:
            row_df = df[df["id"] == item_id]
            if row_df.empty:
                return
            row = json.loads(row_df.to_json(orient="records", date_unit="s"))[0]
            row["hygiene_issues"] = profiling_queries.get_hygiene_issues(
                run_id, row["table_name"], row.get("column_name")
            )
            if not session.auth.user_has_permission("view_pii"):
                pii_cols = get_pii_columns(row["table_group_id"], table_name=row["table_name"])
                mask_hygiene_detail(row["hygiene_issues"], pii_cols)
            st.session_state[SELECTED_ITEM_KEY] = row
            Router().set_query_params({"selected": item_id})

        def on_filter_changed(filters: dict) -> None:
            st.session_state.pop(SELECTED_ITEM_KEY, None)
            Router().set_query_params({
                "selected": None,
                "page": "0",
                "table_name": filters.get("table_name"),
                "column_name": filters.get("column_name"),
            })

        def on_export_all(*_) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "all"}

        def on_export_filtered(filters: dict) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {
                "type": "filtered",
                "table_name": filters.get("table_name"),
                "column_name": filters.get("column_name"),
            }

        def on_export_selected(item_id: str) -> None:
            st.session_state[EXPORT_FILTERS_KEY] = {"type": "selected", "id": item_id}

        def on_page_changed(payload: dict) -> None:
            new_page = payload.get("page", 0)
            new_page_size = payload.get("page_size")
            st.session_state.pop(SELECTED_ITEM_KEY, None)
            params: dict = {"page": str(new_page), "selected": None}
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

        testgen.profiling_results_widget(
            key="profiling_results",
            data={
                "run_id": run_id,
                "items": items,
                "filters": {"table_name": table_name, "column_name": column_name},
                "selected_id": selected,
                "selected_item": json.dumps(selected_item, default=str) if selected_item else None,
                "permissions": {"can_edit": session.auth.user_has_permission("edit")},
                "page": current_page,
                "total_count": total_count,
                "page_size": current_page_size,
                "sort_state": sort_state,
                "filter_options": filter_options,
            },
            on_RowSelected_change=on_row_selected,
            on_FilterChanged_change=on_filter_changed,
            on_ExportAll_change=on_export_all,
            on_ExportFiltered_change=on_export_filtered,
            on_ExportSelected_change=on_export_selected,
            on_PageChanged_change=on_page_changed,
            on_SortChanged_change=on_sort_changed,
        )


@with_database_session
def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    table_group: str,
    schema: str,
    run_date: str,
    run_id: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is not None:
        data = data.copy()
    else:
        data = profiling_queries.get_profiling_results(run_id)
    date_service.accommodate_dataframe_to_timezone(data, st.session_state)

    if not session.auth.user_has_permission("view_pii"):
        pii_columns = get_pii_columns(data["table_group_id"].iloc[0] if "table_group_id" in data.columns else "")
        mask_profiling_pii(data, pii_columns)

    for key in ["datatype_suggestion"]:
        data[key] = data[key].apply(lambda val: val.lower() if not pd.isna(val) else None)

    for key in ["avg_embedded_spaces", "avg_length", "avg_value", "stdev_value"]:
        data[key] = data[key].apply(lambda val: round(val, 2) if not pd.isna(val) else None)

    for key in ["min_date", "max_date"]:
        data[key] = data[key].apply(
            lambda val: parse_fuzzy_date(val) if not pd.isna(val) and val != "NaT" and val != PII_REDACTED else val
        )

    data["hygiene_issues"] = data["hygiene_issues"].apply(lambda val: "Yes" if val else None)

    type_map = {"A": "Alpha", "B": "Boolean", "D": "Datetime", "N": "Numeric"}
    data["general_type"] = data["general_type"].apply(lambda val: type_map.get(val))

    def _format_top_freq_values(val):
        if not val or val == PII_REDACTED:
            return val
        lines = []
        for part in val[2:].split("\n| "):
            left, right = part.split(" | ")
            lines.append(f"{right} | {left}")
        return "\n".join(lines)

    def _format_top_patterns(val):
        if not val or val == PII_REDACTED:
            return val
        parts = val.split(" | ")
        formatted = []
        for index, part in enumerate(parts):
            separator = "\n" if index % 2 else " | "
            formatted.append(f"{part}{separator}")
        return "".join(formatted)

    data["top_freq_values"] = data["top_freq_values"].apply(_format_top_freq_values)
    data["top_patterns"] = data["top_patterns"].apply(_format_top_patterns)

    columns = {
        "table_name": {"header": "Table"},
        "column_name": {"header": "Column"},
        "position": {},
        "general_type": {},
        "db_data_type": {"header": "Data type"},
        "datatype_suggestion": {"header": "Suggested data type"},
        "semantic_data_type": {},
        "record_ct": {"header": "Row count"},
        "value_ct": {"header": "Value count"},
        "distinct_value_ct": {"header": "Distinct values"},
        "null_value_ct": {"header": "Null values"},
        "zero_value_ct": {"header": "Zero values"},
        "zero_length_ct": {"header": "Zero length"},
        "filled_value_ct": {"header": "Dummy values"},
        "mixed_case_ct": {"header": "Mixed case"},
        "lower_case_ct": {"header": "Lower case"},
        "non_alpha_ct": {"header": "Non-alpha"},
        "includes_digit_ct": {"header": "Includes digits"},
        "numeric_ct": {"header": "Numeric values"},
        "date_ct": {"header": "Date values"},
        "quoted_value_ct": {"header": "Quoted values"},
        "lead_space_ct": {"header": "Leading spaces"},
        "embedded_space_ct": {"header": "Embedded spaces"},
        "avg_embedded_spaces": {"header": "Average embedded spaces"},
        "min_length": {"header": "Minimum length"},
        "max_length": {"header": "Maximum length"},
        "avg_length": {"header": "Average length"},
        "min_text": {"header": "Minimum text", "wrap": True},
        "max_text": {"header": "Maximum text", "wrap": True},
        "distinct_std_value_ct": {"header": "Distinct standard values"},
        "distinct_pattern_ct": {"header": "Distinct patterns"},
        "std_pattern_match": {"header": "Standard pattern match"},
        "top_freq_values": {"header": "Frequent values", "wrap": True},
        "top_patterns": {"header": "Frequent patterns", "wrap": True},
        "min_value": {"header": "Minimum value"},
        "min_value_over_0": {"header": "Minimum value > 0"},
        "max_value": {"header": "Maximum value"},
        "avg_value": {"header": "Average value"},
        "stdev_value": {"header": "Standard deviation"},
        "percentile_25": {"header": "25th percentile"},
        "percentile_50": {"header": "Median value"},
        "percentile_75": {"header": "75th percentile"},
        "min_date": {"header": "Minimum date (UTC)"},
        "max_date": {"header": "Maximum date (UTC)"},
        "before_1yr_date_ct": {"header": "Before 1 year"},
        "before_5yr_date_ct": {"header": "Before 5 years"},
        "before_20yr_date_ct": {"header": "Before 20 years"},
        "within_1yr_date_ct": {"header": "Within 1 year"},
        "within_1mo_date_ct": {"header": "Within 1 month"},
        "future_date_ct": {"header": "Future dates"},
        "boolean_true_ct": {"header": "Boolean true values"},
        "result_details": {"header": "Details"},
    }
    return get_excel_file_data(
        data,
        "Profiling Results",
        details={"Table group": table_group, "Schema": schema, "Profiling run date": run_date},
        columns=columns,
        update_progress=update_progress,
    )
