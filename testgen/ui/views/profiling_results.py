import json
import typing
from datetime import datetime
from functools import partial

import pandas as pd
import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.form_service as fm
from testgen.common import date_service
from testgen.common.models import with_database_session
from testgen.common.models.profiling_run import ProfilingRun
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
)
from testgen.ui.components.widgets.page import css_class, flex_row_end
from testgen.ui.components.widgets.testgen_component import testgen_component
from testgen.ui.navigation.page import Page
from testgen.ui.services.database_service import fetch_df_from_db
from testgen.ui.session import session
from testgen.ui.views.dialogs.data_preview_dialog import data_preview_dialog

FORM_DATA_WIDTH = 400


class ProfilingResultsPage(Page):
    path = "profiling-runs:results"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "run_id" in st.query_params or "profiling-runs",
    ]

    def render(self, run_id: str, table_name: str | None = None, column_name: str | None = None, **_kwargs) -> None:
        run = ProfilingRun.get_minimal(run_id)
        if not run:
            self.router.navigate_with_warning(
                f"Profiling run with ID '{run_id}' does not exist. Redirecting to list of Profiling Runs ...",
                "profiling-runs",
            )
            return

        run_date = date_service.get_timezoned_timestamp(st.session_state, run.profiling_starttime)
        session.set_sidebar_project(run.project_code)

        testgen.page_header(
            "Data Profiling Results",
            "view-data-profiling-results",
            breadcrumbs=[
                { "label": "Profiling Runs", "path": "profiling-runs", "params": { "project_code": run.project_code } },
                { "label": f"{run.table_groups_name} | {run_date}" },
            ],
        )

        table_filter_column, column_filter_column, sort_column, export_button_column = st.columns(
            [.3, .3, .08, .32], vertical_alignment="bottom"
        )

        filters_changed = False
        current_filters = (table_name, column_name)
        if (query_filters := st.session_state.get("profiling_results:filters")) != current_filters:
            if query_filters:
                filters_changed = True
            st.session_state["profiling_results:filters"] = current_filters

        run_columns_df = get_profiling_run_columns(run_id)
        with table_filter_column:
            table_name = testgen.select(
                options=list(run_columns_df["table_name"].unique()),
                default_value=table_name,
                bind_to_query="table_name",
                label="Table",
            )

        with column_filter_column:
            if table_name:
                column_options = (
                    run_columns_df
                    .loc[run_columns_df["table_name"] == table_name]
                    ["column_name"]
                    .dropna()
                    .unique()
                    .tolist()
                )
            else:
                column_options = (
                    run_columns_df
                    .groupby("column_name")
                    .first()
                    .reset_index()
                    .sort_values("column_name", key=lambda x: x.str.lower())
                )
            column_name = testgen.select(
                options=column_options,
                default_value=column_name,
                bind_to_query="column_name",
                label="Column",
                accept_new_options=True,
            )

        with sort_column:
            sortable_columns = (
                ("Table", "LOWER(table_name)"),
                ("Column", "LOWER(column_name)"),
                ("Data Type", "LOWER(db_data_type)"),
                ("Semantic Data Type", "semantic_data_type"),
                ("Hygiene Issues", "hygiene_issues"),
            )
            default_sorting = [(sortable_columns[i][1], "ASC") for i in (0, 1, 2)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default_sorting)

        # Display main results grid
        with st.container():
            with st.spinner("Loading data ..."):
                df = profiling_queries.get_profiling_results(
                    run_id,
                    table_name=table_name,
                    column_name=column_name,
                    sorting_columns=sorting_columns,
                )

        selected, selected_row = fm.render_grid_select(
            df,
            ["table_name", "column_name", "db_data_type", "semantic_data_type", "hygiene_issues", "result_details"],
            ["Table", "Column", "Data Type", "Semantic Data Type", "Hygiene Issues", "Details"],
            id_column="id",
            reset_pagination=filters_changed,
            bind_to_query=True,
        )

        popover_container = export_button_column.empty()

        def open_download_dialog(data: pd.DataFrame | None = None) -> None:
            # Hack to programmatically close popover: https://github.com/streamlit/streamlit/issues/8265#issuecomment-3001655849
            with popover_container.container():
                flex_row_end()
                st.button(label="Export", icon=":material/download:", disabled=True)

            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(run.table_groups_name, run.table_group_schema, run_date, run_id, data),
            )

        with popover_container.container(key="tg--export-popover"):
            flex_row_end()
            with st.popover(label="Export", icon=":material/download:", help="Download profiling results to Excel"):
                css_class("tg--export-wrapper")
                st.button(label="All results", type="tertiary", on_click=open_download_dialog)
                st.button(label="Filtered results", type="tertiary", on_click=partial(open_download_dialog, df))
                if selected:
                    st.button(label="Selected results", type="tertiary", on_click=partial(open_download_dialog, pd.DataFrame(selected)))


        # Display profiling for selected row
        if not selected_row:
            st.markdown(":orange[Select a row to see profiling details.]")
        else:
            selected_row["hygiene_issues"] = profiling_queries.get_hygiene_issues(run_id, selected_row["table_name"], selected_row.get("column_name"))
            testgen_component(
                "column_profiling_results",
                props={ "column": json.dumps(selected_row), "data_preview": True },
                on_change_handlers={
                    "DataPreviewClicked": lambda item: data_preview_dialog(
                        item["table_group_id"],
                        item["schema_name"],
                        item["table_name"],
                        item.get("column_name"),
                    ),
                },
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

    for key in ["datatype_suggestion"]:
        data[key] = data[key].apply(lambda val: val.lower() if not pd.isna(val) else None)

    for key in ["avg_embedded_spaces", "avg_length", "avg_value", "stdev_value"]:
        data[key] = data[key].apply(lambda val: round(val, 2) if not pd.isna(val) else None)

    for key in ["min_date", "max_date"]:
        data[key] = data[key].apply(
            lambda val: datetime.strptime(val, "%Y-%m-%d %H:%M:%S").strftime("%b %-d %Y, %-I:%M %p") if not pd.isna(val) and val != "NaT" else None
        )

    data["hygiene_issues"] = data["hygiene_issues"].apply(lambda val: "Yes" if val else None)

    type_map = {"A": "Alpha", "B": "Boolean", "D": "Datetime", "N": "Numeric"}
    data["general_type"] = data["general_type"].apply(lambda val: type_map.get(val))

    data["top_freq_values"] = data["top_freq_values"].apply(
        lambda val: "\n".join([ f"{part.split(" | ")[1]} | {part.split(" | ")[0]}" for part in val[2:].split("\n| ") ])
        if val
        else None
    )
    data["top_patterns"] = data["top_patterns"].apply(
        lambda val: "".join([ f"{part}{'\n' if index % 2 else ' | '}" for index, part in enumerate(val.split(" | ")) ])
        if val
        else None
    )

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


@st.cache_data(show_spinner=False)
def get_profiling_run_columns(profiling_run_id: str) -> pd.DataFrame:
    query = """
    SELECT table_name, column_name
    FROM profile_results
    WHERE profile_run_id = :profiling_run_id
    ORDER BY LOWER(table_name), LOWER(column_name);
    """
    return fetch_df_from_db(query, {"profiling_run_id": profiling_run_id})
