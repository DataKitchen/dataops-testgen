-- Get Freqs for selected columns
-- One row per top value, ordered by rank. A trailing row with a NULL value carries the
-- combined count of the values past the top 10, and how many distinct values it covers.
WITH counts AS (
  SELECT
    `{COL_NAME}` AS col_val,
    COUNT(*) AS ct
  FROM `{DATA_SCHEMA}.{DATA_TABLE}`
  WHERE `{COL_NAME}` > ' '
-- TG-IF do_sample_bool
    AND RAND() * 100 < {SAMPLE_PERCENT_CALC}
-- TG-ENDIF
  GROUP BY `{COL_NAME}`
),
ranked AS (
  SELECT
    col_val,
    ct,
    ROW_NUMBER() OVER (ORDER BY ct DESC, col_val ASC) AS rn
  FROM counts
),
grouped_vals AS (
  SELECT CASE WHEN rn <= 10 THEN col_val END AS top_val, ct, rn
  FROM ranked
)
SELECT
  top_val AS value,
  SUM(ct) AS value_ct,
  MIN(rn) AS value_rank,
  CASE WHEN MIN(rn) > 10 THEN COUNT(*) END AS other_distinct_ct,
  (SELECT TO_HEX(MD5(STRING_AGG(CAST(col_val AS STRING), '|' ORDER BY col_val)))
     FROM counts
  ) AS distinct_value_hash
FROM grouped_vals
GROUP BY top_val
ORDER BY 3;
