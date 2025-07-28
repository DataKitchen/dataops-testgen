WITH stats AS (
  SELECT
    d.id AS test_definition_id,
    CASE d.history_calculation
      WHEN 'Value'   THEN MIN(r.result_signal::NUMERIC)::VARCHAR
      WHEN 'Minimum' THEN MIN(r.result_signal::NUMERIC)::VARCHAR
      WHEN 'Maximum' THEN MAX(r.result_signal::NUMERIC)::VARCHAR
      WHEN 'Sum'     THEN SUM(r.result_signal::NUMERIC)::VARCHAR
      WHEN 'Average' THEN AVG(r.result_signal::NUMERIC)::VARCHAR
    END AS calc_signal
  FROM test_definitions d
  INNER JOIN LATERAL (
    SELECT result_signal
    FROM test_results tr
    WHERE tr.test_definition_id = d.id
    ORDER BY tr.test_time DESC
    LIMIT d.history_lookback
  ) AS r ON TRUE
  WHERE d.test_suite_id    = '{TEST_SUITE_ID}'
    AND d.test_active      = 'Y'
    AND d.history_lookback IS NOT NULL
  GROUP BY d.id, d.history_calculation, d.history_lookback
)
UPDATE test_definitions t
SET baseline_value = s.calc_signal
FROM stats s
WHERE t.id = s.test_definition_id;

/*
UPDATE test_definitions du
   SET baseline_value = stats.calc_signal
  FROM LATERAL (
     SELECT CASE du.history_calculation
               WHEN 'Average' THEN AVG(r.result_signal)
               WHEN 'Minimum' THEN MIN(r.result_signal)
               WHEN 'Maximum' THEN MAX(r.result_signal)
               WHEN 'Sum'     THEN SUM(r.result_signal)
               WHEN 'Value'   THEN MAX(r.result_signal) -- MAX of 1 value
            END AS calc_signal
       FROM ( SELECT result_signal
                FROM test_results tr
               WHERE tr.test_definition_id = du.id
               ORDER BY tr.test_time DESC
               LIMIT du.history_lookback -- dynamically bound per row
       ) AS r
     ) AS stats
 WHERE du.test_suite_id = '{TEST_SUITE_ID}'
   AND du.test_active = 'Y'
   AND du.history_lookback IS NOT NULL;
*/