INSERT INTO test_runs (id, project_code, test_suite, test_starttime, process_id)
(SELECT '{TEST_RUN_ID}' :: UUID  as id,
        '{PROJECT_CODE}' as project_code,
        '{TEST_SUITE}' as test_suite,
        '{RUN_DATE}' as test_starttime,
        '{PROCESS_ID}'as process_id);
