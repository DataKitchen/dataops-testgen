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
SELECT test_definition_id,
  test_time,
  CASE
    WHEN result_signal ~ '^-?[0-9]*\.?[0-9]+$' THEN result_signal::NUMERIC
    ELSE NULL
  END AS result_signal
FROM test_results
WHERE test_suite_id = :TEST_SUITE_ID
  AND test_definition_id IN (SELECT id FROM filtered_defs)
ORDER BY test_time;
