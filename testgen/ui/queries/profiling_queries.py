from typing import Literal

import pandas as pd
import streamlit as st

from testgen.ui.services.database_service import fetch_all_from_db, fetch_df_from_db
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


@st.cache_data(show_spinner=False)
def get_profiling_results(profiling_run_id: str, table_name: str | None = None, column_name: str | None = None, sorting_columns = None) -> pd.DataFrame:
    order_by = ""
    if sorting_columns is None:
        order_by = "ORDER BY LOWER(schema_name), LOWER(table_name), position"
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
        db_data_type,
        functional_data_type,
        datatype_suggestion,
        -- Profile Run
        profile_run_id::VARCHAR,
        run_date AS profile_run_date,
        query_error AS profiling_error,
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
        ) THEN 'Yes' END AS hygiene_issues,
        CASE WHEN query_error IS NOT NULL THEN 'Error: ' || query_error ELSE NULL END AS result_details
    FROM profile_results
    WHERE profile_run_id = :profiling_run_id
        AND table_name ILIKE :table_name
        AND column_name ILIKE :column_name
    {order_by};
    """
    params = {
        "profiling_run_id": profiling_run_id,
        "table_name": table_name or "%%",
        "column_name": column_name or "%%",
    }

    return fetch_df_from_db(query, params)


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
    
    condition = "WHERE table_id = :table_id"
    params = {"table_id": table_id}
    return get_tables_by_condition(condition, params, include_tags, include_has_test_runs, include_active_tests, include_scores)[0]


def get_tables_by_id(
    table_ids: list[str],
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict]:
    condition = """
    INNER JOIN (
        SELECT UNNEST(ARRAY [:table_ids]) AS id
    ) selected ON (table_chars.table_id = selected.id::UUID)"""
    params = {"table_ids": table_ids}
    return get_tables_by_condition(condition, params, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_tables_by_table_group(
    table_group_id: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict]:
    if not is_uuid4(table_group_id):
        return None
    
    condition = "WHERE table_chars.table_groups_id = :table_group_id"
    params = {"table_group_id": table_group_id}
    return get_tables_by_condition(condition, params, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_tables_by_condition(
    filter_condition: str,
    filter_params: dict,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict]:
    query = f"""
    {"""
    WITH active_test_definitions AS (
        SELECT
            test_defs.table_groups_id,
            test_defs.schema_name,
            test_defs.table_name,
            COUNT(*) AS count
        FROM test_definitions test_defs
            LEFT JOIN data_column_chars ON (
                test_defs.table_groups_id = data_column_chars.table_groups_id
                AND test_defs.schema_name = data_column_chars.schema_name
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
        approx_record_ct,
        table_chars.record_ct,
        table_chars.column_ct,
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
        {"""
        -- Has Test Runs
        EXISTS(
            SELECT 1
            FROM test_results
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
    FROM data_table_chars table_chars
        LEFT JOIN profiling_runs ON (
            table_chars.last_complete_profile_run_id = profiling_runs.id
        )
        {"""
        LEFT JOIN table_groups ON (
            table_chars.table_groups_id = table_groups.id
        )
        """ if include_tags else ""}
        {"""
        LEFT JOIN active_test_definitions active_tests ON (
            table_chars.table_groups_id = active_tests.table_groups_id
            AND table_chars.schema_name = active_tests.schema_name
            AND table_chars.table_name = active_tests.table_name
        )
        """ if include_active_tests else ""}
    {filter_condition}
    ORDER BY LOWER(table_chars.table_name);
    """

    results = fetch_all_from_db(query, filter_params)
    return [ dict(row) for row in results ]


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

    condition = "WHERE column_chars.column_id = :column_id"
    params = {"column_id": column_id}
    return get_columns_by_condition(condition, params, include_tags, include_has_test_runs, include_active_tests, include_scores)[0]


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
    condition = """
    WHERE column_chars.column_name = :column_name
    AND column_chars.table_name = :table_name
    AND column_chars.table_groups_id = :table_group_id
    """
    params = {
        "column_name": column_name,
        "table_name": table_name,
        "table_group_id": table_group_id,
    }
    return get_columns_by_condition(condition, params, include_tags, include_has_test_runs, include_active_tests, include_scores)[0]


def get_columns_by_id(
    column_ids: list[str],
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict]:
    condition = """
    INNER JOIN (
        SELECT UNNEST(ARRAY [:column_ids]) AS id
    ) selected ON (column_chars.column_id = selected.id::UUID)"""
    params = {"column_ids": [ col for col in column_ids if is_uuid4(col) ]}
    return get_columns_by_condition(condition, params, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_columns_by_table_group(
    table_group_id: str,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict]:
    if not is_uuid4(table_group_id):
        return None

    condition = "WHERE column_chars.table_groups_id = :table_group_id"
    params = {"table_group_id": table_group_id}
    return get_columns_by_condition(condition, params, include_tags, include_has_test_runs, include_active_tests, include_scores)


def get_columns_by_condition(
    filter_condition: str,
    filter_params: dict,
    include_tags: bool = False,
    include_has_test_runs: bool = False,
    include_active_tests: bool = False,
    include_scores: bool = False,
) -> list[dict]:
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
        column_chars.db_data_type,
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
        query_error AS profiling_error,
        {"""
        -- Has Test Runs
        EXISTS(
            SELECT 1
            FROM test_results
            WHERE table_groups_id = column_chars.table_groups_id
                AND table_name = column_chars.table_name
                AND column_names = column_chars.column_name
        ) AS has_test_runs,
        """ if include_has_test_runs else ""}
        {"""
        -- Test Definition Count
        (
            SELECT COUNT(*)
            FROM test_definitions
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
        table_chars.approx_record_ct,
        {COLUMN_PROFILING_FIELDS}
    FROM data_column_chars column_chars
        LEFT JOIN data_table_chars table_chars ON (
            column_chars.table_id = table_chars.table_id
        )
        {"""
        LEFT JOIN table_groups ON (
            column_chars.table_groups_id = table_groups.id
        )
        """ if include_tags else ""}
        LEFT JOIN profile_results ON (
            column_chars.last_complete_profile_run_id = profile_results.profile_run_id
            AND column_chars.schema_name = profile_results.schema_name
            AND column_chars.table_name = profile_results.table_name
            AND column_chars.column_name = profile_results.column_name
        )
    {filter_condition}
    ORDER BY LOWER(column_chars.table_name), ordinal_position;
    """
    results = fetch_all_from_db(query, filter_params)
    return [ dict(row) for row in results ]


@st.cache_data(show_spinner=False)
def get_hygiene_issues(profile_run_id: str, table_name: str, column_name: str | None = None) -> list[dict]:
    if not profile_run_id:
        return []

    query = f"""
    WITH pii_results AS (
        SELECT id,
            CASE
                WHEN detail LIKE 'Risk: HIGH%%' THEN 'High'
                WHEN detail LIKE 'Risk: MODERATE%%' THEN 'Moderate'
                ELSE null
            END AS pii_risk
        FROM profile_anomaly_results
    )
    SELECT column_name,
        anomaly_name,
        issue_likelihood,
        detail,
        pii_risk
    FROM profile_anomaly_results anomaly_results
        LEFT JOIN profile_anomaly_types anomaly_types ON (
            anomaly_types.id = anomaly_results.anomaly_id
        )
        LEFT JOIN pii_results ON (
            anomaly_results.id = pii_results.id
        )
    WHERE profile_run_id = :profile_run_id
        AND table_name = :table_name
        {"AND column_name = :column_name" if column_name else ""}
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
        LOWER(column_name);
    """
    params = {
        "profile_run_id": profile_run_id,
        "table_name": table_name,
        "column_name": column_name,
    }
    results = fetch_all_from_db(query, params)
    return [ dict(row) for row in results ]


@st.cache_data(show_spinner=False)
def get_profiling_anomalies(
    profile_run_id: str,
    likelihood: str | None = None,
    issue_type_id: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    action: Literal["Confirmed", "Dismissed", "Muted", "No Action"] | None = None,
    sorting_columns: list[str] | None = None,
) -> pd.DataFrame:
    query = f"""
    SELECT
        r.table_name,
        r.column_name,
        r.schema_name,
        r.db_data_type,
        t.anomaly_name,
        t.issue_likelihood,
        r.disposition,
        null as action,
        CASE
            WHEN t.issue_likelihood = 'Possible' THEN 'Possible: speculative test that often identifies problems'
            WHEN t.issue_likelihood = 'Likely'   THEN 'Likely: typically indicates a data problem'
            WHEN t.issue_likelihood = 'Definite'  THEN 'Definite: indicates a highly-likely data problem'
            WHEN t.issue_likelihood = 'Potential PII'
            THEN 'Potential PII: may require privacy policies, standards and procedures for access, storage and transmission.'
        END AS likelihood_explanation,
        CASE
            WHEN t.issue_likelihood = 'Potential PII' THEN 4
            WHEN t.issue_likelihood = 'Possible' THEN 3
            WHEN t.issue_likelihood = 'Likely'   THEN 2
            WHEN t.issue_likelihood = 'Definite'  THEN 1
        END AS likelihood_order,
        t.anomaly_description, r.detail, t.suggested_action,
        r.anomaly_id, r.table_groups_id::VARCHAR, r.id::VARCHAR, p.profiling_starttime, r.profile_run_id::VARCHAR,
        tg.table_groups_name,

        -- These are used in the PDF report
        dcc.functional_data_type,
        dcc.description as column_description,
        COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
        COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
        COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
        COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
        COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
        COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
        COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
        COALESCE(dcc.aggregation_level, dtc.aggregation_level) as aggregation_level,
        COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product
    FROM profile_anomaly_results r
    INNER JOIN profile_anomaly_types t
        ON r.anomaly_id = t.id
    INNER JOIN profiling_runs p
        ON r.profile_run_id = p.id
    INNER JOIN table_groups tg
        ON r.table_groups_id = tg.id
    LEFT JOIN data_column_chars dcc
        ON (tg.id = dcc.table_groups_id
        AND r.schema_name = dcc.schema_name
        AND r.table_name = dcc.table_name
        AND r.column_name = dcc.column_name)
    LEFT JOIN data_table_chars dtc
        ON dcc.table_id = dtc.table_id
    WHERE r.profile_run_id = :profile_run_id
        {"AND t.issue_likelihood = :likelihood" if likelihood else ""}
        {"AND t.id = :issue_type_id" if issue_type_id else ""}
        {"AND r.table_name = :table_name" if table_name else ""}
        {"AND r.column_name ILIKE :column_name" if column_name else ""}
        {"AND r.disposition IS NULL" if action == "No Action" else "AND r.disposition = :disposition" if action else ""}
    {f"ORDER BY {', '.join(' '.join(col) for col in sorting_columns)}" if sorting_columns else ""}
    """
    params = {
        "profile_run_id": profile_run_id,
        "likelihood": likelihood,
        "issue_type_id": issue_type_id,
        "table_name": table_name,
        "column_name": column_name,
        "disposition": {
            "Muted": "Inactive",
        }.get(action, action),
    }
    df = fetch_df_from_db(query, params)
    dct_replace = {"Confirmed": "✓", "Dismissed": "✘", "Inactive": "🔇"}
    df["action"] = df["disposition"].replace(dct_replace)

    return df
