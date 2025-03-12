SET SEARCH_PATH TO {SCHEMA_NAME};

-- ==============================================================================
-- |   Creates Standard Views:
-- |      Runs on new or existing schema, so DROP VIEWS IF EXIST first
-- ==============================================================================

DROP VIEW IF EXISTS v_latest_profile_results CASCADE;

CREATE VIEW v_latest_profile_results
AS
  WITH last_run AS ( SELECT table_groups_id,
                            MAX(profiling_starttime) AS last_run_date
                       FROM profiling_runs
                      GROUP BY table_groups_id )
SELECT r.*
  FROM last_run lr
INNER JOIN profiling_runs p
   ON lr.table_groups_id = p.table_groups_id
  AND lr.last_run_date = p.profiling_starttime
INNER JOIN profile_results r
   ON p.id = r.profile_run_id;


DROP VIEW IF EXISTS v_latest_profile_anomalies;

CREATE VIEW v_latest_profile_anomalies
   AS
WITH last_profile_date
   AS (SELECT table_groups_id, MAX(profiling_starttime) as last_profile_run_date
         FROM profiling_runs
       GROUP BY table_groups_id)
SELECT r.id, r.project_code, r.table_groups_id,
       r.profile_run_id, pr.profiling_starttime as profile_run_date,
       r.schema_name, r.table_name, r.column_name, r.column_type,
       t.anomaly_name, t.anomaly_description, t.issue_likelihood,
       r.detail,
       t.suggested_action, r.disposition
  FROM profile_anomaly_results r
INNER JOIN profile_anomaly_types t
   ON r.anomaly_id = t.id
INNER JOIN profiling_runs pr
   ON (r.profile_run_id = pr.id)
INNER JOIN last_profile_date l
   ON (pr.table_groups_id = l.table_groups_id
  AND  pr.profiling_starttime = l.last_profile_run_date);


DROP VIEW IF EXISTS v_inactive_anomalies;

CREATE VIEW v_inactive_anomalies
 AS
SELECT DISTINCT anomaly_id, table_groups_id, schema_name, table_name, column_name, column_id
  FROM profile_anomaly_results
 WHERE disposition = 'Inactive';


DROP VIEW IF EXISTS v_profiling_runs;

CREATE VIEW v_profiling_runs
 AS
SELECT r.id as profiling_run_id,
       r.project_code, cc.connection_name, r.connection_id, r.table_groups_id,
       tg.table_groups_name,
       tg.table_group_schema as schema_name,
       r.profiling_starttime as start_time,
       TO_CHAR(r.profiling_endtime - r.profiling_starttime, 'HH24:MI:SS') as duration,
       r.status,
       r.log_message,
       r.table_ct,
       r.column_ct,
       r.anomaly_ct, r.anomaly_table_ct, r.anomaly_column_ct,
       process_id, r.dq_score_profiling
  FROM profiling_runs r
INNER JOIN table_groups tg
   ON r.table_groups_id = tg.id
INNER JOIN connections cc
   ON r.connection_id = cc.connection_id
GROUP BY r.id, r.project_code, cc.connection_name, r.connection_id,
         r.table_groups_id, tg.table_groups_name, tg.table_group_schema,
         r.profiling_starttime, r.profiling_endtime, r.status;


DROP VIEW IF EXISTS v_test_runs;

CREATE VIEW v_test_runs
 AS
SELECT r.id as test_run_id,
       p.project_code,
       p.project_name,
       ts.test_suite,
       r.test_starttime,
       TO_CHAR(r.test_endtime - r.test_starttime, 'HH24:MI:SS') as duration,
       r.status, r.log_message,
       COUNT(*) as test_ct,
       SUM(result_code) as passed_ct,
       COALESCE(SUM(CASE WHEN tr.result_status = 'Failed' THEN 1 END), 0) as failed_ct,
       COALESCE(SUM(CASE WHEN tr.result_status = 'Warning' THEN 1 END), 0) as warning_ct,
       r.process_id
  FROM test_runs r
INNER JOIN test_suites ts
   ON (r.test_suite_id = ts.id)
INNER JOIN projects p
   ON (ts.project_code = p.project_code)
INNER JOIN test_results tr
   ON (r.id = tr.test_run_id)
GROUP BY r.id, p.project_code, ts.test_suite, r.test_starttime, r.test_endtime,
         r.process_id, r.status, r.log_message, p.project_name;


DROP VIEW IF EXISTS v_test_results;

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
       (1 - COALESCE(r.result_code, 0))::INTEGER as exception_ct,
       CASE
         WHEN result_status = 'Warning'
          AND result_message NOT ILIKE 'Inactivated%' THEN 1
       END::INTEGER as warning_ct,
       CASE
         WHEN result_status = 'Failed'
          AND result_message NOT ILIKE 'Inactivated%' THEN 1
       END::INTEGER as failed_ct,
       CASE
         WHEN result_message ILIKE 'Inactivated%' THEN 1
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


