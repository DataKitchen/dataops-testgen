SELECT ts.project_code,
       ts.id::VARCHAR as test_suite_id,
       ts.table_groups_id::VARCHAR,
       tg.table_group_schema,
       CASE
         WHEN tg.profiling_table_set ILIKE '''%''' THEN tg.profiling_table_set
         ELSE fn_format_csv_quotes(tg.profiling_table_set)
       END as profiling_table_set,
       tg.profiling_include_mask,
       tg.profiling_exclude_mask
  FROM test_suites ts
  JOIN table_groups tg ON (ts.table_groups_id = tg.id)
 WHERE ts.project_code = :PROJECT_CODE
   AND ts.test_suite = :TEST_SUITE;
