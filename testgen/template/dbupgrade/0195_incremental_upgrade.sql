SET SEARCH_PATH TO {SCHEMA_NAME};

-- Deduplicate the run tables against job_executions.
--
-- The run primary key becomes the job execution id: job_execution_id is
-- promoted to the primary key (which is also a foreign key to
-- job_executions.id with cascade on delete), and the duplicated status,
-- end-time, log-message, and process-id columns are dropped. External
-- references are rewritten from the old run id to the job execution id.
-- Because job_execution_id already holds that value on every row, the
-- run identity is reshaped with pure DDL rather than rewriting primary
-- key values in place.

-- Standard views join the run tables on their primary key, so they must be
-- dropped before the id column can be reshaped. _refresh_static_metadata
-- recreates them from 060_create_standard_views.sql after the upgrade.
DROP VIEW IF EXISTS v_latest_profile_results CASCADE;
DROP VIEW IF EXISTS v_inactive_anomalies CASCADE;
DROP VIEW IF EXISTS v_queued_observability_results CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_column CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_column CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_impact_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_impact_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_history_by_column CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_history_by_column CASCADE;

-- Remove result rows orphaned by an already-deleted run. They are
-- unreachable in the application and would block the value rewrite and the
-- new cascade constraints below.
DO $$
DECLARE
    orphan_ct BIGINT;
BEGIN
    DELETE FROM test_results c
     WHERE NOT EXISTS (SELECT 1 FROM test_runs r WHERE r.id = c.test_run_id);
    GET DIAGNOSTICS orphan_ct = ROW_COUNT;
    IF orphan_ct > 0 THEN RAISE NOTICE 'deleted % orphan test_results row(s)', orphan_ct; END IF;

    DELETE FROM profile_results c
     WHERE NOT EXISTS (SELECT 1 FROM profiling_runs r WHERE r.id = c.profile_run_id);
    GET DIAGNOSTICS orphan_ct = ROW_COUNT;
    IF orphan_ct > 0 THEN RAISE NOTICE 'deleted % orphan profile_results row(s)', orphan_ct; END IF;

    DELETE FROM profile_anomaly_results c
     WHERE NOT EXISTS (SELECT 1 FROM profiling_runs r WHERE r.id = c.profile_run_id);
    GET DIAGNOSTICS orphan_ct = ROW_COUNT;
    IF orphan_ct > 0 THEN RAISE NOTICE 'deleted % orphan profile_anomaly_results row(s)', orphan_ct; END IF;
END $$;

-- Rewrite result-row references from the old run id to the job execution id.
UPDATE test_results c
   SET test_run_id = r.job_execution_id
  FROM test_runs r
 WHERE r.id = c.test_run_id;

UPDATE profile_results c
   SET profile_run_id = r.job_execution_id
  FROM profiling_runs r
 WHERE r.id = c.profile_run_id;

UPDATE profile_anomaly_results c
   SET profile_run_id = r.job_execution_id
  FROM profiling_runs r
 WHERE r.id = c.profile_run_id;

-- Repoint the cache/reference pointers to the job execution id. These are
-- not foreign keys; rows pointing at an already-deleted run are left as-is
-- (a dangling cache that resolves to no run, exactly as before).
UPDATE table_groups tg
   SET last_complete_profile_run_id = r.job_execution_id
  FROM profiling_runs r
 WHERE r.id = tg.last_complete_profile_run_id;

UPDATE test_suites ts
   SET last_complete_test_run_id = r.job_execution_id
  FROM test_runs r
 WHERE r.id = ts.last_complete_test_run_id;

UPDATE data_table_chars dtc
   SET last_complete_profile_run_id = r.job_execution_id
  FROM profiling_runs r
 WHERE r.id = dtc.last_complete_profile_run_id;

UPDATE data_column_chars dcc
   SET last_complete_profile_run_id = r.job_execution_id
  FROM profiling_runs r
 WHERE r.id = dcc.last_complete_profile_run_id;

UPDATE score_history_latest_runs sr
   SET last_test_run_id = r.job_execution_id
  FROM test_runs r
 WHERE r.id = sr.last_test_run_id;

UPDATE score_history_latest_runs sr
   SET last_profiling_run_id = r.job_execution_id
  FROM profiling_runs r
 WHERE r.id = sr.last_profiling_run_id;

UPDATE test_definitions td
   SET profile_run_id = r.job_execution_id
  FROM profiling_runs r
 WHERE r.id = td.profile_run_id;

-- Promote job_execution_id to the primary key on profiling_runs. The column
-- already holds the job execution id, so this is pure DDL.
ALTER TABLE profiling_runs DROP CONSTRAINT pk_prun_id;
ALTER TABLE profiling_runs DROP COLUMN id;
ALTER TABLE profiling_runs RENAME COLUMN job_execution_id TO id;
ALTER TABLE profiling_runs ADD CONSTRAINT pk_prun_id PRIMARY KEY (id);
ALTER TABLE profiling_runs
    ADD CONSTRAINT profiling_runs_job_executions_id_fk
    FOREIGN KEY (id) REFERENCES job_executions (id) ON DELETE CASCADE;

-- Promote job_execution_id to the primary key on test_runs.
ALTER TABLE test_runs DROP CONSTRAINT test_runs_id_pk;
ALTER TABLE test_runs DROP COLUMN id;
ALTER TABLE test_runs RENAME COLUMN job_execution_id TO id;
ALTER TABLE test_runs ADD CONSTRAINT test_runs_id_pk PRIMARY KEY (id);
ALTER TABLE test_runs
    ADD CONSTRAINT test_runs_job_executions_id_fk
    FOREIGN KEY (id) REFERENCES job_executions (id) ON DELETE CASCADE;

-- Make the result-row references real cascade foreign keys so deleting a job
-- execution removes its run and the run's results in one DB-level cascade.
ALTER TABLE test_results
    ADD CONSTRAINT test_results_test_runs_id_fk
    FOREIGN KEY (test_run_id) REFERENCES test_runs (id) ON DELETE CASCADE;

ALTER TABLE profile_results
    ADD CONSTRAINT profile_results_profiling_runs_id_fk
    FOREIGN KEY (profile_run_id) REFERENCES profiling_runs (id) ON DELETE CASCADE;

ALTER TABLE profile_anomaly_results
    ADD CONSTRAINT profile_anomaly_results_profiling_runs_id_fk
    FOREIGN KEY (profile_run_id) REFERENCES profiling_runs (id) ON DELETE CASCADE;

-- Drop the columns now owned by job_executions.
ALTER TABLE test_runs
    DROP COLUMN status,
    DROP COLUMN test_endtime,
    DROP COLUMN log_message,
    DROP COLUMN process_id;

ALTER TABLE profiling_runs
    DROP COLUMN status,
    DROP COLUMN profiling_endtime,
    DROP COLUMN log_message,
    DROP COLUMN process_id;
