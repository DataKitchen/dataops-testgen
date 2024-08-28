SELECT '{TEST_TYPE}'   as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE_ID}' as test_suite_id,
       '{TEST_RUN_ID}' as test_run_id,
       '{RUN_DATE}'    as test_time,
       '{START_TIME}'  as starttime,
       CURRENT_TIMESTAMP       as endtime,
       '{SCHEMA_NAME}' as schema_name,
       '{TABLE_NAME}'  as table_name,
       CASE
         WHEN '{COLUMN_NAME_NO_QUOTES}' = '' OR '{COLUMN_NAME_NO_QUOTES}' IS NULL THEN 'N/A'
         ELSE '{COLUMN_NAME_NO_QUOTES}'
       END as column_names,
    '{SKIP_ERRORS}' as threshold_value,
    {SKIP_ERRORS} as skip_errors,
    /*  TODO:  'custom_query= {CUSTOM_QUERY_ESCAPED}' as input_parameters,  */
    'Skip_Errors={SKIP_ERRORS}' as input_parameters,
    CASE WHEN COUNT (*) > {SKIP_ERRORS} THEN 0 ELSE 1 END as result_code,
       CASE
        WHEN COUNT(*) > 0 THEN
               CONCAT(
                      CONCAT( CAST(COUNT(*) AS VARCHAR), ' error(s) identified, ' ),
                      CONCAT(
                             CASE
                               WHEN COUNT(*) > {SKIP_ERRORS} THEN 'exceeding limit of '
                                                                        ELSE 'within limit of '
                             END,
                             '{SKIP_ERRORS}.'
                             )
                      )
        ELSE 'No errors found.'
       END AS result_message,
       COUNT(*) as result_measure,
       NULL as subset_condition,
       NULL as result_query
  FROM (
        {CUSTOM_QUERY}
       ) TEST;
