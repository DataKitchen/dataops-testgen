import json
import typing

import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
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
        lambda: "run_id" in session.current_page_args or "profiling-runs",
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
        project_service.set_current_project(run_df["project_code"])

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
            render_export_button(df)

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


def render_export_button(df):
    export_columns = [
        "schema_name",
        "table_name",
        "column_name",
        "position",
        "hygiene_issues",
        # Characteristics
        "general_type",
        "column_type",
        "semantic_table_type",
        "semantic_data_type",
        "datatype_suggestion",
        # Value Counts
        "record_ct",
        "value_ct",
        "distinct_value_ct",
        "null_value_ct",
        "zero_value_ct",
        # Alpha
        "zero_length_ct",
        "filled_value_ct",
        "includes_digit_ct",
        "numeric_ct",
        "date_ct",
        "quoted_value_ct",
        "lead_space_ct",
        "embedded_space_ct",
        "avg_embedded_spaces",
        "min_length",
        "max_length",
        "avg_length",
        "min_text",
        "max_text",
        "distinct_std_value_ct",
        "distinct_pattern_ct",
        "std_pattern_match",
        "top_freq_values",
        "top_patterns",
        # Numeric
        "min_value",
        "min_value_over_0",
        "max_value",
        "avg_value",
        "stdev_value",
        "percentile_25",
        "percentile_50",
        "percentile_75",
        # Date
        "min_date",
        "max_date",
        "before_1yr_date_ct",
        "before_5yr_date_ct",
        "before_20yr_date_ct",
        "within_1yr_date_ct",
        "within_1mo_date_ct",
        "future_date_ct",
        # Boolean
        "boolean_true_ct",
        # Extra
        "distinct_value_hash",
        "fractional_sum",
        "date_days_present",
        "date_weeks_present",
        "date_months_present",
    ]
    wrap_columns = ["top_freq_values", "top_patterns"]
    caption = "{TIMESTAMP}"
    fm.render_excel_export(df, export_columns, "Profiling Results", caption, wrap_columns)


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