DROP VIEW IF EXISTS v_queued_observability_results;

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

-- ==============================================================================
-- |   Profile Scoring Views
-- ==============================================================================
DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_column;

CREATE VIEW v_dq_profile_scoring_latest_by_column
AS
SELECT
       tg.project_code,
       dcc.table_groups_id,
       tg.last_complete_profile_run_id as profile_run_id,
       tg.table_groups_name,
       tg.data_location,
       COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
       COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
       COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
       COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
       COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
       COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
       COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
       COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product,
       dcc.functional_data_type as semantic_data_type,
       dtc.table_name, dcc.column_name,
       pr.profiling_starttime as profiling_run_date,
       dcc.valid_profile_issue_ct as issue_ct,
       dtc.last_profile_record_ct as record_ct,
       dcc.dq_score_profiling AS good_data_pct
  FROM data_column_chars dcc
INNER JOIN table_groups tg
   ON (dcc.table_groups_id = tg.id)
INNER JOIN data_table_chars dtc
   ON (dcc.table_id = dtc.table_id)
INNER JOIN profiling_runs pr
   ON (tg.last_complete_profile_run_id = pr.id)
WHERE dcc.drop_date IS NULL;


DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_dimension;

CREATE VIEW v_dq_profile_scoring_latest_by_dimension
AS
SELECT tg.project_code,
       pr.table_groups_id,
       pr.profile_run_id,
       tg.table_groups_name,
       tg.data_location,
       COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
       COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
       COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
       COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
       COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
       COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
       COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
       COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product,
       dcc.functional_data_type as semantic_data_type,
       t.dq_dimension,
       pr.table_name,
       pr.column_name,
       pr.run_date,
       MAX(pr.record_ct) as record_ct,
       COUNT(p.anomaly_id) as issue_ct,
       SUM_LN(COALESCE(p.dq_prevalence, 0.0)) as good_data_pct
  FROM profile_results pr
INNER JOIN table_groups tg
   ON (pr.profile_run_id = tg.last_complete_profile_run_id)
INNER JOIN data_column_chars dcc
   ON (pr.table_groups_id = dcc.table_groups_id
  AND  pr.table_name = dcc.table_name
  AND  pr.column_name = dcc.column_name)
INNER JOIN data_table_chars dtc
   ON (dcc.table_id = dtc.table_id)
LEFT JOIN (profile_anomaly_results p
   INNER JOIN profile_anomaly_types t
      ON p.anomaly_id = t.id)
  ON (pr.profile_run_id = p.profile_run_id
 AND  pr.column_name = p.column_name
 AND  pr.table_name = p.table_name)
WHERE (p.disposition = 'Confirmed' OR p.disposition IS NULL)
   AND dcc.drop_date IS NULL
GROUP BY pr.profile_run_id, pr.table_groups_id,
         pr.table_name, pr.column_name,
         tg.table_groups_name, tg.data_location,
         COALESCE(dcc.data_source, dtc.data_source, tg.data_source),
         COALESCE(dcc.source_system, dtc.source_system, tg.source_system),
         COALESCE(dcc.source_process, dtc.source_process, tg.source_process),
         COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain),
         COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group),
         COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level),
         COALESCE(dcc.critical_data_element, dtc.critical_data_element),
         COALESCE(dcc.data_product, dtc.data_product, tg.data_product),
         dcc.functional_data_type, t.dq_dimension, pr.run_date,
         tg.project_code ;


-- ==============================================================================
-- |   Result Scoring Views
-- ==============================================================================

DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_column;

CREATE OR REPLACE VIEW v_dq_test_scoring_latest_by_column
AS
SELECT
       tg.project_code,
       r.table_groups_id,
       r.test_suite_id,
       r.test_run_id,
       tg.table_groups_name,
       tg.data_location,
       COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
       COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
       COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
       COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
       COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
       COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
       COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
       COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product,
       dcc.functional_data_type as semantic_data_type,
       r.test_time, r.table_name, r.column_names as column_name,
       COUNT(*) as test_ct,
       SUM(r.result_code) as passed_ct,
       SUM(1 - r.result_code) as issue_ct,
       MAX(r.dq_record_ct) as dq_record_ct,
       SUM_LN(COALESCE(r.dq_prevalence, 0.0)) as good_data_pct
  FROM test_results r
INNER JOIN test_suites s
   ON (r.test_run_id = s.last_complete_test_run_id)
INNER JOIN table_groups tg
   ON r.table_groups_id = tg.id
