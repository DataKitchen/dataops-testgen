import json
from datetime import datetime
from typing import NamedTuple

import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
from testgen.common.models import get_current_session
from testgen.utils import is_uuid4

TAG_FIELDS = [
    "data_source",
    "source_system",
    "source_process",
    "business_domain",
    "stakeholder_group",
    "transform_level",
    "aggregation_level",
    "data_product",
]
COLUMN_PROFILING_FIELDS = """
-- Value Counts
profile_results.record_ct,
value_ct,
distinct_value_ct,
null_value_ct,
zero_value_ct,
-- Alpha
zero_length_ct,
filled_value_ct,
mixed_case_ct,
lower_case_ct,
upper_case_ct,
non_alpha_ct,
includes_digit_ct,
numeric_ct,
date_ct,
quoted_value_ct,
lead_space_ct,
embedded_space_ct,
avg_embedded_spaces,
min_length,
max_length,
avg_length,
min_text,
max_text,
distinct_std_value_ct,
distinct_pattern_ct,
std_pattern_match,
top_freq_values,
top_patterns,
-- Numeric
min_value,
min_value_over_0,
max_value,
avg_value,
stdev_value,
percentile_25,
percentile_50,
percentile_75,
-- Date
min_date,
max_date,
before_1yr_date_ct,
before_5yr_date_ct,
before_20yr_date_ct,
within_1yr_date_ct,
within_1mo_date_ct,
future_date_ct,
-- Boolean
boolean_true_ct
"""

@st.cache_data(show_spinner="Loading data ...")
def get_run_by_id(profile_run_id: str) -> pd.Series:
    if not is_uuid4(profile_run_id):
        return pd.Series()
    
    schema: str = st.session_state["dbschema"]
    sql = f"""
    SELECT profiling_starttime, table_groups_id::VARCHAR, table_groups_name, pr.project_code, pr.dq_score_profiling,
        CASE WHEN pr.id = tg.last_complete_profile_run_id THEN true ELSE false END AS is_latest_run
        FROM {schema}.profiling_runs pr
    INNER JOIN {schema}.table_groups tg
        ON pr.table_groups_id = tg.id
    WHERE pr.id = '{profile_run_id}'
    """
    df = db.retrieve_data(sql)
    if not df.empty:
        return df.iloc[0]
    else:
        return pd.Series()


@st.cache_data(show_spinner=False)
def get_profiling_results(profiling_run_id: str, table_name: str | None = None, column_name: str | None = None, sorting_columns = None):
    db_session = get_current_session()
    params = {
        "profiling_run_id": profiling_run_id,
        "table_name": table_name if table_name else "%%",
        "column_name": column_name if column_name else "%%",
    }

    order_by = ""
    if sorting_columns is None:
        order_by = "ORDER BY schema_name, table_name, position"
    elif len(sorting_columns):
        order_by = "ORDER BY " + ", ".join(" ".join(col) for col in sorting_columns)

    query = f"""
    SELECT
        id::VARCHAR,
        'column' AS type,
        schema_name,
        table_name,
        column_name,
        table_groups_id::VARCHAR AS table_group_id,
        -- Characteristics
        general_type,
        column_type,
        functional_data_type,
        datatype_suggestion,
        -- Profile Run
        profile_run_id::VARCHAR,
        run_date AS profile_run_date,
        {COLUMN_PROFILING_FIELDS},
        -- Extra fields for sorting and exporting
        position,
        functional_data_type AS semantic_data_type,
        functional_table_type AS semantic_table_type,
        CASE WHEN EXISTS(
            SELECT 1
            FROM profile_anomaly_results
            WHERE profile_run_id = profile_results.profile_run_id
                AND table_name = profile_results.table_name
                AND column_name = profile_results.column_name
        ) THEN 'Yes' END AS hygiene_issues
    FROM profile_results
    WHERE profile_run_id = :profiling_run_id
        AND table_name ILIKE :table_name
        AND column_name ILIKE :column_name
    {order_by};
    """

    results = db_session.execute(query, params=params)
    columns = [column.name for column in results.cursor.description]

    return pd.DataFrame(list(results), columns=columns)


