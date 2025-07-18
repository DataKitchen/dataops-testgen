WITH score_profiling_runs AS (
    SELECT
        profile_run_id,
        table_name,
        column_name
    FROM v_dq_profile_scoring_latest_by_column
    WHERE {filters} AND {group_by} = :value
),
anomalies AS (
    SELECT results.id::VARCHAR AS id,
        runs.table_groups_id::VARCHAR AS table_group_id,
        results.table_name AS table,
        results.column_name AS column,
        types.anomaly_name AS type,
        types.issue_likelihood AS status,
        results.detail,
        EXTRACT(
            EPOCH
            FROM runs.profiling_starttime
        )::INT AS time,
        '' AS name,
        runs.id::text AS run_id,
        'hygiene' AS issue_type
    FROM profile_anomaly_results AS results
        INNER JOIN profile_anomaly_types AS types ON (types.id = results.anomaly_id)
        INNER JOIN profiling_runs AS runs ON (runs.id = results.profile_run_id)
        INNER JOIN score_profiling_runs ON (
            score_profiling_runs.profile_run_id = runs.id
            AND score_profiling_runs.table_name = results.table_name
            AND score_profiling_runs.column_name = results.column_name
        )
    WHERE COALESCE(results.disposition, 'Confirmed') = 'Confirmed'
),
score_test_runs AS (
    SELECT test_run_id,
        table_name,
        column_name
    FROM v_dq_test_scoring_latest_by_column
    WHERE {filters}
        AND {group_by} = :value
),
tests AS (
    SELECT test_results.id::VARCHAR AS id,
        test_suites.table_groups_id::VARCHAR AS table_group_id,
        test_results.table_name AS table,
        test_results.column_names AS column,
        test_types.test_name_short AS type,
        result_status AS status,
        result_message AS detail,
        EXTRACT(
            EPOCH
            FROM test_time
        )::INT AS time,
        test_suites.test_suite AS name,
        test_results.test_run_id::text AS run_id,
        'test' AS issue_type
    FROM test_results
        INNER JOIN score_test_runs ON (
            score_test_runs.test_run_id = test_results.test_run_id
            AND score_test_runs.table_name = test_results.table_name
            AND score_test_runs.column_name = test_results.column_names
        )
        INNER JOIN test_suites ON (test_suites.id = test_results.test_suite_id)
        INNER JOIN test_types ON (test_types.test_type = test_results.test_type)
    WHERE result_status IN ('Failed', 'Warning')
        AND COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
)
SELECT *
FROM (
    SELECT * FROM anomalies
    UNION ALL
    SELECT * FROM tests
) issues
ORDER BY
    CASE
        status
        WHEN 'Definite' THEN 1
        WHEN 'Failed' THEN 2
        WHEN 'Likely' THEN 3
        WHEN 'Possible' THEN 4
        WHEN 'Warning' THEN 5
        ELSE 6
    END
