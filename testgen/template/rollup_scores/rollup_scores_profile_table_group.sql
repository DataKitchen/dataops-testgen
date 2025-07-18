-- Roll up latest scores to Table Group
WITH last_profile_date
   AS (SELECT table_groups_id, MAX(profiling_starttime) as last_profile_run_date
         FROM profiling_runs
        WHERE status = 'Complete'
       GROUP BY table_groups_id),
score_calc
  AS (SELECT run.table_groups_id, run.id as profile_run_id,
             run.dq_affected_data_points as sum_affected_data_points,
             run.dq_total_data_points as sum_data_points
        FROM profiling_runs run
      INNER JOIN last_profile_date lp
         ON (run.table_groups_id = lp.table_groups_id
        AND  run.profiling_starttime = lp.last_profile_run_date)
      WHERE run.table_groups_id = :TABLE_GROUPS_ID )
UPDATE table_groups
   SET dq_score_profiling = (1.0 - s.sum_affected_data_points::FLOAT / NULLIF(s.sum_data_points::FLOAT, 0)),
       last_complete_profile_run_id = s.profile_run_id
  FROM score_calc s
 WHERE table_groups.id = s.table_groups_id;

-- Reset scoring in data_column_chars
UPDATE data_column_chars
   SET valid_profile_issue_ct = 0,
       dq_score_profiling = 1,
       last_complete_profile_run_id = tg.last_complete_profile_run_id
  FROM table_groups tg
 WHERE data_column_chars.table_groups_id = tg.id
   AND data_column_chars.table_groups_id = :TABLE_GROUPS_ID;

-- Roll up latest scores to data_column_chars
WITH score_detail
  AS (SELECT dcc.column_id,
             COUNT(p.id) as valid_issue_ct,
             MAX(pr.record_ct) as row_ct,
             COALESCE( (1.0 - SUM_LN(COALESCE(p.dq_prevalence, 0.0))) * MAX(pr.record_ct), 0) as affected_data_points
        FROM table_groups tg
      INNER JOIN profiling_runs r
         ON (tg.last_complete_profile_run_id = r.id)
      INNER JOIN profile_results pr
         ON (r.id = pr.profile_run_id)
      INNER JOIN data_column_chars dcc
         ON (pr.table_groups_id = dcc.table_groups_id
        AND  pr.table_name = dcc.table_name
        AND  pr.column_name = dcc.column_name)
      LEFT JOIN profile_anomaly_results p
        ON (pr.profile_run_id = p.profile_run_id
       AND  pr.column_name = p.column_name
       AND  pr.table_name = p.table_name)
      WHERE tg.id = :TABLE_GROUPS_ID
        AND COALESCE(p.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY dcc.column_id )
UPDATE data_column_chars
   SET valid_profile_issue_ct = COALESCE(s.valid_issue_ct, 0),
       dq_score_profiling = (1.0 - s.affected_data_points::FLOAT / NULLIF(s.row_ct::FLOAT, 0))
  FROM score_detail s
 WHERE data_column_chars.column_id = s.column_id;

-- Reset scoring in data_table_chars
UPDATE data_table_chars
   SET dq_score_profiling = 1,
       last_profile_record_ct = 0,
       last_complete_profile_run_id = tg.last_complete_profile_run_id
  FROM table_groups tg
 WHERE data_table_chars.table_groups_id = tg.id
   AND data_table_chars.table_groups_id = :TABLE_GROUPS_ID;

-- Roll up latest scores to data_table_chars
WITH score_detail
  AS (SELECT dcc.column_id, dcc.table_id,
             MAX(pr.record_ct) as row_ct,
             COALESCE((1.0 - SUM_LN(COALESCE(p.dq_prevalence, 0.0))) * MAX(pr.record_ct), 0) as affected_data_points
        FROM table_groups tg
      INNER JOIN profiling_runs r
         ON (tg.last_complete_profile_run_id = r.id)
      INNER JOIN profile_results pr
         ON (r.id = pr.profile_run_id)
      INNER JOIN data_column_chars dcc
         ON (pr.table_groups_id = dcc.table_groups_id
        AND  pr.table_name = dcc.table_name
        AND  pr.column_name = dcc.column_name)
      LEFT JOIN profile_anomaly_results p
        ON (pr.profile_run_id = p.profile_run_id
       AND  pr.column_name = p.column_name
       AND  pr.table_name = p.table_name)
      WHERE tg.id = :TABLE_GROUPS_ID
        AND COALESCE(p.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY dcc.column_id, dcc.table_id ),
score_calc
  AS ( SELECT table_id,
              SUM(affected_data_points) as sum_affected_data_points,
              SUM(row_ct) as sum_data_points,
              MAX(row_ct) as record_ct
         FROM score_detail
       GROUP BY table_id )
UPDATE data_table_chars
   SET dq_score_profiling = (1.0 - s.sum_affected_data_points::FLOAT / NULLIF(s.sum_data_points::FLOAT, 0)),
       last_profile_record_ct = NULLIF(s.record_ct::FLOAT, 0)
  FROM score_calc s
 WHERE data_table_chars.table_id = s.table_id;
