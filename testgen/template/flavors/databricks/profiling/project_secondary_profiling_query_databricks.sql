-- Get Freqs for selected columns
WITH ranked_vals
AS
    (SELECT `{COL_NAME}`,
            COUNT(*) AS  ct,
            ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS rn
     FROM {DATA_SCHEMA}.{DATA_TABLE}
     WHERE `{COL_NAME}` > ' '
     GROUP BY `{COL_NAME}`
    ),
consol_vals
AS (
    SELECT COALESCE (
                CASE WHEN rn <= 10 THEN '| ' || `{COL_NAME}` || ' | ' || ct ELSE NULL END,
                '| Other Values (' || COUNT(DISTINCT CAST(`{COL_NAME}` as STRING)) || ') | ' || SUM(ct)
           ) AS val,
           MIN (rn) as min_rn
    FROM ranked_vals
    GROUP BY CASE WHEN rn <= 10 THEN '| ' || `{COL_NAME}` || ' | ' || ct ELSE NULL
             END
    )
SELECT '{PROJECT_CODE}' as project_code,
       '{DATA_SCHEMA}'  as schema_name,
       '{RUN_DATE}'     as run_date,
       '{DATA_TABLE}'   as table_name,
       '{COL_NAME}'     as column_name,
       REPLACE(CONCAT_WS('^#^', ARRAY_SORT(
                                    COLLECT_LIST(val),
                                    (left, right) -> CASE WHEN CAST(SPLIT(left, '\\|')[0] AS INT) < CAST(SPLIT(right, '\\|')[0] AS INT) THEN -1 ELSE 1 END
                                )), '^#^', '\n') AS top_freq_values,
       (SELECT MD5(CONCAT_WS('|', ARRAY_SORT(COLLECT_LIST(NULLIF(dist_col_name,'')))))  as dvh
        FROM (SELECT DISTINCT `{COL_NAME}` as dist_col_name
              FROM {DATA_SCHEMA}.{DATA_TABLE}) a
       ) as distinct_value_hash
FROM consol_vals;
