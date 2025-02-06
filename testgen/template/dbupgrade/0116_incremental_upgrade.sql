SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE data_table_chars DROP COLUMN data_point_ct;

ALTER TABLE data_table_chars
ADD COLUMN data_point_ct BIGINT GENERATED ALWAYS AS (record_ct * column_ct) STORED;

ALTER TABLE data_table_chars
ADD COLUMN last_refresh_date TIMESTAMP;

ALTER TABLE data_column_chars
ADD COLUMN ordinal_position INTEGER;

CREATE TABLE stg_data_chars_updates (
   project_code          VARCHAR(30),
   table_groups_id       UUID,
   run_date              TIMESTAMP,
   schema_name           VARCHAR(120),
   table_name            VARCHAR(120),
   functional_table_type VARCHAR(50),
   column_name           VARCHAR(120),
   position              INTEGER,
   general_type          VARCHAR(1),
   column_type           VARCHAR(50),
   functional_data_type  VARCHAR(50),
   record_ct             BIGINT
);
