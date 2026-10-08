-- Deletes the tests of tables the version no longer declares, including locked ones
DELETE FROM test_definitions td
WHERE td.test_suite_id = :TEST_SUITE_ID ::UUID
  AND td.version_id = :VERSION_ID ::UUID
  AND td.test_type = 'Schema_Conformance'
  AND NOT EXISTS (
    SELECT 1
    FROM suite_versions sv
      CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(sv.metadata_document -> 'schema') = 'array' THEN sv.metadata_document -> 'schema' ELSE '[]'::JSONB END) AS tbl
    WHERE sv.id = :VERSION_ID ::UUID
      AND tbl ->> 'name' = td.table_name
  );
