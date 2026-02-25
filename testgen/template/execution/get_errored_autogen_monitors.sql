WITH prev_run AS (
    SELECT id
    FROM test_runs
    WHERE test_suite_id = :TEST_SUITE_ID ::UUID
        AND id <> :TEST_RUN_ID ::UUID
        AND status = 'Complete'
    ORDER BY test_starttime DESC
    LIMIT 1
)
SELECT DISTINCT tr.test_type, tr.table_name
FROM test_results tr
INNER JOIN prev_run ON tr.test_run_id = prev_run.id
WHERE tr.result_status = 'Error'
    AND tr.auto_gen IS TRUE
    AND tr.test_type IN ('Freshness_Trend', 'Volume_Trend')
