import json
import typing
from datetime import datetime

import pandas as pd
import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
)
from testgen.ui.components.widgets.testgen_component import testgen_component
from testgen.ui.navigation.page import Page
from testgen.ui.services import project_service, user_session_service
from testgen.ui.session import session
from testgen.ui.views.dialogs.data_preview_dialog import data_preview_dialog

FORM_DATA_WIDTH = 400


class ProfilingResultsPage(Page):
    path = "profiling-runs:results"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "run_id" in st.query_params or "profiling-runs",
    ]

    def render(self, run_id: str, table_name: str | None = None, column_name: str | None = None, **_kwargs) -> None:
        run_df = profiling_queries.get_run_by_id(run_id)
        if run_df.empty:
            self.router.navigate_with_warning(
                f"Profiling run with ID '{run_id}' does not exist. Redirecting to list of Profiling Runs ...",
                "profiling-runs",
            )
            return

        run_date = date_service.get_timezoned_timestamp(st.session_state, run_df["profiling_starttime"])
        project_service.set_sidebar_project(run_df["project_code"])

        testgen.page_header(
            "Data Profiling Results",
            "view-data-profiling-results",
            breadcrumbs=[
                { "label": "Profiling Runs", "path": "profiling-runs", "params": { "project_code": run_df["project_code"] } },
                { "label": f"{run_df['table_groups_name']} | {run_date}" },
            ],
        )

        table_filter_column, column_filter_column, sort_column, export_button_column = st.columns(
            [.3, .3, .08, .32], vertical_alignment="bottom"
        )

        with table_filter_column:
            # Table Name filter
            df = get_profiling_run_tables(run_id)
            table_name = testgen.select(
                options=df,
                value_column="table_name",
                default_value=table_name,
                bind_to_query="table_name",
                label="Table Name",
            )

        with column_filter_column:
            # Column Name filter
            df = get_profiling_run_columns(run_id, table_name)
            column_name = testgen.select(
                options=df,
                value_column="column_name",
                default_value=column_name,
                bind_to_query="column_name",
                label="Column Name",
                disabled=not table_name,
            )

        with sort_column:
            sortable_columns = (
                ("Schema Name", "schema_name"),
                ("Table Name", "table_name"),
                ("Column Name", "column_name"),
                ("Column Type", "column_type"),
                ("Semantic Data Type", "semantic_data_type"),
                ("Hygiene Issues", "hygiene_issues"),
            )
            default_sorting = [(sortable_columns[i][1], "ASC") for i in (0, 1, 2)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default_sorting)

        # Use SQL wildcard to match all values
        if not table_name:
            table_name = "%%"
        if not column_name:
            column_name = "%%"

        # Display main results grid
        with st.container():
            with st.spinner("Loading data ..."):
                df = profiling_queries.get_profiling_results(run_id, table_name, column_name, sorting_columns)
                
        show_columns = [
            "schema_name",
            "table_name",
            "column_name",
            "column_type",
            "semantic_data_type",
            "hygiene_issues",
        ]

        # Show CREATE script button
        if len(df) > 0 and table_name != "%%":
            with st.expander("📜 **Table CREATE script with suggested datatypes**"):
                st.code(generate_create_script(df), "sql")

        selected_row = fm.render_grid_select(
            df,
            show_columns,
            bind_to_query_name="selected",
            bind_to_query_prop="id",
        )

        with export_button_column:
            testgen.flex_row_end()
            if st.button(label=":material/download: Export", help="Download filtered profiling results to Excel"):
                download_dialog(
                    dialog_title="Download Excel Report",
                    file_content_func=get_excel_report_data,
                    args=(df, run_df["table_groups_name"], run_date),
                )

        # Display profiling for selected row
        if not selected_row:
            st.markdown(":orange[Select a row to see profiling details.]")
        else:
            item = selected_row[0]
            item["hygiene_issues"] = profiling_queries.get_hygiene_issues(run_id, item["table_name"], item.get("column_name"))
            testgen_component(
                "column_profiling_results",
                props={ "column": json.dumps(item), "data_preview": True },
                on_change_handlers={
                    "DataPreviewClicked": lambda item: data_preview_dialog(
                        item["table_group_id"],
                        item["schema_name"],
                        item["table_name"],
                        item.get("column_name"),
                    ),
                },
            )


def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    data: pd.DataFrame,
    table_group: str,
    run_date: str,
) -> FILE_DATA_TYPE:
    data = data.copy()

    for key in ["column_type", "datatype_suggestion"]:
        data[key] = data[key].apply(lambda val: val.lower() if not pd.isna(val) else None)

    for key in ["avg_embedded_spaces", "avg_length", "avg_value", "stdev_value"]:
        data[key] = data[key].apply(lambda val: round(val, 2) if not pd.isna(val) else None)

    for key in ["min_date", "max_date"]:
        data[key] = data[key].apply(
            lambda val: datetime.strptime(val, "%Y-%m-%dT%H:%M:%S").strftime("%b %-d %Y, %-I:%M %p") if val != "NaT" else None
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
        "schema_name": {"header": "Schema"},
        "table_name": {"header": "Table"},
        "column_name": {"header": "Column"},
        "position": {},
        "general_type": {},
        "column_type": {"header": "Data type"},
        "datatype_suggestion": {"header": "Suggested data type"},
        "semantic_data_type": {},
        "record_ct": {"header": "Record count"},
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
    }
    return get_excel_file_data(
        data,
        "Profiling Results",
        details={"Table group": table_group, "Profiling run date": run_date},
        columns=columns,
        update_progress=update_progress,
    )


def generate_create_script(df):
    ddf = df[["schema_name", "table_name", "column_name", "column_type", "datatype_suggestion"]].copy()
    ddf.fillna("", inplace=True)

    ddf["comment"] = ddf.apply(
        lambda row: "-- WAS " + row["column_type"] if row["column_type"] != row["datatype_suggestion"] else "", axis=1
    )
    max_len_name = ddf.apply(lambda row: len(row["column_name"]), axis=1).max() + 3
    max_len_type = ddf.apply(lambda row: len(row["datatype_suggestion"]), axis=1).max() + 3

    str_header = f"CREATE TABLE {df.at[0, 'schema_name']}.{ddf.at[0, 'table_name']} ( "
    col_defs = ddf.apply(
        lambda row: f"     {row['column_name']:<{max_len_name}} {row['datatype_suggestion']:<{max_len_type}},    {row['comment']}",
        axis=1,
    ).tolist()
    str_footer = ");"
    # Drop final comma in column definitions
    col_defs[-1] = col_defs[-1].replace(",    --", "    --")

    return "\n".join([str_header, *list(col_defs), str_footer])


@st.cache_data(show_spinner=False)
def get_profiling_run_tables(profiling_run_id: str):
    schema: str = st.session_state["dbschema"]
    query = f"""
    SELECT DISTINCT table_name
        FROM {schema}.profile_results
    WHERE profile_run_id = '{profiling_run_id}'
    ORDER BY table_name
    """
    return db.retrieve_data(query)


@st.cache_data(show_spinner=False)
def get_profiling_run_columns(profiling_run_id: str, table_name: str):
    schema: str = st.session_state["dbschema"]
    query = f"""
    SELECT DISTINCT column_name
        FROM {schema}.profile_results
    WHERE profile_run_id = '{profiling_run_id}'
        AND table_name = '{table_name}'
    ORDER BY column_name
    """
    return db.retrieve_data(query)
