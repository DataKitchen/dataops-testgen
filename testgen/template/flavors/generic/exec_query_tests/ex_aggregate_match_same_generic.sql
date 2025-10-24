SELECT '{TEST_TYPE}'   as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE_ID}' as test_suite_id,
       '{TEST_RUN_ID}' as test_run_id,
       '{RUN_DATE}'    as test_time,
       '{SCHEMA_NAME}' as schema_name,
       '{TABLE_NAME}'  as table_name,
       '{COLUMN_NAME_NO_QUOTES}' as column_names,
       '{SKIP_ERRORS}' as threshold_value,
       {SKIP_ERRORS} as skip_errors,
       '{INPUT_PARAMETERS}' as input_parameters,
       NULL as result_signal,
       CASE WHEN COUNT (*) > {SKIP_ERRORS} THEN 0 ELSE 1 END as result_code,
       CASE
        WHEN COUNT(*) > 0 THEN
               CONCAT(
                      CONCAT( CAST(COUNT(*) AS {VARCHAR_TYPE}), ' error(s) identified, ' ),
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
       COUNT(*) as result_measure
FROM ( SELECT {GROUPBY_NAMES}, SUM(TOTAL) as total, SUM(MATCH_TOTAL) as MATCH_TOTAL
         FROM
              ( SELECT {GROUPBY_NAMES}, {COLUMN_NAME_NO_QUOTES} as total, NULL as match_total
       FROM {QUOTE}{SCHEMA_NAME}{QUOTE}.{QUOTE}{TABLE_NAME}{QUOTE}
       WHERE {SUBSET_CONDITION}
       GROUP BY {GROUPBY_NAMES}
       {HAVING_CONDITION}
              UNION ALL
                SELECT {MATCH_GROUPBY_NAMES}, NULL as total, {MATCH_COLUMN_NAMES} as match_total
       FROM {QUOTE}{MATCH_SCHEMA_NAME}{QUOTE}.{QUOTE}{MATCH_TABLE_NAME}{QUOTE}
       WHERE {MATCH_SUBSET_CONDITION}
       GROUP BY {MATCH_GROUPBY_NAMES}
       {MATCH_HAVING_CONDITION} ) a
         GROUP BY {GROUPBY_NAMES} ) s
         WHERE total <> match_total
             OR (total IS NOT NULL AND match_total IS NULL)
             OR (total IS NULL AND match_total IS NOT NULL);
