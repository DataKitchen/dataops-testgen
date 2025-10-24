SELECT '{TEST_TYPE}' AS test_type,
       '{TEST_DEFINITION_ID}' AS test_definition_id,
       '{TEST_SUITE_ID}' AS test_suite_id,
       '{TEST_RUN_ID}' AS test_run_id,
       '{RUN_DATE}' AS test_time,
       '{SCHEMA_NAME}' AS schema_name,
       '{TABLE_NAME}' AS table_name,
       '{COLUMN_NAME_NO_QUOTES}' AS column_names,
       '{SKIP_ERRORS}' AS threshold_value,
       {SKIP_ERRORS} AS skip_errors,
       '{INPUT_PARAMETERS}' AS input_parameters,
       fingerprint AS result_signal,
       /* Fails if table is the same */
       CASE WHEN fingerprint = '{BASELINE_VALUE}' THEN 0 ELSE 1 END AS result_code,
       CASE
         WHEN fingerprint = '{BASELINE_VALUE}' THEN 'No table change detected.'
         ELSE 'Table change detected.'
       END AS result_message,
       CASE
         WHEN fingerprint = '{BASELINE_VALUE}' THEN 0 ELSE 1
       END AS result_measure
FROM (
  SELECT {CUSTOM_QUERY} AS fingerprint
  FROM `{SCHEMA_NAME}.{TABLE_NAME}`
  WHERE {SUBSET_CONDITION}
) test;
