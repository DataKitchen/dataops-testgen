WITH filtered_defs AS (
  -- Filter definitions first to minimize join surface area
  SELECT id,
    test_suite_id,
    table_groups_id,
    schema_name,
    table_name,
    column_name,
    test_type
  FROM test_definitions
  WHERE test_suite_id = :TEST_SUITE_ID
    AND test_active = 'Y'
    AND history_calculation = 'PREDICT'
)
SELECT r.test_definition_id,
  d.test_type,
  r.test_time,
  CASE
    WHEN r.result_signal ~ '^-?[0-9]*\.?[0-9]+$' THEN r.result_signal::NUMERIC
    ELSE NULL
  END AS result_signal,
  dtc.functional_table_type
FROM test_results r
JOIN filtered_defs d ON d.id = r.test_definition_id
LEFT JOIN data_table_chars dtc
  ON dtc.table_groups_id = d.table_groups_id
  AND dtc.schema_name = d.schema_name
  AND dtc.table_name = d.table_name
WHERE r.test_suite_id = :TEST_SUITE_ID
ORDER BY r.test_time;
