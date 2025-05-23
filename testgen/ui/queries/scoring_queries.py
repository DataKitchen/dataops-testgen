from collections import defaultdict

import pandas as pd
import streamlit as st

from testgen.common.models import engine
from testgen.common.models.scores import ScoreCard, ScoreCategory, ScoreDefinition, SelectedIssue


@st.cache_data(show_spinner="Loading data :gray[:small[(This might take a few minutes)]] ...")
def get_all_score_cards(project_code: str) -> list["ScoreCard"]:
    return [
        definition.as_cached_score_card()
        for definition in ScoreDefinition.all(project_code=project_code)
    ]


def get_score_card_issue_reports(selected_issues: list["SelectedIssue"]):
    profile_ids = []
    test_ids = []
    for issue in selected_issues:
        id_list = profile_ids if issue["issue_type"] == "hygiene" else test_ids
        id_list.append(issue["id"])

    schema: str = st.session_state["dbschema"]
    results = []
    if profile_ids:
        profile_query = f"""
        SELECT
            results.id::VARCHAR,
            'hygiene' AS issue_type,
            types.issue_likelihood,
            runs.profiling_starttime,
            types.anomaly_name,
            types.anomaly_description,
            results.detail,
            results.schema_name,
            results.table_name,
            results.column_name,
            results.column_type,
            groups.table_groups_name,
            results.disposition,
            results.profile_run_id::VARCHAR,
            types.suggested_action,
            results.table_groups_id::VARCHAR,
            results.anomaly_id::VARCHAR,
            column_chars.functional_data_type,
            column_chars.description as column_description,
            COALESCE(column_chars.critical_data_element, table_chars.critical_data_element) as critical_data_element,
            COALESCE(column_chars.data_source, table_chars.data_source, groups.data_source) as data_source,
            COALESCE(column_chars.source_system, table_chars.source_system, groups.source_system) as source_system,
            COALESCE(column_chars.source_process, table_chars.source_process, groups.source_process) as source_process,
            COALESCE(column_chars.business_domain, table_chars.business_domain, groups.business_domain) as business_domain,
            COALESCE(column_chars.stakeholder_group, table_chars.stakeholder_group, groups.stakeholder_group) as stakeholder_group,
            COALESCE(column_chars.transform_level, table_chars.transform_level, groups.transform_level) as transform_level,
            COALESCE(column_chars.aggregation_level, table_chars.aggregation_level) as aggregation_level,
            COALESCE(column_chars.data_product, table_chars.data_product, groups.data_product) as data_product
        FROM {schema}.profile_anomaly_results results
        INNER JOIN {schema}.profile_anomaly_types types
            ON results.anomaly_id = types.id
        INNER JOIN {schema}.profiling_runs runs
            ON results.profile_run_id = runs.id
        INNER JOIN {schema}.table_groups groups
            ON results.table_groups_id = groups.id
        LEFT JOIN {schema}.data_column_chars column_chars
            ON (groups.id = column_chars.table_groups_id
            AND results.schema_name = column_chars.schema_name
            AND results.table_name = column_chars.table_name
            AND results.column_name = column_chars.column_name)
        LEFT JOIN {schema}.data_table_chars table_chars
            ON column_chars.table_id = table_chars.table_id
        WHERE results.id IN ({",".join([f"'{issue_id}'" for issue_id in profile_ids])});
        """
        profile_results = pd.read_sql_query(profile_query, engine)
        results.extend([row.to_dict() for _, row in profile_results.iterrows()])

    if test_ids:
        test_query = f"""
        SELECT
            results.id::VARCHAR AS test_result_id,
            'test' AS issue_type,
            results.result_status,
            results.test_time,
            types.test_name_short,
            types.test_name_long,
            results.test_description,
            results.result_measure::NUMERIC(16, 5),
            types.measure_uom_description,
            results.threshold_value::NUMERIC(16, 5),
            types.threshold_description,
            results.schema_name,
            results.table_name,
            results.column_names,
            groups.table_groups_name,
            suites.test_suite,
            types.dq_dimension,
            CASE
                WHEN results.result_code <> 1 THEN results.disposition
                ELSE 'Passed'
            END as disposition,
            results.test_run_id::VARCHAR,
            types.usage_notes,
            types.test_type,
            results.auto_gen,
            results.test_suite_id,
            results.test_definition_id::VARCHAR as test_definition_id_runtime,
            results.table_groups_id::VARCHAR,
            types.id::VARCHAR AS test_type_id,
            column_chars.description as column_description,
            COALESCE(column_chars.critical_data_element, table_chars.critical_data_element) as critical_data_element,
            COALESCE(column_chars.data_source, table_chars.data_source, groups.data_source) as data_source,
            COALESCE(column_chars.source_system, table_chars.source_system, groups.source_system) as source_system,
            COALESCE(column_chars.source_process, table_chars.source_process, groups.source_process) as source_process,
            COALESCE(column_chars.business_domain, table_chars.business_domain, groups.business_domain) as business_domain,
            COALESCE(column_chars.stakeholder_group, table_chars.stakeholder_group, groups.stakeholder_group) as stakeholder_group,
            COALESCE(column_chars.transform_level, table_chars.transform_level, groups.transform_level) as transform_level,
            COALESCE(column_chars.aggregation_level, table_chars.aggregation_level) as aggregation_level,
            COALESCE(column_chars.data_product, table_chars.data_product, groups.data_product) as data_product
        FROM {schema}.test_results results
        INNER JOIN {schema}.test_types types
            ON (results.test_type = types.test_type)
        INNER JOIN {schema}.test_suites suites
            ON (results.test_suite_id = suites.id)
        INNER JOIN {schema}.table_groups groups
            ON (results.table_groups_id = groups.id)
        LEFT JOIN {schema}.data_column_chars column_chars
            ON (groups.id = column_chars.table_groups_id
            AND results.schema_name = column_chars.schema_name
            AND results.table_name = column_chars.table_name
            AND results.column_names = column_chars.column_name)
        LEFT JOIN {schema}.data_table_chars table_chars
            ON column_chars.table_id = table_chars.table_id
        WHERE results.id IN ({",".join([f"'{issue_id}'" for issue_id in test_ids])});
        """
        test_results = pd.read_sql_query(test_query, engine)
        results.extend([row.to_dict() for _, row in test_results.iterrows()])

    return results


