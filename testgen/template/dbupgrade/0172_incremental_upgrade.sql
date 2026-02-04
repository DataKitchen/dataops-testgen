SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE INDEX IF NOT EXISTS ix_tr_trun_table
   ON test_results(test_run_id, table_name);
