-- Get Freqs for selected columns
WITH target_table AS (
  SELECT *  FROM "{DATA_TABLE}"
-- TG-IF do_sample_bool
        ORDER BY RANDOM() LIMIT {SAMPLE_SIZE}
-- TG-ENDIF
),
ranked_vals AS (
  SELECT "{COL_NAME}",
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, "{COL_NAME}") AS rn
    FROM target_table
   WHERE "{COL_NAME}" > ' '
   GROUP BY "{COL_NAME}"
),
consol_vals AS (
  SELECT COALESCE(CASE WHEN rn <= 10 THEN '| ' || "{COL_NAME}" || ' | ' || CAST(ct AS VARCHAR)
                       ELSE NULL
                  END, '| Other Values (' || CAST(COUNT(DISTINCT "{COL_NAME}")  as VARCHAR) || ') | '  || CAST(SUM(ct)  as VARCHAR) ) AS val,
         MIN(rn) as min_rn
    FROM ranked_vals
   GROUP BY CASE WHEN rn <= 10 THEN '| ' || "{COL_NAME}" || ' | ' || CAST(ct AS VARCHAR)
                 ELSE NULL
            END
)
SELECT '{PROJECT_CODE}' as project_code,
       '{DATA_SCHEMA}' as schema_name,
       '{RUN_DATE}' as run_date,
       '{DATA_TABLE}' as table_name,
       '{COL_NAME}' as column_name,
       REPLACE(ARRAY_JOIN(ARRAY_AGG(val), '^#^'), '^#^', CHR(10)) AS top_freq_values,
       ( SELECT MD5(ARRAY_JOIN(ARRAY_AGG(v), '|')) as dvh
           FROM (SELECT DISTINCT NULLIF("{COL_NAME}", '') AS v
                   FROM target_table
                  WHERE NULLIF("{COL_NAME}", '') IS NOT NULL
                  ORDER BY v) sorted_vals ) as distinct_value_hash
  FROM (SELECT * FROM consol_vals ORDER BY min_rn LIMIT 11) ordered_vals;
