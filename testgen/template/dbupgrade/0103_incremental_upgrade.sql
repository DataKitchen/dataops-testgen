SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_types
 ADD COLUMN column_name_prompt TEXT;

ALTER TABLE test_types
 ADD COLUMN column_name_help TEXT;

ALTER TABLE test_results
 ADD COLUMN auto_gen BOOLEAN;

UPDATE test_results
   SET auto_gen = TRUE
  FROM test_results r
INNER JOIN test_definitions d
   ON (r.project_code = d.project_code
  AND  r.test_suite = d.test_suite
  AND  r.table_name = d.table_name
  AND  r.column_names = COALESCE(d.column_name, 'N/A')
  AND  r.test_type = d.test_type)
WHERE d.last_auto_gen_date IS NOT NULL
  AND test_results.id = r.id;