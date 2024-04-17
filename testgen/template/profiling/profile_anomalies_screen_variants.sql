INSERT INTO profile_anomaly_results
   (project_code, table_groups_id, profile_run_id, anomaly_id,
    schema_name, table_name, column_name, column_type, detail)
WITH all_matches
   AS ( SELECT p.project_code,
               p.table_groups_id,
               p.profile_run_id,
               p.schema_name,
               p.table_name,
               p.column_name,
               p.column_type,
               fn_extract_distinct_items(STRING_AGG(fn_extract_intersecting_items(LOWER(fn_extract_top_values(p.top_freq_values)),
                                                                                  v.check_values, '|'),
                                                    '|'),
                                         '|') AS intersect_list
          FROM profile_results p
               CROSS JOIN variant_codings v
               LEFT JOIN v_inactive_anomalies i
                         ON (p.table_groups_id = i.table_groups_id
                            AND p.schema_name = i.schema_name
                            AND p.table_name = i.table_name
                            AND p.column_name = i.column_name
                            AND '{ANOMALY_ID}' = i.anomaly_id)
         WHERE p.profile_run_id = '{PROFILE_RUN_ID}'::UUID
           AND {ANOMALY_CRITERIA}
           AND p.top_freq_values > ''
           AND i.anomaly_id IS NULL
           AND fn_count_intersecting_items(LOWER(fn_extract_top_values(p.top_freq_values)), v.check_values, '|') > 1
         GROUP BY p.project_code,
            p.table_groups_id,
            p.profile_run_id,
            p.schema_name,
            p.table_name,
            p.column_name,
            p.column_type )
SELECT project_code, table_groups_id, profile_run_id,
       '{ANOMALY_ID}'  AS anomaly_id,
       schema_name, table_name, column_name, column_type,
       {DETAIL_EXPRESSION} AS detail
  FROM all_matches;
