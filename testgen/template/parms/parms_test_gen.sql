    SELECT tg.project_code,
           tg.connection_id,
           cc.sql_flavor,
           cc.project_host,
           cc.project_port,
           cc.project_user,
           cc.connect_by_key,
           cc.private_key,
           cc.private_key_passphrase,
           cc.project_db,
           tg.table_group_schema,
           ts.export_to_observability,
           ts.id::VARCHAR as test_suite_id,
           cc.url,
           cc.connect_by_url,
           CURRENT_TIMESTAMP AT TIME ZONE 'UTC' -
             CAST(tg.profiling_delay_days AS integer) * INTERVAL '1 day' as profiling_as_of_date
      FROM table_groups tg
INNER JOIN connections cc ON tg.connection_id = cc.connection_id
 LEFT JOIN test_suites ts ON tg.connection_id = ts.connection_id AND ts.test_suite = '{TEST_SUITE}'
     WHERE tg.id = '{TABLE_GROUPS_ID}';
