  SELECT schema_name || '.' || table_name || '.' || column_name AS columns,
         ARRAY_AGG(cat_test_id) as test_id_array
   FROM (SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(column_name, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = '{TEST_SUITE_ID}'
         AND t.test_scope IN ('column', 'referential')
         UNION
         SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(groupby_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = '{TEST_SUITE_ID}'
         AND t.test_scope IN ('column', 'referential')
         UNION
         SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(window_date_column, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = '{TEST_SUITE_ID}'
         AND t.test_scope IN ('column', 'referential')
         UNION
         SELECT cat_test_id,
                match_schema_name              AS schema_name,
                match_table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(match_column_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = '{TEST_SUITE_ID}'
         AND t.test_scope = 'referential'
         UNION
         SELECT cat_test_id,
                match_schema_name              AS schema_name,
                match_table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(match_groupby_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = '{TEST_SUITE_ID}'
         AND t.test_scope = 'referential' ) cols
   WHERE column_name SIMILAR TO '[A-Za-z0-9_]+'
GROUP BY columns;
