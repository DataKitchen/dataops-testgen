WITH target_table AS (
-- TG-IF do_sample
  SELECT * FROM "{DATA_SCHEMA}"."{DATA_TABLE}" TABLESAMPLE ({SAMPLE_PERCENT_CALC} PERCENT) WITH (NOLOCK)
-- TG-ELSE
  SELECT * FROM "{DATA_SCHEMA}"."{DATA_TABLE}" WITH (NOLOCK)
-- TG-ENDIF
)
SELECT
  {CONNECTION_ID} AS connection_id,
  '{PROJECT_CODE}' AS project_code,
  '{TABLE_GROUPS_ID}' AS table_groups_id,
  '{DATA_SCHEMA}' AS schema_name,
  '{RUN_DATE}' AS run_date,
  '{DATA_TABLE}' AS table_name,
  {COL_POS} AS position,
  '{COL_NAME_SANITIZED}' AS column_name,
  '{COL_TYPE}' AS column_type,
  '{DB_DATA_TYPE}' AS db_data_type,
  '{COL_GEN_TYPE}' AS general_type,
  COUNT(*) AS record_ct,
-- TG-IF is_type_X
  COUNT(CASE WHEN "{COL_NAME}" IS NOT NULL THEN 1 END) AS value_ct,
  NULL AS distinct_value_ct,
-- TG-ELSE
  COUNT("{COL_NAME}") AS value_ct,
  COUNT(DISTINCT "{COL_NAME}") AS distinct_value_ct,
