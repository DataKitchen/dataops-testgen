WITH mults AS (   SELECT p.project_code,
                         p.table_groups_id,
                         p.schema_name,
                         p.column_name,
                         COUNT(*)                       AS column_ct,
                         COUNT(DISTINCT p.column_type)  AS type_ct,
                         COUNT(DISTINCT p.general_type) AS general_type_ct,
                         MIN(p.column_type::TEXT)       AS min_type,
                         MAX(p.column_type::TEXT)       AS max_type,
                         MIN(p.distinct_pattern_ct)     AS min_pattern_ct,
                         MAX(p.distinct_pattern_ct)     AS max_pattern_ct,
                         SUM(p.distinct_pattern_ct)     AS sum_pattern_ct,
                         STRING_AGG(table_name, ', ' order by table_name) as table_list,
                         MAX(RIGHT(REPEAT('0', 20) || SPLIT_PART(p.top_patterns, '|', 1), 20) || '|' || SPLIT_PART(p.top_patterns, '|', 2) )as very_top_pattern
                    FROM profile_results p
                    WHERE p.profile_run_id = '{PROFILE_RUN_ID}'::UUID
                   GROUP BY p.project_code, p.table_groups_id, schema_name, p.column_name
                  HAVING COUNT(*) > 1 ),
    subset AS
     (
            SELECT p.project_code,
                   p.table_groups_id,
                   p.profile_run_id,
                   '{ANOMALY_ID}' as anomaly_id,
                   p.schema_name,
                   p.table_name,
                   p.column_name,
                   p.column_type,
                   p.top_patterns,
                   ltrim(m.very_top_pattern, '0') as very_top_pattern,
                   m.table_list,
                   {DETAIL_EXPRESSION} AS detail
              FROM profile_results p
            INNER JOIN mults m
               ON p.project_code = m.project_code
              AND p.table_groups_id = m.table_groups_id
              AND p.schema_name = m.schema_name
              AND p.column_name = m.column_name
            LEFT JOIN v_inactive_anomalies i
              ON (p.table_groups_id = i.table_groups_id
             AND  p.schema_name = i.schema_name
             AND  p.table_name = i.table_name
             AND  p.column_name = i.column_name
             AND  '{ANOMALY_ID}' = i.anomaly_id)
             WHERE p.profile_run_id = '{PROFILE_RUN_ID}'::UUID
               AND i.anomaly_id IS NULL
               AND {ANOMALY_CRITERIA}
    )
INSERT INTO profile_anomaly_results
   (project_code, table_groups_id, profile_run_id, anomaly_id,
    schema_name, table_name, column_name, column_type, detail)
SELECT project_code, table_groups_id, profile_run_id, anomaly_id,
       schema_name, '(multi-table)' as table_name,
       column_name, '(multiple)' as column_type,
       detail  || ' , Tables: ' || table_list AS detail
FROM subset
GROUP BY project_code, table_groups_id, profile_run_id, anomaly_id,
         schema_name, column_name, table_list, detail;
