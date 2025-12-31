DELETE FROM stg_test_definition_updates
WHERE test_suite_id = :TEST_SUITE_ID
    AND run_date = :RUN_DATE;
