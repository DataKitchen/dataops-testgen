WITH latest_run AS (
  -- Latest complete profiling run before as-of-date
  SELECT MAX(run_date) AS last_run_date
    FROM profile_results
  WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
    AND run_date::DATE <= :AS_OF_DATE ::DATE
),
latest_results AS (
  -- Column results for latest run
  SELECT p.*
  FROM profile_results p
  INNER JOIN latest_run lr ON p.run_date = lr.last_run_date
  WHERE p.table_groups_id = :TABLE_GROUPS_ID ::UUID
),
all_runs AS (
  SELECT DISTINCT table_groups_id, run_date,
    DENSE_RANK() OVER (PARTITION BY table_groups_id ORDER BY run_date DESC) AS run_rank
  FROM profile_results
  WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
    AND run_date::DATE <= :AS_OF_DATE ::DATE
),
recent_runs AS (
  SELECT table_groups_id, run_date, run_rank
  FROM all_runs
  WHERE run_rank <= 5
),
selected_columns AS (
  -- Select columns based on recent profiling results
  SELECT p.schema_name, p.table_name, p.column_name,
    SUM(CASE WHEN p.distinct_value_ct = 1 THEN 0 ELSE 1 END) AS always_one_val,
    COUNT(
      DISTINCT CASE
        WHEN p.general_type = 'A' THEN p.min_text
        WHEN p.general_type = 'N' THEN p.min_value::VARCHAR
        WHEN p.general_type IN ('D','T') THEN p.min_date::VARCHAR
        WHEN p.general_type = 'B' AND p.boolean_true_ct = p.value_ct THEN 'TRUE'
        WHEN p.general_type = 'B' AND p.boolean_true_ct = 0 AND p.distinct_value_ct = 1 THEN 'FALSE'
      END
    ) AS agg_distinct_val_ct
  FROM recent_runs rr
  INNER JOIN profile_results p ON (
    rr.table_groups_id = p.table_groups_id
    AND rr.run_date = p.run_date
  )
  WHERE p.table_groups_id = :TABLE_GROUPS_ID ::UUID
    -- No dates as constants
    AND NOT (p.general_type = 'D' AND rr.run_rank = 1)
  GROUP BY p.schema_name, p.table_name, p.column_name
  HAVING SUM(CASE WHEN p.distinct_value_ct = 1 THEN 0 ELSE 1 END) = 0
    AND SUM(CASE WHEN p.max_length < 100 THEN 0 ELSE 1 END) = 0
    AND COUNT(
      DISTINCT CASE
        WHEN p.general_type = 'A' THEN p.min_text
        WHEN p.general_type = 'N' THEN p.min_value::VARCHAR
        WHEN p.general_type IN ('D','T') THEN p.min_date::VARCHAR
        WHEN p.general_type = 'B' AND p.boolean_true_ct = p.value_ct THEN 'TRUE'
        WHEN p.general_type = 'B' AND p.boolean_true_ct = 0 AND p.distinct_value_ct = 1 THEN 'FALSE'
      END
    ) = 1
    -- Only constant if more than one profiling result
    AND COUNT(*) > 1
)
INSERT INTO test_definitions (
  table_groups_id, test_suite_id, test_type,
  schema_name, table_name, column_name,
  test_active, last_auto_gen_date, profiling_as_of_date, profile_run_id,
  baseline_value, threshold_value, skip_errors
)
SELECT 
  :TABLE_GROUPS_ID ::UUID AS table_groups_id,
  :TEST_SUITE_ID ::UUID   AS test_suite_id,
  'Constant'              AS test_type,
  r.schema_name,
  r.table_name,
  r.column_name,
  'Y'                     AS test_active, 
  :RUN_DATE ::TIMESTAMP   AS last_auto_gen_date, 
  :AS_OF_DATE ::TIMESTAMP AS profiling_as_of_date,
  r.profile_run_id,
  CASE WHEN r.general_type = 'A' THEN fn_quote_literal_escape(r.min_text, :SQL_FLAVOR)::VARCHAR
    WHEN r.general_type = 'D' THEN fn_quote_literal_escape(r.min_date::VARCHAR, :SQL_FLAVOR)::VARCHAR
    WHEN r.general_type = 'N' THEN r.min_value::VARCHAR
    WHEN r.general_type = 'B' AND r.boolean_true_ct = 0 THEN 'FALSE'::VARCHAR
    WHEN r.general_type = 'B' AND r.boolean_true_ct > 0 THEN 'TRUE'::VARCHAR
    ELSE ''
  END AS baseline_value,
  '0' AS threshold_value,
  0   AS skip_errors
FROM latest_results r
-- Only insert tests for selected columns
INNER JOIN selected_columns c ON (
  r.schema_name = c.schema_name
  AND r.table_name = c.table_name
  AND r.column_name = c.column_name
)
  -- Only insert if test type is active
WHERE EXISTS (SELECT 1 FROM test_types WHERE test_type = 'Constant' AND active = 'Y')
  -- Only insert if test type is included in generation set
  AND EXISTS (SELECT 1 FROM generation_sets WHERE test_type = 'Constant' AND generation_set = :GENERATION_SET)

-- Match "uix_td_autogen_column" unique index exactly
ON CONFLICT (test_suite_id, test_type, schema_name, table_name, column_name)
WHERE last_auto_gen_date IS NOT NULL 
  AND table_name IS NOT NULL 
  AND column_name IS NOT NULL

-- Update tests if they already exist
DO UPDATE SET
  test_active          = EXCLUDED.test_active,
  last_auto_gen_date   = EXCLUDED.last_auto_gen_date,
  profiling_as_of_date = EXCLUDED.profiling_as_of_date,
  profile_run_id       = EXCLUDED.profile_run_id,
  baseline_value       = EXCLUDED.baseline_value,
  threshold_value      = EXCLUDED.threshold_value,
  skip_errors          = EXCLUDED.skip_errors
-- Ignore locked tests
WHERE test_definitions.lock_refresh = 'N';
