    SELECT tg.project_code,
           tg.table_group_schema,
           ts.export_to_observability,
           ts.id::VARCHAR as test_suite_id,
           CURRENT_TIMESTAMP AT TIME ZONE 'UTC' -
             CAST(tg.profiling_delay_days AS integer) * INTERVAL '1 day' as profiling_as_of_date
      FROM table_groups tg
 LEFT JOIN test_suites ts ON tg.connection_id = ts.connection_id AND ts.test_suite = :TEST_SUITE
     WHERE tg.id = :TABLE_GROUP_ID;
