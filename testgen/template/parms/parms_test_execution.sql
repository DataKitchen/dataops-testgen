SELECT ts.project_code,
       ts.connection_id::VARCHAR,
       ts.id::VARCHAR as test_suite_id,
       tg.table_group_schema,
       cc.sql_flavor,
       cc.project_host,
       cc.project_port,
       cc.project_user,
       cc.project_db,
       cc.project_qc_schema,
       cc.connect_by_key,
       cc.private_key,
       cc.private_key_passphrase,
       cc.max_threads,
       cc.max_query_chars,
       cc.url,
       cc.connect_by_url
  FROM test_suites ts
  JOIN connections cc ON (ts.connection_id = cc.connection_id)
  JOIN table_groups tg ON (ts.table_groups_id = tg.id)
 WHERE ts.project_code = '{PROJECT_CODE}'
   AND ts.test_suite = '{TEST_SUITE}';
