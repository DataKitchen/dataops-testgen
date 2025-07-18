-- Reset scoring in profiling run
UPDATE profiling_runs
   SET dq_affected_data_points = 0,
       dq_total_data_points = 0,
       dq_score_profiling = 1
 WHERE id = :RUN_ID;

-- Roll up scoring to profiling run
WITH score_detail
  AS (SELECT pr.profile_run_id, pr.table_name, pr.column_name,
             MAX(pr.record_ct) as row_ct,
             (1.0 - SUM_LN(COALESCE(p.dq_prevalence, 0.0))) * MAX(pr.record_ct) as affected_data_points
        FROM profile_results pr
      INNER JOIN profiling_runs r
         ON (pr.profile_run_id = r.id)
      LEFT JOIN profile_anomaly_results p
        ON (pr.profile_run_id = p.profile_run_id
       AND  pr.column_name = p.column_name
       AND  pr.table_name = p.table_name)
      WHERE pr.profile_run_id = :RUN_ID
        AND COALESCE(p.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY 1, 2, 3 ),
score_calc
  AS ( SELECT profile_run_id,
              SUM(affected_data_points) as sum_affected_data_points,
              SUM(row_ct) as sum_data_points
         FROM score_detail
       GROUP BY profile_run_id )
UPDATE profiling_runs
   SET dq_affected_data_points = sum_affected_data_points,
       dq_total_data_points = sum_data_points,
       dq_score_profiling = (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0))
  FROM score_calc
 WHERE profiling_runs.id = score_calc.profile_run_id;
