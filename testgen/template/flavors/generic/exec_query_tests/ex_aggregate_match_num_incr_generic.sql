SELECT '{TEST_TYPE}' as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE_ID}' as test_suite_id,
       '{RUN_DATE}' as test_time, '{START_TIME}' as starttime, CURRENT_TIMESTAMP as endtime,
       '{SCHEMA_NAME}' as schema_name, '{TABLE_NAME}' as table_name, '{GROUPBY_NAMES}' as column_name,
       {SKIP_ERRORS} as skip_errors,
       'match_schema_name = {MATCH_SCHEMA_NAME}, match_table_name = {MATCH_TABLE_NAME}, match_groupby_names = {MATCH_GROUPBY_NAMES} ,match_column_names = {MATCH_COLUMN_NAMES}, match_subset_condition = {MATCH_SUBSET_CONDITION}, match_having_condition = {MATCH_HAVING_CONDITION}, mode = {MODE}'
         as input_parameters,
       CASE WHEN COUNT(*) > COALESCE(skip_errors, 0) THEN 0 ELSE 1 END as result_code,
       CONCAT(
             CONCAT( 'Mismatched measures: ', CAST( COALESCE(COUNT(*), 0) AS VARCHAR) ),
             CONCAT( ', Threshold: ',
                     CONCAT( CAST(COALESCE(skip_errors, 0) AS VARCHAR), '.')
                    )
              )  AS result_message,
       COUNT(*) as result_measure,
       '{TEST_ACTION}' as test_action,
       '{SUBSET_CONDITION}' as subset_condition,
       NULL as result_query,
       '{TEST_DESCRIPTION}' as test_description
FROM (
      SELECT {GROUPBY_NAMES}, {SUM_COLUMNS}
       FROM {SCHEMA_NAME}.{TABLE_NAME}
       WHERE {SUBSET_CONDITION}
       GROUP BY {GROUPBY_NAMES}
       {HAVING_CONDITION}
           UNION ALL
       SELECT {MATCH_GROUPBY_NAMES}, {MATCH_SUM_COLUMNS}
       FROM {MATCH_SCHEMA_NAME}.{MATCH_TABLE_NAME}
       WHERE {MATCH_SUBSET_CONDITION}
       GROUP BY {MATCH_GROUPBY_NAMES}
       {MATCH_HAVING_CONDITION}
          )
     ) a ;
