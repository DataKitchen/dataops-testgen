-- TG-IF is_type_A
WITH whole_table_measures AS (
  SELECT
    COUNT(*) AS record_ct,
    COUNT(`{COL_NAME}`) AS value_ct,
    COUNT(DISTINCT `{COL_NAME}`) AS distinct_value_ct,
    SUM(CASE WHEN `{COL_NAME}` IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
    MIN(LEN(`{COL_NAME}`)) AS min_length,
    MAX(LEN(`{COL_NAME}`)) AS max_length,
    AVG(CAST(NULLIF(LEN(`{COL_NAME}`), 0) AS DOUBLE)) AS avg_length,
    SUM(CASE
          WHEN LTRIM(RTRIM(`{COL_NAME}`)) RLIKE '0([.]0*)' THEN 1 ELSE 0
        END) AS zero_value_ct,
    COUNT(DISTINCT UPPER(REPLACE(TRANSLATE(`{COL_NAME}`,' '''',.-',REPEAT(' ', LEN(' '''',.-'))),' ',''))) AS distinct_std_value_ct,
    LEFT(MIN(NULLIF(`{COL_NAME}`, '')), 100) AS min_text,
    LEFT(MAX(NULLIF(`{COL_NAME}`, '')), 100) AS max_text
    FROM `{DATA_SCHEMA}`.`{DATA_TABLE}`
)
-- TG-ENDIF
-- TG-IF is_A_sampling
, sampleable_rows AS (
  SELECT `{COL_NAME}`
    FROM `{DATA_SCHEMA}`.`{DATA_TABLE}` TABLESAMPLE ({SAMPLE_PERCENT_CALC} PERCENT)
)
, pattern_rows AS (
  SELECT `{COL_NAME}` AS v
    FROM `{DATA_SCHEMA}`.`{DATA_TABLE}` TABLESAMPLE ({SAMPLE_PERCENT_CALC} PERCENT)
)
-- TG-ENDIF
-- TG-IF is_A_no_sampling
, sampleable_rows AS (
  SELECT `{COL_NAME}`
    FROM `{DATA_SCHEMA}`.`{DATA_TABLE}`
)
, pattern_rows AS (
  SELECT `{COL_NAME}` AS v
    FROM `{DATA_SCHEMA}`.`{DATA_TABLE}`
)
-- TG-ENDIF
-- TG-IF is_type_A
, sampleable_measures AS (
  SELECT
    COUNT(`{COL_NAME}`) AS sample_value_ct,
    SUM(CASE
          WHEN `{COL_NAME}` = '' THEN 1
          ELSE 0
        END) AS zero_length_ct,
    SUM(CASE
          WHEN (`{COL_NAME}` LIKE ' %' AND LTRIM(`{COL_NAME}`) <> '') THEN 1
          ELSE 0
        END) AS lead_space_ct,
    SUM(CASE WHEN `{COL_NAME}` LIKE '"%"' OR `{COL_NAME}` LIKE '\'%\'' THEN 1 ELSE 0 END) AS quoted_value_ct,
    SUM(CASE WHEN `{COL_NAME}` RLIKE '[0-9]' THEN 1 ELSE 0 END) AS includes_digit_ct,
    SUM(CASE
           WHEN LEN(`{COL_NAME}`) > 0
            AND ((LEN(REPLACE(`{COL_NAME}`, '.', ''))= 0 )
                   OR (LEN(REPLACE(`{COL_NAME}`, '-', ''))= 0 )
                   OR (LEN(REPLACE(`{COL_NAME}`, '?', ''))= 0 )
                   OR (LEN(REPLACE(`{COL_NAME}`, ' ', ''))= 0 )
               ) THEN 1
           WHEN LEN(`{COL_NAME}`) > 1
            AND ((LEN(REPLACE(`{COL_NAME}`, '0', ''))= 0 )
                   OR (LEN(REPLACE(`{COL_NAME}`, '9', ''))= 0 )
                   OR (LEN(REPLACE(LOWER(`{COL_NAME}`), 'x', ''))= 0 )
                   OR (LEN(REPLACE(LOWER(`{COL_NAME}`), 'z', ''))= 0 )
               ) THEN 1
           WHEN LOWER(`{COL_NAME}`) IN ('blank','error','missing','tbd',
                                      'n/a','#na','none','null','unknown')           THEN 1
           WHEN LOWER(`{COL_NAME}`) IN ('(blank)','(error)','(missing)','(tbd)',
                                      '(n/a)','(#na)','(none)','(null)','(unknown)') THEN 1
           WHEN LOWER(`{COL_NAME}`) IN ('[blank]','[error]','[missing]','[tbd]',
                                      '[n/a]','[#na]','[none]','[null]','[unknown]') THEN 1
                                                                                     ELSE 0
         END) AS filled_value_ct,
    SUM(CASE WHEN CAST(`{COL_NAME}` AS BINARY) = CAST(UPPER(`{COL_NAME}`) AS BINARY) AND CAST(`{COL_NAME}` AS BINARY) <> CAST(LOWER(`{COL_NAME}`) AS BINARY) THEN 1 ELSE 0 END) AS upper_case_ct,
    SUM(CASE WHEN CAST(`{COL_NAME}` AS BINARY) = CAST(LOWER(`{COL_NAME}`) AS BINARY) AND CAST(`{COL_NAME}` AS BINARY) <> CAST(UPPER(`{COL_NAME}`) AS BINARY) THEN 1 ELSE 0 END) AS lower_case_ct,
    SUM(CASE WHEN CAST(`{COL_NAME}` AS BINARY) = CAST(UPPER(`{COL_NAME}`) AS BINARY) AND CAST(`{COL_NAME}` AS BINARY) = CAST(LOWER(`{COL_NAME}`) AS BINARY) THEN 1 ELSE 0 END) AS non_alpha_ct,
    COUNT(CASE WHEN TRANSLATE(`{COL_NAME}`, '\u00a0\u2009\u200b\u200c\u200d\u200e\u200f\u202f\u3000\ufeff', 'XXXXXXXXXX') <> `{COL_NAME}` THEN 1 END) AS non_printing_ct,
    SUM(<%IS_NUM;LEFT(`{COL_NAME}`, 31)%>) AS numeric_ct,
    SUM(<%IS_DATE;LEFT(`{COL_NAME}`, 26)%>) AS date_ct,
    CASE
      WHEN CAST(SUM( CASE WHEN UPPER(`{COL_NAME}`) RLIKE '[1-9]{1,5} [A-Z]+ .*'
           THEN 1 END ) AS FLOAT) /CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.8  THEN 'STREET_ADDR'
      WHEN CAST(SUM(CASE WHEN `{COL_NAME}` IN ('AL','AK','AS','AZ','AR','CA','CO','CT','DE','DC','FM','FL','GA','GU','HI','ID','IL','IN','IA','KS','KY','LA','ME','MH','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','MP','OH','OK','OR','PW','PA','PR','RI','SC','SD','TN','TX','UT','VT','VI','VA','WA','WV','WI','WY','AE','AP','AA')
           THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.9 THEN 'STATE_USA'
      WHEN CAST(SUM( CASE WHEN `{COL_NAME}` RLIKE '\\+1\\s*\\(?\\d{3}\\)?[-. ]*\\d{3}[-. ]*\\d{4}'
           THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.9 THEN 'PHONE_USA'
      WHEN CAST(SUM( CASE WHEN `{COL_NAME}` RLIKE '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$'
                AND `{COL_NAME}` NOT LIKE '%://%'
           THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.9 THEN 'EMAIL'
      WHEN CAST(SUM( CASE WHEN TRANSLATE(`{COL_NAME}`,'012345678','999999999') IN ('99999', '999999999', '99999-9999')
           THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.9 THEN 'ZIP_USA'
      WHEN CAST(SUM( CASE WHEN `{COL_NAME}` NOT LIKE ' %'
                            AND `{COL_NAME}` RLIKE '[a-z0-9 _-]%'
                            AND (`{COL_NAME}` LIKE '%.txt'
                            OR `{COL_NAME}` LIKE '%.csv'
                            OR `{COL_NAME}` LIKE '%.tsv'
                            OR `{COL_NAME}` LIKE '%.dat'
                            OR `{COL_NAME}` LIKE '%.doc'
                            OR `{COL_NAME}` LIKE '%.pdf'
                            OR `{COL_NAME}` LIKE '%.xlsx')
           THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.9 THEN 'FILE_NAME'
      WHEN CAST(SUM( CASE WHEN `{COL_NAME}` RLIKE '^([0-9]{4}[- ]?){3}[0-9]{4}$'
           THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.8 THEN 'CREDIT_CARD'
      WHEN CAST(SUM( CASE WHEN ( `{COL_NAME}` LIKE '%,%,%,%'
                              OR `{COL_NAME}` LIKE '%|%|%|%'
                              OR `{COL_NAME}` LIKE '%^%^%^%'
                              OR `{COL_NAME}` LIKE '%' || CHAR(9) || '%' || CHAR(9) || '%' || CHAR(9) || '%' )
                           AND NOT ( `{COL_NAME}` LIKE '% and %'
                                  OR `{COL_NAME}` LIKE '% but %'
                                  OR `{COL_NAME}` LIKE '% or %'
                                  OR `{COL_NAME}` LIKE '% yet %' )
                           AND COALESCE(CAST(LEN(`{COL_NAME}`) - LEN(REPLACE(`{COL_NAME}`, ',', '')) AS FLOAT)
                                / CAST(NULLIF(LEN(`{COL_NAME}`) - LEN(REPLACE(`{COL_NAME}`, ' ', '')), 0) AS FLOAT), 1) > 0.6
           THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.8 THEN 'DELIMITED_DATA'
      WHEN CAST(SUM ( CASE WHEN `{COL_NAME}` RLIKE '[0-8][0-9][0-9][- ][0-9][0-9][- ][0-9][0-9][0-9][0-9]'
                       AND LEFT(`{COL_NAME}`, 3) NOT BETWEEN '734' AND '749'
                       AND LEFT(`{COL_NAME}`, 3) <> '666' THEN 1 END) AS FLOAT)/CAST(COUNT(`{COL_NAME}`) AS FLOAT) > 0.9 THEN 'SSN'
    END AS std_pattern_match,
    SUM(CAST(SIGN(LEN(TRIM(`{COL_NAME}`)) - LEN(REPLACE(TRIM(`{COL_NAME}`),' ',''))) AS BIGINT)) AS embedded_space_ct,
    AVG(CAST(LEN(TRIM(`{COL_NAME}`)) - LEN(REPLACE(TRIM(`{COL_NAME}`),' ','')) AS FLOAT)) AS avg_embedded_spaces
    FROM sampleable_rows
)
, pattern_counts AS (
  SELECT pattern,
         COUNT(*) AS pattern_ct,
         COUNT(value_length) AS value_ct,
         MAX(value_length) AS max_length
    FROM ( SELECT CASE
                    WHEN v > ' '
                      THEN TRANSLATE(
                             v, 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', 'aaaaaaaaaaaaaaaaaaaaaaaaaaAAAAAAAAAAAAAAAAAAAAAAAAAANNNNNNNNNN'
                           )
                  END AS pattern,
                  LEN(v) AS value_length
             FROM pattern_rows ) patterned
   GROUP BY pattern
)
, ranked_patterns AS (
  SELECT pattern,
         pattern_ct,
         value_ct,
         CASE
           WHEN pattern IS NOT NULL AND MAX(max_length) OVER () BETWEEN 3 AND {MAX_PATTERN_LENGTH}
             THEN ROW_NUMBER() OVER (ORDER BY CASE WHEN pattern IS NULL THEN 1 ELSE 0 END, pattern_ct DESC, CAST(pattern AS BINARY))
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
    COUNT(pattern) AS distinct_pattern_ct,
    SUM(value_ct) AS sample_pattern_value_ct
    FROM ranked_patterns
)
SELECT *
  FROM whole_table_measures
  CROSS JOIN sampleable_measures
  CROSS JOIN pattern_measures
-- TG-ENDIF
-- TG-IF is_not_A
SELECT
  COUNT(`{COL_NAME}`) AS value_ct,
-- TG-ENDIF
-- TG-IF is_distinct_countable
  COUNT(DISTINCT `{COL_NAME}`) AS distinct_value_ct,
-- TG-ENDIF
-- TG-IF is_X_text_counted
  -- An X type may have no equality operator (map, variant), so it is counted by its text form
  COUNT(DISTINCT CAST(`{COL_NAME}` AS STRING)) AS distinct_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A
  SUM(CASE WHEN `{COL_NAME}` IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
-- TG-ENDIF
-- TG-IF is_type_DN
  MIN(LEN(`{COL_NAME}`)) AS min_length,
  MAX(LEN(`{COL_NAME}`)) AS max_length,
  AVG(CAST(NULLIF(LEN(`{COL_NAME}`), 0) AS DOUBLE)) AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_N
  CAST(SUM( 1 - ABS(SIGN(`{COL_NAME}`)))AS BIGINT ) AS zero_value_ct,
  MIN(`{COL_NAME}`) AS min_value,
  MIN(CASE WHEN `{COL_NAME}` > 0 THEN `{COL_NAME}` ELSE NULL END) AS min_value_over_0,
  MAX(`{COL_NAME}`) AS max_value,
  AVG(CAST(`{COL_NAME}` AS DOUBLE)) AS avg_value,
  STDDEV_SAMP(CAST(`{COL_NAME}` AS DOUBLE)) AS stdev_value,
  MIN(pct_25) AS percentile_25,
  MIN(pct_50) AS percentile_50,
  MIN(pct_75) AS percentile_75,
-- TG-ENDIF
-- TG-IF is_N_decimal
  SUM(ROUND(CAST(ABS(MOD(`{COL_NAME}`, 1)) AS DECIMAL(38,8)), 5)) AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_type_D
  CASE
         WHEN MIN(`{COL_NAME}`) IS NULL THEN NULL
         ELSE CASE WHEN MIN(`{COL_NAME}`) >= CAST('0001-01-01' AS date) THEN MIN(`{COL_NAME}`) ELSE CAST('0001-01-01' AS date) END
       END AS min_date,
  MAX(`{COL_NAME}`) AS max_date,
  SUM(CASE
        WHEN <%DATEDIFF_MONTH; `{COL_NAME}`; '{RUN_DATE}'::TIMESTAMP%> > 12 THEN 1
                                                            ELSE 0
      END) AS before_1yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_MONTH; `{COL_NAME}`; '{RUN_DATE}'::TIMESTAMP%> > 60 THEN 1
                                                            ELSE 0
      END) AS before_5yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_MONTH; `{COL_NAME}`; '{RUN_DATE}'::TIMESTAMP%> > 240 THEN 1
                                                              ELSE 0
      END) AS before_20yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_MONTH; `{COL_NAME}`; '{RUN_DATE}'::TIMESTAMP%> > 1200 THEN 1
                                                                ELSE 0
      END) AS before_100yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_DAY; `{COL_NAME}`; '{RUN_DATE}'::TIMESTAMP%> BETWEEN 0 AND 365 THEN 1
                                                                         ELSE 0
      END) AS within_1yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_DAY; `{COL_NAME}`; '{RUN_DATE}'::TIMESTAMP%> BETWEEN 0 AND 30 THEN 1
                                                                        ELSE 0
      END) AS within_1mo_date_ct,
  SUM(CASE
        WHEN `{COL_NAME}` > '{RUN_DATE}' THEN 1 ELSE 0
      END) AS future_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_MONTH; '{RUN_DATE}'::TIMESTAMP; `{COL_NAME}`%> > 240 THEN 1
                                                               ELSE 0
      END) AS distant_future_date_ct,
  COUNT(DISTINCT <%DATEDIFF_DAY; `{COL_NAME}`; '{RUN_DATE}'::DATE%>) AS date_days_present,
  COUNT(DISTINCT <%DATEDIFF_WEEK; `{COL_NAME}`; '{RUN_DATE}'::DATE%>) AS date_weeks_present,
  COUNT(DISTINCT <%DATEDIFF_MONTH; `{COL_NAME}`; '{RUN_DATE}'::DATE%>) AS date_months_present,
-- TG-ENDIF
-- TG-IF is_type_B
  SUM(CAST(`{COL_NAME}` AS INTEGER)) AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_not_A
  COUNT(*) AS record_ct
  FROM `{DATA_SCHEMA}`.`{DATA_TABLE}`
-- TG-ENDIF
-- TG-IF is_N_approx_pctile
  , (SELECT
             approx_percentile(`{COL_NAME}`, 0.25) AS pct_25,
             approx_percentile(`{COL_NAME}`, 0.50) AS pct_50,
             approx_percentile(`{COL_NAME}`, 0.75) AS pct_75
        FROM `{DATA_SCHEMA}`.`{DATA_TABLE}` LIMIT 1) pctile
-- TG-ENDIF
-- TG-IF is_N_exact_pctile
  , (SELECT
             PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY `{COL_NAME}`) OVER () AS pct_25,
             PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY `{COL_NAME}`) OVER () AS pct_50,
             PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY `{COL_NAME}`) OVER () AS pct_75
        FROM `{DATA_SCHEMA}`.`{DATA_TABLE}` LIMIT 1) pctile
-- TG-ENDIF
