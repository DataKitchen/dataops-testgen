WITH stats AS (
  SELECT
    d.id AS test_definition_id,
    COALESCE(
      MIN(r.result_signal) FILTER (WHERE d.history_calculation = 'Value'),
      MIN(r.result_signal::NUMERIC) FILTER (WHERE d.history_calculation = 'Minimum')::VARCHAR,
      MAX(r.result_signal::NUMERIC) FILTER (WHERE d.history_calculation = 'Maximum')::VARCHAR,
      SUM(r.result_signal::NUMERIC) FILTER (WHERE d.history_calculation = 'Sum')::VARCHAR,
      AVG(r.result_signal::NUMERIC) FILTER (WHERE d.history_calculation = 'Average')::VARCHAR
    ) as calc_signal
  FROM test_definitions d
  INNER JOIN LATERAL (
    SELECT result_signal
    FROM test_results tr
    WHERE tr.test_definition_id = d.id
    ORDER BY tr.test_time DESC
    LIMIT CASE WHEN d.history_calculation = 'Value' THEN 1 ELSE d.history_lookback END
  ) AS r ON TRUE
  WHERE d.test_suite_id    = :TEST_SUITE_ID
    AND d.test_active      = 'Y'
    AND d.history_lookback IS NOT NULL
  GROUP BY d.id, d.history_calculation, d.history_lookback
)
UPDATE test_definitions t
SET baseline_value = s.calc_signal
FROM stats s
WHERE t.id = s.test_definition_id;