def get_score_category_values(project_code: str) -> dict[ScoreCategory, list[str]]:
    values = defaultdict(list, {
        "dq_dimension": [
            "Accuracy",
            "Completeness",
            "Consistency",
            "Timeliness",
            "Uniqueness",
            "Validity",
        ],
    })
    categories = [
        "table_groups_name",
        "data_location",
        "data_source",
        "source_system",
        "source_process",
        "business_domain",
        "stakeholder_group",
        "transform_level",
        "data_product",
    ]

    quote = lambda v: f"'{v}'"
    query = f"""
        SELECT DISTINCT
            UNNEST(array[{', '.join([quote(c) for c in categories])}]) as category,
            UNNEST(array[{', '.join(categories)}]) AS value
        FROM v_dq_test_scoring_latest_by_column
        WHERE project_code = '{project_code}'
        UNION
        SELECT DISTINCT
            UNNEST(array[{', '.join([quote(c) for c in categories])}]) as category,
            UNNEST(array[{', '.join(categories)}]) AS value
        FROM v_dq_profile_scoring_latest_by_column
        WHERE project_code = '{project_code}'
        ORDER BY value
    """
    results = pd.read_sql_query(query, engine)
    for _, row in results.iterrows():
        if row["category"] and row["value"]:
            values[row["category"]].append(row["value"])
    return values


@st.cache_data(show_spinner="Loading data :gray[:small[(This might take a few minutes)]] ...")
def get_column_filters(project_code: str) -> list[dict]:
    query = f"""
    SELECT
        data_column_chars.column_id::text AS column_id,
        data_column_chars.column_name AS name,
        data_column_chars.table_id::text AS table_id,
        data_column_chars.table_name AS table,
        data_column_chars.table_groups_id::text AS table_group_id,
        table_groups.table_groups_name AS table_group
    FROM data_column_chars
    INNER JOIN table_groups ON (table_groups.id = data_column_chars.table_groups_id)
    WHERE table_groups.project_code = '{project_code}'
    ORDER BY table_name, ordinal_position;
    """
    return [row.to_dict() for _, row in pd.read_sql_query(query, engine).iterrows()]
