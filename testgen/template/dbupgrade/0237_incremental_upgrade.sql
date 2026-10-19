SET SEARCH_PATH TO {SCHEMA_NAME};

-- Custom-scope tests require a Test Focus (column_name): fill blanks with the test type's name.
UPDATE test_definitions td
   SET column_name = tt.test_name_short
  FROM test_types tt
 WHERE td.test_type = tt.test_type
   AND tt.test_scope = 'custom'
   AND NULLIF(TRIM(td.column_name), '') IS NULL;
