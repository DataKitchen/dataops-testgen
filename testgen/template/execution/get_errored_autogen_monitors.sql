WITH prev_run AS (
    SELECT test_runs.id
    FROM test_runs
    INNER JOIN job_executions ON job_executions.id = test_runs.id
    WHERE test_suite_id = :TEST_SUITE_ID ::UUID
        AND test_runs.id <> :TEST_RUN_ID ::UUID
        AND job_executions.status = 'completed'
    ORDER BY test_starttime DESC
    LIMIT 1
)
SELECT DISTINCT tr.test_type, tr.table_name
FROM test_results tr
INNER JOIN prev_run ON tr.test_run_id = prev_run.id
WHERE tr.result_status = 'Error'
    AND tr.auto_gen IS TRUE
    AND tr.test_type IN ('Freshness_Trend', 'Volume_Trend')
