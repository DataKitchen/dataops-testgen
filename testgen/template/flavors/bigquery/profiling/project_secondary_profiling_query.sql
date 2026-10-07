-- Get Freqs for selected columns
-- One row per top value, ordered by rank. A trailing row with a NULL value carries the
-- combined count of the values past the top 10, and how many distinct values it covers.
-- Every row also carries sample_value_ct, the number of non-null values the read held, blank ones
-- included. Blank values are ranked after every other value so that they never reach the output.
WITH counts AS (
  SELECT
    `{COL_NAME}` AS col_val,
    COUNT(*) AS ct
  FROM `{DATA_SCHEMA}.{DATA_TABLE}`
  WHERE `{COL_NAME}` IS NOT NULL
-- TG-IF do_sample_bool
    AND RAND() * 100 < {SAMPLE_PERCENT_CALC}
-- TG-ENDIF
  GROUP BY `{COL_NAME}`
),
ranked AS (
  SELECT
    col_val,
    ct,
    ROW_NUMBER() OVER (ORDER BY CASE WHEN col_val > ' ' THEN 0 ELSE 1 END, ct DESC, CAST(col_val AS BYTES) ASC) AS rn,
    SUM(ct) OVER () AS sample_value_ct
  FROM counts
),
grouped_vals AS (
  SELECT CASE WHEN rn <= 10 THEN col_val END AS top_val, ct, rn, sample_value_ct
  FROM ranked
  WHERE col_val > ' '
)
SELECT
  top_val AS value,
  SUM(ct) AS value_ct,
  MIN(rn) AS value_rank,
  CASE WHEN MIN(rn) > 10 THEN COUNT(*) END AS other_distinct_ct,
  MAX(sample_value_ct) AS sample_value_ct,
  (SELECT CASE WHEN COUNT(*) <= 70 THEN TO_HEX(MD5(STRING_AGG(CAST(col_val AS STRING), '|' ORDER BY CAST(col_val AS BYTES)))) END
     FROM counts
  ) AS distinct_value_hash
FROM grouped_vals
GROUP BY top_val
ORDER BY 3;
