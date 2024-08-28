SET SEARCH_PATH TO {SCHEMA_NAME};

-- Step 1: Drop everything that depends on the current state

DROP VIEW v_test_runs; -- Not needed, unused
DROP VIEW v_test_results;
DROP VIEW v_queued_observability_results;
DROP INDEX cix_tr_pc_ts;
DROP INDEX ix_tr_pc_ts; -- Not needed, replaced by a FK
DROP INDEX ix_tr_pc_sctc_tt;
DROP INDEX ix_trun_pc_ts_time;
DROP INDEX working_agg_cat_tests_test_run_id_index; -- Not needed, given the column is a FK

-- Step 2: Adjust the tables

ALTER TABLE test_runs ADD COLUMN test_suite_id UUID;

    UPDATE test_runs
       SET test_suite_id = ts.id
      FROM test_runs tr
INNER JOIN test_suites AS ts ON tr.test_suite = ts.test_suite AND tr.project_code = ts.project_code;

ALTER TABLE test_runs ALTER COLUMN test_suite_id SET NOT NULL;


    UPDATE test_results
       SET test_suite_id = ts.id
      FROM test_results tr
INNER JOIN test_suites AS ts ON tr.test_suite = ts.test_suite AND tr.project_code = ts.project_code
     WHERE tr.test_suite_id is NULL;

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

CREATE VIEW v_test_results
AS
SELECT p.project_name,
       ts.test_suite,
       tg.table_groups_name,
       cn.connection_name, cn.project_host, cn.sql_flavor,
       tt.dq_dimension,
       r.schema_name, r.table_name, r.column_names,
       r.test_time as test_date,
       r.test_type,  tt.id as test_type_id, tt.test_name_short, tt.test_name_long,
       r.test_description,
       tt.measure_uom, tt.measure_uom_description,
       c.test_operator,
       r.threshold_value::NUMERIC(16, 5) as threshold_value,
       r.result_measure::NUMERIC(16, 5),
       r.result_status,
       r.input_parameters,
       r.result_message,
       CASE WHEN result_code <> 1 THEN r.severity END as severity,
       CASE
         WHEN result_code <> 1 THEN r.disposition
            ELSE 'Passed'
       END as disposition,
       r.result_code as passed_ct,
       (1 - r.result_code)::INTEGER as exception_ct,
       CASE
         WHEN result_status = 'Warning'
          AND result_message NOT ILIKE 'ERROR - TEST COLUMN MISSING%' THEN 1
       END::INTEGER as warning_ct,
       CASE
         WHEN result_status = 'Failed'
          AND result_message NOT ILIKE 'ERROR - TEST COLUMN MISSING%' THEN 1
       END::INTEGER as failed_ct,
       CASE
         WHEN result_message ILIKE 'ERROR - TEST COLUMN MISSING%' THEN 1
       END as execution_error_ct,
       p.project_code,
       r.table_groups_id,
       r.id as test_result_id, c.id as connection_id,
       r.test_suite_id,
       r.test_definition_id as test_definition_id_runtime,
       CASE
         WHEN r.auto_gen = TRUE THEN d.id
                                ELSE r.test_definition_id
       END as test_definition_id_current,
       r.test_run_id as test_run_id,
       r.auto_gen
  FROM test_results r
INNER JOIN test_types tt
   ON (r.test_type = tt.test_type)
LEFT JOIN test_definitions d
   ON (r.test_suite_id = d.test_suite_id
  AND  r.table_name = d.table_name
  AND  r.column_names = COALESCE(d.column_name, 'N/A')
  AND  r.test_type = d.test_type
  AND  r.auto_gen = TRUE
  AND  d.last_auto_gen_date IS NOT NULL)
INNER JOIN test_suites ts
   ON (r.test_suite_id = ts.id)
INNER JOIN projects p
   ON (ts.project_code = p.project_code)
INNER JOIN table_groups tg
   ON (r.table_groups_id = tg.id)
INNER JOIN connections cn
   ON (tg.connection_id = cn.connection_id)
LEFT JOIN cat_test_conditions c
   ON (cn.sql_flavor = c.sql_flavor
  AND  r.test_type = c.test_type);

CREATE VIEW v_queued_observability_results
  AS
SELECT
       p.project_name,
       cn.sql_flavor as component_tool,
       ts.test_suite_schema as schema,
       cn.connection_name,
       cn.project_db,

       CASE
         WHEN tg.profile_use_sampling = 'Y' THEN tg.profile_sample_min_count
       END as sample_min_count,
       tg.id as group_id,
       tg.profile_use_sampling = 'Y' as uses_sampling,
       ts.project_code,
       CASE
         WHEN tg.profile_use_sampling = 'Y' THEN tg.profile_sample_percent
       END as sample_percentage,

       tg.profiling_table_set,
       tg.profiling_include_mask,
       tg.profiling_exclude_mask,

       COALESCE(ts.component_type, 'dataset') as component_type,
       COALESCE(ts.component_key, tg.id::VARCHAR) as component_key,
       COALESCE(ts.component_name, tg.table_groups_name) as component_name,

       r.column_names,
       r.table_name,
       ts.test_suite,
       ts.id AS test_suite_id,
       r.input_parameters,
       r.test_definition_id,
       tt.test_name_short as type,
       CASE
         WHEN c.test_operator IN ('>', '>=') THEN d.threshold_value
       END as min_threshold,
       CASE
         WHEN c.test_operator IN ('<', '<=') THEN d.threshold_value
       END as max_threshold,
      tt.test_name_long as name,
      tt.test_description as description,
      r.test_time as start_time,
      r.test_time as end_time,
      r.result_message as result_message,
      tt.dq_dimension,
      r.result_status,
      r.result_id,
      r.result_measure as metric_value,
      tt.measure_uom,
      tt.measure_uom_description
  FROM test_results r
INNER JOIN test_types tt
   ON (r.test_type = tt.test_type)
INNER JOIN test_definitions d
   ON (r.test_definition_id = d.id)
INNER JOIN test_suites ts
   ON r.test_suite_id = ts.id
INNER JOIN table_groups tg
   ON (d.table_groups_id = tg.id)
INNER JOIN connections cn
   ON (tg.connection_id = cn.connection_id)
INNER JOIN projects p
   ON (ts.project_code = p.project_code)
INNER JOIN cat_test_conditions c
   ON (cn.sql_flavor = c.sql_flavor
  AND  d.test_type = c.test_type)
WHERE r.observability_status = 'Queued';
