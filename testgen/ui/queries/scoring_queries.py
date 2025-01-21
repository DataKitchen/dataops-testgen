from typing import Literal, TypedDict

import streamlit as st

import testgen.ui.services.database_service as db


@st.cache_data(show_spinner="Loading data ...")
def get_table_groups_score_cards(
    project_code: str,
    sorted_by: Literal["name", "score"] = "name",
    filter_term: str | None = None
) -> list["ScoreCard"]:
    schema: str = st.session_state["dbschema"]
    query = f"""
    SET SEARCH_PATH TO {schema};
    {_TABLE_GROUP_SCORES_QUERY}
    INNER JOIN table_groups
        ON (table_groups.id = profiling_cols.table_groups_id
        OR table_groups.id = test_cols.table_groups_id)
    WHERE table_groups.project_code = '{project_code}'
    {f"AND name ILIKE '%%{filter_term}%%'  " if filter_term else ''}
    ORDER BY {sorted_by} ASC;
    """
    results = db.retrieve_data(query)

    return [
        {
            "project_code": project_code,
            "name": row["name"],
            "score": row["score"],
            "cde_score": row["cde_score"],
            "dimensions": [
                {"label": "Accuracy", "score": row["accuracy_score"]},
                {"label": "Completeness", "score": row["completeness_score"]},
                {"label": "Consistency", "score": row["consistency_score"]},
                {"label": "Timeliness", "score": row["timeliness_score"]},
                {"label": "Uniqueness", "score": row["uniqueness_score"]},
                {"label": "Validity", "score": row["validity_score"]},
            ],
        } for _, row in results.iterrows()
    ]


def get_table_group_score_card(project_code: str, table_group_id: str) -> "ScoreCard":
    schema: str = st.session_state["dbschema"]
    query = f"""
    SET SEARCH_PATH TO {schema};
    {_TABLE_GROUP_SCORES_QUERY}
    WHERE profiling_cols.table_groups_id = '{table_group_id}'
        OR test_cols.table_groups_id = '{table_group_id}';
    """
    results = db.retrieve_data(query)
    row = results.iloc[0]

    return {
        "project_code": project_code,
        "name": row["name"],
        "score": row["score"],
        "cde_score": row["cde_score"],
        "dimensions": [
            {"label": "Accuracy", "score": row["accuracy_score"]},
            {"label": "Completeness", "score": row["completeness_score"]},
            {"label": "Consistency", "score": row["consistency_score"]},
            {"label": "Timeliness", "score": row["timeliness_score"]},
            {"label": "Uniqueness", "score": row["uniqueness_score"]},
            {"label": "Validity", "score": row["validity_score"]},
        ],
    }


@st.cache_data(show_spinner="Loading data ...")
def get_score_card_breakdown(
    _project_code: str,
    table_group_id: str,
    score_type: Literal["score", "cde_score"],
    group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
) -> list[dict]:
    schema: str = st.session_state["dbschema"]
    columns = {
        "column_name": ["table_name", "column_name"],
    }.get(group_by, [group_by])
    profiling_score_view = {
        "dq_dimension": "v_dq_profile_scoring_latest_by_dimension",
    }.get(group_by, "v_dq_profile_scoring_latest_by_column")
    test_score_view = {
        "dq_dimension": "v_dq_test_scoring_latest_by_dimension",
    }.get(group_by, "v_dq_test_scoring_latest_by_column")
    filters = [
        "AND critical_data_element = true" if score_type == "cde_score" else "",
    ]
    join_condition = " AND ".join([f"test_records.{column} = profiling_records.{column}" for column in columns])

    query = f"""
        SET SEARCH_PATH TO {schema};
        WITH
        profiling_records AS (
            SELECT
                table_groups_id,
                {', '.join(columns)},
                SUM(issue_ct) AS issue_ct,
                SUM(record_ct) AS record_ct,
                SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
            FROM {profiling_score_view}
            WHERE table_groups_id = '{table_group_id}'
                AND NULLIF({group_by}, '') IS NOT NULL
                {" ".join(filters)}
            GROUP BY table_groups_id, {', '.join(columns)}
        ),
        test_records AS (
            SELECT
                table_groups_id,
                {",".join(columns)},
                SUM(issue_ct) AS issue_ct,
                SUM(dq_record_ct) AS record_ct,
                SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
            FROM {test_score_view}
            WHERE table_groups_id = '{table_group_id}'
                AND NULLIF({group_by}, '') IS NOT NULL
                {" ".join(filters)}
            GROUP BY table_groups_id, {', '.join(columns)}
        ),
        table_group AS (
            SELECT 
                table_groups_id,
                SUM(data_point_ct) AS all_records
            FROM data_table_chars
            WHERE table_groups_id = '{table_group_id}'
            GROUP BY table_groups_id
        )
        SELECT
            {', '.join([ f"COALESCE(profiling_records.{column}, test_records.{column}) AS {column}" for column in columns ])},
            100 * COALESCE(profiling_records.record_ct, test_records.record_ct, 0) * (1 - COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) / table_group.all_records AS impact,
            (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
            (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct
        FROM profiling_records
        FULL OUTER JOIN test_records
            ON (test_records.table_groups_id = profiling_records.table_groups_id AND {join_condition})
        INNER JOIN table_group
            ON (table_group.table_groups_id = profiling_records.table_groups_id
            OR table_group.table_groups_id = test_records.table_groups_id)
        ORDER BY impact DESC
        LIMIT 100;
    """
    results = db.retrieve_data(query)

    return [row.to_dict() for _, row in results.iterrows()]


