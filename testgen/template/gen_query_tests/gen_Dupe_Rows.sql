WITH latest_run AS (
  -- Latest complete profiling run before as-of-date
  SELECT MAX(run_date) AS last_run_date
    FROM profile_results
  WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
    AND run_date::DATE <= :AS_OF_DATE ::DATE
),
selected_tables AS (
  SELECT profile_run_id, schema_name, table_name,
    STRING_AGG(:QUOTE || column_name || :QUOTE, ', ' ORDER BY position) AS groupby_names
  FROM profile_results p
  INNER JOIN latest_run lr ON p.run_date = lr.last_run_date
  WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
  GROUP BY profile_run_id, schema_name, table_name
)
INSERT INTO test_definitions (
  table_groups_id, test_suite_id, test_type,
  schema_name, table_name,
  test_active, last_auto_gen_date, profiling_as_of_date, profile_run_id,
  groupby_names, skip_errors
)
SELECT
  :TABLE_GROUPS_ID ::UUID AS table_groups_id,
  :TEST_SUITE_ID ::UUID   AS test_suite_id,
  'Dupe_Rows'             AS test_type,
  s.schema_name,
  s.table_name,
  'Y'                     AS test_active,
  :RUN_DATE ::TIMESTAMP   AS last_auto_gen_date,
  :AS_OF_DATE ::TIMESTAMP AS profiling_as_of_date,
  s.profile_run_id,
  s.groupby_names,
  0                       AS skip_errors
FROM selected_tables s
  -- Only insert if test type is active
WHERE EXISTS (SELECT 1 FROM test_types WHERE test_type = 'Dupe_Rows' AND active = 'Y')
  -- Only insert if test type is included in generation set
  AND EXISTS (SELECT 1 FROM generation_sets WHERE test_type = 'Dupe_Rows' AND generation_set = :GENERATION_SET)

-- Match "uix_td_autogen_table" unique index exactly
ON CONFLICT (test_suite_id, test_type, schema_name, table_name) 
WHERE last_auto_gen_date IS NOT NULL 
  AND table_name IS NOT NULL 
  AND column_name IS NULL

-- Update tests if they already exist
DO UPDATE SET
  test_active         = EXCLUDED.test_active,
  last_auto_gen_date  = EXCLUDED.last_auto_gen_date,
  groupby_names       = EXCLUDED.groupby_names,
  skip_errors         = EXCLUDED.skip_errors
-- Ignore locked tests
WHERE test_definitions.lock_refresh = 'N';
