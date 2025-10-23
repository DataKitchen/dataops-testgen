SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_suites
    ADD COLUMN monitor_lookback INTEGER DEFAULT NULL;

ALTER TABLE data_structure_log
    ADD COLUMN table_groups_id UUID;

ALTER TABLE data_structure_log
    ADD COLUMN table_name VARCHAR(120);

ALTER TABLE data_structure_log
    ADD COLUMN column_name VARCHAR(120);

WITH update_log AS (
	SELECT
  	data_structure_log.element_id,
	  data_column_chars.table_groups_id,
	  data_column_chars.table_name,
	  data_column_chars.column_name
  FROM data_structure_log
  INNER JOIN data_column_chars
	  ON (data_structure_log.element_id = data_column_chars.column_id)
)
UPDATE data_structure_log
SET table_groups_id = u.table_groups_id,
		table_name = u.table_name,
    column_name = u.column_name
FROM update_log as u
INNER JOIN data_column_chars AS d
    ON (
      d.column_id = u.element_id
      AND d.table_groups_id = u.table_groups_id
      AND d.table_name = u.table_name
      AND d.column_name = u.column_name
    )
WHERE data_structure_log.element_id = d.column_id;
