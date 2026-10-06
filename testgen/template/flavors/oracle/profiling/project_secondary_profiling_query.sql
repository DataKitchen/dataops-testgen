-- Get Freqs for selected columns
-- One row per top value, ordered by rank. A trailing row with a NULL value carries the
-- combined count of the values past the top 10, and how many distinct values it covers.
WITH ranked_vals AS (
  SELECT "{COL_NAME}" AS val,
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, NLSSORT("{COL_NAME}", 'NLS_SORT=BINARY')) AS rn
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
        SAMPLE ({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
   WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' '
   GROUP BY "{COL_NAME}"
),
grouped_vals AS (
  SELECT CASE WHEN rn <= 10 THEN val END AS top_val, ct, rn
    FROM ranked_vals
),
hash_val AS (
  -- LISTAGG returns VARCHAR2, so a list past 4000 bytes gets no hash rather than failing the query
  SELECT LOWER(RAWTOHEX(STANDARD_HASH(
           LISTAGG(val, '|') WITHIN GROUP (ORDER BY NLSSORT(val, 'NLS_SORT=BINARY')), 'MD5'))) as hash_result
    FROM (SELECT val, SUM(LENGTHB(val)) OVER () + COUNT(*) OVER () - 1 AS list_bytes, COUNT(*) OVER () AS distinct_ct
            FROM (SELECT DISTINCT TO_CHAR("{COL_NAME}") AS val
                    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
                         SAMPLE ({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
                   WHERE "{COL_NAME}" IS NOT NULL))
   WHERE list_bytes <= 4000 AND distinct_ct <= 70
)
SELECT top_val AS value,
       SUM(ct) AS value_ct,
       MIN(rn) AS value_rank,
       CASE WHEN MIN(rn) > 10 THEN COUNT(*) END AS other_distinct_ct,
       (SELECT hash_result FROM hash_val) AS distinct_value_hash
  FROM grouped_vals
 GROUP BY top_val
 ORDER BY 3
