import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.query_service as query_service


@st.cache_data(show_spinner=False)
def get_projects():
    schema: str = st.session_state["dbschema"]
    return query_service.run_project_lookup_query(schema)


@st.cache_data(show_spinner=False)
def get_summary_by_code(project_code: str) -> pd.Series:
    schema: str = st.session_state["dbschema"]
    sql = f"""
    SELECT (
            SELECT COUNT(*) AS count
            FROM {schema}.connections
            WHERE connections.project_code = '{project_code}'
        ) AS connections_ct,
        (
            SELECT connection_id
            FROM {schema}.connections
            WHERE connections.project_code = '{project_code}'
            LIMIT 1
        ) AS default_connection_id,
        (
            SELECT COUNT(*)
            FROM {schema}.table_groups
            WHERE table_groups.project_code = '{project_code}'
        ) AS table_groups_ct,
        (
            SELECT COUNT(*)
            FROM {schema}.profiling_runs
                LEFT JOIN {schema}.table_groups ON profiling_runs.table_groups_id = table_groups.id
            WHERE table_groups.project_code = '{project_code}'
        ) AS profiling_runs_ct,
        (
            SELECT COUNT(*)
            FROM {schema}.test_suites
            WHERE test_suites.project_code = '{project_code}'
        ) AS test_suites_ct,
        (
            SELECT COUNT(*)
            FROM {schema}.test_definitions
                LEFT JOIN {schema}.test_suites ON test_definitions.test_suite_id = test_suites.id
            WHERE test_suites.project_code = '{project_code}'
        ) AS test_definitions_ct,
        (
            SELECT COUNT(*)
            FROM {schema}.test_runs
                LEFT JOIN {schema}.test_suites ON test_runs.test_suite_id = test_suites.id
            WHERE test_suites.project_code = '{project_code}'
        ) AS test_runs_ct;
    """
    return db.retrieve_data(sql).iloc[0]
