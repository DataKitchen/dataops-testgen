WITH prev_test AS (
    SELECT MAX(test_starttime) AS last_run_time
    FROM test_runs
    WHERE test_suite_id = :TEST_SUITE_ID ::UUID
        -- Ignore current run
        AND id <> :TEST_RUN_ID ::UUID
)
SELECT EXISTS (
    SELECT 1
    FROM data_structure_log dsl
        CROSS JOIN prev_test
    WHERE dsl.table_groups_id = :TABLE_GROUPS_ID ::UUID
        -- Changes since previous test run
        AND dsl.change_date > COALESCE(prev_test.last_run_time, '1900-01-01')
);
