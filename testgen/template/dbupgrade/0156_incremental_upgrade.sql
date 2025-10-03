SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE data_structure_log RENAME COLUMN old_column_type TO old_data_type;
ALTER TABLE data_structure_log RENAME COLUMN new_column_type TO new_data_type;

ALTER TABLE stg_data_chars_updates ADD COLUMN db_data_type VARCHAR(50);
ALTER TABLE profile_results ADD COLUMN db_data_type VARCHAR(50);
ALTER TABLE profile_anomaly_results ADD COLUMN db_data_type VARCHAR(50);
ALTER TABLE data_column_chars ADD COLUMN db_data_type VARCHAR(50);

UPDATE profile_results
    SET db_data_type = column_type
    WHERE db_data_type IS NULL;

UPDATE profile_anomaly_results
    SET db_data_type = column_type
    WHERE db_data_type IS NULL;

UPDATE data_column_chars
    SET db_data_type = column_type
    WHERE db_data_type IS NULL;
