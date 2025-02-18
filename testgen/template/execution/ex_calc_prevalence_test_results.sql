-- ==============================================================================
-- |   Data Quality Scoring
-- |     - Prevalence % * dq_score_risk_factor = calculated prevalence %
-- |     - Save with total datapoints (record count).
-- |     - When scoring, calculate SUM(calculated prevalence * record count)
-- |                                / SUM(record count)
-- ==============================================================================

-- Initialize prevalence to zero for all tests
UPDATE test_results
   SET dq_record_ct = tc.record_ct,
       dq_prevalence = 0
  FROM test_results r
INNER JOIN data_table_chars tc
  ON (r.table_groups_id = tc.table_groups_id
 AND r.table_name ILIKE tc.table_name)
 WHERE r.test_run_id = '{TEST_RUN_ID}'::UUID
   AND test_results.id = r.id;

-- PROFILED COLUMN TESTS:  Update to calculated prevalence for all fails/warnings - result_code = 0
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
         WHERE r.test_run_id = '{TEST_RUN_ID}'::UUID
           AND result_code = 0
           AND r.result_measure IS NOT NULL
           AND tt.test_scope = 'column'
           AND NOT COALESCE(disposition, '') IN ('Dismissed', 'Inactive') )
UPDATE test_results
   SET dq_record_ct = c.dq_record_ct,
       dq_prevalence = LEAST(1.0, risk_calc * fn_eval(c.built_score_prevalance_formula))
  FROM result_calc c
 WHERE test_results.id = c.id;

-- UNPROFILED TESTS (non-column): Update to calculated prevalence for all fails/warnings - result_code = 0
WITH result_calc
   AS ( SELECT r.id,
               tt.dq_score_risk_factor::FLOAT as risk_calc,
               REPLACE( REPLACE( REPLACE(
                 tt.dq_score_prevalence_formula,
                 '{RESULT_MEASURE}',      COALESCE(r.result_measure::VARCHAR, '')),
                 '{THRESHOLD_VALUE}',     COALESCE(r.threshold_value::VARCHAR, '')),
                 '{RECORD_CT}',           COALESCE(r.dq_record_ct::VARCHAR, tc.record_ct::VARCHAR, ''))
                 as built_score_prevalance_formula,
               COALESCE(r.dq_record_ct, tc.record_ct) as dq_record_ct
          FROM test_results r
          INNER JOIN test_types tt
                ON r.test_type = tt.test_type
          INNER JOIN data_table_chars tc
                ON (r.table_groups_id = tc.table_groups_id
             AND r.table_name ILIKE tc.table_name)
         WHERE r.test_run_id = '{TEST_RUN_ID}'::UUID
           AND result_code = 0
           AND r.result_measure IS NOT NULL
           AND tt.test_scope <> 'column'
           AND NOT COALESCE(disposition, '') IN ('Dismissed', 'Inactive') )
UPDATE test_results
   SET dq_record_ct = c.dq_record_ct,
       dq_prevalence = LEAST(1.0, risk_calc * fn_eval(c.built_score_prevalance_formula))
  FROM result_calc c
 WHERE test_results.id = c.id;
