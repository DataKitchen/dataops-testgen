import typing

import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.form_service as fm
import testgen.ui.services.toolbar_service as tb
from testgen.common import date_service
from testgen.ui.navigation.page import Page
from testgen.ui.session import session
from testgen.ui.views.profiling_details import show_profiling_detail

FORM_DATA_WIDTH = 400


class ProfilingResultsPage(Page):
    path = "profiling:results"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]

    def render(self) -> None:
        export_container = fm.render_page_header(
            "Data Profiling Results",
            "https://docs.datakitchen.io/article/dataops-testgen-help/investigate-profiling",
            lst_breadcrumbs=[
                {"label": "Overview", "path": "overview"},
                {"label": "Data Profiling", "path": "profiling"},
                {"label": "Profiling Results", "path": None},
            ],
        )

        if "project" not in st.session_state:
            st.write("Select a Project from the Overview page.")
        else:
            # Retrieve State Variables

            str_project = st.session_state["project"]
            # Look for drill-down from another page
            if "drill_profile_run" in st.session_state:
                str_profile_run_id = st.session_state["drill_profile_run"]
            else:
                str_profile_run_id = ""

            # Setup Toolbar
            tool_bar = tb.ToolBar(4, 0, 1, None)

            # Retrieve Choices data
            if str_profile_run_id:
                # Lookup profiling run date and table group name from passed profile run
                str_lookfor_run_date, str_lookfor_table_group = profiling_queries.lookup_db_parentage_from_run(
                    str_profile_run_id
                )
                str_lookfor_run_date = date_service.get_timezoned_timestamp(st.session_state, str_lookfor_run_date)
            else:
                str_lookfor_run_date = ""
                str_lookfor_table_group = ""

            with tool_bar.long_slots[0]:
                # Prompt for Table Group (with passed default)
                df = profiling_queries.run_table_groups_lookup_query(str_project)
                str_table_groups_id = fm.render_select(
                    "Table Group", df, "table_groups_name", "id", True, str_lookfor_table_group, True
                )

            with tool_bar.long_slots[1]:
                # Prompt for Profile Run (with passed default)
                df = profiling_queries.get_db_profile_run_choices(str_table_groups_id)
                date_service.create_timezoned_column_in_dataframe(
                    st.session_state, df, "profile_run_date_with_timezone", "profile_run_date"
                )
                str_profile_run_id = fm.render_select(
                    "Profile Run", df, "profile_run_date_with_timezone", "id", True, str_lookfor_run_date, True
                )

            # Reset passed parameter
            # st.session_state["drill_profile_run"] = None

            with tool_bar.long_slots[2]:
                # Prompt for Table Name
                df = profiling_queries.run_table_lookup_query(str_table_groups_id)
                str_table_name = fm.render_select("Table Name", df, "table_name", "table_name", False)

            with tool_bar.long_slots[3]:
                # Prompt for Column Name
                if str_table_name:
                    df = profiling_queries.run_column_lookup_query(str_table_groups_id, str_table_name)
                    str_column_name = fm.render_select("Column Name", df, "column_name", "column_name", False)
                    if not str_column_name:
                        # Use SQL wildcard to match all values
                        str_column_name = "%%"
                else:
                    # Use SQL wildcard to match all values
                    str_table_name = "%%"
                    str_column_name = "%%"

            # Display main results grid
            if str_profile_run_id:
                df = profiling_queries.get_profiling_detail(str_profile_run_id, str_table_name, str_column_name)
                show_columns = [
                    "schema_name",
                    "table_name",
                    "column_name",
                    "column_type",
                    "semantic_data_type",
                    "anomalies",
                ]

                # Show CREATE script button
                if len(df) > 0 and str_table_name != "%%":
                    with st.expander("📜 **Table CREATE script with suggested datatypes**"):
                        st.code(generate_create_script(df), "sql")

                selected_row = fm.render_grid_select(df, show_columns)

                with export_container:
                    lst_export_columns = [
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
                    lst_wrap_columns = ["top_freq_values", "top_patterns"]
                    str_caption = "{TIMESTAMP}"
                    fm.render_excel_export(df, lst_export_columns, "Profiling Results", str_caption, lst_wrap_columns)

                # Display profiling for selected row
                if not selected_row:
                    st.markdown(":orange[Select a row to see profiling details.]")
                else:
                    show_profiling_detail(selected_row[0], FORM_DATA_WIDTH)
            else:
                st.markdown(":orange[Select a profiling run.]")


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
