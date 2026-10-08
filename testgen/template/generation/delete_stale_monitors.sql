-- Deletes all monitors for dropped tables, including manual and locked ones
DELETE FROM test_definitions td
WHERE td.test_suite_id = :TEST_SUITE_ID ::UUID
  AND td.version_id = :VERSION_ID ::UUID
  -- Filter by test types if specified (NULL = no filter)
  AND (:TEST_TYPES_FILTER IS NULL OR td.test_type = ANY(:TEST_TYPES_FILTER))
  AND EXISTS (
    -- A catalogued table is identified by (table_groups_id, table_name), which the catalog's
    -- unique index enforces, so this reaches exactly one row. Matching on schema as well would
    -- reach none once a table group reads another schema: the catalog stamps a drop date without
    -- touching schema_name, so a table the new schema lacks keeps the one it was last scanned in
    -- while its definitions name the schema the table group now reads.
    SELECT 1 FROM data_table_chars dtc
    WHERE dtc.table_groups_id = td.table_groups_id
      AND dtc.table_name = td.table_name
      AND dtc.drop_date IS NOT NULL
  );
