SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE OR REPLACE VIEW v_dq_profile_scoring_latest_by_column
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
