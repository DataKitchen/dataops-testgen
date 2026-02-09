-- Get Freqs for selected columns
WITH ranked_vals AS (
  SELECT "{COL_NAME}",
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, "{COL_NAME}") AS rn
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
        SAMPLE ({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
   WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' '
   GROUP BY "{COL_NAME}"
),
consol_vals AS (
  SELECT COALESCE(CASE WHEN rn <= 10 THEN '| ' || "{COL_NAME}" || ' | ' || TO_CHAR(ct)
                       ELSE NULL
                  END, '| Other Values (' || TO_CHAR(COUNT(DISTINCT "{COL_NAME}")) || ') | ' || TO_CHAR(SUM(ct))) AS val,
         MIN(rn) as min_rn
    FROM ranked_vals
   GROUP BY CASE WHEN rn <= 10 THEN '| ' || "{COL_NAME}" || ' | ' || TO_CHAR(ct)
                 ELSE NULL
            END
),
hash_val AS (
  SELECT RAWTOHEX(STANDARD_HASH(LISTAGG("{COL_NAME}", '|') WITHIN GROUP (ORDER BY "{COL_NAME}"), 'MD5')) as hash_result
    FROM (SELECT DISTINCT "{COL_NAME}"
            FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
                 SAMPLE ({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
           WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' ')
)
SELECT '{PROJECT_CODE}' as project_code,
       '{DATA_SCHEMA}' as schema_name,
       '{RUN_DATE}' as run_date,
       '{DATA_TABLE}' as table_name,
       '{COL_NAME}' as column_name,
       REPLACE(LISTAGG(val, '^#^') WITHIN GROUP (ORDER BY min_rn), '^#^', CHR(10)) AS top_freq_values,
       MAX(h.hash_result) as distinct_value_hash
  FROM consol_vals
  CROSS JOIN hash_val h
  GROUP BY h.hash_result
