-- Relative Entropy:  measured by Jensen-Shannon Divergence
--   Smoothed and normalized version of KL divergence,
--   with scores between 0 (identical) and 1 (maximally different),
--   when using the base-2 logarithm.   Formula is:
--   0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m)
--   Log base 2 of x = LN(x)/LN(2)
WITH latest_ver AS (
  SELECT {CONCAT_COLUMNS} AS category,
         CAST(COUNT(*) AS FLOAT64) / CAST(SUM(COUNT(*)) OVER () AS FLOAT64) AS pct_of_total
  FROM `{SCHEMA_NAME}.{TABLE_NAME}` v1
  WHERE {SUBSET_CONDITION}
  GROUP BY {COLUMN_NAME_NO_QUOTES}
),
older_ver AS (
  SELECT {CONCAT_MATCH_GROUPBY} AS category,
         CAST(COUNT(*) AS FLOAT64) / CAST(SUM(COUNT(*)) OVER () AS FLOAT64) AS pct_of_total
  FROM `{MATCH_SCHEMA_NAME}.{TABLE_NAME}` v2
  WHERE {MATCH_SUBSET_CONDITION}
  GROUP BY {MATCH_GROUPBY_NAMES}
),
dataset AS (
  SELECT COALESCE(l.category, o.category) AS category,
         COALESCE(o.pct_of_total, 0.0000001) AS old_pct,
         COALESCE(l.pct_of_total, 0.0000001) AS new_pct,
         (COALESCE(o.pct_of_total, 0.0000001) + COALESCE(l.pct_of_total, 0.0000001)) / 2.0 AS avg_pct
  FROM latest_ver l
  FULL JOIN older_ver o
    ON l.category = o.category
)
SELECT '{TEST_TYPE}' AS test_type,
       '{TEST_DEFINITION_ID}' AS test_definition_id,
       '{TEST_SUITE_ID}' AS test_suite_id,
       '{TEST_RUN_ID}' AS test_run_id,
       '{RUN_DATE}' AS test_time,
       '{SCHEMA_NAME}' AS schema_name,
       '{TABLE_NAME}' AS table_name,
       '{COLUMN_NAME_NO_QUOTES}' AS column_names,
       -- '{GROUPBY_NAMES}' as column_names,
       '{THRESHOLD_VALUE}' AS threshold_value,
       NULL AS skip_errors,
       '{INPUT_PARAMETERS}' AS input_parameters,
       NULL as result_signal,
       CASE WHEN js_divergence > {THRESHOLD_VALUE} THEN 0 ELSE 1 END AS result_code,
       CONCAT('Divergence Level: ', CAST(js_divergence AS STRING), ', Threshold: {THRESHOLD_VALUE}.') AS result_message,
       js_divergence AS result_measure
FROM (
  SELECT 0.5 * ABS(SUM(new_pct * LN(new_pct/avg_pct)/LN(2)))
         + 0.5 * ABS(SUM(old_pct * LN(old_pct/avg_pct)/LN(2))) AS js_divergence
  FROM dataset
) rslt;
