-- TG-IF is_type_A
WITH whole_table_measures AS (
  SELECT
    COUNT(*) AS record_ct,
    COUNT(`{COL_NAME}`) AS value_ct,
    COUNT(DISTINCT `{COL_NAME}`) AS distinct_value_ct,
    SUM(IF(`{COL_NAME}` IS NULL, 1, 0)) AS null_value_ct,
    MIN(LENGTH(CAST(`{COL_NAME}` AS STRING))) AS min_length,
    MAX(LENGTH(CAST(`{COL_NAME}` AS STRING))) AS max_length,
    AVG(NULLIF(LENGTH(CAST(`{COL_NAME}` AS STRING)), 0)) AS avg_length,
    SUM(
      CASE
        WHEN REGEXP_CONTAINS(TRIM(CAST(`{COL_NAME}` AS STRING)), r'^0(\.0*)?$') THEN 1
        ELSE 0
      END
    ) AS zero_value_ct,
    COUNT(
      DISTINCT UPPER(
        REGEXP_REPLACE(CAST(`{COL_NAME}` AS STRING), r"[ '\.,-]", "")
      )
    ) AS distinct_std_value_ct,
    LEFT(MIN(NULLIF(`{COL_NAME}`, '')), 100) AS min_text,
    LEFT(MAX(NULLIF(`{COL_NAME}`, '')), 100) AS max_text
    FROM `{DATA_SCHEMA}.{DATA_TABLE}`
)
-- TG-ENDIF
-- TG-IF is_A_sampling
, sampleable_rows AS (
  SELECT `{COL_NAME}`
    FROM `{DATA_SCHEMA}.{DATA_TABLE}` WHERE RAND() * 100 < {SAMPLE_PERCENT_CALC}
)
, pattern_rows AS (
  SELECT `{COL_NAME}` AS v
    FROM `{DATA_SCHEMA}.{DATA_TABLE}` WHERE RAND() * 100 < {SAMPLE_PERCENT_CALC}
)
-- TG-ENDIF
-- TG-IF is_A_no_sampling
, sampleable_rows AS (
  SELECT `{COL_NAME}`
    FROM `{DATA_SCHEMA}.{DATA_TABLE}`
)
, pattern_rows AS (
  SELECT `{COL_NAME}` AS v
    FROM `{DATA_SCHEMA}.{DATA_TABLE}`
)
-- TG-ENDIF
-- TG-IF is_type_A
, sampleable_measures AS (
  SELECT
    COUNT(`{COL_NAME}`) AS sample_value_ct,
    SUM(CASE WHEN `{COL_NAME}` = '' THEN 1 ELSE 0 END) AS zero_length_ct,
    SUM(CASE WHEN (`{COL_NAME}` LIKE ' %' AND LTRIM(`{COL_NAME}`) <> '') THEN 1 ELSE 0 END) AS lead_space_ct,
    SUM(
      CASE
        WHEN LOWER(CAST(`{COL_NAME}` AS STRING)) LIKE '"%"'
          OR LOWER(CAST(`{COL_NAME}` AS STRING)) LIKE "'%'" THEN 1
        ELSE 0
      END
    ) AS quoted_value_ct,
    SUM(
      CASE
        WHEN REGEXP_CONTAINS(CAST(`{COL_NAME}` AS STRING), r'.*[0-9].*') THEN 1
        ELSE 0
      END
    ) AS includes_digit_ct,
    SUM(
      CASE
        WHEN REGEXP_CONTAINS(LOWER(CAST(`{COL_NAME}` AS STRING)), r'^(\.{1,}|-{1,}|\?{1,}|\s{1,}|0{2,}|9{2,}|x{2,}|z{2,})$') THEN 1
        WHEN LOWER(CAST(`{COL_NAME}` AS STRING)) IN ('blank','error','missing','tbd',
                                                     'n/a','#na','none','null','unknown') THEN 1
        WHEN LOWER(CAST(`{COL_NAME}` AS STRING)) IN ('(blank)','(error)','(missing)','(tbd)',
                                                     '(n/a)','(#na)','(none)','(null)','(unknown)') THEN 1
        WHEN LOWER(CAST(`{COL_NAME}` AS STRING)) IN ('[blank]','[error]','[missing]','[tbd]',
                                                     '[n/a]','[#na]','[none]','[null]','[unknown]') THEN 1
        ELSE 0
      END
    ) AS filled_value_ct,
    SUM(CASE WHEN CAST(`{COL_NAME}` AS BYTES) = CAST(UPPER(`{COL_NAME}`) AS BYTES) AND CAST(`{COL_NAME}` AS BYTES) <> CAST(LOWER(`{COL_NAME}`) AS BYTES) THEN 1 ELSE 0 END) AS upper_case_ct,
    SUM(CASE WHEN CAST(`{COL_NAME}` AS BYTES) = CAST(LOWER(`{COL_NAME}`) AS BYTES) AND CAST(`{COL_NAME}` AS BYTES) <> CAST(UPPER(`{COL_NAME}`) AS BYTES) THEN 1 ELSE 0 END) AS lower_case_ct,
    SUM(CASE WHEN CAST(`{COL_NAME}` AS BYTES) = CAST(UPPER(`{COL_NAME}`) AS BYTES) AND CAST(`{COL_NAME}` AS BYTES) = CAST(LOWER(`{COL_NAME}`) AS BYTES) THEN 1 ELSE 0 END) AS non_alpha_ct,
    COUNTIF(
      TRANSLATE(
        CAST(`{COL_NAME}` AS STRING),
        CODE_POINTS_TO_STRING([160, 8201, 8203, 8204, 8205, 8206, 8207, 8239, 12288, 65279]),
        REPEAT('X', 10)
      ) <> CAST(`{COL_NAME}` AS STRING)
    ) AS non_printing_ct,
    SUM(<%IS_NUM;LEFT(`{COL_NAME}`, 31)%>) AS numeric_ct,
    SUM(<%IS_DATE;LEFT(`{COL_NAME}`, 26)%>) AS date_ct,
    CASE
      WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^[0-9]{1,5}[a-zA-Z]?\s\w{1,5}\.?\s?\w*\s?\w*\s[a-zA-Z]{1,6}\.?\s?[0-9]{0,5}[A-Z]{0,1}$')
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.8 THEN 'STREET_ADDR'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN `{COL_NAME}` IN ('AL','AK','AS','AZ','AR','CA','CO','CT','DE','DC','FM','FL','GA','GU','HI','ID','IL','IN','IA','KS','KY','LA','ME','MH','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','MP','OH','OK','OR','PW','PA','PR','RI','SC','SD','TN','TX','UT','VT','VI','VA','WA','WV','WI','WY','AE','AP','AA')
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'STATE_USA'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^(\\+1|1)?[ .-]?(\\([2-9][0-9]{2}\\)|[2-9][0-9]{2})[ .-]?[2-9][0-9]{2}[ .-]?[0-9]{4}$')
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.8 THEN 'PHONE_USA'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
                AND `{COL_NAME}` NOT LIKE '%://%'
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'EMAIL'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN TRANSLATE(`{COL_NAME}`, '012345678', '999999999') IN ('99999', '999999999', '99999-9999')
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'ZIP_USA'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^[\w\s\-]+\.(txt|csv|tsv|dat|doc|pdf|xlsx)$')
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'FILE_NAME'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^([0-9]{4}[- ]?){3}[0-9]{4}$')
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.8 THEN 'CREDIT_CARD'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^([^,|\t]{1,20}[,|\t]){2,}[^,|\t]{0,20}([,|\t]{0,1}[^,|\t]{0,20})*$')
      AND NOT REGEXP_CONTAINS(`{COL_NAME}`, r'\s(and|but|or|yet)\s')
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.8 THEN 'DELIMITED_DATA'
      WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^[0-8][0-9]{2}-[0-9]{2}-[0-9]{4}$')
      AND CAST(SUBSTR(`{COL_NAME}`, 1, 3) AS INT64) NOT BETWEEN 734 AND 749
      AND SUBSTR(`{COL_NAME}`, 1, 3) <> '666'
      THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'SSN'
    END AS std_pattern_match,
    SUM(CAST(SIGN(LENGTH(TRIM(`{COL_NAME}`)) - LENGTH(REPLACE(TRIM(`{COL_NAME}`), ' ', ''))) AS INT64)) AS embedded_space_ct,
    AVG(CAST(LENGTH(TRIM(`{COL_NAME}`)) - LENGTH(REPLACE(TRIM(`{COL_NAME}`), ' ', '')) AS FLOAT64)) AS avg_embedded_spaces
    FROM sampleable_rows
)
, pattern_counts AS (
  SELECT pattern,
         COUNT(*) AS pattern_ct,
         COUNT(value_length) AS value_ct,
         MAX(value_length) AS max_length
    FROM ( SELECT CASE
                    WHEN CAST(v AS STRING) > ' '
                      THEN REGEXP_REPLACE(
                             REGEXP_REPLACE(
                               REGEXP_REPLACE(CAST(v AS STRING), r'[a-z]', 'a'),
                             r'[A-Z]', 'A'),
                           r'[0-9]', 'N')
                  END AS pattern,
                  LENGTH(CAST(v AS STRING)) AS value_length
             FROM pattern_rows ) patterned
   GROUP BY pattern
)
, ranked_patterns AS (
  SELECT pattern,
         pattern_ct,
         value_ct,
         CASE
           WHEN pattern IS NOT NULL AND MAX(max_length) OVER () BETWEEN 3 AND {MAX_PATTERN_LENGTH}
             THEN ROW_NUMBER() OVER (ORDER BY CASE WHEN pattern IS NULL THEN 1 ELSE 0 END, pattern_ct DESC, CAST(pattern AS BYTES))
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
  -- An X type may have no equality operator (JSON, STRUCT, ARRAY), so it is counted by its text form
  COUNT(DISTINCT TO_JSON_STRING(`{COL_NAME}`)) AS distinct_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A
  SUM(IF(`{COL_NAME}` IS NULL, 1, 0)) AS null_value_ct,
-- TG-ENDIF
-- TG-IF is_type_DN
  MIN(LENGTH(CAST(`{COL_NAME}` AS STRING))) AS min_length,
  MAX(LENGTH(CAST(`{COL_NAME}` AS STRING))) AS max_length,
  AVG(NULLIF(LENGTH(CAST(`{COL_NAME}` AS STRING)), 0)) AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_N
  CAST(SUM(1 - ABS(SIGN(CAST(`{COL_NAME}` AS NUMERIC)))) AS INT64) AS zero_value_ct,
  MIN(`{COL_NAME}`) AS min_value,
  MIN(CASE WHEN `{COL_NAME}` > 0 THEN `{COL_NAME}` ELSE NULL END) AS min_value_over_0,
  MAX(`{COL_NAME}`) AS max_value,
  AVG(CAST(`{COL_NAME}` AS FLOAT64)) AS avg_value,
  STDDEV(CAST(`{COL_NAME}` AS FLOAT64)) AS stdev_value,
  MIN(pct_25) AS percentile_25,
  MIN(pct_50) AS percentile_50,
  MIN(pct_75) AS percentile_75,
-- TG-ENDIF
-- TG-IF is_N_decimal
  SUM(COALESCE(ROUND(ROUND(CAST(ABS(MOD(`{COL_NAME}`, 1)) AS NUMERIC), 8), 5), 0)) AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_N_exact_sum
  CASE WHEN MAX(ABS(CAST(`{COL_NAME}` AS FLOAT64))) < 1e20 AND COUNT(`{COL_NAME}`) < 1e10
       THEN SUM(CASE WHEN ABS(CAST(`{COL_NAME}` AS FLOAT64)) < 1e20 THEN ROUND(CAST(`{COL_NAME}` AS BIGNUMERIC), 8) END)
  END AS sum_value,
-- TG-ENDIF
-- TG-IF is_type_D
  MIN(`{COL_NAME}`) AS min_date, -- Other flavors have a minimum threshold of 0001-01-01, but BigQuery doesn't make it easy to to the same
  MAX(`{COL_NAME}`) AS max_date,
  COUNT(CASE WHEN DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), MONTH) > 12 THEN 1 END) AS before_1yr_date_ct,
  COUNT(CASE WHEN DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), MONTH) > 60 THEN 1 END) AS before_5yr_date_ct,
  COUNT(CASE WHEN DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), MONTH) > 240 THEN 1 END) AS before_20yr_date_ct,
  COUNT(CASE WHEN DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), MONTH) > 1200 THEN 1 END) AS before_100yr_date_ct,
  COUNT(CASE WHEN DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), DAY) BETWEEN 0 AND 365 THEN 1 END) AS within_1yr_date_ct,
  COUNT(CASE WHEN DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), DAY) BETWEEN 0 AND 30 THEN 1 END) AS within_1mo_date_ct,
  COUNT(CASE WHEN SAFE_CAST(DATE(`{COL_NAME}`) AS DATE) > SAFE_CAST(DATE('{RUN_DATE}') AS DATE) THEN 1 END) AS future_date_ct,
  COUNT(CASE WHEN DATE_DIFF(SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), SAFE_CAST(DATE('{RUN_DATE}') AS DATE), MONTH) > 240 THEN 1 END) AS distant_future_date_ct,
  COUNT(DISTINCT DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), DAY)) AS date_days_present,
  COUNT(DISTINCT DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), ISOWEEK)) AS date_weeks_present,
  COUNT(DISTINCT DATE_DIFF(SAFE_CAST(DATE('{RUN_DATE}') AS DATE), SAFE_CAST(DATE(`{COL_NAME}`) AS DATE), MONTH)) AS date_months_present,
