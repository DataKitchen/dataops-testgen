SELECT DISTINCT schema_name || '.' || table_name || '.' || column_name AS columns
  FROM ( SELECT cat_test_id,
                project_code,
                test_suite,
                schema_name,
                table_name,
                UNNEST(STRING_TO_ARRAY(all_columns, '~|~')) AS column_name
           FROM ( SELECT cat_test_id,
                         project_code,
                         test_suite,
                         schema_name,
                         table_name,
                         CONCAT_WS('~|~', column_name,
                                   groupby_names,
                                   window_date_column) AS all_columns
                    FROM test_definitions d
                         INNER JOIN test_types t
                                    ON d.test_type = t.test_type
                   WHERE project_code = '{PROJECT_CODE}'
                     AND test_suite = '{TEST_SUITE}'
                     AND t.test_scope = 'column'

                   UNION
                  SELECT cat_test_id,
                         project_code,
                         test_suite,
                         match_schema_name              AS schema_name,
                         match_table_name               AS table_name,
                         CONCAT_WS('~|~',
                                   match_column_names,
                                   match_groupby_names) AS all_columns
                    FROM test_definitions d
                         INNER JOIN test_types t
                                    ON d.test_type = t.test_type
                   WHERE project_code = '{PROJECT_CODE}'
                     AND test_suite = '{TEST_SUITE}'
                     AND t.test_scope = 'column') a ) b;
