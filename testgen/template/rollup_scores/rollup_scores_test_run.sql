-- Reset scoring in test run
UPDATE test_runs
   SET dq_affected_data_points = 0,
       dq_total_data_points = 0,
       dq_score_test_run = 1
 WHERE id = :RUN_ID;

-- Roll up scoring to test run
WITH score_detail
  AS (SELECT r.test_run_id, r.table_name, r.column_names,
             MAX(r.dq_record_ct) as row_ct,
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0))) * MAX(r.dq_record_ct) as affected_data_points
        FROM test_results r
       WHERE r.test_run_id = :RUN_ID
         AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY r.test_run_id, r.table_name, r.column_names ),
score_calc
  AS ( SELECT test_run_id,
              SUM(affected_data_points) as sum_affected_data_points,
              SUM(row_ct) as sum_data_points
         FROM score_detail
       GROUP BY test_run_id )
UPDATE test_runs
   SET dq_affected_data_points = sum_affected_data_points,
       dq_total_data_points = sum_data_points,
       dq_score_test_run = (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0))
  FROM score_calc
 WHERE test_runs.id = score_calc.test_run_id;
