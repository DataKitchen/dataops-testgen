-- Roll up scoring to test run
WITH score_detail
  AS (SELECT r.test_run_id, r.table_name, r.column_names,
             MAX(r.dq_record_ct) as row_ct,
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0), r.dq_record_ct)) * MAX(r.dq_record_ct) as affected_data_points
        FROM test_results r
       WHERE r.test_run_id = '{TEST_RUN_ID}'
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
       dq_score_test_run =
--           CASE
--             WHEN sum_affected_data_points >= sum_data_points THEN 0
--             ELSE
               (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0) )
--           END
  FROM score_calc
 WHERE test_runs.id = score_calc.test_run_id;


-- Roll up scores from latest Test Runs per Test Suite to Table Group
WITH last_test_date
   AS (SELECT r.test_suite_id, MAX(r.test_starttime) as last_test_run_date
         FROM test_runs r
        WHERE r.status = 'Complete'
       GROUP BY r.test_suite_id),
score_calc
  AS (SELECT ts.table_groups_id,
             SUM(run.dq_affected_data_points) as sum_affected_data_points,
             SUM(run.dq_total_data_points) as sum_data_points
        FROM test_runs run
      INNER JOIN test_suites ts
         ON (run.test_suite_id = ts.id)
      INNER JOIN last_test_date lp
         ON (run.test_suite_id = lp.test_suite_id
        AND  run.test_starttime = lp.last_test_run_date)
      WHERE ts.table_groups_id = '{TABLE_GROUPS_ID}'
        AND ts.dq_score_exclude = FALSE
      GROUP BY ts.table_groups_id)
UPDATE table_groups
   SET dq_score_testing =
      CASE
        WHEN sum_affected_data_points >= sum_data_points THEN 0
        ELSE (1.0 - s.sum_affected_data_points::FLOAT / NULLIF(s.sum_data_points::FLOAT, 0) )
      END
  FROM score_calc s
 WHERE table_groups.id = s.table_groups_id;

-- Roll up latest scores to data_column_chars
WITH score_calc
  AS (SELECT dcc.column_id,
             -- Use AVG instead of MAX because column counts may differ by test_run
             AVG(r.dq_record_ct) as row_ct,
             -- bad data pct * record count = affected_data_points
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0), r.dq_record_ct)) * AVG(r.dq_record_ct) as affected_data_points
        FROM test_results r
      INNER JOIN test_suites ts
         ON (r.test_suite_id = ts.id
        AND  r.test_run_id = ts.last_complete_test_run_id)
      INNER JOIN data_column_chars dcc
         ON (ts.table_groups_id = dcc.table_groups_id
        AND  r.table_name = dcc.table_name
        AND  r.column_names = dcc.column_name)
       WHERE ts.table_groups_id = '{TABLE_GROUPS_ID}'
         AND ts.dq_score_exclude = FALSE
         AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY dcc.column_id )
UPDATE data_column_chars
   SET dq_score_testing =
--           CASE
--             WHEN affected_data_points >= row_ct THEN 0
--             ELSE
               (1.0 - affected_data_points::FLOAT / NULLIF(row_ct::FLOAT, 0))
--           END
  FROM score_calc s
 WHERE data_column_chars.column_id = s.column_id;

-- Roll up latest scores to data_table_chars
WITH score_detail
  AS (SELECT dcc.table_id, dcc.column_id,
             -- Use AVG instead of MAX because column counts may differ by test_run
             AVG(r.dq_record_ct) as row_ct,
             -- bad data pct * record count = affected_data_points
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0), r.dq_record_ct)) * AVG(r.dq_record_ct) as affected_data_points
        FROM test_results r
      INNER JOIN test_suites ts
         ON (r.test_suite_id = ts.id
        AND  r.test_run_id = ts.last_complete_test_run_id)
      INNER JOIN data_column_chars dcc
         ON (ts.table_groups_id = dcc.table_groups_id
        AND  r.table_name = dcc.table_name
        AND  r.column_names = dcc.column_name)
       WHERE ts.table_groups_id = '{TABLE_GROUPS_ID}'
         AND ts.dq_score_exclude = FALSE
         AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY dcc.table_id, dcc.column_id ),
score_calc
  AS (SELECT table_id,
             SUM(affected_data_points) as sum_affected_data_points,
             SUM(row_ct) as sum_data_points
        FROM score_detail
      GROUP BY table_id)
UPDATE data_table_chars
   SET dq_score_testing =
          CASE
            WHEN sum_affected_data_points >= sum_data_points THEN 0
            ELSE (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0) )
          END
  FROM score_calc s
 WHERE data_table_chars.table_id = s.table_id;
