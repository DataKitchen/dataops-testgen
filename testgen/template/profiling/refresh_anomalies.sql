

WITH anomalies
   AS ( SELECT profile_run_id,
               COUNT(*) as anomaly_ct,
               COUNT(DISTINCT schema_name || '.' || table_name) as anomaly_table_ct,
               COUNT(DISTINCT schema_name || '.' || table_name || '.' || column_name) as anomaly_column_ct
          FROM profile_anomaly_results
         WHERE profile_run_id = '{PROFILE_RUN_ID}'::UUID
        GROUP BY profile_run_id ),
profiles
   AS ( SELECT r.id as profile_run_id,
               COUNT(DISTINCT p.schema_name || '.' || p.table_name) as table_ct,
               COUNT(*) as column_ct
          FROM profiling_runs r
         INNER JOIN profile_results p
            ON r.id = p.profile_run_id
         WHERE r.id = '{PROFILE_RUN_ID}'::UUID
         GROUP BY r.id ),
stats
   AS ( SELECT p.profile_run_id, table_ct, column_ct,
               a.anomaly_ct, a.anomaly_table_ct, a.anomaly_column_ct
          FROM profiles p
               LEFT JOIN anomalies a
                          ON (p.profile_run_id = a.profile_run_id) )
UPDATE profiling_runs
   SET table_ct = stats.table_ct,
       column_ct = stats.column_ct,
       anomaly_ct = COALESCE(stats.anomaly_ct, 0),
       anomaly_table_ct = COALESCE(stats.anomaly_table_ct, 0),
       anomaly_column_ct = COALESCE(stats.anomaly_column_ct, 0)
  FROM stats
 WHERE profiling_runs.id = stats.profile_run_id ;
