

WITH stats
   AS ( SELECT profile_run_id,
               COUNT(*) as anomaly_ct,
               COUNT(DISTINCT schema_name || '.' || table_name) as anomaly_table_ct,
               COUNT(DISTINCT schema_name || '.' || table_name || '.' || column_name) as anomaly_column_ct
          FROM profile_anomaly_results
         WHERE profile_run_id = :PROFILE_RUN_ID
        GROUP BY profile_run_id )
UPDATE profiling_runs
   SET anomaly_ct = COALESCE(stats.anomaly_ct, 0),
       anomaly_table_ct = COALESCE(stats.anomaly_table_ct, 0),
       anomaly_column_ct = COALESCE(stats.anomaly_column_ct, 0)
  FROM stats
 WHERE profiling_runs.id = stats.profile_run_id ;
