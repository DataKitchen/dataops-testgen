SELECT DISTINCT schema_name, table_name,
                project_qc_schema as replace_qc_schema
  FROM test_definitions t
INNER JOIN test_types tt
   ON t.test_type = tt.test_type
INNER JOIN table_groups tg
   ON (t.table_groups_id = tg.id)
INNER JOIN connections c
   ON (tg.connection_id = c.connection_id)
  WHERE t.test_suite = '{TEST_SUITE}'
    AND tt.run_type = 'CAT';
