SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE table_groups ADD COLUMN IF NOT EXISTS table_filters JSONB;

ALTER TABLE profiling_runs ADD COLUMN IF NOT EXISTS table_filters JSONB;

ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS table_filters JSONB;

ALTER TABLE stg_data_chars_updates ADD COLUMN IF NOT EXISTS table_filter VARCHAR;

ALTER TABLE data_table_chars ADD COLUMN IF NOT EXISTS table_filter VARCHAR;

ALTER TABLE test_results ADD COLUMN IF NOT EXISTS table_filter VARCHAR;

ALTER TABLE test_results ADD COLUMN IF NOT EXISTS match_table_filter VARCHAR;
