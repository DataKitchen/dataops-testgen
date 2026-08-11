WITH latest_run AS (
  -- The run the caller resolved. Resolving by date here would read profile_results, whose rows
  -- are committed per column, so a partial run is indistinguishable from a finished one.
  SELECT :PROFILE_RUN_ID ::UUID AS profile_run_id
),
selected_tables AS (
  SELECT p.profile_run_id, schema_name, table_name,
    STRING_AGG(:QUOTE || column_name || :QUOTE, ', ' ORDER BY position) AS groupby_names
  FROM profile_results p
  INNER JOIN latest_run lr ON p.profile_run_id = lr.profile_run_id
  WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
    -- Skip X types - SAP HANA does not allow grouping by LOB types like BLOB, CLOB, NCLOB, TEXT, BINTEXT
    AND general_type <> 'X'
  GROUP BY p.profile_run_id, schema_name, table_name
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
