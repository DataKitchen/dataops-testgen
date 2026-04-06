SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_definitions ADD COLUMN IF NOT EXISTS external_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS uix_td_external_id
  ON test_definitions (test_suite_id, external_id)
  WHERE external_id IS NOT NULL;