-- TG-ENDIF
  SUM(CASE WHEN "{COL_NAME}" IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
-- TG-IF is_type_ADN
  MIN(LEN("{COL_NAME}")) AS min_length,
  MAX(LEN("{COL_NAME}")) AS max_length,
  AVG(CAST(NULLIF(LEN("{COL_NAME}"), 0) AS FLOAT)) AS avg_length,
-- TG-ELSE
  NULL AS min_length,
  NULL AS max_length,
  NULL AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_A
  SUM(CASE
        WHEN LTRIM(RTRIM("{COL_NAME}")) LIKE '0([.]0*)' THEN 1 ELSE 0
      END) AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_type_N
  CAST(SUM( 1 - ABS(SIGN("{COL_NAME}")))AS BIGINT ) AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A_not_N
  NULL AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_type_A
  COUNT(DISTINCT UPPER(REPLACE(TRANSLATE("{COL_NAME}",' '''',.-',REPLICATE(' ', LEN(' '''',.-'))),' ',''))) AS distinct_std_value_ct,
  SUM(CASE
        WHEN "{COL_NAME}" = '' THEN 1
        ELSE 0
      END) AS zero_length_ct,
  SUM(CASE
        WHEN "{COL_NAME}" BETWEEN ' !' AND '!' THEN 1
        ELSE 0
      END) AS lead_space_ct,
  SUM(CASE WHEN "{COL_NAME}" LIKE '"%"' OR "{COL_NAME}" LIKE '''%''' THEN 1 ELSE 0 END ) AS quoted_value_ct,
  SUM(CASE WHEN "{COL_NAME}" LIKE '%[0-9]%' THEN 1 ELSE 0 END ) AS includes_digit_ct,
  SUM(CASE
         WHEN LEN("{COL_NAME}") > 0
          AND ((LEN(REPLACE("{COL_NAME}", '.', ''))= 0 )
                 OR (LEN(REPLACE("{COL_NAME}", '-', ''))= 0 )
                 OR (LEN(REPLACE("{COL_NAME}", '?', ''))= 0 )
             ) THEN 1
         WHEN DATALENGTH("{COL_NAME}") > 0
          AND LEN(LTRIM(RTRIM("{COL_NAME}")))= 0
               THEN 1
         WHEN LEN("{COL_NAME}") > 1
          AND ((LEN(REPLACE("{COL_NAME}", '0', ''))= 0 )
                 OR (LEN(REPLACE("{COL_NAME}", '9', ''))= 0 )
                 OR (LEN(REPLACE(LOWER("{COL_NAME}"), 'x', ''))= 0 )
                 OR (LEN(REPLACE(LOWER("{COL_NAME}"), 'z', ''))= 0 )
             ) THEN 1
         WHEN LOWER("{COL_NAME}") IN ('blank','error','missing','tbd',
                                    'n/a','#na','none','null','unknown')           THEN 1
         WHEN LOWER("{COL_NAME}") IN ('(blank)','(error)','(missing)','(tbd)',
                                    '(n/a)','(#na)','(none)','(null)','(unknown)') THEN 1
         WHEN LOWER("{COL_NAME}") IN ('[blank]','[error]','[missing]','[tbd]',
                                    '[n/a]','[#na]','[none]','[null]','[unknown]') THEN 1
                                                                                   ELSE 0
       END) AS filled_value_ct,
  LEFT(MIN(NULLIF("{COL_NAME}", '') COLLATE Latin1_General_BIN ), 100) AS min_text,
  LEFT(MAX(NULLIF("{COL_NAME}", '') COLLATE Latin1_General_BIN ), 100) AS max_text,
  SUM(CASE
        WHEN "{COL_NAME}" COLLATE Latin1_General_BIN = UPPER("{COL_NAME}")
         AND "{COL_NAME}" COLLATE Latin1_General_BIN <> LOWER("{COL_NAME}") THEN 1
        ELSE 0
      END) AS upper_case_ct,
  SUM(CASE
        WHEN "{COL_NAME}" COLLATE Latin1_General_BIN = LOWER("{COL_NAME}")
         AND "{COL_NAME}" COLLATE Latin1_General_BIN <> UPPER("{COL_NAME}") THEN 1
        ELSE 0
      END) AS lower_case_ct,
  SUM(CASE
        WHEN TRANSLATE("{COL_NAME}", 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz', '                                                    ') = "{COL_NAME}" THEN 1
        ELSE 0
      END) AS non_alpha_ct,
  COUNT(CASE WHEN TRANSLATE("{COL_NAME}", NCHAR(160), 'X') <> "{COL_NAME}" THEN 1 END) AS non_printing_ct,
  SUM(<%IS_NUM;LEFT("{COL_NAME}", 31)%>) AS numeric_ct,
  SUM(<%IS_DATE;LEFT("{COL_NAME}", 26)%>) AS date_ct,
  CASE
    WHEN CAST(SUM(CASE WHEN UPPER("{COL_NAME}") LIKE '[1-9]% [A-Z]% %'
                           AND CHARINDEX(' ', "{COL_NAME}") BETWEEN 2 and 6  THEN 1
                     END) AS FLOAT) /CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.8  THEN 'STREET_ADDR'
    WHEN CAST(SUM(CASE WHEN "{COL_NAME}" IN ('AL','AK','AS','AZ','AR','CA','CO','CT','DE','DC','FM','FL','GA','GU','HI','ID','IL','IN','IA','KS','KY','LA','ME','MH','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','MP','OH','OK','OR','PW','PA','PR','RI','SC','SD','TN','TX','UT','VT','VI','VA','WA','WV','WI','WY','AE','AP','AA')
         THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.9 THEN 'STATE_USA'
    WHEN CAST(SUM(CASE WHEN ("{COL_NAME}" LIKE '[+]1%[0-9][0-9][0-9]%[-. ][0-9][0-9][0-9]%[0-9][0-9][0-9][0-9,0-9,0-9,0-9,0-9,0-9]' AND "{COL_NAME}" NOT LIKE '%[^0-9+()-]%')
                     OR ("{COL_NAME}" LIKE '[+]1%[0-9][0-9][0-9][-. ][0-9][0-9][0-9][-. ][0-9][0-9][0-9][0-9]' AND "{COL_NAME}" NOT LIKE '%[^0-9+-]%')
         THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.8 THEN 'PHONE_USA'
    WHEN CAST(SUM(CASE WHEN "{COL_NAME}" LIKE '%[_a-zA-Z0-9.-]%@%[a-zA-Z0-9.-]%.[a-zA-Z][a-zA-Z]%'
         THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.9 THEN 'EMAIL'
    WHEN CAST(SUM(CASE WHEN TRANSLATE("{COL_NAME}",'012345678','999999999') IN ('99999', '999999999', '99999-9999')
         THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.9 THEN 'ZIP_USA'
    WHEN CAST(SUM(CASE WHEN "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS NOT LIKE ' %'
                          AND "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '[a-z0-9 _-]%'
                          AND ("{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.txt'
                          OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.csv'
                          OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.tsv'
                          OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.dat'
                          OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.doc'
                          OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.pdf'
                          OR "{COL_NAME}" COLLATE SQL_Latin1_General_CP1_CI_AS LIKE '%.xlsx')
         THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.9 THEN 'FILE_NAME'
    WHEN CAST(SUM(CASE WHEN "{COL_NAME}" LIKE '[0-9][0-9][0-9][0-9][- ][0-9][0-9][0-9][0-9][- ][0-9][0-9][0-9][0-9][- ][0-9][0-9][0-9][0-9]'
         THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.8 THEN 'CREDIT_CARD'
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
         THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.8 THEN 'DELIMITED_DATA'
    WHEN CAST(SUM (CASE WHEN "{COL_NAME}" LIKE '[0-8][0-9][0-9][- ][0-9][0-9][- ][0-9][0-9][0-9][0-9]'
                     AND LEFT("{COL_NAME}", 3) NOT BETWEEN '734' AND '749'
                     AND LEFT("{COL_NAME}", 3) <> '666' THEN 1 END) AS FLOAT)/CAST(COUNT("{COL_NAME}") AS FLOAT) > 0.9 THEN 'SSN'
  END AS std_pattern_match,
-- TG-ELSE
  NULL AS distinct_std_value_ct,
  NULL AS zero_length_ct,
  NULL AS lead_space_ct,
  NULL AS quoted_value_ct,
  NULL AS includes_digit_ct,
  NULL AS filled_value_ct,
  NULL AS min_text,
  NULL AS max_text,
  NULL AS upper_case_ct,
  NULL AS lower_case_ct,
  NULL AS non_alpha_ct,
  NULL AS non_printing_ct,
  NULL AS numeric_ct,
  NULL AS date_ct,
  NULL AS std_pattern_match,
-- TG-ENDIF
-- TG-IF is_type_A
  (SELECT LEFT(STRING_AGG(pattern, ' | ') WITHIN GROUP (ORDER BY ct DESC), 1000) AS concat_pats
     FROM (
           SELECT TOP 5 CAST(COUNT(*) AS VARCHAR(40)) + ' | ' + pattern AS pattern,
                  COUNT(*) AS ct
             FROM (SELECT TRANSLATE("{COL_NAME}"  COLLATE Latin1_General_BIN,
                            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                            'aaaaaaaaaaaaaaaaaaaaaaaaaaAAAAAAAAAAAAAAAAAAAAAAAAAANNNNNNNNNN' )
                   AS pattern
                      FROM target_table
                     WHERE "{COL_NAME}" > ' ' AND ((SELECT MAX(LEN("{COL_NAME}"))
                                                    FROM target_table) BETWEEN 3 and {MAX_PATTERN_LENGTH})) p
           GROUP BY pattern
           HAVING pattern > ' '
           ORDER BY COUNT(*) DESC
          ) ps) AS top_patterns,
-- TG-ELSE
  NULL AS top_patterns,
-- TG-ENDIF
-- TG-IF is_type_N
  MIN("{COL_NAME}") AS min_value,
  MIN(CASE WHEN "{COL_NAME}" > 0 THEN "{COL_NAME}" ELSE NULL END) AS min_value_over_0,
  MAX("{COL_NAME}") AS max_value,
  AVG(CAST("{COL_NAME}" AS FLOAT)) AS avg_value,
  STDEV(CAST("{COL_NAME}" AS FLOAT)) AS stdev_value,
  MIN(pct_25) AS percentile_25,
  MIN(pct_50) AS percentile_50,
  MIN(pct_75) AS percentile_75,
-- TG-ELSE
  NULL AS min_value,
  NULL AS min_value_over_0,
  NULL AS max_value,
  NULL AS avg_value,
  NULL AS stdev_value,
  NULL AS percentile_25,
  NULL AS percentile_50,
  NULL AS percentile_75,
-- TG-ENDIF
-- TG-IF is_N_decimal
  SUM(ROUND(ABS(("{COL_NAME}" % 1)), 5)) AS fractional_sum,
-- TG-ELSE
  NULL AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_type_D
  CASE
         WHEN MIN("{COL_NAME}") IS NULL THEN NULL
         ELSE CASE WHEN MIN("{COL_NAME}") >= CAST('0001-01-01' AS date) THEN MIN("{COL_NAME}") ELSE CAST('0001-01-01' AS date) END
       END AS min_date,
  MAX("{COL_NAME}") AS max_date,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 12 THEN 1
                                                            ELSE 0
      END) AS before_1yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 60 THEN 1
                                                            ELSE 0
      END) AS before_5yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 240 THEN 1
                                                              ELSE 0
      END) AS before_20yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}') > 1200 THEN 1
                                                                ELSE 0
      END) AS before_100yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(day, "{COL_NAME}", '{RUN_DATE}') BETWEEN 0 AND 365 THEN 1
                                                                         ELSE 0
      END) AS within_1yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF(day, "{COL_NAME}", '{RUN_DATE}') BETWEEN 0 AND 30 THEN 1
                                                                        ELSE 0
      END) AS within_1mo_date_ct,
  SUM(CASE
        WHEN "{COL_NAME}" > '{RUN_DATE}' THEN 1 ELSE 0
      END) AS future_date_ct,
  SUM(CASE
        WHEN DATEDIFF(month, '{RUN_DATE}', "{COL_NAME}") > 240 THEN 1
                                                               ELSE 0
      END) AS distant_future_date_ct,
  COUNT(DISTINCT DATEDIFF(day, "{COL_NAME}", '{RUN_DATE}' ) ) AS date_days_present,
  COUNT(DISTINCT DATEDIFF(week, DATEADD(day, -1, "{COL_NAME}"), DATEADD(day, -1, CAST('{RUN_DATE}' AS DATE)) ) ) AS date_weeks_present,
  COUNT(DISTINCT DATEDIFF(month, "{COL_NAME}", '{RUN_DATE}' ) ) AS date_months_present,
-- TG-ELSE
  NULL AS min_date,
  NULL AS max_date,
  NULL AS before_1yr_date_ct,
  NULL AS before_5yr_date_ct,
  NULL AS before_20yr_date_ct,
  NULL AS before_100yr_date_ct,
  NULL AS within_1yr_date_ct,
  NULL AS within_1mo_date_ct,
  NULL AS future_date_ct,
  NULL AS distant_future_date_ct,
  NULL AS date_days_present,
  NULL AS date_weeks_present,
  NULL AS date_months_present,
-- TG-ENDIF
-- TG-IF is_type_B
  SUM(CAST("{COL_NAME}" AS INTEGER)) AS boolean_true_ct,
-- TG-ELSE
  NULL AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_type_A
  (SELECT COUNT(DISTINCT TRANSLATE("{COL_NAME}"  COLLATE Latin1_General_BIN,
                                'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                                'aaaaaaaaaaaaaaaaaaaaaaaaaaAAAAAAAAAAAAAAAAAAAAAAAAAANNNNNNNNNN'
                              )
             ) AS pattern_ct
  FROM target_table
 WHERE "{COL_NAME}" > ' ' ) AS distinct_pattern_ct,
  SUM(CAST(SIGN(LEN(RTRIM(LTRIM("{COL_NAME}"))) - LEN(REPLACE(RTRIM(LTRIM("{COL_NAME}")),' ',''))) AS BIGINT)) AS embedded_space_ct,
  AVG(CAST(LEN(RTRIM(LTRIM("{COL_NAME}"))) - LEN(REPLACE(RTRIM(LTRIM("{COL_NAME}")),' ','')) AS FLOAT)) AS avg_embedded_spaces,
-- TG-ELSE
  NULL AS distinct_pattern_ct,
  NULL AS embedded_space_ct,
  NULL AS avg_embedded_spaces,
-- TG-ENDIF
  '{PROFILE_RUN_ID}' AS profile_run_id
  FROM target_table
-- TG-IF is_N_sampling
  , (SELECT TOP 1
             PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS pct_25,
             PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS pct_50,
             PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS pct_75
        FROM "{DATA_SCHEMA}"."{DATA_TABLE}" TABLESAMPLE ({SAMPLE_PERCENT_CALC} PERCENT) WITH (NOLOCK)) pctile
-- TG-ENDIF
-- TG-IF is_N_no_sampling
  , (SELECT TOP 1
             PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS pct_25,
             PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS pct_50,
             PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") OVER () AS pct_75
        FROM "{DATA_SCHEMA}"."{DATA_TABLE}" WITH (NOLOCK)) pctile
-- TG-ENDIF
