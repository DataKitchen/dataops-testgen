WITH target_table AS (
-- TG-IF do_sample
  SELECT * FROM `{DATA_SCHEMA}.{DATA_TABLE}` WHERE RAND() * 100 < {SAMPLE_PERCENT_CALC}
-- TG-ELSE
  SELECT * FROM `{DATA_SCHEMA}.{DATA_TABLE}`
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
  COUNT(`{COL_NAME}`) AS value_ct,
  COUNT(DISTINCT `{COL_NAME}`) AS distinct_value_ct,
  SUM(IF(`{COL_NAME}` IS NULL, 1, 0)) AS null_value_ct,
-- TG-IF is_type_ADN
  MIN(LENGTH(CAST(`{COL_NAME}` AS STRING))) AS min_length,
  MAX(LENGTH(CAST(`{COL_NAME}` AS STRING))) AS max_length,
  AVG(NULLIF(LENGTH(CAST(`{COL_NAME}` AS STRING)), 0)) AS avg_length,
-- TG-ELSE
  NULL AS min_length,
  NULL AS max_length,
  NULL AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_A
  SUM(
    CASE
      WHEN REGEXP_CONTAINS(TRIM(CAST(`{COL_NAME}` AS STRING)), r'^0(\.0*)?$') THEN 1
      ELSE 0
    END
  ) AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_type_N
  CAST(SUM(1 - ABS(SIGN(CAST(`{COL_NAME}` AS NUMERIC)))) AS INT64) AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A_not_N
  NULL AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_type_A
  COUNT(
    DISTINCT UPPER(
      REGEXP_REPLACE(CAST(`{COL_NAME}` AS STRING), r"[ '\.,-]", "")
    )
  ) AS distinct_std_value_ct,
  SUM(CASE WHEN `{COL_NAME}` = '' THEN 1 ELSE 0 END) AS zero_length_ct,
  SUM(CASE WHEN `{COL_NAME}` BETWEEN ' !' AND '!' THEN 1 ELSE 0 END) AS lead_space_ct,
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
  LEFT(MIN(NULLIF(`{COL_NAME}`, '')), 100) AS min_text,
  LEFT(MAX(NULLIF(`{COL_NAME}`, '')), 100) AS max_text,
  SUM(CASE WHEN `{COL_NAME}` = UPPER(`{COL_NAME}`) AND `{COL_NAME}` <> LOWER(`{COL_NAME}`) THEN 1 ELSE 0 END) AS upper_case_ct,
  SUM(CASE WHEN `{COL_NAME}` = LOWER(`{COL_NAME}`) AND `{COL_NAME}` <> UPPER(`{COL_NAME}`) THEN 1 ELSE 0 END) AS lower_case_ct,
  SUM(CASE WHEN `{COL_NAME}` = UPPER(`{COL_NAME}`) AND `{COL_NAME}` = LOWER(`{COL_NAME}`) THEN 1 ELSE 0 END) AS non_alpha_ct,
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
    THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'EMAIL'
    WHEN SAFE_DIVIDE(SUM(CASE WHEN TRANSLATE(`{COL_NAME}`, '012345678', '999999999') IN ('99999', '999999999', '99999-9999')
    THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'ZIP_USA'
    WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^[\w\s\-]+\.(txt|csv|tsv|dat|doc|pdf|xlsx)$')
    THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'FILE_NAME'
    WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^([0-9]{4}[- ]){3}[0-9]{4}$')
    THEN 1 END), COUNT(`{COL_NAME}`)) > 0.8 THEN 'CREDIT_CARD'
    WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^([^,|\t]{1,20}[,|\t]){2,}[^,|\t]{0,20}([,|\t]{0,1}[^,|\t]{0,20})*$')
    AND NOT REGEXP_CONTAINS(`{COL_NAME}`, r'\s(and|but|or|yet)\s')
    THEN 1 END), COUNT(`{COL_NAME}`)) > 0.8 THEN 'DELIMITED_DATA'
    WHEN SAFE_DIVIDE(SUM(CASE WHEN REGEXP_CONTAINS(`{COL_NAME}`, r'^[0-8][0-9]{2}-[0-9]{2}-[0-9]{4}$')
    AND CAST(SUBSTR(`{COL_NAME}`, 1, 3) AS INT64) NOT BETWEEN 734 AND 749
    AND SUBSTR(`{COL_NAME}`, 1, 3) <> '666'
    THEN 1 END), COUNT(`{COL_NAME}`)) > 0.9 THEN 'SSN'
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
  (
    SELECT LEFT(STRING_AGG(val, ' | ' ORDER BY ct DESC), 1000) AS top_patterns
    FROM (
      SELECT CONCAT(CAST(ct AS STRING), ' | ', pattern) AS val,
             ct
      FROM (
        SELECT pattern,
               COUNT(*) AS ct
        FROM (
          SELECT REGEXP_REPLACE(
                   REGEXP_REPLACE(
                     REGEXP_REPLACE(CAST({COL_NAME} AS STRING), r'[a-z]', 'a'),
                   r'[A-Z]', 'A'),
                 r'[0-9]', 'N') AS pattern
          FROM `target_table`
          WHERE {COL_NAME} > ' '
            AND (
              SELECT MAX(LENGTH(CAST({COL_NAME} AS STRING)))
              FROM `target_table`
            ) BETWEEN 3 AND {MAX_PATTERN_LENGTH}
        ) p
        GROUP BY pattern
        HAVING pattern > ' '
        ORDER BY ct DESC
        LIMIT 5
      )
    ) ps
  ) AS top_patterns,
