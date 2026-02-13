-- Get Freqs for selected columns
WITH ranked_vals AS (
  SELECT "{COL_NAME}",
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, "{COL_NAME}") AS rn
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
        TABLESAMPLE BERNOULLI({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
   WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' '
   GROUP BY "{COL_NAME}"
),
consol_vals AS (
  SELECT COALESCE(CASE WHEN rn <= 10 THEN '| ' || "{COL_NAME}" || ' | ' || TO_VARCHAR(ct)
                       ELSE NULL
                  END, '| Other Values (' || TO_VARCHAR(COUNT(DISTINCT "{COL_NAME}")) || ') | ' || TO_VARCHAR(SUM(ct))) AS val,
         MIN(rn) as min_rn
    FROM ranked_vals
   GROUP BY CASE WHEN rn <= 10 THEN '| ' || "{COL_NAME}" || ' | ' || TO_VARCHAR(ct)
                 ELSE NULL
            END
)
SELECT '{PROJECT_CODE}' as project_code,
       '{DATA_SCHEMA}' as schema_name,
       '{RUN_DATE}' as run_date,
       '{DATA_TABLE}' as table_name,
       '{COL_NAME}' as column_name,
       REPLACE(STRING_AGG(val, '^#^' ORDER BY min_rn), '^#^', CHAR(10)) AS top_freq_values,
       (SELECT LOWER(BINTOHEX(HASH_MD5(TO_BINARY(STRING_AGG("{COL_NAME}", '|' ORDER BY "{COL_NAME}")))))
          FROM (SELECT DISTINCT "{COL_NAME}"
                  FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-IF do_sample_bool
                       TABLESAMPLE BERNOULLI({SAMPLE_PERCENT_CALC})
-- TG-ENDIF
                 WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' ')) as distinct_value_hash
  FROM consol_vals
