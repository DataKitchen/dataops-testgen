UPDATE test_definitions
SET lower_tolerance = s.lower_tolerance,
  upper_tolerance = s.upper_tolerance,
  threshold_value = COALESCE(s.threshold_value, s.upper_tolerance),
  prediction = s.prediction
FROM stg_test_definition_updates s
WHERE s.test_definition_id = test_definitions.id
  AND s.test_suite_id = :TEST_SUITE_ID
  AND s.run_date = :RUN_DATE;
