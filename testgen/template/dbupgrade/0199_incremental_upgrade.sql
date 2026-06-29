SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE table_groups ADD COLUMN IF NOT EXISTS data_classification VARCHAR(40);
ALTER TABLE data_table_chars ADD COLUMN IF NOT EXISTS data_classification VARCHAR(40);
ALTER TABLE data_column_chars ADD COLUMN IF NOT EXISTS data_classification VARCHAR(40);
ALTER TABLE score_definition_results_breakdown ADD COLUMN IF NOT EXISTS data_classification TEXT DEFAULT NULL;
