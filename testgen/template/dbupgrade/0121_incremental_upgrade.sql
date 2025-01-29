SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE table_groups ADD COLUMN data_product VARCHAR(40);
ALTER TABLE data_table_chars ADD COLUMN data_product VARCHAR(40);
ALTER TABLE data_column_chars ADD COLUMN data_product VARCHAR(40);

ALTER TABLE table_groups ADD COLUMN description VARCHAR(1000);
ALTER TABLE data_table_chars ADD COLUMN description VARCHAR(1000);
ALTER TABLE data_column_chars ADD COLUMN description VARCHAR(1000);
