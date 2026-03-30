SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE table_groups
    ADD COLUMN IF NOT EXISTS profile_flag_pii BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS profile_exclude_xde BOOLEAN DEFAULT TRUE;

ALTER TABLE data_column_chars
    ADD COLUMN IF NOT EXISTS excluded_data_element BOOLEAN,
    ADD COLUMN IF NOT EXISTS pii_flag VARCHAR(50);

ALTER TABLE target_data_lookups ADD COLUMN IF NOT EXISTS lookup_redactable_columns VARCHAR(100);

ALTER TABLE profile_anomaly_types ADD COLUMN IF NOT EXISTS detail_redactable BOOLEAN DEFAULT FALSE;
