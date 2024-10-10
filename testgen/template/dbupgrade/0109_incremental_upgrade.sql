SET SEARCH_PATH TO {SCHEMA_NAME};

-- Step 1: Drop everything that depends on the current state

DROP VIEW IF EXISTS v_test_runs;
DROP VIEW IF EXISTS v_test_results;
DROP VIEW IF EXISTS v_queued_observability_results;
DROP INDEX cix_tr_pc_ts;
DROP INDEX ix_tr_pc_ts;
DROP INDEX ix_tr_pc_sctc_tt;
DROP INDEX ix_trun_pc_ts_time;
DROP INDEX working_agg_cat_tests_test_run_id_index;

-- Step 2: Adjust the tables

ALTER TABLE test_runs ADD COLUMN test_suite_id UUID;

    UPDATE test_runs
       SET test_suite_id = ts.id
      FROM test_runs tr
INNER JOIN test_suites AS ts ON tr.test_suite = ts.test_suite AND tr.project_code = ts.project_code
     WHERE test_runs.id = tr.id;

ALTER TABLE test_runs ALTER COLUMN test_suite_id SET NOT NULL;


    UPDATE test_results
       SET test_suite_id = ts.id
      FROM test_results tr
INNER JOIN test_suites AS ts ON tr.test_suite = ts.test_suite AND tr.project_code = ts.project_code
     WHERE tr.test_suite_id is NULL
       AND test_results.id = tr.id;

ALTER TABLE test_results ALTER COLUMN test_suite_id SET NOT NULL;
ALTER TABLE test_results ALTER COLUMN test_run_id SET NOT NULL;


ALTER TABLE working_agg_cat_tests RENAME COLUMN test_run_id TO varchar_test_run_id;
ALTER TABLE working_agg_cat_tests ADD COLUMN test_run_id UUID;
UPDATE working_agg_cat_tests SET test_run_id = varchar_test_run_id::UUID;
ALTER TABLE working_agg_cat_tests ALTER COLUMN test_run_id SET NOT NULL;
ALTER TABLE working_agg_cat_tests DROP COLUMN varchar_test_run_id;


ALTER TABLE working_agg_cat_results RENAME COLUMN test_run_id TO varchar_test_run_id;
ALTER TABLE working_agg_cat_results ADD COLUMN test_run_id UUID;
UPDATE working_agg_cat_results SET test_run_id = varchar_test_run_id::UUID;
ALTER TABLE working_agg_cat_results ALTER COLUMN test_run_id SET NOT NULL;
ALTER TABLE working_agg_cat_results DROP COLUMN varchar_test_run_id;

-- Step 3: Clean up

ALTER TABLE test_runs
DROP COLUMN test_suite,
DROP COLUMN project_code;

ALTER TABLE test_results
DROP COLUMN test_suite,
DROP COLUMN project_code;

ALTER TABLE working_agg_cat_tests
DROP COLUMN project_code,
DROP COLUMN test_suite;

ALTER TABLE working_agg_cat_results
DROP COLUMN project_code,
DROP COLUMN test_suite;

-- Step 4: Re-create views and indexes

CREATE INDEX ix_tr_pc_sctc_tt
   ON test_results(test_suite_id, schema_name, table_name, column_names, test_type);

CREATE INDEX cix_tr_pc_ts
   ON test_results(test_suite_id) WHERE observability_status = 'Queued';

CREATE INDEX ix_trun_pc_ts_time
   ON test_runs(test_suite_id, test_starttime);
