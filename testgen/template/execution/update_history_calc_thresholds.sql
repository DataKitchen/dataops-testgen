WITH filtered_defs AS (
  -- Step 1: Filter definitions first to minimize join surface area
  SELECT id,
    history_calculation,
    history_calculation_upper,
    GREATEST(
      CASE WHEN history_calculation = 'Value' THEN 1 ELSE COALESCE(history_lookback, 1) END,
      CASE WHEN history_calculation_upper = 'Value' THEN 1 ELSE COALESCE(history_lookback, 1) END
    ) AS lookback
  FROM test_definitions
  WHERE test_suite_id = :TEST_SUITE_ID
    AND test_active = 'Y'
    AND history_calculation IS NOT NULL
    AND history_calculation <> 'PREDICT'
    AND history_lookback IS NOT NULL
),
ranked_results AS (
  -- Step 2: Use a Window Function to get the N most recent results
  SELECT r.test_definition_id,
    r.result_signal,
    CASE
      WHEN r.result_signal ~ '^-?[0-9]*\.?[0-9]+$' THEN r.result_signal::NUMERIC
      ELSE NULL
    END AS signal_numeric,
    ROW_NUMBER() OVER (PARTITION BY r.test_definition_id ORDER BY r.test_time DESC) AS rank
  FROM test_results r
  WHERE r.test_definition_id IN (SELECT id FROM filtered_defs)
),
stats AS (
  -- Step 3: Aggregate only the rows within the lookback range
  SELECT d.id AS test_definition_id,
    d.history_calculation,
    d.history_calculation_upper,
    MAX(CASE WHEN rr.rank = 1 THEN rr.result_signal END) AS val,
    MIN(rr.signal_numeric) AS min,
    MAX(rr.signal_numeric) AS max,
    SUM(rr.signal_numeric) AS sum,
    AVG(rr.signal_numeric) AS avg,
    STDDEV(rr.signal_numeric) AS stddev
  FROM filtered_defs d
    JOIN ranked_results rr ON d.id = rr.test_definition_id
  WHERE rr.rank <= d.lookback
  GROUP BY d.id,
    d.history_calculation,
    d.history_calculation_upper
)
UPDATE test_definitions t
SET lower_tolerance = CASE
    WHEN s.history_calculation = 'Value' THEN s.val
    WHEN s.history_calculation = 'Minimum' THEN s.min::VARCHAR
    WHEN s.history_calculation = 'Maximum' THEN s.max::VARCHAR
    WHEN s.history_calculation = 'Sum' THEN s.sum::VARCHAR
    WHEN s.history_calculation = 'Average' THEN s.avg::VARCHAR
    WHEN s.history_calculation LIKE 'EXPR:[%]' THEN
      REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
        SUBSTRING(s.history_calculation, 7, LENGTH(s.history_calculation) - 7),
        '{VALUE}', COALESCE(s.val, 'NULL')),
        '{MINIMUM}', COALESCE(s.min::VARCHAR, 'NULL')),
        '{MAXIMUM}', COALESCE(s.max::VARCHAR, 'NULL')),
        '{SUM}', COALESCE(s.sum::VARCHAR, 'NULL')),
        '{AVERAGE}', COALESCE(s.avg::VARCHAR, 'NULL')),
        '{STANDARD_DEVIATION}', COALESCE(s.stddev::VARCHAR, 'NULL'))
    ELSE NULL
  END,
  upper_tolerance = CASE
    WHEN s.history_calculation_upper = 'Value' THEN s.val
    WHEN s.history_calculation_upper = 'Minimum' THEN s.min::VARCHAR
    WHEN s.history_calculation_upper = 'Maximum' THEN s.max::VARCHAR
    WHEN s.history_calculation_upper = 'Sum' THEN s.sum::VARCHAR
    WHEN s.history_calculation_upper = 'Average' THEN s.avg::VARCHAR
    WHEN s.history_calculation_upper LIKE 'EXPR:[%]' THEN
      REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
        SUBSTRING(s.history_calculation_upper, 7, LENGTH(s.history_calculation_upper) - 7),
        '{VALUE}', COALESCE(s.val, 'NULL')),
        '{MINIMUM}', COALESCE(s.min::VARCHAR, 'NULL')),
        '{MAXIMUM}', COALESCE(s.max::VARCHAR, 'NULL')),
        '{SUM}', COALESCE(s.sum::VARCHAR, 'NULL')),
        '{AVERAGE}', COALESCE(s.avg::VARCHAR, 'NULL')),
        '{STANDARD_DEVIATION}', COALESCE(s.stddev::VARCHAR, 'NULL'))
    ELSE NULL
  END
FROM stats s
WHERE t.id = s.test_definition_id;
