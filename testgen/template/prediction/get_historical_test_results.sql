WITH filtered_defs AS (
  -- Filter definitions first to minimize join surface area
  SELECT id,
    test_suite_id,
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
  END AS result_signal
FROM test_results r
JOIN filtered_defs d ON d.id = r.test_definition_id
WHERE r.test_suite_id = :TEST_SUITE_ID
ORDER BY r.test_time;
