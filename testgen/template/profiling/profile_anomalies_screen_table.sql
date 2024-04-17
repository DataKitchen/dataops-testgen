INSERT INTO profile_anomaly_results
   (project_code, table_groups_id, profile_run_id, anomaly_id,
    schema_name, table_name, column_name, detail, disposition)
SELECT p.project_code,
       p.table_groups_id,
       p.profile_run_id,
       '{ANOMALY_ID}' as anomaly_id,
       p.schema_name,
       p.table_name,
       '(Table)' as column_name,
       {DETAIL_EXPRESSION} AS detail,
       CASE WHEN i.anomaly_id IS NULL THEN NULL ELSE 'Inactive' END as disposition
  FROM profile_results p
LEFT JOIN v_inactive_anomalies i
  ON (p.table_groups_id = i.table_groups_id
 AND  p.schema_name = i.schema_name
 AND  p.table_name = i.table_name
 AND  '{ANOMALY_ID}' = i.anomaly_id)
 WHERE p.profile_run_id = '{PROFILE_RUN_ID}'::UUID
GROUP BY p.project_code, p.table_groups_id, p.profile_run_id,
         p.schema_name, p.table_name
HAVING {ANOMALY_CRITERIA};
