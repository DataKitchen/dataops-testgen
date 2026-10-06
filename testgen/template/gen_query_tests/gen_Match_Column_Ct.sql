WITH latest_run AS (
  -- The run the caller resolved. Resolving by date here would read profile_results, whose rows
  -- are committed per column, so a partial run is indistinguishable from a finished one.
  SELECT :PROFILE_RUN_ID ::UUID AS profile_run_id
),
profiled_tables AS (
  SELECT DISTINCT p.profile_run_id, p.table_groups_id, schema_name, table_name
  FROM profile_results p
  INNER JOIN latest_run lr ON p.profile_run_id = lr.profile_run_id
  WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
),
selected_tables AS (
  -- Counted from the column catalog, which includes the columns profiling excludes
  SELECT t.profile_run_id, t.schema_name, t.table_name,
    COUNT(*) AS column_ct
  FROM profiled_tables t
  INNER JOIN data_column_chars c
    ON c.table_groups_id = t.table_groups_id
   AND c.table_name = t.table_name
  WHERE c.drop_date IS NULL
  GROUP BY t.profile_run_id, t.schema_name, t.table_name
)
INSERT INTO test_definitions (
  table_groups_id, test_suite_id, version_id, test_type,
  schema_name, table_name,
  test_active, last_auto_gen_date, profiling_as_of_date, profile_run_id,
  threshold_value, skip_errors
)
SELECT
  :TABLE_GROUPS_ID ::UUID AS table_groups_id,
  :TEST_SUITE_ID ::UUID   AS test_suite_id,
  :VERSION_ID ::UUID      AS version_id,
  'Match_Column_Ct'          AS test_type,
  s.schema_name,
  s.table_name,
  'Y'                     AS test_active,
  :RUN_DATE ::TIMESTAMP   AS last_auto_gen_date,
  :AS_OF_DATE ::TIMESTAMP AS profiling_as_of_date,
  s.profile_run_id,
  s.column_ct             AS threshold_value,
  0                       AS skip_errors
FROM selected_tables s
WHERE EXISTS (SELECT 1 FROM test_types WHERE test_type = 'Match_Column_Ct' AND active = 'Y')
  {TABLE_FILTER}

-- Match "uix_td_autogen_table" unique index exactly
ON CONFLICT (test_suite_id, version_id, test_type, schema_name, table_name)
WHERE last_auto_gen_date IS NOT NULL
  AND table_name IS NOT NULL
  AND column_name IS NULL

DO UPDATE SET
  test_active          = EXCLUDED.test_active,
  last_auto_gen_date   = EXCLUDED.last_auto_gen_date,
  profiling_as_of_date = EXCLUDED.profiling_as_of_date,
  profile_run_id       = EXCLUDED.profile_run_id,
  threshold_value      = EXCLUDED.threshold_value,
  skip_errors          = EXCLUDED.skip_errors
-- Ignore locked tests
WHERE test_definitions.lock_refresh = 'N';
