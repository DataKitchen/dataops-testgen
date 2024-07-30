SELECT g.project_code, g.connection_id::varchar(50),
       cc.sql_flavor,
       cc.project_host, cc.project_port,
       cc.project_user, cc.project_db, tg.table_group_schema, cc.project_qc_schema,
       cc.connect_by_key,
       cc.private_key,
       cc.private_key_passphrase,
       cc.max_threads, cc.max_query_chars, cc.url, cc.connect_by_url
  FROM test_suites g
INNER JOIN connections cc    ON (g.connection_id = cc.connection_id)
INNER join table_groups tg   ON (g.table_groups_id = tg.id)
 WHERE g.project_code = '{PROJECT_CODE}'
   AND g.test_suite = '{TEST_SUITE}';
