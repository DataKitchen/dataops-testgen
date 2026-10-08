-- One test per table the version declares that the table group's catalog holds, dropped or not:
-- a declared table that has left the source keeps its test, so the run reports it
INSERT INTO test_definitions (
  table_groups_id, test_suite_id, version_id, test_type,
  schema_name, table_name,
  test_active, last_auto_gen_date
)
SELECT
  :TABLE_GROUPS_ID ::UUID AS table_groups_id,
  :TEST_SUITE_ID ::UUID   AS test_suite_id,
  :VERSION_ID ::UUID      AS version_id,
  'Schema_Conformance'    AS test_type,
  c.schema_name,
  c.table_name,
  'Y'                     AS test_active,
  :RUN_DATE ::TIMESTAMP   AS last_auto_gen_date
FROM data_table_chars c
WHERE c.table_groups_id = :TABLE_GROUPS_ID ::UUID
  AND EXISTS (
    SELECT 1
    FROM suite_versions sv
      CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(sv.metadata_document -> 'schema') = 'array' THEN sv.metadata_document -> 'schema' ELSE '[]'::JSONB END) AS tbl
    WHERE sv.id = :VERSION_ID ::UUID
      AND tbl ->> 'name' = c.table_name
  )
  AND EXISTS (SELECT 1 FROM test_types WHERE test_type = 'Schema_Conformance' AND active = 'Y')
  {TABLE_FILTER}

-- Match "uix_td_autogen_table" unique index exactly
ON CONFLICT (test_suite_id, version_id, test_type, schema_name, table_name)
WHERE last_auto_gen_date IS NOT NULL
  AND table_name IS NOT NULL
  AND column_name IS NULL

-- The test takes no parameters, so an existing one has nothing to update
DO NOTHING;
