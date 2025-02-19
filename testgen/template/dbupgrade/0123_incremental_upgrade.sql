SET SEARCH_PATH TO {SCHEMA_NAME};

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
   ON (tg.last_complete_profile_run_id = pr.id);


DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_dimension;

CREATE VIEW v_dq_profile_scoring_latest_by_dimension
AS
SELECT tg.project_code,
       pr.table_groups_id,
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
       t.dq_dimension,
       dcc.table_name,
       dcc.column_name,
       pr.run_date,
       MAX(pr.record_ct) as record_ct,
       COUNT(p.anomaly_id) as issue_ct,
       SUM_LN(COALESCE(p.dq_prevalence, 0.0)) as good_data_pct
  FROM table_groups tg
INNER JOIN profile_results pr
   ON (tg.last_complete_profile_run_id = pr.profile_run_id)
INNER JOIN data_column_chars dcc
   ON (pr.table_groups_id = dcc.table_groups_id
  AND  pr.table_name = dcc.table_name
  AND  pr.column_name = dcc.column_name)
INNER JOIN data_table_chars dtc
   ON (dcc.table_groups_id = dtc.table_groups_id
  AND  dcc.table_id = dtc.table_id)
LEFT JOIN (profile_anomaly_results p
   INNER JOIN profile_anomaly_types t
      ON p.anomaly_id = t.id)
  ON (pr.profile_run_id = p.profile_run_id
 AND  pr.column_name = p.column_name
 AND  pr.table_name = p.table_name)
WHERE COALESCE(p.disposition, 'Confirmed') = 'Confirmed'
GROUP BY tg.project_code, pr.table_groups_id, tg.last_complete_profile_run_id, tg.table_groups_name,
         tg.data_location, COALESCE(dcc.data_source, dtc.data_source, tg.data_source),
         COALESCE(dcc.source_system, dtc.source_system, tg.source_system),
         COALESCE(dcc.source_process, dtc.source_process, tg.source_process),
         COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain),
         COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group),
         COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level),
         COALESCE(dcc.critical_data_element, dtc.critical_data_element),
         COALESCE(dcc.data_product, dtc.data_product, tg.data_product),
         dcc.functional_data_type, dcc.table_name, dcc.column_name, t.dq_dimension,
         pr.run_date;


-- ==============================================================================
-- |   Result Scoring Views
-- ==============================================================================

DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_column;

CREATE VIEW v_dq_test_scoring_latest_by_column
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
       r.test_time, r.table_name, dcc.column_name,
       COUNT(*) as test_ct,
       SUM(r.result_code) as passed_ct,
       SUM(1 - r.result_code) as issue_ct,
       MAX(r.dq_record_ct) as dq_record_ct,
       SUM_LN(COALESCE(r.dq_prevalence, 0.0)) as good_data_pct
  FROM test_results r
INNER JOIN test_suites s
   ON (r.test_suite_id = s.id
  AND  r.test_run_id = s.last_complete_test_run_id)
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
   AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
GROUP BY tg.project_code, r.table_groups_id, r.test_suite_id, r.test_run_id,
         tg.table_groups_name, dcc.data_source, dtc.data_source,
         tg.data_source, tg.data_location, dcc.data_source, dtc.data_source,
         tg.data_source, dcc.source_system, dtc.source_system, tg.source_system,
         dcc.source_process, dtc.source_process, tg.source_process, dcc.business_domain,
         dtc.business_domain, tg.business_domain, dcc.stakeholder_group, dtc.stakeholder_group,
         tg.stakeholder_group, dcc.transform_level, dtc.transform_level, tg.transform_level,
         dcc.critical_data_element, dtc.critical_data_element,
         dcc.data_product, dtc.data_product, tg.data_product,
         dcc.functional_data_type, r.test_time, r.table_name, dcc.column_name;


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
            ON (r.test_suite_id = s.id
           AND  r.test_run_id = s.last_complete_test_run_id)
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
GROUP BY tg.project_code, r.table_groups_id, r.test_suite_id, r.test_run_id,
         tg.table_groups_name, dcc.data_source, dtc.data_source,
         tg.data_source, tg.data_location, dcc.data_source, dtc.data_source,
         tg.data_source, dcc.source_system, dtc.source_system, tg.source_system,
         dcc.source_process, dtc.source_process, tg.source_process, dcc.business_domain,
         dtc.business_domain, tg.business_domain, dcc.stakeholder_group, dtc.stakeholder_group,
         tg.stakeholder_group, dcc.transform_level, dtc.transform_level, tg.transform_level,
         dcc.critical_data_element, dtc.critical_data_element,
         dcc.data_product, dtc.data_product, tg.data_product,
         dcc.functional_data_type, r.dq_dimension, r.test_time, r.table_name, dcc.column_name;


-- ==============================================================================
-- |   Default scorecards for each table group
-- ==============================================================================


INSERT INTO score_definitions
SELECT
    gen_random_uuid() AS id,
    table_group.project_code AS project_code,
    table_group.table_groups_name AS name,
    true AS total_score,
    true AS cde_score,
    'dq_dimension' AS category
FROM table_groups AS table_group;

INSERT INTO score_definition_filters
SELECT
    gen_random_uuid() AS id,
    score_definition.id AS definition_id,
    'table_groups_name' AS field,
    table_group.table_groups_name AS value
FROM table_groups AS table_group
INNER JOIN score_definitions AS score_definition
    ON (score_definition.project_code = table_group.project_code AND score_definition.name = table_group.table_groups_name);

