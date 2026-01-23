SET SEARCH_PATH TO {SCHEMA_NAME};

DROP VIEW IF EXISTS v_test_results;

UPDATE test_results
  SET column_names = NULL
WHERE column_names = 'N/A';

UPDATE test_results
  SET test_definition_id = d.id
FROM test_results r
  INNER JOIN test_definitions d ON (
    r.auto_gen IS TRUE
    AND r.test_suite_id = d.test_suite_id
    AND r.schema_name = d.schema_name
    AND r.table_name IS NOT DISTINCT FROM d.table_name
    AND r.column_names IS NOT DISTINCT FROM d.column_name
    AND r.test_type = d.test_type
  )
WHERE d.last_auto_gen_date IS NOT NULL
  AND test_results.id = r.id;

CREATE UNIQUE INDEX uix_td_autogen_schema
  ON test_definitions (test_suite_id, test_type, schema_name)
  WHERE last_auto_gen_date IS NOT NULL 
    AND table_name IS NULL 
    AND column_name IS NULL;

CREATE UNIQUE INDEX uix_td_autogen_table
  ON test_definitions (test_suite_id, test_type, schema_name, table_name)
  WHERE last_auto_gen_date IS NOT NULL 
    AND table_name IS NOT NULL 
    AND column_name IS NULL;

CREATE UNIQUE INDEX uix_td_autogen_column
  ON test_definitions (test_suite_id, test_type, schema_name, table_name, column_name)
  WHERE last_auto_gen_date IS NOT NULL 
    AND table_name IS NOT NULL 
    AND column_name IS NOT NULL;

DROP INDEX idx_dtc_tgid_table;

CREATE INDEX idx_dtc_tg_schema_table
  ON data_table_chars (table_groups_id, schema_name, table_name);

CREATE INDEX idx_dtc_id
  ON data_table_chars (table_id);

DROP INDEX idx_dcc_tg_table_column;

CREATE INDEX idx_dcc_tg_schema_table_column
  ON data_column_chars (table_groups_id, schema_name, table_name, column_name);

CREATE INDEX idx_dcc_tableid_column
  ON data_column_chars (table_id, column_name);

CREATE INDEX idx_dcc_id
  ON data_column_chars (column_id);

ALTER INDEX IF EXISTS profile_results_tgid_sn_tn_cn
  RENAME TO ix_pr_tg_s_t_c;

CREATE INDEX ix_pr_tg_rd
  ON profile_results (table_groups_id, run_date);