LEFT JOIN data_table_chars dtc
   ON (r.table_groups_id = dtc.table_groups_id
  AND  r.table_name = dtc.table_name)
LEFT JOIN data_column_chars dcc
  ON (r.table_groups_id = dcc.table_groups_id
 AND  r.table_name = dcc.table_name
 AND  r.column_names = dcc.column_name)
 WHERE r.dq_prevalence IS NOT NULL
   AND s.dq_score_exclude = FALSE
   AND (r.disposition IS NULL OR r.disposition = 'Confirmed')
   AND dcc.drop_date IS NULL
GROUP BY r.table_groups_id, r.table_name, r.column_names,
         r.test_suite_id, r.test_run_id, tg.table_groups_name, dcc.data_source, dtc.data_source,
         tg.data_source, tg.data_location, dcc.data_source, dtc.data_source,
         tg.data_source, dcc.source_system, dtc.source_system, tg.source_system,
         dcc.source_process, dtc.source_process, tg.source_process, dcc.business_domain,
         dtc.business_domain, tg.business_domain, dcc.stakeholder_group, dtc.stakeholder_group,
         tg.stakeholder_group, dcc.transform_level, dtc.transform_level, tg.transform_level,
         dcc.critical_data_element, dtc.critical_data_element,
         dcc.data_product, dtc.data_product, tg.data_product,
         dcc.functional_data_type, r.test_time,
         tg.project_code;


DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_dimension;

CREATE OR REPLACE VIEW v_dq_test_scoring_latest_by_dimension
AS
WITH dimension_rollup
   AS (SELECT r.test_run_id, r.test_suite_id, r.table_groups_id, r.test_time,
              r.table_name, r.column_names, tt.dq_dimension,
              COUNT(*) as test_ct,
              SUM(r.result_code) as passed_ct,
              SUM(1 - r.result_code) as issue_ct,
              MAX(r.dq_record_ct) as dq_record_ct,
              SUM_LN(COALESCE(r.dq_prevalence::NUMERIC, 0)) as good_data_pct
         FROM test_results r
         INNER JOIN test_types tt
            ON (r.test_type = tt.test_type)
         INNER JOIN test_suites s
            ON (r.test_run_id = s.last_complete_test_run_id)
         WHERE r.dq_prevalence IS NOT NULL
           AND s.dq_score_exclude = FALSE
           AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
         GROUP BY r.test_run_id, r.test_suite_id, r.table_groups_id, r.test_time,
              r.table_name, r.column_names, tt.dq_dimension )
SELECT
       tg.project_code,
       r.table_groups_id,
       r.test_suite_id,
       r.test_run_id,
       tg.table_groups_name,
       tg.data_location,
       COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
       COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
       COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
       COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
       COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
       COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
       COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
       COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product,
       dcc.functional_data_type as semantic_data_type,
       r.dq_dimension,
       r.test_time, r.table_name, dcc.column_name,
       SUM(r.test_ct) as test_ct,
       SUM(r.passed_ct) as passed_ct,
       SUM(r.issue_ct) as issue_ct,
       MAX(r.dq_record_ct) as dq_record_ct,
       SUM_LN(COALESCE(1.0-r.good_data_pct, 0)) as good_data_pct
  FROM dimension_rollup r
INNER JOIN table_groups tg
   ON r.table_groups_id = tg.id
LEFT JOIN data_table_chars dtc
   ON (r.table_groups_id = dtc.table_groups_id
  AND  r.table_name = dtc.table_name)
LEFT JOIN data_column_chars dcc
  ON (r.table_groups_id = dcc.table_groups_id
 AND  r.table_name = dcc.table_name
 AND  r.column_names = dcc.column_name)
WHERE dcc.drop_date IS NULL
GROUP BY r.table_groups_id, r.test_run_id, r.test_suite_id,
         tg.table_groups_name, dcc.data_source, dtc.data_source,
         tg.data_source, tg.data_location, dcc.data_source, dtc.data_source,
         tg.data_source, dcc.source_system, dtc.source_system, tg.source_system,
         dcc.source_process, dtc.source_process, tg.source_process, dcc.business_domain,
         dtc.business_domain, tg.business_domain, dcc.stakeholder_group, dtc.stakeholder_group,
         tg.stakeholder_group, dcc.transform_level, dtc.transform_level, tg.transform_level,
         dcc.critical_data_element, dtc.critical_data_element,
         dcc.data_product, dtc.data_product, tg.data_product,
         dcc.functional_data_type, r.dq_dimension, r.test_time, r.table_name, dcc.column_name,
         tg.project_code;


