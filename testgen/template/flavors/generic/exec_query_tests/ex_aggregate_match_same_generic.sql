SELECT '{PROJECT_CODE}'   as project_code,
       '{TEST_TYPE}'   as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE}'  as test_suite,
       '{TEST_RUN_ID}' as test_run_id,
       '{RUN_DATE}'    as test_time,
       '{START_TIME}'  as starttime,
       CURRENT_TIMESTAMP       as endtime,
       '{SCHEMA_NAME}' as schema_name,
       '{TABLE_NAME}'  as table_name,
       CASE WHEN '{COLUMN_NAME}' = '' OR '{COLUMN_NAME}' IS NULL THEN 'N/A' ELSE '{COLUMN_NAME}' END as column_names,
    '{SKIP_ERRORS}' as threshold_value,
    {SKIP_ERRORS} as skip_errors,
    'match_schema_name = {MATCH_SCHEMA_NAME}, match_table_name = {MATCH_TABLE_NAME}, match_groupby_names = {MATCH_GROUPBY_NAMES} ,match_column_names = {MATCH_COLUMN_NAMES}, match_subset_condition = {MATCH_SUBSET_CONDITION}, match_having_condition = {MATCH_HAVING_CONDITION}, mode = {MODE}'
       as input_parameters,
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
       '{SUBSET_CONDITION}' as subset_condition,
       NULL as result_query
FROM (
    (SELECT {GROUPBY_NAMES}, {SUM_COLUMNS}
       FROM {SCHEMA_NAME}.{TABLE_NAME}
       WHERE {SUBSET_CONDITION}
       GROUP BY {GROUPBY_NAMES}
       {HAVING_CONDITION}
           EXCEPT
       SELECT {MATCH_GROUPBY_NAMES}, {MATCH_SUM_COLUMNS}
       FROM {MATCH_SCHEMA_NAME}.{MATCH_TABLE_NAME}
       WHERE {MATCH_SUBSET_CONDITION}
       GROUP BY {MATCH_GROUPBY_NAMES}
       {MATCH_HAVING_CONDITION}
	)
      UNION
      (SELECT {MATCH_GROUPBY_NAMES}, {MATCH_SUM_COLUMNS}
       FROM {MATCH_SCHEMA_NAME}.{MATCH_TABLE_NAME}
       WHERE {MATCH_SUBSET_CONDITION}
       GROUP BY {MATCH_GROUPBY_NAMES}
       {MATCH_HAVING_CONDITION}
           EXCEPT
       SELECT {GROUPBY_NAMES}, {SUM_COLUMNS}
       FROM {SCHEMA_NAME}.{TABLE_NAME}
       WHERE {SUBSET_CONDITION}
       GROUP BY {GROUPBY_NAMES}
       {HAVING_CONDITION})
     ) a;
