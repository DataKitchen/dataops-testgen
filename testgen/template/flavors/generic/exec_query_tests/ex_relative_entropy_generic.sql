-- Relative Entropy:  measured by Jensen-Shannon Divergence
--   Smoothed and normalized version of KL divergence,
--   with scores between 0 (identical) and 1 (maximally different),
--   when using the base-2 logarithm.   Formula is:
--   0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m)
--   Log base 2 of x = LN(x)/LN(2)
WITH latest_ver
   AS ( SELECT COALESCE({GROUPBY_NAMES}, '<NULL>') as category,
               COUNT(*)::FLOAT / SUM(COUNT(*)) OVER ()::FLOAT AS pct_of_total
          FROM {SCHEMA_NAME}.{TABLE_NAME} v1
         WHERE {SUBSET_CONDITION}
         GROUP BY 1 ),
older_ver
   AS ( SELECT COALESCE({MATCH_GROUPBY_NAMES}, '<NULL>') as category,
               COUNT(*)::FLOAT / SUM(COUNT(*)) OVER ()::FLOAT AS pct_of_total
          FROM {MATCH_SCHEMA_NAME}.{TABLE_NAME} v2
         WHERE {MATCH_SUBSET_CONDITION}
         GROUP BY 1 ),
dataset
   AS ( SELECT COALESCE(l.category, o.category) AS category,
               COALESCE(o.pct_of_total, 0.0000001)        AS old_pct,
               COALESCE(l.pct_of_total, 0.0000001)        AS new_pct,
               (COALESCE(o.pct_of_total, 0.0000001)
                + COALESCE(l.pct_of_total, 0.0000001))/2.0 AS avg_pct
          FROM latest_ver l
          FULL JOIN older_ver o
            ON (l.category = o.category) )
SELECT '{PROJECT_CODE}' as project_code, '{TEST_TYPE}' as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE}' as test_suite,
       '{RUN_DATE}' as test_time, '{START_TIME}' as starttime, GETDATE() as endtime,
       '{SCHEMA_NAME}' as schema_name, '{TABLE_NAME}' as table_name, '{GROUPBY_NAMES}' as column_names,
       NULL as skip_errors,
       'schema_name = {SCHEMA_NAME}, matching_schema = {MATCH_SCHEMA_NAME}, table_name = {TABLE_NAME}, column_names = {GROUPBY_NAMES}, subset_condition = {SUBSET_CONDITION}'
         as input_parameters,
       CASE WHEN js_divergence <= {THRESHOLD_VALUE} THEN 0 ELSE 1 END as result_code,
       CONCAT('Divergence Level: ',
              CONCAT(CAST(js_divergence AS VARCHAR),
                     ', Threshold: {THRESHOLD_VALUE}.')) as result_message,
       COUNT(*) as result_measure,
       '{TEST_ACTION}' as test_action,
       '{SUBSET_CONDITION}' as subset_condition,
       NULL as result_query,
       '{TEST_DESCRIPTION}' as test_description
  FROM (
         SELECT 0.5 * ABS(SUM(new_pct * LN(new_pct/avg_pct)/LN(2)))
                 + 0.5 * ABS(SUM(old_pct * LN(old_pct/avg_pct)/LN(2))) as js_divergence
           FROM dataset ) rslt;
