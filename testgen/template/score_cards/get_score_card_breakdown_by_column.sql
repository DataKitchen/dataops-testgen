WITH
profiling_records AS (
    SELECT
        project_code,
        {columns},
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE {filters}
    GROUP BY project_code, {columns}
),
test_records AS (
    SELECT
        project_code,
        {columns},
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE {filters}
    GROUP BY project_code, {columns}
),
parent AS (
    SELECT 
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    WHERE {records_count_filters}
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code)
)
SELECT
    {non_null_columns},
    100 * (
        COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
        + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
    ) AS impact,
    (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
    (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct
FROM profiling_records
FULL OUTER JOIN test_records
    ON (test_records.project_code = profiling_records.project_code AND {join_condition})
INNER JOIN parent
    ON (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
ORDER BY impact DESC
LIMIT 100