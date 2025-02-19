SET SEARCH_PATH TO {SCHEMA_NAME};

-- Patch column_id in profile_anomaly_results
UPDATE profile_anomaly_results
   SET column_id = u.column_id
  FROM (
         SELECT par.id, dcc.column_id
           FROM data_column_chars dcc
         INNER JOIN profile_anomaly_results par
           ON (dcc.table_groups_id = par.table_groups_id
          AND  dcc.table_name = par.table_name
          AND  dcc.column_name = par.column_name)
         WHERE par.column_id IS NULL ) u
 WHERE profile_anomaly_results.id = u.id;

-- ==============================================================================
-- |   Recalculates Profile Scoring for All Table Groups
-- ==============================================================================

DO $$
DECLARE
    rpr       RECORD;
    rat       RECORD;
    qtemplate TEXT;
    query     TEXT;
    ptg       RECORD;
BEGIN

    qtemplate := E'
        UPDATE profile_anomaly_results r
           SET dq_prevalence = ({PREV}) * {RISK}
          FROM profile_anomaly_results r2
        INNER JOIN profile_results p
           ON (r2.profile_run_id = p.profile_run_id
          AND  r2.table_name = p.table_name
          AND  r2.column_name = p.column_name)
         WHERE r2.profile_run_id = \'{RUN}\'::UUID
           AND r2.anomaly_id = \'{ANID}\'
           AND r.id = r2.id
';

   FOR rpr IN SELECT id FROM profiling_runs WHERE status = 'Complete'
   LOOP
      
      FOR rat IN SELECT t.id::VARCHAR as anomaly_id, t.dq_score_prevalence_formula, t.dq_score_risk_factor
                  FROM profile_anomaly_types t
                INNER JOIN (SELECT DISTINCT anomaly_id
                              FROM profile_anomaly_results
                             WHERE profile_run_id = rpr.id) at
                   ON (t.id = at.anomaly_id)
                 WHERE t.dq_score_prevalence_formula  IS NOT NULL
                   AND t.dq_score_risk_factor IS NOT NULL
      LOOP
         query := REPLACE(qtemplate, '{RUN}',  rpr.id::VARCHAR );
         query := REPLACE(query,          '{ANID}',  rat.anomaly_id );
         query := REPLACE(query,          '{PREV}', rat.dq_score_prevalence_formula );
         query := REPLACE(query,          '{RISK}', rat.dq_score_risk_factor );
      
         EXECUTE query;
         -- RAISE NOTICE 'QUERY: %1', query;
         
      END LOOP;
      
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
            WHERE pr.profile_run_id = rpr.id
              AND COALESCE(p.disposition, 'Confirmed') = 'Confirmed'
            GROUP BY pr.profile_run_id, pr.table_name, pr.column_name ),
      score_calc
        AS ( SELECT profile_run_id,
                    SUM(affected_data_points) as sum_affected_data_points,
                    SUM(row_ct) as sum_data_points
               FROM score_detail
             GROUP BY profile_run_id )
      UPDATE profiling_runs
         SET dq_affected_data_points = sum_affected_data_points,
             dq_total_data_points = sum_data_points,
             dq_score_profiling =
                CASE
                  WHEN sum_affected_data_points >= sum_data_points THEN 0
                  ELSE (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0))
                END
        FROM score_calc
       WHERE profiling_runs.id = score_calc.profile_run_id;
    
   END LOOP;

   FOR ptg IN SELECT DISTINCT table_groups_id FROM profiling_runs WHERE status = 'Complete'
   LOOP
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
            WHERE run.table_groups_id = ptg.table_groups_id )
      UPDATE table_groups
         SET dq_score_profiling =
                CASE
                  WHEN  s.sum_affected_data_points >= s.sum_data_points THEN 0
                  ELSE (1.0 - s.sum_affected_data_points::FLOAT / NULLIF(s.sum_data_points::FLOAT, 0))
                END,
             last_complete_profile_run_id = s.profile_run_id
        FROM score_calc s
       WHERE table_groups.id = s.table_groups_id;
      
      -- Roll up latest scores to data_column_chars
      WITH score_detail
        AS (SELECT dcc.column_id, tg.last_complete_profile_run_id,
                   COUNT(p.id) as valid_issue_ct,
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
            WHERE tg.id = ptg.table_groups_id
              AND COALESCE(p.disposition, 'Confirmed') = 'Confirmed'
            GROUP BY dcc.column_id, tg.last_complete_profile_run_id )
      UPDATE data_column_chars
         SET dq_score_profiling =
               CASE
                 WHEN s.affected_data_points >= s.row_ct THEN 0
                 ELSE (1.0 - s.affected_data_points::FLOAT / NULLIF(s.row_ct::FLOAT, 0))
               END,
             valid_profile_issue_ct = s.valid_issue_ct,
             last_complete_profile_run_id = s.last_complete_profile_run_id
        FROM score_detail s
       WHERE data_column_chars.column_id = s.column_id;
      
      -- Roll up latest scores to data_table_chars
      WITH score_detail
        AS (SELECT dcc.column_id, dcc.table_id, tg.last_complete_profile_run_id,
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
            WHERE tg.id = ptg.table_groups_id
              AND COALESCE(p.disposition, 'Confirmed') = 'Confirmed'
            GROUP BY dcc.column_id, dcc.table_id, tg.last_complete_profile_run_id ),
      score_calc
        AS ( SELECT table_id, last_complete_profile_run_id,
                    SUM(affected_data_points) as sum_affected_data_points,
                    SUM(row_ct) as sum_data_points
               FROM score_detail
             GROUP BY table_id, last_complete_profile_run_id )
      UPDATE data_table_chars
         SET dq_score_profiling =
               CASE
                 WHEN s.sum_affected_data_points >= s.sum_data_points THEN 0
                 ELSE (1.0 - s.sum_affected_data_points::FLOAT / NULLIF(s.sum_data_points::FLOAT, 0))
               END,
             last_complete_profile_run_id = s.last_complete_profile_run_id
        FROM score_calc s
       WHERE data_table_chars.table_id = s.table_id;
      
   END LOOP;
   
END;
$$;
