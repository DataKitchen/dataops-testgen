-- Insert test for current schema
INSERT INTO test_definitions (
  table_groups_id, test_suite_id, test_type,
  schema_name,
  test_active, last_auto_gen_date
)
SELECT
  :TABLE_GROUPS_ID ::UUID AS table_groups_id,
  :TEST_SUITE_ID ::UUID   AS test_suite_id,
  'Schema_Drift'          AS test_type,
  :DATA_SCHEMA            AS schema_name,
  'Y'                     AS test_active,
  :RUN_DATE ::TIMESTAMP   AS last_auto_gen_date
  -- Only insert if test type is active
WHERE EXISTS (SELECT 1 FROM test_types WHERE test_type = 'Schema_Drift' AND active = 'Y')
  -- Only insert if test type is included in generation set
  AND EXISTS (SELECT 1 FROM generation_sets WHERE test_type = 'Schema_Drift' AND generation_set = :GENERATION_SET)

-- Match "uix_td_autogen_schema" unique index exactly
ON CONFLICT (test_suite_id, test_type, schema_name) 
WHERE last_auto_gen_date IS NOT NULL 
  AND table_name IS NULL 
  AND column_name IS NULL

-- Update test if it already exists
DO UPDATE SET
  test_active         = EXCLUDED.test_active,
  last_auto_gen_date  = EXCLUDED.last_auto_gen_date
-- Ignore locked tests
WHERE test_definitions.lock_refresh = 'N';
