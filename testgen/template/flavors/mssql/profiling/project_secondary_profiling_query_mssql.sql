-- Get Freqs for selected columns
WITH ranked_vals
AS
    (SELECT "{COL_NAME}",
            COUNT(*) AS  ct,
            ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS rn
     FROM {DATA_SCHEMA}.{DATA_TABLE}
     WHERE "{COL_NAME}" > ' '
     GROUP BY "{COL_NAME}"
    ),
consol_vals
AS (
    SELECT COALESCE (CASE WHEN rn <= 10 THEN '| ' + "{COL_NAME}" + ' | ' + CAST (ct AS VARCHAR)
                                        ELSE NULL
                     END,
                    '| Other Values (' + CAST ( CAST(COUNT (DISTINCT CAST ("{COL_NAME}" as VARCHAR)) AS VARCHAR ) + ') | '
                    + CAST (SUM (ct) as VARCHAR) AS VARCHAR)) AS val,
            MIN (rn) as min_rn
    FROM ranked_vals
    GROUP BY CASE WHEN rn <= 10 THEN '| ' + "{COL_NAME}" + ' | ' + CAST (ct AS VARCHAR) ELSE NULL
             END
    )
SELECT '{PROJECT_CODE}' as project_code,
       '{DATA_SCHEMA}'  as schema_name,
       '{RUN_DATE}'     as run_date,
       '{DATA_TABLE}'   as table_name,
       '{COL_NAME}'     as column_name,
       REPLACE(STRING_AGG(CONVERT(NVARCHAR(max), val), '^#^') WITHIN GROUP (ORDER BY min_rn), '^#^', CHAR(10)) AS top_freq_values,
       (SELECT CONVERT(VARCHAR(40), HASHBYTES('MD5', STRING_AGG( NULLIF(dist_col_name,''),
                       '|') WITHIN GROUP (ORDER BY dist_col_name)), 2)  as dvh
        FROM (SELECT DISTINCT "{COL_NAME}" as dist_col_name
              FROM {DATA_SCHEMA}.{DATA_TABLE}) a
       ) as distinct_value_hash
FROM consol_vals;

-- Convert function has style = 2 : The characters 0x aren't added to the left of the converted result for style 2.