@st.cache_data(show_spinner=False)
def get_table_by_id(
    table_id: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> dict | None:
    if not is_uuid4(table_id):
        return None
    
    condition = f"WHERE table_id = '{table_id}'"
    return get_tables_by_condition(condition, include_tags, include_has_test_runs, include_active_tests, include_scores)[0]


def get_tables_by_id(
    table_ids: list[str],
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict] | None:
    condition = f"""
    INNER JOIN (
        SELECT UNNEST(ARRAY [{", ".join([ f"'{col}'" for col in table_ids if is_uuid4(col) ])}]) AS id
    ) selected ON (table_chars.table_id = selected.id::UUID)"""
    return get_tables_by_condition(condition, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_tables_by_table_group(
    table_group_id: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict] | None:
    if not is_uuid4(table_group_id):
        return None
    
    condition = f"WHERE table_chars.table_groups_id = '{table_group_id}'"
    return get_tables_by_condition(condition, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_tables_by_condition(
    filter_condition: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict] | None:
    schema: str = st.session_state["dbschema"]
    query = f"""
    {f"""
    WITH active_test_definitions AS (
        SELECT
            test_defs.table_groups_id,
            test_defs.table_name,
            COUNT(*) AS count
        FROM {schema}.test_definitions test_defs
            LEFT JOIN {schema}.data_column_chars ON (
                test_defs.table_groups_id = data_column_chars.table_groups_id
                AND test_defs.table_name = data_column_chars.table_name
                AND test_defs.column_name = data_column_chars.column_name
            )
        WHERE test_active = 'Y'
            AND column_id IS NULL
        GROUP BY test_defs.table_groups_id,
            test_defs.table_name
    )
    """ if include_active_tests else ""}
    SELECT
        table_chars.table_id::VARCHAR AS id,
        'table' AS type,
        table_chars.table_name,
        table_chars.schema_name,
        table_chars.table_groups_id::VARCHAR AS table_group_id,
        -- Characteristics
        functional_table_type,
        record_ct,
        table_chars.column_ct,
        data_point_ct,
        add_date,
        last_refresh_date,
        drop_date,
        {f"""
        -- Table Tags
        table_chars.description,
        table_chars.critical_data_element,
        {", ".join([ f"table_chars.{tag}" for tag in TAG_FIELDS ])},
        -- Table Groups Tags
        {", ".join([ f"table_groups.{tag} AS table_group_{tag}" for tag in TAG_FIELDS if tag != "aggregation_level" ])},
        """ if include_tags else ""}
        {f"""
        -- Has Test Runs
        EXISTS(
            SELECT 1
            FROM {schema}.test_results
            WHERE table_groups_id = table_chars.table_groups_id
                AND table_name = table_chars.table_name
        ) AS has_test_runs,
        """ if include_has_test_runs else ""}
        {"""
        -- Test Definition Count
        active_tests.count AS active_test_count,
        """ if include_active_tests else ""}
        {"""
        -- Scores
        table_chars.dq_score_profiling,
        table_chars.dq_score_testing,
        """ if include_scores else ""}
        -- Profile Run
        table_chars.last_complete_profile_run_id::VARCHAR AS profile_run_id,
        profiling_starttime AS profile_run_date,
        TRUE AS is_latest_profile
    FROM {schema}.data_table_chars table_chars
        LEFT JOIN {schema}.profiling_runs ON (
            table_chars.last_complete_profile_run_id = profiling_runs.id
        )
        {f"""
        LEFT JOIN {schema}.table_groups ON (
            table_chars.table_groups_id = table_groups.id
        )
        """ if include_tags else ""}
        {"""
        LEFT JOIN active_test_definitions active_tests ON (
            table_chars.table_groups_id = active_tests.table_groups_id
            AND table_chars.table_name = active_tests.table_name
        )
        """ if include_active_tests else ""}
    {filter_condition}
    ORDER BY table_name;
    """

    results = db.retrieve_data(query)
    if not results.empty:
        # to_json converts datetimes, NaN, etc, to JSON-safe values (Note: to_dict does not)
        return json.loads(results.to_json(orient="records"))


@st.cache_data(show_spinner=False)
def get_column_by_id(
    column_id: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> dict | None:
    if not is_uuid4(column_id):
        return None

    condition = f"WHERE column_chars.column_id = '{column_id}'"
    return get_columns_by_condition(condition, include_tags, include_has_test_runs, include_active_tests, include_scores)[0]


@st.cache_data(show_spinner="Loading data ...")
def get_column_by_name(
    column_name: str,
    table_name: str,
    table_group_id: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> dict | None:

    condition = f"""
    WHERE column_chars.column_name = '{column_name}'
    AND column_chars.table_name = '{table_name}'
    AND column_chars.table_groups_id = '{table_group_id}'
    """
    return get_columns_by_condition(condition, include_tags, include_has_test_runs, include_active_tests, include_scores)[0]


def get_columns_by_id(
    column_ids: list[str],
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict] | None:
    condition = f"""
    INNER JOIN (
        SELECT UNNEST(ARRAY [{", ".join([ f"'{col}'" for col in column_ids if is_uuid4(col) ])}]) AS id
    ) selected ON (column_chars.column_id = selected.id::UUID)"""
    return get_columns_by_condition(condition, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_columns_by_table_group(
    table_group_id: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict] | None:
    if not is_uuid4(table_group_id):
        return None

    condition = f"WHERE column_chars.table_groups_id = '{table_group_id}'"
    return get_columns_by_condition(condition, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_columns_by_condition(
    filter_condition: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict] | None:
    schema: str = st.session_state["dbschema"]

    query = f"""
    SELECT
        column_chars.column_id::VARCHAR AS id,
        'column' AS type,
        column_chars.column_name,
        column_chars.table_name,
        column_chars.schema_name,
        column_chars.table_groups_id::VARCHAR AS table_group_id,
        column_chars.ordinal_position,
        -- Characteristics
        column_chars.general_type,
        column_chars.column_type,
        column_chars.functional_data_type,
        datatype_suggestion,
        column_chars.add_date,
        column_chars.last_mod_date,
        column_chars.drop_date,
        {f"""
        -- Column Tags
        column_chars.description,
        column_chars.critical_data_element,
        {", ".join([ f"column_chars.{tag}" for tag in TAG_FIELDS ])},
        -- Table Tags
        table_chars.critical_data_element AS table_critical_data_element,
        {", ".join([ f"table_chars.{tag} AS table_{tag}" for tag in TAG_FIELDS ])},
        -- Table Groups Tags
        {", ".join([ f"table_groups.{tag} AS table_group_{tag}" for tag in TAG_FIELDS if tag != "aggregation_level" ])},
        """ if include_tags else ""}
        -- Profile Run
        column_chars.last_complete_profile_run_id::VARCHAR AS profile_run_id,
        run_date AS profile_run_date,
        TRUE AS is_latest_profile,
        {f"""
        -- Has Test Runs
        EXISTS(
            SELECT 1
            FROM {schema}.test_results
            WHERE table_groups_id = column_chars.table_groups_id
                AND table_name = column_chars.table_name
                AND column_names = column_chars.column_name
        ) AS has_test_runs,
        """ if include_has_test_runs else ""}
        {f"""
        -- Test Definition Count
        (
            SELECT COUNT(*)
            FROM {schema}.test_definitions
            WHERE table_groups_id = column_chars.table_groups_id
                AND table_name = column_chars.table_name
                AND column_name = column_chars.column_name
                AND test_active = 'Y'
        ) AS active_test_count,
        """ if include_active_tests else ""}
        {"""
        -- Scores
        column_chars.dq_score_profiling,
        column_chars.dq_score_testing,
        """ if include_scores else ""}
        {COLUMN_PROFILING_FIELDS}
    FROM {schema}.data_column_chars column_chars
        {f"""
        LEFT JOIN {schema}.data_table_chars table_chars ON (
            column_chars.table_id = table_chars.table_id
        )
        LEFT JOIN {schema}.table_groups ON (
            column_chars.table_groups_id = table_groups.id
        )
        """ if include_tags else ""}
        LEFT JOIN {schema}.profile_results ON (
            column_chars.last_complete_profile_run_id = profile_results.profile_run_id
            AND column_chars.table_name = profile_results.table_name
            AND column_chars.column_name = profile_results.column_name
        )
    {filter_condition}
    ORDER BY table_name, ordinal_position;
    """

    results = db.retrieve_data(query)
    if not results.empty:
        # to_json converts datetimes, NaN, etc, to JSON-safe values (Note: to_dict does not)
        return json.loads(results.to_json(orient="records"))


@st.cache_data(show_spinner=False)
def get_hygiene_issues(profile_run_id: str, table_name: str, column_name: str | None = None) -> list[dict]:
    if not profile_run_id:
        return []

    schema: str = st.session_state["dbschema"]

    column_condition = ""
    if column_name:
        column_condition = f"AND column_name = '{column_name}'"

    query = f"""
    WITH pii_results AS (
        SELECT id,
            CASE
                WHEN detail LIKE 'Risk: HIGH%%' THEN 'High'
                WHEN detail LIKE 'Risk: MODERATE%%' THEN 'Moderate'
                ELSE null
            END AS pii_risk
        FROM {schema}.profile_anomaly_results
    )
    SELECT column_name,
        anomaly_name,
        issue_likelihood,
        detail,
        pii_risk
    FROM {schema}.profile_anomaly_results anomaly_results
        LEFT JOIN {schema}.profile_anomaly_types anomaly_types ON (
            anomaly_types.id = anomaly_results.anomaly_id
        )
        LEFT JOIN pii_results ON (
            anomaly_results.id = pii_results.id
        )
    WHERE profile_run_id = '{profile_run_id}'
        AND table_name = '{table_name}'
        {column_condition}
        AND COALESCE(disposition, 'Confirmed') = 'Confirmed'
    ORDER BY
        CASE issue_likelihood
            WHEN 'Definite' THEN 1
            WHEN 'Likely' THEN 2
            WHEN 'Possible' THEN 3
            ELSE 4
        END,
        CASE pii_risk
            WHEN 'High' THEN 1
            WHEN 'Moderate' THEN 2
            ELSE 3
        END,
        column_name;
    """

    results = db.retrieve_data(query)
    return [row.to_dict() for _, row in results.iterrows()]


class LatestProfilingRun(NamedTuple):
    id: str
    run_time: datetime


def get_latest_run_date(project_code: str) -> LatestProfilingRun | None:
    session = get_current_session()
    result = session.execute(
        """
        SELECT id, profiling_starttime
        FROM profiling_runs
        WHERE project_code = :project_code
            AND status = 'Complete'
        ORDER BY profiling_starttime DESC
        LIMIT 1
        """,
        params={"project_code": project_code},
    )
    if result and (latest_run := result.first()):
        return LatestProfilingRun(str(latest_run.id), latest_run.profiling_starttime)
    return None
