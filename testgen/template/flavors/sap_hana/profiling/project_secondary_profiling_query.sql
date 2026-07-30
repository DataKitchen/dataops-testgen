-- Get Freqs for selected columns
-- One row per top value, ordered by rank. A trailing row with a NULL value carries the
-- combined count of the values past the top 10, and how many distinct values it covers.
WITH ranked_vals AS (
  SELECT "{COL_NAME}" AS val,
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, "{COL_NAME}") AS rn
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
        TABLESAMPLE BERNOULLI({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
   WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' '
   GROUP BY "{COL_NAME}"
),
grouped_vals AS (
  SELECT CASE WHEN rn <= 10 THEN val END AS top_val, ct, rn
    FROM ranked_vals
)
SELECT top_val AS value,
       SUM(ct) AS value_ct,
       MIN(rn) AS value_rank,
       CASE WHEN MIN(rn) > 10 THEN COUNT(*) END AS other_distinct_ct,
       (SELECT LOWER(BINTOHEX(HASH_MD5(TO_BINARY(STRING_AGG("{COL_NAME}", '|' ORDER BY "{COL_NAME}")))))
          FROM (SELECT DISTINCT "{COL_NAME}"
                  FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
                       TABLESAMPLE BERNOULLI({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
                 WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' ')) AS distinct_value_hash
  FROM grouped_vals
 GROUP BY top_val
 ORDER BY 3