-- TG-ENDIF
-- TG-IF is_type_B
  SUM(CAST(`{COL_NAME}` AS INT64)) AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_not_A
  COUNT(*) AS record_ct
  FROM `{DATA_SCHEMA}.{DATA_TABLE}`
-- TG-ENDIF
-- TG-IF is_N_approx_pctile
  ,
  (SELECT
       APPROX_QUANTILES(`{COL_NAME}`, 100)[OFFSET(25)] AS pct_25,
       APPROX_QUANTILES(`{COL_NAME}`, 100)[OFFSET(50)] AS pct_50,
       APPROX_QUANTILES(`{COL_NAME}`, 100)[OFFSET(75)] AS pct_75
  FROM `{DATA_SCHEMA}.{DATA_TABLE}` LIMIT 1) pctile
-- TG-ENDIF
-- TG-IF is_N_exact_pctile
  ,
  (SELECT
         PERCENTILE_CONT(`{COL_NAME}`, 0.25) OVER() AS pct_25,
         PERCENTILE_CONT(`{COL_NAME}`, 0.50) OVER() AS pct_50,
         PERCENTILE_CONT(`{COL_NAME}`, 0.75) OVER() AS pct_75
    FROM `{DATA_SCHEMA}.{DATA_TABLE}` LIMIT 1) pctile
-- TG-ENDIF
