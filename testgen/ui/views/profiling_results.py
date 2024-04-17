import typing

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
import testgen.ui.services.toolbar_service as tb
from testgen.common import date_service
from testgen.ui.navigation.page import Page
from testgen.ui.session import session

FORM_DATA_WIDTH = 400


class ProfilingResultsPage(Page):
    path = "profiling/results"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status or "login",
    ]

    def render(self) -> None:
        fm.render_page_header(
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
                str_lookfor_run_date, str_lookfor_table_group = lookup_db_parentage_from_run(str_profile_run_id)
                str_lookfor_run_date = date_service.get_timezoned_timestamp(st.session_state, str_lookfor_run_date)
            else:
                str_lookfor_run_date = ""
                str_lookfor_table_group = ""

            with tool_bar.long_slots[0]:
                # Prompt for Table Group (with passed default)
                df = run_table_groups_lookup_query(str_project)
                str_table_groups_id = fm.render_select(
                    "Table Group", df, "table_groups_name", "id", True, str_lookfor_table_group, True
                )

            with tool_bar.long_slots[1]:
                # Prompt for Profile Run (with passed default)
                df = get_db_profile_run_choices(str_table_groups_id)
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
                df = run_table_lookup_query(str_table_groups_id)
                str_table_name = fm.render_select("Table Name", df, "table_name", "table_name", False)

            with tool_bar.long_slots[3]:
                # Prompt for Column Name
                if str_table_name:
                    df = run_column_lookup_query(str_table_groups_id, str_table_name)
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
                df, show_columns = get_main_dataset(str_profile_run_id, str_table_name, str_column_name)

                # Show CREATE script button
                if len(df) > 0 and str_table_name != "%%":
                    # if tool_bar.button_slots[0].button("📜", help="Show table CREATE script with suggested datatypes"):
                    with st.expander("📜 **Table CREATE script with suggested datatypes**"):
                        st.code(generate_create_script(df), "sql")

                selected_row = fm.render_grid_select(df, show_columns)

                # Display profiling for selected row
                if not selected_row:
                    st.markdown(":orange[Select a row to see profiling details.]")
                else:
                    show_record_detail(selected_row[0])
            else:
                st.markdown(":orange[Select a profiling run.]")


@st.cache_data(show_spinner=False)
def run_table_groups_lookup_query(str_project_code):
    str_schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(str_schema, str_project_code)


@st.cache_data(show_spinner=False)
def get_db_profile_run_choices(str_table_groups_id):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
            SELECT DISTINCT profiling_starttime as profile_run_date, id
              FROM {str_schema}.profiling_runs pr
             WHERE pr.table_groups_id = '{str_table_groups_id}'
            ORDER BY profiling_starttime DESC;
    """
    # Retrieve and return data as df
    return db.retrieve_data(str_sql)


@st.cache_data(show_spinner=False)
def run_table_lookup_query(str_table_groups_id):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
           SELECT DISTINCT table_name
             FROM {str_schema}.profile_results
            WHERE table_groups_id = '{str_table_groups_id}'::UUID
           ORDER BY table_name
    """
    return db.retrieve_data(str_sql)


@st.cache_data(show_spinner=False)
def run_column_lookup_query(str_table_groups_id, str_table_name):
    str_schema = st.session_state["dbschema"]
    return dq.run_column_lookup_query(str_schema, str_table_groups_id, str_table_name)


@st.cache_data(show_spinner=False)
def lookup_db_parentage_from_run(str_profile_run_id):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
            SELECT profiling_starttime as profile_run_date, g.table_groups_name
              FROM {str_schema}.profiling_runs pr
             INNER JOIN {str_schema}.table_groups g
                ON pr.table_groups_id = g.id
             WHERE pr.id = '{str_profile_run_id}'
    """
    df = db.retrieve_data(str_sql)
    if not df.empty:
        return df.at[0, "profile_run_date"], df.at[0, "table_groups_name"]


@st.cache_data(show_spinner="Retrieving Data")
def get_main_dataset(str_profile_run_id, str_table_name, str_column_name):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
          SELECT   -- Identifiers
                   id::VARCHAR, dk_id,
                   p.project_code, connection_id, p.table_groups_id::VARCHAR,
                   p.profile_run_id::VARCHAR,
                   run_date, sample_ratio,
                   -- Column basics
                   p.schema_name, p.table_name, position, p.column_name,
                   p.column_type, general_type as general_type_abbr,
                   CASE general_type
                     WHEN 'A' THEN 'Alpha'
                     WHEN 'N' THEN 'Numeric'
                     WHEN 'D' THEN 'Date'
                     WHEN 'T' THEN 'Time'
                     WHEN 'B' THEN 'Boolean'
                              ELSE 'N/A'
                   END as general_type,
                   functional_table_type, functional_data_type,
                   datatype_suggestion,
                   CASE WHEN s.column_name IS NOT NULL THEN 'Yes' END as anomalies,
                   -- Shared counts
                   record_ct, value_ct, distinct_value_ct, null_value_ct,
                   -- Shared except for B and X
                   min_length, max_length, avg_length,
                   -- Alpha counts
                   distinct_std_value_ct,
                   numeric_ct, date_ct,
                   filled_value_ct as dummy_value_ct,
                   zero_length_ct, lead_space_ct, quoted_value_ct,
                   includes_digit_ct,
                   embedded_space_ct, avg_embedded_spaces,
                   min_text, max_text,
                   std_pattern_match,
                   top_patterns,
                   top_freq_values, distinct_value_hash,
                   distinct_pattern_ct,
                   -- A and N
                   zero_value_ct,
                   -- Numeric
                   min_value, min_value_over_0, max_value,
                   avg_value, stdev_value, percentile_25, percentile_50, percentile_75,
                   fractional_sum,
                   -- Dates
                   min_date, max_date,
                   before_1yr_date_ct, before_5yr_date_ct, within_1yr_date_ct, within_1mo_date_ct, future_date_ct,
                   date_days_present, date_weeks_present, date_months_present,
                   -- Boolean
                   boolean_true_ct
           FROM {str_schema}.profile_results p
          LEFT JOIN (SELECT DISTINCT profile_run_id, table_name, column_name
                       FROM {str_schema}.profile_anomaly_results) s
          ON (p.profile_run_id = s.profile_run_id
          AND p.table_name = s.table_name
          AND p.column_name = s.column_name)
          WHERE p.profile_run_id = '{str_profile_run_id}'::UUID
            AND p.table_name ILIKE '{str_table_name}'
            AND p.column_name ILIKE '{str_column_name}'
          ORDER BY p.schema_name, p.table_name, position;
    """

    show_columns = ["schema_name", "table_name", "column_name", "column_type", "functional_data_type", "anomalies"]

    return db.retrieve_data(str_sql), show_columns


@st.cache_data(show_spinner="Retrieving Details")
def get_profile_screen(str_profile_run_id, str_table_name, str_column_name):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
            SELECT pr.column_name, t.anomaly_name, replace(pr.detail, ' | ', '  ') as detail
              FROM {str_schema}.profile_anomaly_results pr
            INNER JOIN {str_schema}.profile_anomaly_types t
               ON (pr.anomaly_id = t.id)
             WHERE pr.profile_run_id = '{str_profile_run_id}'::UUID
               AND pr.table_name = '{str_table_name}'
               AND pr.column_name = '{str_column_name}'
               AND t.anomaly_name <> 'Suggested Data Type'
            ORDER BY anomaly_name;
    """
    # Retrieve and return data as df
    return db.retrieve_data(str_sql)


def reverse_count_category_pairs(input_str):
    # Split the string by ' | ' to get individual elements
    elements = input_str.split(" | ")
    # Initialize an empty list to store reversed pairs
    reversed_pairs = []
    display_pairs = []

    # Loop to populate the list with reversed pairs
    for i in range(0, len(elements), 2):
        count = elements[i]
        category = elements[i + 1]

        # Reverse count and category
        reversed_pair = f"{category} | {count}"
        reversed_pairs.append(reversed_pair)
        # Reverse second version, for display on separate lines
        display_pair = f"{category}: {count}"
        display_pairs.append(display_pair)

    # Join the reversed pairs back into a single string
    reversed_str = " | ".join(reversed_pairs)

    # Join the reversed pairs back into a single string
    display_str = "<br>".join(display_pairs)

    return reversed_str, display_str


def write_profile_screen(selected_row):
    df_screen = get_profile_screen(
        selected_row["profile_run_id"], selected_row["table_name"], selected_row["column_name"]
    )
    if not df_screen.empty:
        with st.expander("**Profiling Anomalies**"):
            # fm.render_markdown_table(df_screen, ["column_name", "anomaly_name", "detail"])
            st.dataframe(df_screen, use_container_width=True, hide_index=True)


def write_column_header(selected_row):
    str_header = "Profiling Results"
    lst_columns = [
        "column_name",
        "table_name",
        "schema_name",
        "general_type",
        "column_type",
        "functional_data_type",
        "datatype_suggestion",
    ]
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_shared_header(selected_row):
    str_header = "Data Overview"
    # lst_columns = "record_ct, value_ct, distinct_value_ct, min_length, max_length, avg_length".split(", ")
    lst_columns = "record_ct, value_ct, distinct_value_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_alpha_missing_values(selected_row):
    str_header = "Missing Values"
    lst_columns = "null_value_ct, zero_length_ct, dummy_value_ct, zero_value_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_numeric_missing_values(selected_row):
    str_header = "Missing Values"
    lst_columns = "null_value_ct, zero_value_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_alpha_content_analysis(selected_row):
    str_header = "Content Analysis"
    lst_columns = "numeric_ct, date_ct, includes_digit_ct, embedded_space_ct, avg_embedded_spaces".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_alpha_value_analysis(selected_row):
    str_header = "Value Analysis"
    lst_columns = "min_length, max_length, avg_length, min_text, max_text, top_freq_values, distinct_pattern_ct, top_patterns, std_pattern_match".split(
        ", "
    )
    if selected_row["top_patterns"]:
        # Need to reverse this, as it's saved | NNNN | Category | NNN | Category
        str_top_patterns, str_top_patterns_display = reverse_count_category_pairs(selected_row["top_patterns"])
        selected_row["top_patterns"] = str_top_patterns_display

    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)
    # Now reset for graph
    if selected_row["top_patterns"]:
        selected_row["top_patterns"] = str_top_patterns


def write_numeric_value_analysis(selected_row):
    str_header = "Values and Ranges"
    lst_columns = "min_value, min_value_over_0, max_value, min_length, max_length, avg_length".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_stats_value_analysis(selected_row):
    str_header = "Descriptive Statistics"
    lst_columns = "avg_value, stdev_value, percentile_25, percentile_50, percentile_75".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_date_analysis(selected_row):
    str_header = "Date Value Analysis"
    lst_columns = "min_date, max_date, before_1yr_date_ct, before_5yr_date_ct, within_1yr_date_ct, within_1mo_date_ct, future_date_ct".split(
        ", "
    )
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_boolean_analysis(selected_row):
    str_header = "Boolean Value Analysis"
    lst_columns = "boolean_true_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, FORM_DATA_WIDTH)


def write_missing_values_graph(value_ct, null_value_ct, zero_length_ct, dummy_values_ct):
    lst_status = ["Value Present", "Null Value"]
    lst_ct = [value_ct, null_value_ct]

    if zero_length_ct:
        lst_status.append("Zero-Length")
        lst_ct.append(zero_length_ct)
    if dummy_values_ct:
        lst_status.append("Dummy Value")
        lst_ct.append(dummy_values_ct)

    dfg = pd.DataFrame({"Status": lst_status, "Count": lst_ct})

    # fig = px.bar(dfg, x='Count', y='Status', orientation='h', title='Missing Values')
    fig = px.pie(dfg, values="Count", names="Status", title="Missing Values")
    # Show percentage in the pie chart
    fig.update_traces(textinfo="percent+label")
    fig.update_layout(
        width=400,
        title_font={"color": "green"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    # Create the stacked bar chart
    st.plotly_chart(fig, use_container_width=True)


def write_top_freq_graph(input_str):
    lines = input_str.strip().split("\n")

    # Initialize empty lists to store categories and frequencies
    categories = []
    frequencies = []

    # Loop through each line to extract category and frequency
    for line in lines:
        parts = line.split(" | ")
        # Remove the leading pipe character from the category
        category = parts[0].replace("| ", "").strip()
        frequency = int(parts[1])

        categories.append(category)
        frequencies.append(frequency)

    # Create a Pandas DataFrame
    dff = pd.DataFrame({"Value": categories, "Frequency": frequencies})

    # Calculate the total count and percentages
    total_count = dff["Frequency"].sum()
    dff["pct"] = (dff["Frequency"] / total_count * 100).round(2)

    # Create the Plotly Express histogram
    fig = px.bar(dff, x="Value", y="Frequency", title="Value Frequency", text=dff["pct"].apply(lambda x: f"{x}%"))
    # Update the trace to position text labels
    fig.update_traces(textposition="outside")
    fig.update_xaxes(type="category")
    fig.update_layout(
        width=400,
        height=500,
        title_font={"color": "green"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    st.plotly_chart(fig)


def write_top_patterns_graph(input_str):
    # Split the string by ' | ' to get individual elements
    elements = input_str.split(" | ")

    # Initialize empty lists to store categories and frequencies
    categories = []
    frequencies = []

    # Loop to populate the lists with data
    for i in range(0, len(elements), 2):
        categories.append(elements[i])
        frequencies.append(int(elements[i + 1]))  # Convert string to integer for count

    # Create a DataFrame using the populated lists
    dff = pd.DataFrame({"Category": categories, "Frequency": frequencies})

    # Create the Plotly Express histogram
    fig = px.bar(dff, x="Category", y="Frequency", title="Top Patterns")
    fig.update_layout(
        width=400,
        title_font={"color": "green"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    st.plotly_chart(fig)


def write_box_plot(min_value, max_value, avg_value, stdev_value, percentile_25, percentile_75):
    # Pick right IQR values
    iqr_25 = percentile_25 if percentile_25 else avg_value - stdev_value
    iqr_75 = percentile_75 if percentile_75 else avg_value + stdev_value

    # Create a DataFrame for the box plot
    df = pd.DataFrame(
        {
            # "Value": [min_value, avg_value - stdev_value, avg_value, avg_value + stdev_value, max_value],
            "Value": [min_value, iqr_25, avg_value, iqr_75, max_value],
            "Category": ["Data Distribution"] * 5,
        }
    )

    # Create a box plot
    fig = px.box(df, y="Value", title="Summary Stats", labels={"Value": "Value"})

    # Add Dot plot for min, max, and average
    # fig.add_scatter(
    #     y=[min_value, avg_value, max_value],
    #     mode="markers",
    #     marker={"size": [10, 15, 10], "color": ["blue", "green", "red"]},
    #     name="Min, Avg, Max",
    # )

    # Add line for standard deviation
    fig.add_shape(
        go.layout.Shape(
            type="line",
            x0=0.5,
            x1=0.5,
            y0=avg_value - stdev_value,
            y1=avg_value + stdev_value,
            line={
                "color": "Purple",
                "width": 4,
                "dash": "dot",
            },
        )
    )

    fig.update_layout(
        width=400,
        title_font={"color": "green"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig)


def show_record_detail(selected_row):
    write_profile_screen(selected_row)

    layout_column_1, layout_column_2 = st.columns([0.5, 0.5])

    with layout_column_1:
        write_column_header(selected_row)
        write_shared_header(selected_row)
        if selected_row["general_type_abbr"] == "A":
            write_alpha_missing_values(selected_row)
            write_alpha_content_analysis(selected_row)
            write_alpha_value_analysis(selected_row)
        elif selected_row["general_type_abbr"] == "N":
            write_numeric_missing_values(selected_row)
            write_numeric_value_analysis(selected_row)
            write_stats_value_analysis(selected_row)
        elif selected_row["general_type_abbr"] == "D":
            write_date_analysis(selected_row)
        # elif selected_row['general_type_abbr'] == "T":
        elif selected_row["general_type_abbr"] == "B":
            write_boolean_analysis(selected_row)

    with layout_column_2:
        if selected_row["avg_value"] is not None:
            write_box_plot(
                selected_row["min_value"],
                selected_row["max_value"],
                selected_row["avg_value"],
                selected_row["stdev_value"],
                selected_row["percentile_25"],
                selected_row["percentile_75"],
            )
        if selected_row["top_freq_values"] is not None:
            write_top_freq_graph(selected_row["top_freq_values"])
        if selected_row["top_patterns"] is not None:
            write_top_patterns_graph(selected_row["top_patterns"])
        write_missing_values_graph(
            selected_row["value_ct"],
            selected_row["null_value_ct"],
            selected_row["zero_length_ct"],
            selected_row["dummy_value_ct"],
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
