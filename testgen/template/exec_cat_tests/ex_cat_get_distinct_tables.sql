SELECT DISTINCT schema_name,
                table_name,
                project_qc_schema as replace_qc_schema
           FROM test_definitions td
     INNER JOIN test_types tt
             ON td.test_type = tt.test_type
     INNER JOIN table_groups tg
             ON (td.table_groups_id = tg.id)
     INNER JOIN connections c
             ON (tg.connection_id = c.connection_id)
          WHERE td.test_suite_id = '{TEST_SUITE_ID}'
            AND tt.run_type = 'CAT';
