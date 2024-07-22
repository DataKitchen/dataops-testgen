import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm


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
        with st.expander("**Hygiene Issues**"):
            # fm.render_markdown_table(df_screen, ["column_name", "anomaly_name", "detail"])
            st.dataframe(df_screen, use_container_width=True, hide_index=True)


def write_column_header(selected_row, form_data_width):
    str_header = "Profiling Results"
    lst_columns = [
        "column_name",
        "table_name",
        "schema_name",
        "general_type",
        "column_type",
        "semantic_data_type",
        "datatype_suggestion",
    ]
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_shared_header(selected_row, form_data_width):
    str_header = "Data Overview"
    # lst_columns = "record_ct, value_ct, distinct_value_ct, min_length, max_length, avg_length".split(", ")
    lst_columns = "record_ct, value_ct, distinct_value_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_alpha_missing_values(selected_row, form_data_width):
    str_header = "Missing Values"
    lst_columns = "null_value_ct, zero_length_ct, dummy_value_ct, zero_value_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_numeric_missing_values(selected_row, form_data_width):
    str_header = "Missing Values"
    lst_columns = "null_value_ct, zero_value_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_alpha_content_analysis(selected_row, form_data_width):
    str_header = "Content Analysis"
    lst_columns = "numeric_ct, date_ct, includes_digit_ct, embedded_space_ct, avg_embedded_spaces".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_alpha_value_analysis(selected_row, form_data_width):
    str_header = "Value Analysis"
    lst_columns = "min_length, max_length, avg_length, min_text, max_text, top_freq_values, distinct_pattern_ct, top_patterns, std_pattern_match".split(
        ", "
    )
    if selected_row["top_patterns"]:
        # Need to reverse this, as it's saved | NNNN | Category | NNN | Category
        str_top_patterns, str_top_patterns_display = reverse_count_category_pairs(selected_row["top_patterns"])
        selected_row["top_patterns"] = str_top_patterns_display

    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)
    # Now reset for graph
    if selected_row["top_patterns"]:
        selected_row["top_patterns"] = str_top_patterns


def write_numeric_value_analysis(selected_row, form_data_width):
    str_header = "Values and Ranges"
    lst_columns = "min_value, min_value_over_0, max_value, min_length, max_length, avg_length".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_stats_value_analysis(selected_row, form_data_width):
    str_header = "Descriptive Statistics"
    lst_columns = "avg_value, stdev_value, percentile_25, percentile_50, percentile_75".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_date_analysis(selected_row, form_data_width):
    str_header = "Date Value Analysis"
    lst_columns = "min_date, max_date, before_1yr_date_ct, before_5yr_date_ct, within_1yr_date_ct, within_1mo_date_ct, future_date_ct".split(
        ", "
    )
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


def write_boolean_analysis(selected_row, form_data_width):
    str_header = "Boolean Value Analysis"
    lst_columns = "boolean_true_ct".split(", ")
    fm.render_html_list(selected_row, lst_columns, str_header, form_data_width)


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


def show_profiling_detail(selected_row, form_data_width=400):
    write_profile_screen(selected_row)

    layout_column_1, layout_column_2 = st.columns([0.5, 0.5])

    with layout_column_1:
        write_column_header(selected_row, form_data_width)
        write_shared_header(selected_row, form_data_width)
        if selected_row["general_type_abbr"] == "A":
            write_alpha_missing_values(selected_row, form_data_width)
            write_alpha_content_analysis(selected_row, form_data_width)
            write_alpha_value_analysis(selected_row, form_data_width)
        elif selected_row["general_type_abbr"] == "N":
            write_numeric_missing_values(selected_row, form_data_width)
            write_numeric_value_analysis(selected_row, form_data_width)
            write_stats_value_analysis(selected_row, form_data_width)
        elif selected_row["general_type_abbr"] == "D":
            write_date_analysis(selected_row, form_data_width)
        # elif selected_row['general_type_abbr'] == "T":
        elif selected_row["general_type_abbr"] == "B":
            write_boolean_analysis(selected_row, form_data_width)

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
