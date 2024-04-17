SELECT '{PROJECT_CODE}' as project_code, '{TEST_TYPE}' as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE}' as test_suite,
       '{RUN_DATE}' as test_time, '{START_TIME}' as starttime, CURRENT_TIMESTAMP as endtime,
       '{SCHEMA_NAME}' as schema_name, '{TABLE_NAME}' as table_name, '{COLUMN_NAME}' as column_names,
       '{SKIP_ERRORS}' as skip_errors,
       'match_schema_name = {MATCH_SCHEMA_NAME}, match_table_name = {MATCH_TABLE_NAME}, match_column_names = {MATCH_COLUMN_NAMES}, match_subset_condition = {MATCH_SUBSET_CONDITION}, test_mode = {MODE}'
         as input_parameters,
       CASE WHEN COUNT(*) > COALESCE('{SKIP_ERRORS}', 0) THEN 0 ELSE 1 END as result_code,
       CONCAT(
             CONCAT( 'Mismatched values: ', CAST( COALESCE(COUNT(*), 0) AS VARCHAR) ),
             CONCAT( ', Threshold: ',
                     CONCAT( CAST(COALESCE('{SKIP_ERRORS}', 0) AS VARCHAR), '.')
                    )
              )  AS result_message,
       COUNT(*) as result_measure,
       '{TEST_ACTION}' as test_action,
       '{SUBSET_CONDITION}' as subset_condition,
       NULL as result_query,
       '{TEST_DESCRIPTION}' as test_description
  FROM (
         ( SELECT {COLUMN_NAME}
             FROM {SCHEMA_NAME}.{TABLE_NAME}
             WHERE {SUBSET_CONDITION}
           EXCEPT
           SELECT {MATCH_COLUMN_NAMES}
             FROM {MATCH_SCHEMA_NAME}.{MATCH_TABLE_NAME}
            WHERE {MATCH_SUBSET_CONDITION}
         )
          UNION
         ( SELECT {MATCH_COLUMN_NAMES}
             FROM {MATCH_SCHEMA_NAME}.{MATCH_TABLE_NAME}
             WHERE {MATCH_SUBSET_CONDITION}
           EXCEPT
           SELECT {COLUMN_NAME}
             FROM {SCHEMA_NAME}.{TABLE_NAME}
             WHERE {SUBSET_CONDITION} )
       ) test;
