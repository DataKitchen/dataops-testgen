INSERT INTO test_runs (id, test_suite_id, test_starttime, process_id)
(SELECT '{TEST_RUN_ID}' :: UUID  as id,
        '{TEST_SUITE_ID}' as test_suite_id,
        '{RUN_DATE}' as test_starttime,
        '{PROCESS_ID}'as process_id);
