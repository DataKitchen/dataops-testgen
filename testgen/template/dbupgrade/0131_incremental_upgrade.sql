SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE score_history_latest_runs (
   definition_id             UUID,
   score_history_cutoff_time TIMESTAMP,
   table_groups_id           UUID,
   last_profiling_run_id     UUID,
   test_suite_id             UUID,
   last_test_run_id          UUID
);

CREATE INDEX shlast_runs_def_cutoff
   ON score_history_latest_runs(definition_id, score_history_cutoff_time);

CREATE INDEX shlast_runs_pro_run
   ON score_history_latest_runs(last_profiling_run_id);

CREATE INDEX shlast_runs_tst_run
   ON score_history_latest_runs(last_test_run_id);

