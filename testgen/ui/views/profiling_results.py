import typing

import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.form_service as fm
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.services import project_service
from testgen.ui.session import session
from testgen.ui.views.profiling_details import show_profiling_detail

FORM_DATA_WIDTH = 400


class ProfilingResultsPage(Page):
    path = "profiling-runs:results"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: "run_id" in session.current_page_args or "profiling-runs",
    ]

    def render(self, run_id: str, table_name: str | None = None, column_name: str | None = None, **_kwargs) -> None:
        run_parentage = profiling_queries.lookup_db_parentage_from_run(
            run_id
        )
        if not run_parentage:
            self.router.navigate_with_warning(
                f"Profiling run with ID '{run_id}' does not exist. Redirecting to list of Profiling Runs ...",
                "profiling-runs",
            )

        run_date, table_group_id, table_group_name, project_code = run_parentage
        run_date = date_service.get_timezoned_timestamp(st.session_state, run_date)
        project_service.set_current_project(project_code)

        testgen.page_header(
            "Data Profiling Results",
            "https://docs.datakitchen.io/article/dataops-testgen-help/investigate-profiling",
            breadcrumbs=[
                { "label": "Profiling Runs", "path": "profiling-runs", "params": { "project_code": project_code } },
                { "label": f"{table_group_name} | {run_date}" },
            ],
        )

        table_filter_column, column_filter_column, sort_column, export_button_column = st.columns(
            [.3, .3, .08, .32], vertical_alignment="bottom"
        )

        with table_filter_column:
            # Table Name filter
            df = profiling_queries.run_table_lookup_query(table_group_id)
            table_name = testgen.toolbar_select(
                options=df,
                value_column="table_name",
                default_value=table_name,
                bind_to_query="table_name",
                label="Table Name",
            )

        with column_filter_column:
            # Column Name filter
            df = profiling_queries.run_column_lookup_query(table_group_id, table_name)
            column_name = testgen.toolbar_select(
                options=df,
                value_column="column_name",
                default_value=column_name,
                bind_to_query="column_name",
                label="Column Name",
                disabled=not table_name,
            )

        with sort_column:
            sortable_columns = (
                ("Schema Name", "p.schema_name"),
                ("Table Name", "p.table_name"),
                ("Column Name", "p.column_name"),
                ("Column Type", "p.column_type"),
                ("Semantic Data Type", "semantic_data_type"),
                ("Anomalies", "anomalies"),
            )
            default_sorting = [(sortable_columns[i][1], "ASC") for i in (0, 1, 2)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default_sorting)

        # Use SQL wildcard to match all values
        if not table_name:
            table_name = "%%"
        if not column_name:
            column_name = "%%"

        # Display main results grid
        df = profiling_queries.get_profiling_detail(run_id, table_name, column_name, sorting_columns)
        show_columns = [
            "schema_name",
            "table_name",
            "column_name",
            "column_type",
            "semantic_data_type",
            "anomalies",
        ]

        # Show CREATE script button
        if len(df) > 0 and table_name != "%%":
            with st.expander("📜 **Table CREATE script with suggested datatypes**"):
                st.code(generate_create_script(df), "sql")

        selected_row = fm.render_grid_select(df, show_columns)

        with export_button_column:
            testgen.flex_row_end()
            render_export_button(df)

        # Display profiling for selected row
        if not selected_row:
            st.markdown(":orange[Select a row to see profiling details.]")
        else:
            show_profiling_detail(selected_row[0], FORM_DATA_WIDTH)


def render_export_button(df):
    export_columns = [
        "schema_name",
        "table_name",
        "column_name",
        "position",
        "column_type",
        "general_type",
        "semantic_table_type",
        "semantic_data_type",
        "datatype_suggestion",
        "anomalies",
        "record_ct",
        "value_ct",
        "distinct_value_ct",
        "top_freq_values",
        "null_value_ct",
        "min_length",
        "max_length",
        "avg_length",
        "distinct_std_value_ct",
        "numeric_ct",
        "date_ct",
        "dummy_value_ct",
        "zero_length_ct",
        "lead_space_ct",
        "quoted_value_ct",
        "includes_digit_ct",
        "embedded_space_ct",
        "avg_embedded_spaces",
        "min_text",
        "max_text",
        "std_pattern_match",
        "distinct_pattern_ct",
        "top_patterns",
        "distinct_value_hash",
        "min_value",
        "min_value_over_0",
        "max_value",
        "avg_value",
        "stdev_value",
        "percentile_25",
        "percentile_50",
        "percentile_75",
        "zero_value_ct",
        "fractional_sum",
        "min_date",
        "max_date",
        "before_1yr_date_ct",
        "before_5yr_date_ct",
        "within_1yr_date_ct",
        "within_1mo_date_ct",
        "future_date_ct",
        "date_days_present",
        "date_weeks_present",
        "date_months_present",
        "boolean_true_ct",
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
