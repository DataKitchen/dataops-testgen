WITH existing_rec
 AS ( SELECT tg.project_code, tg.connection_id,
             cc.sql_flavor,
             cc.project_host,
             cc.project_port,
             cc.project_user,
             cc.project_db,
             tg.table_group_schema,
             s.export_to_observability,
             s.test_suite,
             s.id as test_suite_id,
             cc.url,
             cc.connect_by_url,
             CURRENT_TIMESTAMP AT TIME ZONE
             'UTC' - CAST(tg.profiling_delay_days AS INTEGER) * INTERVAL '1 day' AS profiling_as_of_date
        FROM table_groups tg
             INNER JOIN connections cc
                        ON (tg.connection_id = cc.connection_id)
             INNER JOIN test_suites s
                        ON (tg.id = s.table_groups_id
                          AND '{TEST_SUITE}' = s.test_suite)
       WHERE tg.id = '{TABLE_GROUPS_ID}' ),
new_rec
 AS ( INSERT INTO test_suites
         (project_code, test_suite, connection_id, table_groups_id, test_suite_description,
          component_type, component_key)
      SELECT '{PROJECT_CODE}', '{TEST_SUITE}', {CONNECTION_ID}, '{TABLE_GROUPS_ID}', '{TEST_SUITE} Test Suite',
              'dataset', '{TEST_SUITE}'
      WHERE NOT EXISTS
             (SELECT 1
                FROM test_suites
               WHERE table_groups_id = '{TABLE_GROUPS_ID}'
                 AND test_suite = '{TEST_SUITE}')
      RETURNING id as test_suite_id, test_suite, table_groups_id, export_to_observability )
SELECT project_code, connection_id, sql_flavor,
       project_host, project_port, project_user, project_db, table_group_schema,
       export_to_observability, test_suite, test_suite_id, url, connect_by_url, profiling_as_of_date
  FROM existing_rec
 UNION ALL
SELECT tg.project_code, tg.connection_id,
       cc.sql_flavor,
       cc.project_host,
       cc.project_port,
       cc.project_user,
       cc.project_db,
       tg.table_group_schema,
       s.export_to_observability,
       s.test_suite,
       s.test_suite_id,
       cc.url,
       cc.connect_by_url,
       CURRENT_TIMESTAMP AT TIME ZONE
       'UTC' - CAST(tg.profiling_delay_days AS INTEGER) * INTERVAL '1 day' AS profiling_as_of_date
  FROM new_rec s
INNER JOIN table_groups tg
   ON (s.table_groups_id = tg.id)
INNER JOIN connections cc
   ON (tg.connection_id = cc.connection_id);