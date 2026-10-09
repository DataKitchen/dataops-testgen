-- TG-IF is_type_A
WITH whole_table_measures AS (
  SELECT
    COUNT_BIG(*) AS record_ct,
    COUNT_BIG("{COL_NAME}") AS value_ct,
    COUNT_BIG(DISTINCT "{COL_NAME}") AS distinct_value_ct,
    SUM(CASE WHEN "{COL_NAME}" IS NULL THEN CAST(1 AS BIGINT) ELSE 0 END) AS null_value_ct,
    MIN((LEN(CAST("{COL_NAME}" AS NVARCHAR(MAX)) + N'.') - 1)) AS min_length,
    MAX((LEN(CAST("{COL_NAME}" AS NVARCHAR(MAX)) + N'.') - 1)) AS max_length,
    AVG(CAST(NULLIF((LEN(CAST("{COL_NAME}" AS NVARCHAR(MAX)) + N'.') - 1), 0) AS FLOAT)) AS avg_length,
    SUM(CASE
          WHEN LTRIM(RTRIM("{COL_NAME}")) LIKE '0([.]0*)' THEN CAST(1 AS BIGINT) ELSE 0
        END) AS zero_value_ct,
    COUNT_BIG(DISTINCT UPPER(REPLACE(TRANSLATE("{COL_NAME}",' '''',.-',REPLICATE(' ', LEN(' '''',.-'))),' ',''))) AS distinct_std_value_ct,
    LEFT(MIN(NULLIF("{COL_NAME}", '') COLLATE Latin1_General_BIN ), 100) AS min_text,
    LEFT(MAX(NULLIF("{COL_NAME}", '') COLLATE Latin1_General_BIN ), 100) AS max_text
    FROM (SELECT {COL_VALUE} AS "{COL_NAME}" FROM "{DATA_SCHEMA}"."{DATA_TABLE}" {TABLE_HINT}) source_rows
)
-- TG-ENDIF
-- TG-IF is_A_sampling
, sampleable_rows AS (
  SELECT {COL_VALUE} AS "{COL_NAME}"
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" TABLESAMPLE ({SAMPLE_PERCENT_CALC} PERCENT) {TABLE_HINT}
)
, pattern_rows AS (
  SELECT {COL_VALUE} AS v
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" TABLESAMPLE ({SAMPLE_PERCENT_CALC} PERCENT) {TABLE_HINT}
)
-- TG-ENDIF
-- TG-IF is_A_no_sampling
, sampleable_rows AS (
  SELECT {COL_VALUE} AS "{COL_NAME}"
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" {TABLE_HINT}
)
, pattern_rows AS (
  SELECT {COL_VALUE} AS v
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" {TABLE_HINT}
)
-- TG-ENDIF
-- TG-IF is_type_A
, sampleable_measures AS (
  SELECT
    COUNT_BIG("{COL_NAME}") AS sample_value_ct,
    SUM(CASE
          WHEN DATALENGTH("{COL_NAME}") = 0 THEN CAST(1 AS BIGINT)
          ELSE 0
        END) AS zero_length_ct,
    SUM(CASE
          WHEN ("{COL_NAME}" LIKE ' %' AND LTRIM("{COL_NAME}") <> '') THEN CAST(1 AS BIGINT)
          ELSE 0
        END) AS lead_space_ct,
    SUM(CASE WHEN "{COL_NAME}" LIKE '"%"' OR "{COL_NAME}" LIKE '''%''' THEN CAST(1 AS BIGINT) ELSE 0 END ) AS quoted_value_ct,
    SUM(CASE WHEN "{COL_NAME}" LIKE '%[0-9]%' THEN CAST(1 AS BIGINT) ELSE 0 END ) AS includes_digit_ct,
    SUM(CASE
           WHEN LEN("{COL_NAME}") > 0
            AND ((LEN(REPLACE("{COL_NAME}", '.', ''))= 0 )
                   OR (LEN(REPLACE("{COL_NAME}", '-', ''))= 0 )
                   OR (LEN(REPLACE("{COL_NAME}", '?', ''))= 0 )
               ) THEN CAST(1 AS BIGINT)
           WHEN DATALENGTH("{COL_NAME}") > 0
            AND LEN(LTRIM(RTRIM("{COL_NAME}")))= 0
                 THEN CAST(1 AS BIGINT)
           WHEN LEN("{COL_NAME}") > 1
            AND ((LEN(REPLACE("{COL_NAME}", '0', ''))= 0 )
                   OR (LEN(REPLACE("{COL_NAME}", '9', ''))= 0 )
                   OR (LEN(REPLACE(LOWER("{COL_NAME}"), 'x', ''))= 0 )
                   OR (LEN(REPLACE(LOWER("{COL_NAME}"), 'z', ''))= 0 )
               ) THEN CAST(1 AS BIGINT)
           WHEN LOWER("{COL_NAME}") IN ('blank','error','missing','tbd',
                                      'n/a','#na','none','null','unknown')           THEN CAST(1 AS BIGINT)
           WHEN LOWER("{COL_NAME}") IN ('(blank)','(error)','(missing)','(tbd)',
                                      '(n/a)','(#na)','(none)','(null)','(unknown)') THEN CAST(1 AS BIGINT)
           WHEN LOWER("{COL_NAME}") IN ('[blank]','[error]','[missing]','[tbd]',
                                      '[n/a]','[#na]','[none]','[null]','[unknown]') THEN CAST(1 AS BIGINT)
                                                                                     ELSE 0
         END) AS filled_value_ct,
    SUM(CASE
          WHEN "{COL_NAME}" COLLATE Latin1_General_BIN = UPPER("{COL_NAME}")
           AND "{COL_NAME}" COLLATE Latin1_General_BIN <> LOWER("{COL_NAME}") THEN CAST(1 AS BIGINT)
          ELSE 0
        END) AS upper_case_ct,
    SUM(CASE
          WHEN "{COL_NAME}" COLLATE Latin1_General_BIN = LOWER("{COL_NAME}")
           AND "{COL_NAME}" COLLATE Latin1_General_BIN <> UPPER("{COL_NAME}") THEN CAST(1 AS BIGINT)
          ELSE 0
        END) AS lower_case_ct,
    SUM(CASE
          WHEN "{COL_NAME}" COLLATE Latin1_General_BIN = UPPER("{COL_NAME}")
           AND "{COL_NAME}" COLLATE Latin1_General_BIN = LOWER("{COL_NAME}") THEN CAST(1 AS BIGINT)
          ELSE 0
        END) AS non_alpha_ct,
    -- Binary collation: Windows collations ignore zero-width characters
    COUNT_BIG(CASE WHEN TRANSLATE(CAST("{COL_NAME}" AS NVARCHAR(MAX)) COLLATE Latin1_General_100_BIN2,
                                  NCHAR(160) + NCHAR(8201) + NCHAR(8203) + NCHAR(8204) + NCHAR(8205) + NCHAR(8206) + NCHAR(8207) + NCHAR(8239) + NCHAR(12288) + NCHAR(65279), N'XXXXXXXXXX')
                      <> CAST("{COL_NAME}" AS NVARCHAR(MAX)) COLLATE Latin1_General_100_BIN2 THEN 1 END) AS non_printing_ct,
    SUM(CAST(<%IS_NUM;LEFT("{COL_NAME}", 31)%> AS BIGINT)) AS numeric_ct,
    SUM(CAST(<%IS_DATE;LEFT("{COL_NAME}", 26)%> AS BIGINT)) AS date_ct,
    CASE
      WHEN CAST(SUM(CASE WHEN UPPER("{COL_NAME}") LIKE '[1-9]% [A-Z]% %'
                             AND CHARINDEX(' ', "{COL_NAME}") BETWEEN 2 and 6  THEN CAST(1 AS BIGINT)
                       END) AS FLOAT) /CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.8  THEN 'STREET_ADDR'
      WHEN CAST(SUM(CASE WHEN "{COL_NAME}" IN ('AL','AK','AS','AZ','AR','CA','CO','CT','DE','DC','FM','FL','GA','GU','HI','ID','IL','IN','IA','KS','KY','LA','ME','MH','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','MP','OH','OK','OR','PW','PA','PR','RI','SC','SD','TN','TX','UT','VT','VI','VA','WA','WV','WI','WY','AE','AP','AA')
           THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.9 THEN 'STATE_USA'
      WHEN CAST(SUM(CASE WHEN ("{COL_NAME}" LIKE '[+]1%[0-9][0-9][0-9]%[-. ][0-9][0-9][0-9]%[0-9][0-9][0-9][0-9,0-9,0-9,0-9,0-9,0-9]' AND "{COL_NAME}" NOT LIKE '%[^0-9+()-]%')
                       OR ("{COL_NAME}" LIKE '[+]1%[0-9][0-9][0-9][-. ][0-9][0-9][0-9][-. ][0-9][0-9][0-9][0-9]' AND "{COL_NAME}" NOT LIKE '%[^0-9+-]%')
           THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.8 THEN 'PHONE_USA'
      WHEN CAST(SUM(CASE WHEN "{COL_NAME}" LIKE '%[_a-zA-Z0-9.-]%@%[a-zA-Z0-9.-]%.[a-zA-Z][a-zA-Z]%'
                AND "{COL_NAME}" NOT LIKE '%://%'
           THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.9 THEN 'EMAIL'
      WHEN CAST(SUM(CASE WHEN TRANSLATE("{COL_NAME}",'012345678','999999999') IN ('99999', '999999999', '99999-9999')
           THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.9 THEN 'ZIP_USA'
      WHEN CAST(SUM(CASE WHEN "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS NOT LIKE ' %'
                            AND "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '[a-z0-9 _-]%'
                            AND ("{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.txt'
                            OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.csv'
                            OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.tsv'
                            OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.dat'
                            OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.doc'
                            OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.pdf'
                            OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.xlsx')
           THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.9 THEN 'FILE_NAME'
      WHEN CAST(SUM(CASE WHEN "{COL_NAME}" LIKE '[0-9][0-9][0-9][0-9][- ][0-9][0-9][0-9][0-9][- ][0-9][0-9][0-9][0-9][- ][0-9][0-9][0-9][0-9]'
                        OR "{COL_NAME}" LIKE '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
           THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.8 THEN 'CREDIT_CARD'
      WHEN CAST(SUM(CASE WHEN ( "{COL_NAME}" LIKE '%,%,%,%'
                              OR "{COL_NAME}" LIKE '%|%|%|%'
                              OR "{COL_NAME}" LIKE '%^%^%^%'
                              OR "{COL_NAME}" LIKE '%' + CHAR(9) + '%' + CHAR(9) + '%' + CHAR(9) + '%' )
                           AND NOT ( "{COL_NAME}" LIKE '% and %'
                                  OR "{COL_NAME}" LIKE '% but %'
                                  OR "{COL_NAME}" LIKE '% or %'
                                  OR "{COL_NAME}" LIKE '% yet %' )
                           AND ISNULL(CAST(LEN("{COL_NAME}") - LEN(REPLACE("{COL_NAME}", ',', '')) AS FLOAT)
                                / CAST(NULLIF(LEN("{COL_NAME}") - LEN(REPLACE("{COL_NAME}", ' ', '')), 0) AS FLOAT), 1) > 0.6
           THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.8 THEN 'DELIMITED_DATA'
      WHEN CAST(SUM (CASE WHEN "{COL_NAME}" LIKE '[0-8][0-9][0-9][- ][0-9][0-9][- ][0-9][0-9][0-9][0-9]'
                       AND LEFT("{COL_NAME}", 3) NOT BETWEEN '734' AND '749'
                       AND LEFT("{COL_NAME}", 3) <> '666' THEN CAST(1 AS BIGINT) END) AS FLOAT)/CAST(COUNT_BIG("{COL_NAME}") AS FLOAT) > 0.9 THEN 'SSN'
    END AS std_pattern_match,
    SUM(CAST(SIGN(LEN(RTRIM(LTRIM("{COL_NAME}"))) - LEN(REPLACE(RTRIM(LTRIM("{COL_NAME}")),' ',''))) AS BIGINT)) AS embedded_space_ct,
    AVG(CAST(LEN(RTRIM(LTRIM("{COL_NAME}"))) - LEN(REPLACE(RTRIM(LTRIM("{COL_NAME}")),' ','')) AS FLOAT)) AS avg_embedded_spaces
    FROM sampleable_rows
)
, pattern_counts AS (
  SELECT pattern,
         COUNT_BIG(*) AS pattern_ct,
         COUNT_BIG(value_length) AS value_ct,
         MAX(value_length) AS max_length
    FROM ( SELECT CASE
                    WHEN v > ' '
                      THEN TRANSLATE(v COLLATE Latin1_General_BIN,
                             'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', 'aaaaaaaaaaaaaaaaaaaaaaaaaaAAAAAAAAAAAAAAAAAAAAAAAAAANNNNNNNNNN' )
                  END AS pattern,
                  (LEN(CAST(v AS NVARCHAR(MAX)) + N'.') - 1) AS value_length
             FROM pattern_rows ) patterned
   GROUP BY pattern
)
, ranked_patterns AS (
  SELECT pattern,
         pattern_ct,
         value_ct,
         CASE
           WHEN pattern > ' ' AND MAX(max_length) OVER () BETWEEN 3 AND {MAX_PATTERN_LENGTH}
             THEN ROW_NUMBER() OVER (ORDER BY CASE WHEN pattern > ' ' THEN 0 ELSE 1 END, pattern_ct DESC, CAST(pattern AS NVARCHAR(4000)) COLLATE Latin1_General_100_BIN2)
         END AS pattern_rank
    FROM pattern_counts
)
, pattern_measures AS (
  SELECT
    MAX(CASE WHEN pattern_rank = 1 THEN pattern END) AS pattern_0,
    MAX(CASE WHEN pattern_rank = 1 THEN pattern_ct END) AS pattern_ct_0,
    MAX(CASE WHEN pattern_rank = 2 THEN pattern END) AS pattern_1,
    MAX(CASE WHEN pattern_rank = 2 THEN pattern_ct END) AS pattern_ct_1,
    MAX(CASE WHEN pattern_rank = 3 THEN pattern END) AS pattern_2,
    MAX(CASE WHEN pattern_rank = 3 THEN pattern_ct END) AS pattern_ct_2,
    MAX(CASE WHEN pattern_rank = 4 THEN pattern END) AS pattern_3,
    MAX(CASE WHEN pattern_rank = 4 THEN pattern_ct END) AS pattern_ct_3,
    MAX(CASE WHEN pattern_rank = 5 THEN pattern END) AS pattern_4,
    MAX(CASE WHEN pattern_rank = 5 THEN pattern_ct END) AS pattern_ct_4,
    COUNT_BIG(pattern) AS distinct_pattern_ct,
    SUM(value_ct) AS sample_pattern_value_ct
    FROM ranked_patterns
)
SELECT *
  FROM whole_table_measures
  CROSS JOIN sampleable_measures
  CROSS JOIN pattern_measures
-- TG-ENDIF
-- TG-IF is_not_A
WITH column_measures AS (
SELECT
-- TG-ENDIF
-- TG-IF is_type_X
  COUNT_BIG(CASE WHEN "{COL_NAME}" IS NOT NULL THEN 1 END) AS value_ct,
-- TG-ENDIF
-- TG-IF is_not_A_or_X
  COUNT_BIG("{COL_NAME}") AS value_ct,
  COUNT_BIG(DISTINCT "{COL_NAME}") AS distinct_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A
  SUM(CASE WHEN "{COL_NAME}" IS NULL THEN CAST(1 AS BIGINT) ELSE 0 END) AS null_value_ct,
-- TG-ENDIF
-- TG-IF is_type_DN
  MIN((LEN(CAST("{COL_NAME}" AS NVARCHAR(MAX)) + N'.') - 1)) AS min_length,
  MAX((LEN(CAST("{COL_NAME}" AS NVARCHAR(MAX)) + N'.') - 1)) AS max_length,
  AVG(CAST(NULLIF((LEN(CAST("{COL_NAME}" AS NVARCHAR(MAX)) + N'.') - 1), 0) AS FLOAT)) AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_N
  SUM(CAST(1 - ABS(SIGN("{COL_NAME}")) AS BIGINT)) AS zero_value_ct,
  MIN("{COL_NAME}") AS min_value,
  MIN(CASE WHEN "{COL_NAME}" > 0 THEN "{COL_NAME}" ELSE NULL END) AS min_value_over_0,
  MAX("{COL_NAME}") AS max_value,
  AVG(CAST("{COL_NAME}" AS FLOAT)) AS avg_value,
  STDEV(CAST("{COL_NAME}" AS FLOAT)) AS stdev_value,
-- TG-ENDIF
-- TG-IF is_N_decimal
  SUM(ROUND(CAST(ABS(("{COL_NAME}" % 1)) AS DECIMAL(38,8)), 5)) AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_N_exact_sum
  CASE WHEN MAX(ABS(CAST("{COL_NAME}" AS FLOAT))) < 1e20 AND COUNT("{COL_NAME}") < 1e10
       THEN SUM(CASE WHEN ABS(CAST("{COL_NAME}" AS FLOAT)) < 1e20 THEN CAST("{COL_NAME}" AS DECIMAL(38,8)) END)
  END AS sum_value,
-- TG-ENDIF
-- TG-IF is_type_D
  CASE
         WHEN MIN("{COL_NAME}") IS NULL THEN NULL
         ELSE CASE WHEN MIN("{COL_NAME}") >= CAST('0001-01-01' AS date) THEN MIN("{COL_NAME}") ELSE CAST('0001-01-01' AS date) END
       END AS min_date,
  MAX("{COL_NAME}") AS max_date,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 12 THEN CAST(1 AS BIGINT)
                                                            ELSE 0
      END) AS before_1yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 60 THEN CAST(1 AS BIGINT)
                                                            ELSE 0
      END) AS before_5yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 240 THEN CAST(1 AS BIGINT)
                                                              ELSE 0
      END) AS before_20yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 1200 THEN CAST(1 AS BIGINT)
                                                                ELSE 0
      END) AS before_100yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(day, "{COL_NAME}", '{RUN_DATE}') BETWEEN 0 AND 365 THEN CAST(1 AS BIGINT)
                                                                         ELSE 0
      END) AS within_1yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(day, "{COL_NAME}", '{RUN_DATE}') BETWEEN 0 AND 30 THEN CAST(1 AS BIGINT)
                                                                        ELSE 0
      END) AS within_1mo_date_ct,
  SUM(CASE
        WHEN "{COL_NAME}" > '{RUN_DATE}' THEN CAST(1 AS BIGINT) ELSE 0
      END) AS future_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, '{RUN_DATE}', "{COL_NAME}") > 240 THEN CAST(1 AS BIGINT)
                                                               ELSE 0
      END) AS distant_future_date_ct,
  COUNT_BIG(DISTINCT DATEDIFF(day, "{COL_NAME}", '{RUN_DATE}' ) ) AS date_days_present,
  COUNT_BIG(DISTINCT DATEDIFF(week, DATEADD(day, -1, "{COL_NAME}"), DATEADD(day, -1, CAST('{RUN_DATE}' AS DATE)) ) ) AS date_weeks_present,
  COUNT_BIG(DISTINCT DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}' ) ) AS date_months_present,
-- TG-ENDIF
-- TG-IF is_type_B
  SUM(CAST("{COL_NAME}" AS BIGINT)) AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_not_A
  COUNT_BIG(*) AS record_ct
  FROM "{DATA_SCHEMA}"."{DATA_TABLE}" {TABLE_HINT}
-- TG-ENDIF
-- TG-IF is_not_A
)
-- TG-ENDIF
-- TG-IF is_N_approx_pctile
, percentiles AS (
  SELECT
    APPROX_PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") AS percentile_25,
    APPROX_PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") AS percentile_50,
    APPROX_PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") AS percentile_75
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" {TABLE_HINT}
)
-- TG-ENDIF
-- TG-IF is_N_exact_pctile
, percentiles AS (
  SELECT TOP 1
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS percentile_25,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS percentile_50,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS percentile_75
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" {TABLE_HINT}
)
-- TG-ENDIF
-- TG-IF is_not_A
SELECT *
  FROM column_measures
-- TG-ENDIF
-- TG-IF is_type_N
  -- Joined to the aggregated row: joined before aggregating, SQL Server spools every row of a small table.
  -- An outer join: the exact percentile query returns no row for an empty table.
  LEFT JOIN percentiles ON 1 = 1
-- TG-ENDIF
