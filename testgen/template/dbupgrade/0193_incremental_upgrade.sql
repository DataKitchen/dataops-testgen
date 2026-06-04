SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE data_table_chars
    ADD COLUMN IF NOT EXISTS object_type VARCHAR(20);

ALTER TABLE stg_data_chars_updates
    ADD COLUMN IF NOT EXISTS object_type VARCHAR(20);
