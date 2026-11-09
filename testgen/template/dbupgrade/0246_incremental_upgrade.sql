SET SEARCH_PATH TO {SCHEMA_NAME};

-- subset_condition is read only by the test types that declare it as a parameter, but an import could
-- store one on any test. Migrations run before the test types are refreshed, so this clears every
-- condition its test's type does not read yet: a type that reads it after the refresh finds it empty
-- rather than filtering by a condition that had no effect.
UPDATE test_definitions td
   SET subset_condition = NULL
  FROM test_types tt
 WHERE tt.test_type = td.test_type
   AND td.subset_condition IS NOT NULL
   AND NOT 'subset_condition' = ANY (STRING_TO_ARRAY(REPLACE(COALESCE(tt.default_parm_columns, ''), ' ', ''), ','));
