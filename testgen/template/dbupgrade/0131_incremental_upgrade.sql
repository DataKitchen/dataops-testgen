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


CREATE OR REPLACE VIEW v_dq_profile_scoring_history_by_dimension
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
       t.dq_dimension,
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
         dcc.functional_data_type, t.dq_dimension, pr.run_date,
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


CREATE OR REPLACE VIEW v_dq_test_scoring_history_by_dimension
AS
WITH dimension_rollup
   AS (SELECT r.test_run_id, r.test_suite_id, r.table_groups_id, r.test_time,
              r.table_name, r.column_names, tt.dq_dimension,
              sr.definition_id, sr.score_history_cutoff_time,
              COUNT(*) as test_ct,
              SUM(r.result_code) as passed_ct,
              SUM(1 - r.result_code) as issue_ct,
              MAX(r.dq_record_ct) as dq_record_ct,
              SUM_LN(COALESCE(r.dq_prevalence::NUMERIC, 0)) as good_data_pct
         FROM test_results r
         INNER JOIN test_types tt
            ON (r.test_type = tt.test_type)
         INNER JOIN test_suites s
            ON (r.test_suite_id = s.id)
         INNER JOIN score_history_latest_runs sr
            ON (s.id = sr.test_suite_id
           AND  r.test_run_id = sr.last_test_run_id)
         WHERE r.dq_prevalence IS NOT NULL
           AND s.dq_score_exclude = FALSE
           AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
         GROUP BY r.test_run_id, r.test_suite_id, r.table_groups_id, r.test_time,
              r.table_name, r.column_names,
              tt.dq_dimension,
              sr.definition_id, sr.score_history_cutoff_time )
SELECT
       tg.project_code,
       r.definition_id, r.score_history_cutoff_time,
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
GROUP BY r.definition_id, r.score_history_cutoff_time,
         r.table_groups_id, r.test_run_id, r.test_suite_id,
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
