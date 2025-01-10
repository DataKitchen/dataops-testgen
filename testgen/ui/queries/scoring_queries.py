from typing import Literal, TypedDict

import testgen.ui.services.database_service as db


def get_table_groups_score_cards(
    project_code: str,
    sorted_by: Literal["name", "score"] = "name",
    filter_term: str | None = None
) -> list["ScoreCard"]:
    query = f"""
    {_TABLE_GROUP_SCORES_QUERY}
    {f"WHERE name ILIKE '%%{filter_term}%%'  " if filter_term else ''}
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
    query = f"""
    {_TABLE_GROUP_SCORES_QUERY}
    WHERE profiling_records.table_groups_id = '{table_group_id}';
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


def get_score_card_breakdown(
    _project_code: str,
    table_group_id: str,
    score_type: Literal["score", "cde_score"],
    group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
) -> list[dict]:
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
                {
                    ",".join([
                        'column_names AS column_name' if column == 'column_name' else column for column in columns
                    ])
                },
                SUM(issue_ct) AS issue_ct,
                SUM(dq_record_ct) AS record_ct,
                SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
            FROM {test_score_view}
            WHERE table_groups_id = '{table_group_id}'
                AND NULLIF({'column_names' if group_by == 'column_name' else group_by}, '') IS NOT NULL
                {" ".join(filters)}
            GROUP BY table_groups_id, {', '.join(columns)}
        ),
        table_group AS (
            SELECT
                profiling.table_groups_id,
                SUM(profiling.record_ct) + SUM(test.dq_record_ct) AS all_records
            FROM {profiling_score_view} AS profiling
            INNER JOIN {test_score_view} AS test
                ON (test.table_groups_id = profiling.table_groups_id)
            WHERE profiling.table_groups_id = '{table_group_id}'
            GROUP BY profiling.table_groups_id
        )
        SELECT
            {', '.join([ 'profiling_records.' + column for column in columns    ])},
            ROUND(100 * (profiling_records.record_ct + test_records.record_ct) / table_group.all_records, 2) AS impact,
            (profiling_records.score * test_records.score) AS score,
            (profiling_records.issue_ct + test_records.issue_ct) AS issue_ct
        FROM profiling_records
        INNER JOIN test_records
            ON (test_records.table_groups_id = profiling_records.table_groups_id AND {join_condition})
        INNER JOIN table_group
            ON (table_group.table_groups_id = test_records.table_groups_id)
        ORDER BY impact DESC;
    """
    results = db.retrieve_data(query)

    return [row.to_dict() for _, row in results.iterrows()]


def get_score_card_issues(
    _project_code: str,
    table_group_id: str,
    score_type: Literal["score", "cde_score"],
    group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
    value: str,
):
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
    WITH
    score_profiling_runs AS (
        SELECT
            profile_run_id
        FROM {profiling_score_view}
        WHERE table_groups_id = '{table_group_id}'
            {' '.join(filters)}
            AND {group_by} = '{value_}'
    ),
    anomalies AS (
        SELECT
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
            ON (score_profiling_runs.profile_run_id = runs.id)
    ),
    score_test_runs AS (
        SELECT
            test_run_id
        FROM {test_score_view}
        WHERE table_groups_id = '{table_group_id}'
            {' '.join(filters)}
            AND {'column_names' if group_by == 'column_name' else group_by} = '{value_}'
    ),
    tests AS (
        SELECT
            test_results.test_type AS type,
            result_status AS status,
            result_message AS detail,
            EXTRACT(EPOCH FROM test_time) AS time,
            test_suites.test_suite AS name,
            test_types.dq_dimension AS category,
            test_results.test_run_id::text AS run_id,
            'test' AS issue_type
        FROM test_results
        INNER JOIN score_test_runs
            ON (score_test_runs.test_run_id = test_results.test_run_id)
        INNER JOIN test_suites
            ON (test_suites.id = test_results.test_suite_id)
        INNER JOIN test_types
            ON (test_types.test_type = test_results.test_type)
        WHERE result_status IN ('Failed', 'Warning')
    )
    SELECT * FROM anomalies
    UNION ALL
    SELECT * FROM tests;
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
    profiling_records AS (
        SELECT
            table_groups_id,
            table_groups_name,
            SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score,
            SUM(CASE critical_data_element WHEN true THEN (good_data_pct * record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE critical_data_element WHEN true THEN record_ct ELSE 0 END), 0) AS cde_score,
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
        GROUP BY table_groups_id, table_groups_name
    ),
    test_records AS (
        SELECT
            table_groups_id,
            table_groups_name,
            SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score,
            SUM(CASE critical_data_element WHEN true THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE critical_data_element WHEN true THEN dq_record_ct ELSE 0 END), 0) AS cde_score,
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
        GROUP BY table_groups_id, table_groups_name
    )
    SELECT
        profiling_records.table_groups_id AS id,
        profiling_records.table_groups_name AS name,
        (profiling_records.score * test_records.score) AS score,
        (profiling_records.cde_score * test_records.cde_score) AS cde_score,
        (profiling_records.accuracy_score * test_records.accuracy_score) AS accuracy_score,
        (profiling_records.completeness_score * test_records.completeness_score) AS completeness_score,
        (profiling_records.consistency_score * test_records.consistency_score) AS consistency_score,
        (profiling_records.timeliness_score * test_records.timeliness_score) AS timeliness_score,
        (profiling_records.uniqueness_score * test_records.uniqueness_score) AS uniqueness_score,
        (profiling_records.validity_score * test_records.validity_score) AS validity_score
    FROM profiling_records
    INNER JOIN test_records
        ON (test_records.table_groups_id = profiling_records.table_groups_id)
"""
