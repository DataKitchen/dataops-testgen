SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE table_groups ALTER COLUMN profile_id_column_mask SET DEFAULT '%_id';