-- ==============================================================================
-- |   Scoring History Views
-- ==============================================================================
CREATE OR REPLACE VIEW v_dq_profile_scoring_history_by_column
AS
SELECT tg.project_code,
       sr.definition_id,
       sr.score_history_cutoff_time,
       pr.table_groups_id,
       pr.profile_run_id,
       tg.table_groups_name,
       tg.data_location,
       COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
       COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
       COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
       COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
       COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
       COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
       COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
       COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product,
       dcc.functional_data_type as semantic_data_type,
       pr.table_name,
       pr.column_name,
       pr.run_date,
       MAX(pr.record_ct) as record_ct,
       COUNT(p.anomaly_id) as issue_ct,
       SUM_LN(COALESCE(p.dq_prevalence, 0.0)) as good_data_pct
  FROM profile_results pr
INNER JOIN score_history_latest_runs sr
   ON (pr.profile_run_id = sr.last_profiling_run_id)
INNER JOIN data_column_chars dcc
   ON (pr.table_groups_id = dcc.table_groups_id
  AND  pr.table_name = dcc.table_name
  AND  pr.column_name = dcc.column_name)
INNER JOIN data_table_chars dtc
   ON (dcc.table_id = dtc.table_id)
INNER JOIN table_groups tg
   ON (pr.table_groups_id = tg.id)
LEFT JOIN (profile_anomaly_results p
   INNER JOIN profile_anomaly_types t
      ON p.anomaly_id = t.id)
  ON (pr.profile_run_id = p.profile_run_id
 AND  pr.column_name = p.column_name
 AND  pr.table_name = p.table_name)
WHERE p.disposition = 'Confirmed' OR p.disposition IS NULL
GROUP BY pr.profile_run_id,
         sr.definition_id,
         sr.score_history_cutoff_time,
         pr.table_groups_id,
         pr.table_name, pr.column_name,
         tg.table_groups_name, tg.data_location,
         COALESCE(dcc.data_source, dtc.data_source, tg.data_source),
         COALESCE(dcc.source_system, dtc.source_system, tg.source_system),
         COALESCE(dcc.source_process, dtc.source_process, tg.source_process),
         COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain),
         COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group),
         COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level),
         COALESCE(dcc.critical_data_element, dtc.critical_data_element),
         COALESCE(dcc.data_product, dtc.data_product, tg.data_product),
         dcc.functional_data_type, pr.run_date,
         tg.project_code ;

CREATE OR REPLACE VIEW v_dq_test_scoring_history_by_column
AS
SELECT
       tg.project_code,
       sr.definition_id,
       sr.score_history_cutoff_time,
       r.table_groups_id,
       r.test_suite_id,
       r.test_run_id,
       tg.table_groups_name,
       tg.data_location,
       COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
       COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
       COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
       COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
       COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
       COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
       COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
       COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product,
       dcc.functional_data_type as semantic_data_type,
       r.test_time, r.table_name, r.column_names as column_name,
       COUNT(*) as test_ct,
       SUM(r.result_code) as passed_ct,
       SUM(1 - r.result_code) as issue_ct,
       MAX(r.dq_record_ct) as dq_record_ct,
       SUM_LN(COALESCE(r.dq_prevalence, 0.0)) as good_data_pct
  FROM test_results r
INNER JOIN test_suites s
   ON (r.test_suite_id = s.id)
INNER JOIN score_history_latest_runs sr
   ON (r.test_run_id = sr.last_test_run_id)
INNER JOIN table_groups tg
   ON r.table_groups_id = tg.id
LEFT JOIN data_table_chars dtc
   ON (r.table_groups_id = dtc.table_groups_id
  AND  r.table_name = dtc.table_name)
LEFT JOIN data_column_chars dcc
  ON (r.table_groups_id = dcc.table_groups_id
 AND  r.table_name = dcc.table_name
 AND  r.column_names = dcc.column_name)
 WHERE r.dq_prevalence IS NOT NULL
   AND s.dq_score_exclude = FALSE
   AND (r.disposition IS NULL OR r.disposition = 'Confirmed')
GROUP BY sr.definition_id,
         sr.score_history_cutoff_time,
         r.table_groups_id, r.table_name, r.column_names,
         r.test_suite_id, r.test_run_id, tg.table_groups_name, dcc.data_source, dtc.data_source,
         tg.data_source, tg.data_location, dcc.data_source, dtc.data_source,
         tg.data_source, dcc.source_system, dtc.source_system, tg.source_system,
         dcc.source_process, dtc.source_process, tg.source_process, dcc.business_domain,
         dtc.business_domain, tg.business_domain, dcc.stakeholder_group, dtc.stakeholder_group,
         tg.stakeholder_group, dcc.transform_level, dtc.transform_level, tg.transform_level,
         dcc.critical_data_element, dtc.critical_data_element,
         dcc.data_product, dtc.data_product, tg.data_product,
         dcc.functional_data_type, r.test_time,
         tg.project_code;
