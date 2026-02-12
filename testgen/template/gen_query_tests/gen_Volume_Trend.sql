-- Insert tests for current tables
INSERT INTO test_definitions (
  table_groups_id, test_suite_id, test_type,
  schema_name, table_name,
  test_active, last_auto_gen_date,
  history_calculation, history_lookback, subset_condition, custom_query
)
SELECT
  :TABLE_GROUPS_ID ::UUID AS table_groups_id,
  :TEST_SUITE_ID ::UUID   AS test_suite_id,
  'Volume_Trend'          AS test_type,
  c.schema_name,
  c.table_name,
  'Y'                     AS test_active,
  :RUN_DATE ::TIMESTAMP   AS last_auto_gen_date,
  'PREDICT'               AS history_calculation,
  NULL                    AS history_lookback,
  NULL                    AS subset_condition,
  'COUNT(CASE WHEN {SUBSET_CONDITION} THEN 1 END)' AS custom_query
FROM data_table_chars c
WHERE c.table_groups_id = :TABLE_GROUPS_ID ::UUID
  -- Ignore dropped tables
  AND c.drop_date IS NULL
  -- Only insert if test type is active
  AND EXISTS (SELECT 1 FROM test_types WHERE test_type = 'Volume_Trend' AND active = 'Y')
  -- Only insert if test type is included in generation set
  AND EXISTS (SELECT 1 FROM generation_sets WHERE test_type = 'Volume_Trend' AND generation_set = :GENERATION_SET)
  {TABLE_FILTER}

-- Match "uix_td_autogen_table" unique index exactly
ON CONFLICT (test_suite_id, test_type, schema_name, table_name) 
WHERE last_auto_gen_date IS NOT NULL 
  AND table_name IS NOT NULL 
  AND column_name IS NULL

-- Update tests if they already exist
DO UPDATE SET
  test_active         = EXCLUDED.test_active,
  last_auto_gen_date  = EXCLUDED.last_auto_gen_date,
  history_calculation = EXCLUDED.history_calculation,
  history_lookback    = EXCLUDED.history_lookback,
  subset_condition    = EXCLUDED.subset_condition,
  custom_query        = EXCLUDED.custom_query
-- Ignore locked tests
WHERE test_definitions.lock_refresh = 'N'
  -- Don't update existing tests in "insert" mode
  AND NOT COALESCE(:INSERT_ONLY, FALSE);
