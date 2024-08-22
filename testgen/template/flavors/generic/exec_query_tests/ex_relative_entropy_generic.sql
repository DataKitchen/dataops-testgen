-- Relative Entropy:  measured by Jensen-Shannon Divergence
--   Smoothed and normalized version of KL divergence,
--   with scores between 0 (identical) and 1 (maximally different),
--   when using the base-2 logarithm.   Formula is:
--   0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m)
--   Log base 2 of x = LN(x)/LN(2)
WITH latest_ver
   AS ( SELECT {CONCAT_COLUMNS} as category,
               COUNT(*)::FLOAT / SUM(COUNT(*)) OVER ()::FLOAT AS pct_of_total
          FROM {SCHEMA_NAME}.{TABLE_NAME} v1
         WHERE {SUBSET_CONDITION}
         GROUP BY {COLUMN_NAME_NO_QUOTES} ),
older_ver
   AS ( SELECT {CONCAT_MATCH_GROUPBY} as category,
               COUNT(*)::FLOAT / SUM(COUNT(*)) OVER ()::FLOAT AS pct_of_total
          FROM {MATCH_SCHEMA_NAME}.{TABLE_NAME} v2
         WHERE {MATCH_SUBSET_CONDITION}
         GROUP BY {MATCH_GROUPBY_NAMES} ),
dataset
   AS ( SELECT COALESCE(l.category, o.category) AS category,
               COALESCE(o.pct_of_total, 0.0000001)        AS old_pct,
               COALESCE(l.pct_of_total, 0.0000001)        AS new_pct,
               (COALESCE(o.pct_of_total, 0.0000001)
                + COALESCE(l.pct_of_total, 0.0000001))/2.0 AS avg_pct
          FROM latest_ver l
          FULL JOIN older_ver o
            ON (l.category = o.category) )
SELECT '{TEST_TYPE}' as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE_ID}' as test_suite_id,
       '{TEST_RUN_ID}' as test_run_id,
       '{RUN_DATE}' as test_time,
       '{START_TIME}' as starttime,
       CURRENT_TIMESTAMP as endtime,
       '{SCHEMA_NAME}' as schema_name,
       '{TABLE_NAME}' as table_name,
       '{COLUMN_NAME_NO_QUOTES}' as column_names,
--        '{GROUPBY_NAMES}' as column_names,
       '{THRESHOLD_VALUE}' as threshold_value,
       NULL as skip_errors,
       '{INPUT_PARAMETERS}' as input_parameters,
       CASE WHEN js_divergence > {THRESHOLD_VALUE} THEN 0 ELSE 1 END as result_code,
       CONCAT('Divergence Level: ',
              CONCAT(CAST(js_divergence AS VARCHAR),
                     ', Threshold: {THRESHOLD_VALUE}.')) as result_message,
       js_divergence as result_measure,
       '{SUBSET_DISPLAY}' as subset_condition,
       NULL as result_query
  FROM (
         SELECT 0.5 * ABS(SUM(new_pct * LN(new_pct/avg_pct)/LN(2)))
                 + 0.5 * ABS(SUM(old_pct * LN(old_pct/avg_pct)/LN(2))) as js_divergence
           FROM dataset ) rslt;