@st.cache_data(show_spinner="Loading data ...")
def get_score_card_issues(
    _project_code: str,
    table_group_id: str,
    score_type: Literal["score", "cde_score"],
    group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
    value: str,
):
    schema: str = st.session_state["dbschema"]
    value_ = value.split(".")[1] if group_by == "column_name" else value
    profiling_score_view = {
        "dq_dimension": "v_dq_profile_scoring_latest_by_dimension",
    }.get(group_by, "v_dq_profile_scoring_latest_by_column")
    test_score_view = {
        "dq_dimension": "v_dq_test_scoring_latest_by_dimension",
    }.get(group_by, "v_dq_test_scoring_latest_by_column")
    filters = [
        "AND critical_data_element = true" if score_type == "cde_score" else "",
        f"AND table_name = '{value.split('.')[0]}'" if group_by == "column_name" else "",
    ]

    query = f"""
    SET SEARCH_PATH TO {schema};
    WITH
    score_profiling_runs AS (
        SELECT
            profile_run_id,
            table_name,
            column_name
        FROM {profiling_score_view}
        WHERE table_groups_id = '{table_group_id}'
            {' '.join(filters)}
            AND {group_by} = '{value_}'
    ),
    anomalies AS (
        SELECT
            results.table_name AS table,
            results.column_name AS column,
            types.anomaly_name AS type,
            types.issue_likelihood AS status,
            results.detail,
            EXTRACT(EPOCH FROM runs.profiling_starttime) AS time,
            '' AS name,
            'Hygiene Issue' AS category,
            runs.id::text AS run_id,
            'profile' AS issue_type
        FROM profile_anomaly_results AS results
        INNER JOIN profile_anomaly_types AS types
            ON (types.id = results.anomaly_id)
        INNER JOIN profiling_runs AS runs
            ON (runs.id = results.profile_run_id)
        INNER JOIN score_profiling_runs
            ON (score_profiling_runs.profile_run_id = runs.id
            AND score_profiling_runs.table_name = results.table_name
            AND score_profiling_runs.column_name = results.column_name)
        {f"WHERE {group_by} = '{value_}'" if group_by == "dq_dimension" else ""}
    ),
    score_test_runs AS (
        SELECT
            test_run_id,
            table_name,
            column_name
        FROM {test_score_view}
        WHERE table_groups_id = '{table_group_id}'
            {' '.join(filters)}
            AND {group_by} = '{value_}'
    ),
    tests AS (
        SELECT
            test_results.table_name AS table,
            test_results.column_names AS column,
            test_types.test_name_short AS type,
            result_status AS status,
            result_message AS detail,
            EXTRACT(EPOCH FROM test_time) AS time,
            test_suites.test_suite AS name,
            test_types.dq_dimension AS category,
            test_results.test_run_id::text AS run_id,
            'test' AS issue_type
        FROM test_results
        INNER JOIN score_test_runs
            ON (score_test_runs.test_run_id = test_results.test_run_id
            AND score_test_runs.table_name = test_results.table_name
            AND score_test_runs.column_name = test_results.column_names)
        INNER JOIN test_suites
            ON (test_suites.id = test_results.test_suite_id)
        INNER JOIN test_types
            ON (test_types.test_type = test_results.test_type)
        WHERE result_status IN ('Failed', 'Warning')
        {f"AND {group_by} = '{value_}'" if group_by == "dq_dimension" else ""}
    )
    SELECT * FROM (
        SELECT * FROM anomalies
        UNION ALL
        SELECT * FROM tests
    ) issues
    ORDER BY
        CASE status
            WHEN 'Definite' THEN 1
            WHEN 'Failed' THEN 2
            WHEN 'Likely' THEN 3
            WHEN 'Possible' THEN 4
            WHEN 'Warning' THEN 5
            ELSE 6
        END;
    """
    results = db.retrieve_data(query)
    return [row.to_dict() for _, row in results.iterrows()]


class ScoreCard(TypedDict):
    project_code: str
    table_group: str
    score: float
    cde_score: float
    dimensions: list["DimensionScore"]


