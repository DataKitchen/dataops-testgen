SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE data_structure_log
    ADD COLUMN table_id UUID,
    ADD COLUMN column_id UUID;

UPDATE data_structure_log
SET table_id = dcc.table_id,
    column_id = dcc.column_id
FROM data_column_chars dcc
WHERE data_structure_log.element_id = dcc.column_id;

ALTER TABLE data_structure_log
    DROP COLUMN element_id;

CREATE INDEX ix_dsl_tg_tcd 
   ON data_structure_log (table_groups_id, table_name, change_date);
