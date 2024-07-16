SELECT DISTINCT schema_name || '.' || table_name || '.' || column_name AS columns
  FROM ( SELECT cat_test_id,
                project_code,
                test_suite,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(column_name, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE project_code = '{PROJECT_CODE}'
         AND test_suite = '{TEST_SUITE}'
         AND t.test_scope IN ('column', 'referential')
         UNION
         SELECT cat_test_id,
                project_code,
                test_suite,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(groupby_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE project_code = '{PROJECT_CODE}'
         AND test_suite = '{TEST_SUITE}'
         AND t.test_scope IN ('column', 'referential')
         UNION
         SELECT cat_test_id,
                project_code,
                test_suite,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(window_date_column, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE project_code = '{PROJECT_CODE}'
         AND test_suite = '{TEST_SUITE}'
         AND t.test_scope IN ('column', 'referential')
         UNION
         SELECT cat_test_id,
                project_code,
                test_suite,
                match_schema_name              AS schema_name,
                match_table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(match_column_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE project_code = '{PROJECT_CODE}'
         AND test_suite = '{TEST_SUITE}'
         AND t.test_scope = 'referential'
         UNION
         SELECT cat_test_id,
                project_code,
                test_suite,
                match_schema_name              AS schema_name,
                match_table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(match_groupby_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE project_code = '{PROJECT_CODE}'
         AND test_suite = '{TEST_SUITE}'
         AND t.test_scope = 'referential' ) cols;
