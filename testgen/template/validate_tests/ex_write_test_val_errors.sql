INSERT INTO test_results
   (project_code, test_suite, test_type, test_definition_id,
    schema_name, table_name, column_names, test_time, test_run_id,
    input_parameters, result_code, result_message, result_measure)
SELECT '{PROJECT_CODE}'   as project_code,
       '{TEST_SUITE}'  as test_suite,
       test_type,
       id,
       schema_name,
       table_name,
       column_name,
       '{RUN_DATE}'    as test_time,
       '{TEST_RUN_ID}' as test_run_id,
    NULL as input_parameters,
    0 as result_code,
    -- TODO: show only missing columns referenced in this test
    left('ERROR - TEST COLUMN MISSING: {MISSING_COLUMNS_NO_QUOTES}', 470) AS result_message,
    NULL as result_measure
  FROM test_definitions
 WHERE test_active = '-1'
   AND project_code = '{PROJECT_CODE}'
   AND test_suite = '{TEST_SUITE}';
