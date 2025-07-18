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
      WHERE ts.table_groups_id = :TABLE_GROUPS_ID
        AND ts.dq_score_exclude = FALSE
      GROUP BY ts.table_groups_id)
UPDATE table_groups
   SET dq_score_testing = (1.0 - s.sum_affected_data_points::FLOAT / NULLIF(s.sum_data_points::FLOAT, 0))
  FROM score_calc s
 WHERE table_groups.id = s.table_groups_id;

 -- Reset scoring in data_column_chars
UPDATE data_column_chars
   SET valid_test_issue_ct = 0,
       dq_score_testing = 1
 WHERE table_groups_id = :TABLE_GROUPS_ID;

-- Roll up latest scores to data_column_chars -- excludes multi-column tests
WITH score_calc
  AS (SELECT dcc.column_id,
             SUM(1 - r.result_code) as issue_ct,
             -- Use AVG instead of MAX because column counts may differ by test_run
             AVG(r.dq_record_ct) as row_ct,
             -- bad data pct * record count = affected_data_points
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0))) * AVG(r.dq_record_ct) as affected_data_points
        FROM data_column_chars dcc
      LEFT JOIN (test_results r
                  INNER JOIN test_suites ts
                     ON (r.test_suite_id = ts.id
                    AND  r.test_run_id = ts.last_complete_test_run_id))
         ON (dcc.table_groups_id = ts.table_groups_id
        AND  dcc.table_name = r.table_name
        AND  dcc.column_name = r.column_names)
       WHERE dcc.table_groups_id = :TABLE_GROUPS_ID
         AND COALESCE(ts.dq_score_exclude, FALSE) = FALSE
         AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY dcc.column_id )
UPDATE data_column_chars
   SET valid_test_issue_ct = COALESCE(issue_ct, 0),
       dq_score_testing = (1.0 - affected_data_points::FLOAT / NULLIF(row_ct::FLOAT, 0))
  FROM score_calc s
 WHERE data_column_chars.column_id = s.column_id;

-- Reset scoring in data_table_chars
UPDATE data_table_chars
   SET dq_score_testing = 1
 WHERE table_groups_id = :TABLE_GROUPS_ID;

-- Roll up latest scores to data_table_chars -- includes multi-column tests
WITH score_detail
  AS (SELECT dtc.table_id, r.column_names,
             -- Use AVG instead of MAX because column counts may differ by test_run
             AVG(r.dq_record_ct) as row_ct,
             -- bad data pct * record count = affected_data_points
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0))) * AVG(r.dq_record_ct) as affected_data_points
        FROM data_table_chars dtc
      LEFT JOIN (test_results r
                  INNER JOIN test_suites ts
                     ON (r.test_suite_id = ts.id
                    AND  r.test_run_id = ts.last_complete_test_run_id))
         ON (dtc.table_groups_id = ts.table_groups_id
        AND  dtc.table_name = r.table_name)
       WHERE dtc.table_groups_id = :TABLE_GROUPS_ID
         AND COALESCE(ts.dq_score_exclude, FALSE) = FALSE
         AND COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY dtc.table_id, r.column_names),
score_calc
  AS (SELECT table_id,
             SUM(affected_data_points) as sum_affected_data_points,
             SUM(row_ct) as sum_data_points
        FROM score_detail
      GROUP BY table_id)
UPDATE data_table_chars
   SET dq_score_testing = (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0) )
  FROM score_calc s
 WHERE data_table_chars.table_id = s.table_id;