-- TG-ELSE
  NULL AS top_patterns,
-- TG-ENDIF
-- TG-IF is_type_N
  MIN(`{COL_NAME}`) AS min_value,
  MIN(CASE WHEN `{COL_NAME}` > 0 THEN `{COL_NAME}` ELSE NULL END) AS min_value_over_0,
  MAX(`{COL_NAME}`) AS max_value,
  AVG(CAST(`{COL_NAME}` AS FLOAT64)) AS avg_value,
  STDDEV(CAST(`{COL_NAME}` AS FLOAT64)) AS stdev_value,
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
  SUM(COALESCE(ROUND(ABS(MOD(`{COL_NAME}`, 1)), 5), 0)) AS fractional_sum,
-- TG-ELSE
  NULL AS fractional_sum,
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
  SUM(CAST(`{COL_NAME}` AS INT64)) AS boolean_true_ct,
-- TG-ELSE
  NULL AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_type_A
  (
    SELECT
      COUNT(DISTINCT REGEXP_REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(CAST(`{COL_NAME}` AS STRING), r'[a-z]', 'a'),
          r'[A-Z]', 'A'
        ),
        r'[0-9]', 'N'
      )) AS pattern_ct
    FROM `target_table`
    WHERE `{COL_NAME}` > ' '
  ) AS distinct_pattern_ct,
  SUM(CAST(SIGN(LENGTH(TRIM(`{COL_NAME}`)) - LENGTH(REPLACE(TRIM(`{COL_NAME}`), ' ', ''))) AS INT64)) AS embedded_space_ct,
  AVG(CAST(LENGTH(TRIM(`{COL_NAME}`)) - LENGTH(REPLACE(TRIM(`{COL_NAME}`), ' ', '')) AS FLOAT64)) AS avg_embedded_spaces,
-- TG-ELSE
  NULL AS distinct_pattern_ct,
  NULL AS embedded_space_ct,
  NULL AS avg_embedded_spaces,
-- TG-ENDIF
  '{PROFILE_RUN_ID}' AS profile_run_id
  FROM target_table
-- TG-IF is_N_sampling
  ,
  (SELECT
       APPROX_QUANTILES(`{COL_NAME}`, 100)[OFFSET(25)] AS pct_25,
       APPROX_QUANTILES(`{COL_NAME}`, 100)[OFFSET(50)] AS pct_50,
       APPROX_QUANTILES(`{COL_NAME}`, 100)[OFFSET(75)] AS pct_75
  FROM `{DATA_SCHEMA}.{DATA_TABLE}` LIMIT 1) pctile
-- TG-ENDIF
-- TG-IF is_N_no_sampling
  ,
  (SELECT
         PERCENTILE_CONT(`{COL_NAME}`, 0.25) OVER() AS pct_25,
         PERCENTILE_CONT(`{COL_NAME}`, 0.50) OVER() AS pct_50,
         PERCENTILE_CONT(`{COL_NAME}`, 0.75) OVER() AS pct_75
    FROM `{DATA_SCHEMA}.{DATA_TABLE}` LIMIT 1) pctile
-- TG-ENDIF
