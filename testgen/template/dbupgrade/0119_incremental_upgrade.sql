SET SEARCH_PATH TO {SCHEMA_NAME};

-- ==============================================================================
-- |  Recalculates Test Scoring for All Table Groups
-- |-----------------------------------------------------------------------------
-- |   Data Quality Scoring
-- |     - Prevalence% * dq_score_risk_factor = calculated prevalence%
-- |     - Save with total datapoints (record count).
-- |     - When scoring, calculate SUM(calculated prevalence * record count)
-- |                                / SUM(record count)
-- ==============================================================================

-- First UPDATE record counts per latest Row_Ct tests
UPDATE data_table_chars
   SET record_ct = test_record_ct
  FROM ( WITH all_latest
                 AS ( SELECT r.table_groups_id, r.table_name, r.test_time,
                             r.result_measure::BIGINT AS test_record_ct
                        FROM test_results r
                        INNER JOIN test_suites s
                              ON r.test_suite_id = s.id
                        INNER JOIN table_groups tg
                              ON r.table_groups_id = tg.id
                           AND r.test_run_id = s.last_complete_test_run_id
                       WHERE test_type = 'Row_Ct'
                         AND result_measure IS NOT NULL ),
              latest_by_table
                 AS ( SELECT table_groups_id, table_name, MAX(test_time) AS max_test_time
                        FROM all_latest
                       GROUP BY table_groups_id, table_name )
       SELECT a.table_groups_id, a.table_name, test_record_ct
         FROM all_latest a
         INNER JOIN latest_by_table l
               ON (a.table_groups_id = l.table_groups_id
            AND a.table_name = l.table_name
            AND a.test_time = l.max_test_time) ) u
WHERE data_table_chars.table_groups_id = u.table_groups_id
  AND data_table_chars.table_name = u.table_name;
  
-- UPDATE prevalence to zero for all passed or excluded tests
UPDATE test_results
   SET dq_record_ct = tc.record_ct,
       dq_prevalence = 0
  FROM test_results r
INNER JOIN data_table_chars tc
  ON (r.table_groups_id = tc.table_groups_id
 AND r.table_name ILIKE tc.table_name)
 WHERE ( r.result_code = 1
    OR r.disposition IN ('Dismissed', 'Inactive') )
   AND test_results.id = r.id;


-- UPDATE TO calculated prevalence for all fails/warnings - result_code = 0
WITH result_calc
   AS ( SELECT r.id,
               tt.dq_score_risk_factor::FLOAT as risk_calc,
               REPLACE( REPLACE( REPLACE( REPLACE( REPLACE( REPLACE( REPLACE(
                REPLACE( REPLACE( REPLACE( REPLACE( REPLACE( REPLACE(
                 tt.dq_score_prevalence_formula,
                 '{RESULT_MEASURE}',      COALESCE(r.result_measure::VARCHAR, '')),
                 '{THRESHOLD_VALUE}',     COALESCE(r.threshold_value::VARCHAR, '')),
         
                 '{PRO_RECORD_CT}',       COALESCE(p.record_ct::VARCHAR, '')),
                 '{DATE_DAYS_PRESENT}',   COALESCE(p.date_days_present::VARCHAR, '')),
                 '{DATE_MONTHS_PRESENT}', COALESCE(p.date_months_present::VARCHAR, '')),
                 '{DATE_WEEKS_PRESENT}',  COALESCE(p.date_weeks_present::VARCHAR, '')),
                 '{MIN_DATE}',            COALESCE(p.min_date::VARCHAR, '')),
                 '{MAX_DATE}',            COALESCE(p.max_date::VARCHAR, '')),
                 '{DISTINCT_VALUE_CT}',   COALESCE(p.distinct_value_ct::VARCHAR, '')),
                 '{VALUE_CT}',            COALESCE(p.value_ct::VARCHAR, '')),
                 '{MAX_LENGTH}',          COALESCE(p.max_length::VARCHAR, '')),
                 '{AVG_LENGTH}',          COALESCE(p.avg_length::VARCHAR, '')),
                 
                 '{RECORD_CT}',           COALESCE(r.dq_record_ct::VARCHAR, tc.record_ct::VARCHAR, ''))
                 as built_score_prevalance_formula,
               COALESCE(r.dq_record_ct, tc.record_ct) as dq_record_ct
          FROM test_results r
          INNER JOIN test_types tt
                ON r.test_type = tt.test_type
          INNER JOIN v_latest_profile_results p
                ON (r.table_groups_id = p.table_groups_id
             AND r.table_name = p.table_name
             AND r.column_names = p.column_name)
          LEFT JOIN data_table_chars tc
                ON (r.table_groups_id = tc.table_groups_id
             AND r.table_name ILIKE tc.table_name)
         WHERE result_code = 0
           AND result_measure IS NOT NULL
           AND NOT COALESCE(disposition, '') IN ('Dismissed', 'Inactive') )
