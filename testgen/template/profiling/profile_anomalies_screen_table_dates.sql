INSERT INTO profile_anomaly_results
   (project_code, table_groups_id, profile_run_id, anomaly_id,
    schema_name, table_name, column_name, detail)
SELECT p.project_code,
       p.table_groups_id,
       p.profile_run_id,
       '{ANOMALY_ID}' as anomaly_id,
       p.schema_name,
       p.table_name,
       CASE
         WHEN COUNT(p.column_name) > 2 THEN '(multi-column)'
         ELSE STRING_AGG(p.column_name, ', ' ORDER BY p.position)
       END as column_name,
       {DETAIL_EXPRESSION}
         || CASE
              WHEN COUNT(p.column_name) > 2 THEN ', Columns: ' || STRING_AGG(p.column_name, ', ' ORDER BY p.position)
              ELSE ''
            END as detail
  FROM profile_results p
LEFT JOIN v_inactive_anomalies i
  ON (p.table_groups_id = i.table_groups_id
 AND  p.schema_name = i.schema_name
 AND  p.table_name = i.table_name
 AND  '{ANOMALY_ID}' = i.anomaly_id)
 WHERE p.profile_run_id = '{PROFILE_RUN_ID}'::UUID
   AND i.anomaly_id IS NULL
   AND p.general_type = 'D'
GROUP BY p.project_code, p.table_groups_id, p.profile_run_id,
         p.schema_name, p.table_name, i.anomaly_id
HAVING {ANOMALY_CRITERIA};
