-- Deletes all monitors for dropped tables, including manual and locked ones
DELETE FROM test_definitions td
WHERE td.test_suite_id = :TEST_SUITE_ID ::UUID
  -- Filter by test types if specified (NULL = no filter)
  AND (:TEST_TYPES_FILTER IS NULL OR td.test_type = ANY(:TEST_TYPES_FILTER))
  AND EXISTS (
    SELECT 1 FROM data_table_chars dtc
    WHERE dtc.table_groups_id = td.table_groups_id
      AND dtc.schema_name = td.schema_name
      AND dtc.table_name = td.table_name
      AND dtc.drop_date IS NOT NULL
  );