WITH
profiling_cols AS (
    SELECT
        table_groups_id,
        table_groups_name,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score,
        SUM(CASE critical_data_element WHEN true THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE critical_data_element WHEN true THEN record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_profile_scoring_latest_by_column
    GROUP BY table_groups_id, table_groups_name
),
profiling_dims AS (
    SELECT
        table_groups_id,
        SUM(CASE dq_dimension WHEN 'Accuracy' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Accuracy' THEN record_ct ELSE 0 END), 0) AS accuracy_score,
        SUM(CASE dq_dimension WHEN 'Completeness' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Completeness' THEN record_ct ELSE 0 END), 0) AS completeness_score,
        SUM(CASE dq_dimension WHEN 'Consistency' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Consistency' THEN record_ct ELSE 0 END), 0) AS consistency_score,
        SUM(CASE dq_dimension WHEN 'Timeliness' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Timeliness' THEN record_ct ELSE 0 END), 0) AS timeliness_score,
        SUM(CASE dq_dimension WHEN 'Uniqueness' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Uniqueness' THEN record_ct ELSE 0 END), 0) AS uniqueness_score,
        SUM(CASE dq_dimension WHEN 'Validity' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Validity' THEN record_ct ELSE 0 END), 0) AS validity_score
    FROM v_dq_profile_scoring_latest_by_dimension
    GROUP BY table_groups_id
),
test_cols AS (
    SELECT
        table_groups_id,
        table_groups_name,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score,
        SUM(CASE critical_data_element WHEN true THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE critical_data_element WHEN true THEN dq_record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_test_scoring_latest_by_column
    GROUP BY table_groups_id, table_groups_name
),
test_dims AS (
    SELECT
        table_groups_id,
        SUM(CASE dq_dimension WHEN 'Accuracy' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Accuracy' THEN dq_record_ct ELSE 0 END), 0) AS accuracy_score,
        SUM(CASE dq_dimension WHEN 'Completeness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Completeness' THEN dq_record_ct ELSE 0 END), 0) AS completeness_score,
        SUM(CASE dq_dimension WHEN 'Consistency' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Consistency' THEN dq_record_ct ELSE 0 END), 0) AS consistency_score,
        SUM(CASE dq_dimension WHEN 'Timeliness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Timeliness' THEN dq_record_ct ELSE 0 END), 0) AS timeliness_score,
        SUM(CASE dq_dimension WHEN 'Uniqueness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Uniqueness' THEN dq_record_ct ELSE 0 END), 0) AS uniqueness_score,
        SUM(CASE dq_dimension WHEN 'Validity' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Validity' THEN dq_record_ct ELSE 0 END), 0) AS validity_score
    FROM v_dq_test_scoring_latest_by_dimension
    GROUP BY table_groups_id
)
INSERT INTO score_definition_results
SELECT
    definition_id,
    UNNEST(array['score', 'cde_score', 'profiling_score', 'testing_score', 'Accuracy', 'Completeness', 'Consistency', 'Timeliness', 'Uniqueness', 'Validity']) AS category,
    UNNEST(array[score, cde_score, profiling_score, testing_score, accuracy_score, completeness_score, consistency_score, timeliness_score, uniqueness_score, validity_score]) AS score
FROM (
    SELECT
        score_definition.id AS definition_id,
        COALESCE(profiling_cols.table_groups_id, test_cols.table_groups_id) AS id,
        COALESCE(profiling_cols.table_groups_name, test_cols.table_groups_name) AS name,
        (COALESCE(profiling_cols.score, 1) * COALESCE(test_cols.score, 1)) AS score,
        profiling_cols.score AS profiling_score,
        test_cols.score AS testing_score,
        (COALESCE(profiling_cols.cde_score, 1) * COALESCE(test_cols.cde_score, 1)) AS cde_score,
        (COALESCE(profiling_dims.accuracy_score, 1) * COALESCE(test_dims.accuracy_score, 1)) AS accuracy_score,
        (COALESCE(profiling_dims.completeness_score, 1) * COALESCE(test_dims.completeness_score, 1)) AS completeness_score,
        (COALESCE(profiling_dims.consistency_score, 1) * COALESCE(test_dims.consistency_score, 1)) AS consistency_score,
        (COALESCE(profiling_dims.timeliness_score, 1) * COALESCE(test_dims.timeliness_score, 1)) AS timeliness_score,
        (COALESCE(profiling_dims.uniqueness_score, 1) * COALESCE(test_dims.uniqueness_score, 1)) AS uniqueness_score,
        (COALESCE(profiling_dims.validity_score, 1) * COALESCE(test_dims.validity_score, 1)) AS validity_score
    FROM profiling_cols
    INNER JOIN profiling_dims
        ON (profiling_dims.table_groups_id = profiling_cols.table_groups_id)
    FULL OUTER JOIN test_cols
        ON (test_cols.table_groups_id = profiling_cols.table_groups_id)
    FULL OUTER JOIN test_dims
        ON (test_dims.table_groups_id = test_cols.table_groups_id)
    INNER JOIN table_groups AS table_group
        ON (table_group.id = profiling_cols.table_groups_id OR table_group.id = test_cols.table_groups_id)
    INNER JOIN score_definitions AS score_definition
        ON (score_definition.project_code = table_group.project_code AND score_definition.name = table_group.table_groups_name)
) AS results;
