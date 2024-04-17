-- Get Freqs for selected columns
WITH ranked_vals AS (
  SELECT "{COL_NAME}",
         COUNT(*) AS ct,
         ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, "{COL_NAME}") AS rn
    FROM {DATA_SCHEMA}.{DATA_TABLE}
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
       REPLACE(LISTAGG(val, '^#^') WITHIN GROUP (ORDER BY min_rn), '^#^', CHR(10)) AS top_freq_values,
       ( SELECT MD5(LISTAGG(DISTINCT "{COL_NAME}", '|')
                           WITHIN GROUP (ORDER BY "{COL_NAME}")) as dvh
           FROM {DATA_SCHEMA}.{DATA_TABLE} ) as distinct_value_hash
  FROM consol_vals;
