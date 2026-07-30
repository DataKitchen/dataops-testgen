-- Get Freqs for selected columns
-- One row per top value, ordered by rank. A trailing row with a NULL value carries the
-- combined count of the values past the top 10, and how many distinct values it covers.
WITH target_table AS (
  SELECT *  FROM "{DATA_TABLE}"
-- TG-IF do_sample_bool
        ORDER BY RANDOM() LIMIT {SAMPLE_SIZE}
-- TG-ENDIF
),
ranked_vals AS (
  SELECT "{COL_NAME}" AS val,
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, "{COL_NAME}") AS rn
    FROM target_table
   WHERE "{COL_NAME}" > ' '
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
       ( SELECT MD5(ARRAY_JOIN(ARRAY_AGG(v), '|')) as dvh
           FROM (SELECT DISTINCT NULLIF("{COL_NAME}", '') AS v
                   FROM target_table
                  WHERE NULLIF("{COL_NAME}", '') IS NOT NULL
                  ORDER BY v) sorted_vals ) AS distinct_value_hash
  FROM grouped_vals
 GROUP BY top_val
 ORDER BY 3;
