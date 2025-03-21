SET SEARCH_PATH TO {SCHEMA_NAME};

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

DO $$
DECLARE
  current_project VARCHAR(30);
  current_definition UUID;
  current_definition_filter RECORD;
  where_condition TEXT;
  existing_history_entries TIMESTAMP[];
  history_entry RECORD;
BEGIN
  FOR current_project IN SELECT project_code FROM projects LOOP
    FOR current_definition IN SELECT id FROM score_definitions WHERE project_code = current_project LOOP

      -- Build the where condition for the scores queries
      where_condition := format('WHERE definition_id = %L AND project_code = %L', current_definition, current_project);
      FOR current_definition_filter IN SELECT field, string_agg(quote_literal(value), ', ') AS values FROM score_definition_filters WHERE definition_id = current_definition GROUP BY field LOOP
        where_condition := where_condition || format(' AND %I IN (%s)', current_definition_filter.field, current_definition_filter.values);
      END LOOP;

      -- Get already existing history entries
      SELECT ARRAY_AGG(last_run_time) INTO existing_history_entries FROM score_definition_results_history WHERE definition_id = current_definition;

      FOR history_entry IN EXECUTE format('
        SELECT DISTINCT ON (last_run_time)
            COALESCE(profiling_scores.project_code, test_scores.project_code) AS project_code,
            COALESCE(profiling_scores.definition_id, test_scores.definition_id) AS definition_id,
            COALESCE(profiling_scores.last_run_time, test_scores.last_run_time) AS last_run_time,
            (COALESCE(profiling_scores.score, 1) * COALESCE(test_scores.score, 1)) AS score,
            (COALESCE(profiling_scores.cde_score, 1) * COALESCE(test_scores.cde_score, 1)) AS cde_score
        FROM (
            SELECT
                project_code,
                definition_id,
                score_history_cutoff_time AS last_run_time,
                SUM(good_data_pct * record_ct) / NULLIF(SUM(record_ct), 0) AS score,
                SUM(CASE critical_data_element WHEN true THEN (good_data_pct * record_ct) ELSE 0 END)
                    / NULLIF(SUM(CASE critical_data_element WHEN true THEN record_ct ELSE 0 END), 0) AS cde_score
            FROM v_dq_profile_scoring_history_by_column
            %s
            GROUP BY project_code, definition_id, score_history_cutoff_time
        )  AS profiling_scores
        FULL OUTER JOIN (
            SELECT
                project_code,
                definition_id,
                score_history_cutoff_time AS last_run_time,
                SUM(good_data_pct * dq_record_ct) / NULLIF(SUM(dq_record_ct), 0) AS score,
                SUM(CASE critical_data_element WHEN true THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                    / NULLIF(SUM(CASE critical_data_element WHEN true THEN dq_record_ct ELSE 0 END), 0) AS cde_score
            FROM v_dq_test_scoring_history_by_column
            %s
            GROUP BY project_code, definition_id, score_history_cutoff_time
        ) AS test_scores
          ON (
            test_scores.project_code = profiling_scores.project_code
            AND test_scores.definition_id = profiling_scores.definition_id
            AND test_scores.last_run_time = profiling_scores.last_run_time
          )
      ', where_condition, where_condition) LOOP
        -- If a history entry with this `last_run_time` does not exist
        CONTINUE WHEN history_entry.last_run_time = ANY(existing_history_entries);

        -- insert it for both score and cde score
        EXECUTE format('
          INSERT INTO score_definition_results_history (definition_id, category, score, last_run_time)
          VALUES (%L, %L, %L, %L)
        ', history_entry.definition_id, 'score', history_entry.score, history_entry.last_run_time);
        EXECUTE format('
          INSERT INTO score_definition_results_history (definition_id, category, score, last_run_time)
          VALUES (%L, %L, %L, %L)
        ', history_entry.definition_id, 'cde_score', history_entry.cde_score, history_entry.last_run_time);
      END LOOP;
    END LOOP;
  END LOOP;
END $$;
