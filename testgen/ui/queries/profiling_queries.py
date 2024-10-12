import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.query_service as dq


@st.cache_data(show_spinner=False)
def run_table_groups_lookup_query(str_project_code):
    str_schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(str_schema, str_project_code)


@st.cache_data(show_spinner=False)
def get_latest_profile_run(str_table_group):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
            WITH last_profile_run
               AS (SELECT table_groups_id, MAX(profiling_starttime) as last_profile_run_date
                     FROM {str_schema}.profiling_runs
                   GROUP BY table_groups_id)
            SELECT id as profile_run_id
              FROM {str_schema}.profiling_runs r
            INNER JOIN last_profile_run l
               ON (r.table_groups_id = l.table_groups_id
              AND  r.profiling_starttime = l.last_profile_run_date)
             WHERE r.table_groups_id = '{str_table_group}';
"""
    str_profile_run_id = db.retrieve_single_result(str_sql)

    return str_profile_run_id


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
def lookup_db_parentage_from_run(profile_run_id: str) -> tuple[pd.Timestamp, str, str, str] | None:
    schema: str = st.session_state["dbschema"]
    sql = f"""
            SELECT profiling_starttime as profile_run_date, table_groups_id, g.table_groups_name, g.project_code
              FROM {schema}.profiling_runs pr
             INNER JOIN {schema}.table_groups g
                ON pr.table_groups_id = g.id
             WHERE pr.id = '{profile_run_id}'
    """
    df = db.retrieve_data(sql)
    if not df.empty:
        return df.at[0, "profile_run_date"], str(df.at[0, "table_groups_id"]), df.at[0, "table_groups_name"], df.at[0, "project_code"]


@st.cache_data(show_spinner="Retrieving Data")
def get_profiling_detail(str_profile_run_id, str_table_name, str_column_name, sorting_columns = None):
    str_schema = st.session_state["dbschema"]
    if sorting_columns is None:
        order_by_str = "ORDER BY p.schema_name, p.table_name, position"
    elif len(sorting_columns):
        order_by_str = "ORDER BY " + ", ".join(" ".join(col) for col in sorting_columns)
    else:
        order_by_str = ""

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
                   functional_table_type as semantic_table_type,
                   functional_data_type as semantic_data_type,
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
                   CASE WHEN general_type = 'A' THEN COALESCE(zero_length_ct, 0) END as zero_length_ct,
                   CASE WHEN general_type = 'A' THEN COALESCE(lead_space_ct, 0) END as lead_space_ct,
                   CASE WHEN general_type = 'A' THEN COALESCE(quoted_value_ct, 0) END as quoted_value_ct,
                   CASE WHEN general_type = 'A' THEN COALESCE(includes_digit_ct, 0) END as includes_digit_ct,
                   CASE WHEN general_type = 'A' THEN COALESCE(embedded_space_ct, 0) END as embedded_space_ct,
                   avg_embedded_spaces,
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
          {order_by_str};
    """

    return db.retrieve_data(str_sql)
