-- Get Freqs for selected columns
-- One row per top value, ordered by rank. A trailing row with a NULL value carries the
-- combined count of the values past the top 10, and how many distinct values it covers.
-- Every row also carries sample_value_ct, the number of non-null values the read held, blank ones
-- included. Blank values are ranked after every other value so that they never reach the output.
WITH target_table AS (
  SELECT {COL_VALUE} AS "{COL_NAME}" FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
     WHERE RAND() <= 1.0 / {PROFILE_SAMPLE_RATIO}
-- TG-ENDIF
),
-- Grouped by bytes: comparisons ignore trailing blanks whatever the collation, and a list of expected
-- values built from merged values would leave the others out
ranked_vals AS (
  SELECT MIN("{COL_NAME}") AS val,
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY CASE WHEN MIN("{COL_NAME}") > ' ' THEN 0 ELSE 1 END, COUNT(*) DESC,
                                     COLLATE(MIN("{COL_NAME}"), 'case_sensitive'), OCTET_LENGTH(MIN("{COL_NAME}"))) AS rn,
         SUM(COUNT(*)) OVER () AS sample_value_ct
    FROM target_table
   WHERE "{COL_NAME}" IS NOT NULL
   GROUP BY TO_VARBYTE(CAST("{COL_NAME}" AS VARCHAR(65535)), 'utf8')
),
grouped_vals AS (
  SELECT CASE WHEN rn <= 10 THEN val END AS top_val, CASE WHEN rn <= 10 THEN rn END AS top_rn, ct, rn, sample_value_ct
    FROM ranked_vals
    WHERE val > ' '
)
SELECT MIN(top_val) AS value,
       SUM(ct) AS value_ct,
       MIN(rn) AS value_rank,
       CASE WHEN MIN(rn) > 10 THEN COUNT(*) END AS other_distinct_ct,
       MAX(sample_value_ct) AS sample_value_ct,
       ( SELECT CASE WHEN COUNT(*) <= 70
                     THEN MD5(LISTAGG(val, '|') WITHIN GROUP (ORDER BY COLLATE(val, 'case_sensitive'))) END
           FROM ( SELECT DISTINCT COLLATE("{COL_NAME}", 'case_sensitive') AS val
                    FROM target_table
                   WHERE "{COL_NAME}" IS NOT NULL ) distinct_vals ) AS distinct_value_hash
  FROM grouped_vals
 -- By rank, not by value: grouping the text would merge the byte-distinct values again
 GROUP BY top_rn
 ORDER BY 3;
