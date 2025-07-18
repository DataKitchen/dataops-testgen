  SELECT schema_name || '.' || table_name || '.' || column_name AS columns,
         ARRAY_AGG(cat_test_id) as test_id_array
   FROM (
         -- FROM: column_name - column scope (single column)
         SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = :TEST_SUITE_ID
         AND COALESCE(test_active, 'Y') = 'Y'
         AND t.test_scope = 'column'
         UNION
         -- FROM: column_name - referential scope (could be multiple columns)
         SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(column_name, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = :TEST_SUITE_ID
         AND COALESCE(test_active, 'Y') = 'Y'
         AND t.test_scope = 'referential'
         AND t.test_type NOT LIKE 'Aggregate_%'
         UNION
         -- FROM: groupby_names (should be referential)
         SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(groupby_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = :TEST_SUITE_ID
         AND COALESCE(test_active, 'Y') = 'Y'
         AND t.test_scope IN ('column', 'referential')
         UNION
         -- FROM: window_date_column (referential)
         SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(window_date_column, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = :TEST_SUITE_ID
         AND COALESCE(test_active, 'Y') = 'Y'
         AND t.test_scope = 'referential'
         UNION
         -- FROM: match_column_names (referential)
         SELECT cat_test_id,
                match_schema_name              AS schema_name,
                match_table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(match_column_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = :TEST_SUITE_ID
         AND COALESCE(test_active, 'Y') = 'Y'
         AND t.test_scope = 'referential'
         AND t.test_type NOT LIKE 'Aggregate_%'
         UNION
         -- FROM: match_groupby_names (referential)
         SELECT cat_test_id,
                match_schema_name              AS schema_name,
                match_table_name               AS table_name,
                TRIM(UNNEST(STRING_TO_ARRAY(match_groupby_names, ','))) as column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = :TEST_SUITE_ID
         AND COALESCE(test_active, 'Y') = 'Y'
         AND t.test_scope = 'referential'
         UNION
         SELECT cat_test_id,
                schema_name              AS schema_name,
                table_name               AS table_name,
                '' AS column_name
         FROM test_definitions d
         INNER JOIN test_types t
               ON d.test_type = t.test_type
         WHERE test_suite_id = :TEST_SUITE_ID
         AND COALESCE(test_active, 'Y') = 'Y'
         AND t.test_scope = 'table' ) cols
GROUP BY columns;
