/*
Mark Test inactive for Missing columns with update status
*/
with test_columns as
         (SELECT DISTINCT schema_name || '.' || table_name || '.' || column_name AS columns
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
                     AND t.test_scope = 'column') a ) b)
update test_definitions
set test_active            = '{FLAG}',
    test_definition_status = 'Inactivated {RUN_DATE}: Missing Column'
where cat_test_id in (select distinct cat_test_id
                      from test_columns
                      where lower(columns) in
                            ({MISSING_COLUMNS}));


/*
Mark Test inactive for Missing table with update status
*/
with test_columns as
         (select distinct cat_test_id, schema_name || '.' || table_name || '.' || column_name as columns
          from test_definitions
          where project_code = '{PROJECT_CODE}'
            and test_suite = '{TEST_SUITE}'
            and lower(schema_name || '.' || table_name) in ({MISSING_TABLES}))
update test_definitions
set test_active            = '{FLAG}',
    test_definition_status = 'Inactivated {RUN_DATE}: Missing Table'
where cat_test_id in (select distinct cat_test_id
                      from test_columns);