UPDATE test_results
   SET dq_record_ct = c.dq_record_ct,
       -- Prevalence between 0 and 1
       dq_prevalence = LEAST(1.0, risk_calc * fn_eval(c.built_score_prevalance_formula))
  FROM result_calc c
 WHERE test_results.id = c.id;


-- Roll up scoring to test run
WITH score_detail
  AS (SELECT r.test_run_id, r.table_name, r.column_names,
             MAX(r.dq_record_ct) as dq_record_ct,
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0))) * MAX(r.dq_record_ct) as affected_data_points
        FROM test_results r
       WHERE COALESCE(r.disposition, 'Confirmed') = 'Confirmed'
      GROUP BY r.test_run_id, r.table_name, r.column_names ),
score_calc
  AS ( SELECT test_run_id,
              SUM(affected_data_points) as sum_affected_data_points,
              SUM(dq_record_ct) as sum_data_points
         FROM score_detail
       GROUP BY test_run_id )
UPDATE test_runs
   SET dq_affected_data_points = sum_affected_data_points,
       dq_total_data_points = sum_data_points,
       dq_score_test_run =
          CASE
            WHEN sum_affected_data_points >= sum_data_points THEN 0
            ELSE (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0))
          END
  FROM score_calc
 WHERE test_runs.id = score_calc.test_run_id;


-- Roll up scores from latest Test Runs per Test Suite to Table Group
WITH score_calc
  AS (SELECT ts.table_groups_id,
             SUM(run.dq_affected_data_points) as sum_affected_data_points,
             SUM(run.dq_total_data_points) as sum_data_points
        FROM test_runs run
      INNER JOIN test_suites ts
         ON (run.test_suite_id = ts.id
        AND  run.id = ts.last_complete_test_run_id)
      WHERE ts.dq_score_exclude = FALSE
      GROUP BY ts.table_groups_id)
UPDATE table_groups
   SET dq_score_testing =
          CASE
            WHEN sum_affected_data_points >= sum_data_points THEN 0
            ELSE (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0))
          END
  FROM score_calc s
 WHERE table_groups.id = s.table_groups_id;

-- Roll up latest scores to data_column_chars
WITH score_calc
  AS (SELECT dcc.column_id,
             -- Use AVG instead of MAX because column counts may differ by test_run
             AVG(r.dq_record_ct) as row_ct,
             -- bad data pct * record count = affected_data_points
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0))) * AVG(r.dq_record_ct) as affected_data_points
        FROM test_results r
      INNER JOIN test_suites ts
         ON (r.test_suite_id = ts.id
        AND  r.test_run_id = ts.last_complete_test_run_id)
      INNER JOIN data_column_chars dcc
         ON (ts.table_groups_id = dcc.table_groups_id
        AND  r.table_name = dcc.table_name
        AND  r.column_names = dcc.column_name)
       WHERE ts.dq_score_exclude = FALSE
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
             (1.0 - SUM_LN(COALESCE(r.dq_prevalence, 0.0))) * AVG(r.dq_record_ct) as affected_data_points
        FROM test_results r
      INNER JOIN test_suites ts
         ON (r.test_suite_id = ts.id
        AND  r.test_run_id = ts.last_complete_test_run_id)
      INNER JOIN data_column_chars dcc
         ON (ts.table_groups_id = dcc.table_groups_id
        AND  r.table_name = dcc.table_name
        AND  r.column_names = dcc.column_name)
       WHERE ts.dq_score_exclude = FALSE
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
            ELSE (1.0 - sum_affected_data_points::FLOAT / NULLIF(sum_data_points::FLOAT, 0))
          END
  FROM score_calc s
 WHERE data_table_chars.table_id = s.table_id;