class DimensionScore(TypedDict):
    label: str
    score: float


_TABLE_GROUP_SCORES_QUERY = """
    WITH
    profiling_cols AS (
        SELECT
            table_groups_id,
            table_groups_name,
            SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score,
            SUM(CASE critical_data_element WHEN true THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE critical_data_element WHEN true THEN record_ct ELSE 0 END), 0) AS cde_score
        FROM v_dq_profile_scoring_latest_by_column
        GROUP BY table_groups_id, table_groups_name
    ),
    profiling_dims AS (
        SELECT
            table_groups_id,
            SUM(CASE dq_dimension WHEN 'Accuracy' THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Accuracy' THEN record_ct ELSE 0 END), 0) AS accuracy_score,
            SUM(CASE dq_dimension WHEN 'Completeness' THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Completeness' THEN record_ct ELSE 0 END), 0) AS completeness_score,
            SUM(CASE dq_dimension WHEN 'Consistency' THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Consistency' THEN record_ct ELSE 0 END), 0) AS consistency_score,
            SUM(CASE dq_dimension WHEN 'Timeliness' THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Timeliness' THEN record_ct ELSE 0 END), 0) AS timeliness_score,
            SUM(CASE dq_dimension WHEN 'Uniqueness' THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Uniqueness' THEN record_ct ELSE 0 END), 0) AS uniqueness_score,
            SUM(CASE dq_dimension WHEN 'Validity' THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Validity' THEN record_ct ELSE 0 END), 0) AS validity_score
        FROM v_dq_profile_scoring_latest_by_dimension
        GROUP BY table_groups_id
    ),
    test_cols AS (
        SELECT
            table_groups_id,
            table_groups_name,
            SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score,
            SUM(CASE critical_data_element WHEN true THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE critical_data_element WHEN true THEN dq_record_ct ELSE 0 END), 0) AS cde_score
        FROM v_dq_test_scoring_latest_by_column
        GROUP BY table_groups_id, table_groups_name
    ),
    test_dims AS (
        SELECT
            table_groups_id,
            SUM(CASE dq_dimension WHEN 'Accuracy' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Accuracy' THEN dq_record_ct ELSE 0 END), 0) AS accuracy_score,
            SUM(CASE dq_dimension WHEN 'Completeness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Completeness' THEN dq_record_ct ELSE 0 END), 0) AS completeness_score,
            SUM(CASE dq_dimension WHEN 'Consistency' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Consistency' THEN dq_record_ct ELSE 0 END), 0) AS consistency_score,
            SUM(CASE dq_dimension WHEN 'Timeliness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Timeliness' THEN dq_record_ct ELSE 0 END), 0) AS timeliness_score,
            SUM(CASE dq_dimension WHEN 'Uniqueness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Uniqueness' THEN dq_record_ct ELSE 0 END), 0) AS uniqueness_score,
            SUM(CASE dq_dimension WHEN 'Validity' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE dq_dimension WHEN 'Validity' THEN dq_record_ct ELSE 0 END), 0) AS validity_score
        FROM v_dq_test_scoring_latest_by_dimension
        GROUP BY table_groups_id
    )
    SELECT
        COALESCE(profiling_cols.table_groups_id, test_cols.table_groups_id) AS id,
        COALESCE(profiling_cols.table_groups_name, test_cols.table_groups_name) AS name,
        (COALESCE(profiling_cols.score, 1) * COALESCE(test_cols.score, 1)) AS score,
        (COALESCE(profiling_cols.cde_score, 1) * COALESCE(test_cols.cde_score, 1)) AS cde_score,
        (COALESCE(profiling_dims.accuracy_score, 1) * COALESCE(test_dims.accuracy_score, 1)) AS accuracy_score,
        (COALESCE(profiling_dims.completeness_score, 1) * COALESCE(test_dims.completeness_score, 1)) AS completeness_score,
        (COALESCE(profiling_dims.consistency_score, 1) * COALESCE(test_dims.consistency_score, 1)) AS consistency_score,
        (COALESCE(profiling_dims.timeliness_score, 1) * COALESCE(test_dims.timeliness_score, 1)) AS timeliness_score,
        (COALESCE(profiling_dims.uniqueness_score, 1) * COALESCE(test_dims.uniqueness_score, 1)) AS uniqueness_score,
        (COALESCE(profiling_dims.validity_score, 1) * COALESCE(test_dims.validity_score, 1)) AS validity_score
    FROM profiling_cols
    INNER JOIN profiling_dims
        ON (profiling_dims.table_groups_id = profiling_cols.table_groups_id)
    FULL OUTER JOIN test_cols
        ON (test_cols.table_groups_id = profiling_cols.table_groups_id)
    FULL OUTER JOIN test_dims
        ON (test_dims.table_groups_id = test_cols.table_groups_id)
"""
