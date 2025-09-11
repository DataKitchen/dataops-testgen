SELECT '{TEST_TYPE}'   as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE_ID}' as test_suite_id,
       '{TEST_RUN_ID}' as test_run_id,
       '{RUN_DATE}'    as test_time,
       '{START_TIME}'  as starttime,
       CURRENT_TIMESTAMP       as endtime,
       '{SCHEMA_NAME}' as schema_name,
       '{TABLE_NAME}'  as table_name,
       '{COLUMN_NAME_NO_QUOTES}' as column_names,
       '{SKIP_ERRORS}' as threshold_value,
       {SKIP_ERRORS} as skip_errors,
       '{INPUT_PARAMETERS}' as input_parameters,
       fingerprint as result_signal,
       /*  Fails if table is the same  */
       CASE WHEN fingerprint = '{BASELINE_VALUE}' THEN 0 ELSE 1 END as result_code,

       CASE
        WHEN fingerprint = '{BASELINE_VALUE}'
          THEN 'No table change detected.'
          ELSE 'Table change detected.'
       END AS result_message,
       CASE
        WHEN fingerprint = '{BASELINE_VALUE}'
          THEN 0
          ELSE 1
       END as result_measure,
       '{SUBSET_DISPLAY}' as subset_condition,
       NULL as result_query
  FROM ( SELECT {CUSTOM_QUERY} as fingerprint
           FROM {SCHEMA_NAME}.{TABLE_NAME} WITH (NOLOCK)
          WHERE {SUBSET_CONDITION}
       ) test;
