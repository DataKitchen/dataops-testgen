SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE data_table_chars
  ADD CONSTRAINT pk_dtc_id
  PRIMARY KEY (table_id);

CREATE INDEX idx_dtc_tgid_table
  ON data_table_chars (table_groups_id, table_name);

ALTER TABLE data_column_chars
  ADD CONSTRAINT pk_dcc_id
  PRIMARY KEY (column_id);

CREATE INDEX idx_dcc_tg_table_column
  ON data_column_chars (table_groups_id, table_name, column_name);

CREATE UNIQUE INDEX idx_ts_last_run
  ON test_suites (last_complete_test_run_id)
  WHERE last_complete_test_run_id IS NOT NULL;

CREATE UNIQUE INDEX idx_tg_last_profile
  ON table_groups (last_complete_profile_run_id)
  WHERE last_complete_profile_run_id IS NOT NULL;

DROP INDEX IF EXISTS ix_ares_prun;

CREATE INDEX ix_ares_prun
   ON profile_anomaly_results(profile_run_id, table_name, column_name);

CREATE INDEX idx_test_results_filter_join
  ON test_results (test_run_id, table_groups_id, table_name, column_names)
  WHERE dq_prevalence IS NOT NULL
    AND (disposition IS NULL OR disposition = 'Confirmed');
