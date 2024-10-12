SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE INDEX working_agg_cat_tests_test_run_id_index
   ON working_agg_cat_tests(test_run_id);

CREATE INDEX ix_td_ts_fk
   ON test_definitions(test_suite_id);

CREATE INDEX ix_trun_ts_fk
   ON test_runs(test_suite_id);

CREATE INDEX ix_tr_pc_ts
   ON test_results(test_suite_id);
