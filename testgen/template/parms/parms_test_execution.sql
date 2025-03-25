SELECT ts.project_code,
       ts.connection_id::VARCHAR,
       ts.id::VARCHAR as test_suite_id,
       ts.table_groups_id::VARCHAR,
       tg.table_group_schema,
       CASE
         WHEN tg.profiling_table_set ILIKE '''%''' THEN tg.profiling_table_set
         ELSE fn_format_csv_quotes(tg.profiling_table_set)
       END as profiling_table_set,
       tg.profiling_include_mask,
       tg.profiling_exclude_mask,
       cc.sql_flavor,
       cc.project_host,
       cc.project_port,
       cc.project_user,
       cc.project_db,
       cc.connect_by_key,
       cc.private_key,
       cc.private_key_passphrase,
       cc.max_threads,
       cc.max_query_chars,
       cc.url,
       cc.connect_by_url,
       cc.http_path
  FROM test_suites ts
  JOIN connections cc ON (ts.connection_id = cc.connection_id)
  JOIN table_groups tg ON (ts.table_groups_id = tg.id)
 WHERE ts.project_code = '{PROJECT_CODE}'
   AND ts.test_suite = '{TEST_SUITE}';
