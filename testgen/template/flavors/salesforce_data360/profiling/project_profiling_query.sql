-- TG-IF is_type_A
WITH whole_table_measures AS (
  SELECT
    COUNT(*) AS record_ct,
    COUNT("{COL_NAME}") AS value_ct,
    COUNT(DISTINCT "{COL_NAME}") AS distinct_value_ct,
    SUM(CASE WHEN "{COL_NAME}" IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
    MIN(LENGTH(CAST("{COL_NAME}" AS VARCHAR))) AS min_length,
    MAX(LENGTH(CAST("{COL_NAME}" AS VARCHAR))) AS max_length,
    AVG(CAST(NULLIF(LENGTH(CAST("{COL_NAME}" AS VARCHAR)), 0) AS DOUBLE)) AS avg_length,
    SUM(CASE
          WHEN REGEXP_LIKE(TRIM("{COL_NAME}"), '^0(\.0*)?$') THEN 1 ELSE 0
        END) AS zero_value_ct,
    COUNT(DISTINCT UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("{COL_NAME}", ' ', ''), '''', ''), ',', ''), '.', ''), '-', ''))) AS distinct_std_value_ct,
    SUBSTR(MIN(NULLIF("{COL_NAME}", '')), 1, 100) AS min_text,
    SUBSTR(MAX(NULLIF("{COL_NAME}", '')), 1, 100) AS max_text
    FROM "{DATA_TABLE}"
)
-- TG-ENDIF
-- TG-IF is_A_sampling
, sampleable_rows AS (
  SELECT "{COL_NAME}"
    FROM "{DATA_TABLE}" ORDER BY RANDOM() LIMIT {SAMPLE_SIZE}
)
, pattern_rows AS (
  SELECT "{COL_NAME}" AS v
    FROM "{DATA_TABLE}" ORDER BY RANDOM() LIMIT {SAMPLE_SIZE}
)
-- TG-ENDIF
-- TG-IF is_A_no_sampling
, sampleable_rows AS (
  SELECT "{COL_NAME}"
    FROM "{DATA_TABLE}"
)
, pattern_rows AS (
  SELECT "{COL_NAME}" AS v
    FROM "{DATA_TABLE}"
)
-- TG-ENDIF
-- TG-IF is_type_A
, sampleable_measures AS (
  SELECT
    COUNT("{COL_NAME}") AS sample_value_ct,
    SUM(CASE
          WHEN "{COL_NAME}" = '' THEN 1
                               ELSE 0
        END) AS zero_length_ct,
    SUM( CASE
           WHEN ("{COL_NAME}" LIKE ' %' AND LTRIM("{COL_NAME}") <> '') THEN 1
                                                ELSE 0
         END ) AS lead_space_ct,
    SUM( CASE WHEN "{COL_NAME}" LIKE '"%"' OR "{COL_NAME}" LIKE '''%''' THEN 1 ELSE 0 END ) AS quoted_value_ct,
    SUM( CASE WHEN REGEXP_LIKE("{COL_NAME}", '[0-9]') THEN 1 ELSE 0 END ) AS includes_digit_ct,
    SUM( CASE
           WHEN REGEXP_LIKE(LOWER("{COL_NAME}"), '^(\.{1,}|-{1,}|\?{1,}|\s{1,}|0{2,}|9{2,}|x{2,}|z{2,})$') THEN 1
           WHEN LOWER("{COL_NAME}") IN ('blank','error','missing','tbd',
                                      'n/a','#na','none','null','unknown')           THEN 1
           WHEN LOWER("{COL_NAME}") IN ('(blank)','(error)','(missing)','(tbd)',
                                      '(n/a)','(#na)','(none)','(null)','(unknown)') THEN 1
           WHEN LOWER("{COL_NAME}") IN ('[blank]','[error]','[missing]','[tbd]',
                                      '[n/a]','[#na]','[none]','[null]','[unknown]') THEN 1
                                                                                     ELSE 0
         END ) AS filled_value_ct,
    SUM(CASE WHEN "{COL_NAME}" = UPPER("{COL_NAME}") AND "{COL_NAME}" <> LOWER("{COL_NAME}") THEN 1 ELSE 0 END) AS upper_case_ct,
    SUM(CASE WHEN "{COL_NAME}" = LOWER("{COL_NAME}") AND "{COL_NAME}" <> UPPER("{COL_NAME}") THEN 1 ELSE 0 END) AS lower_case_ct,
    SUM(CASE WHEN "{COL_NAME}" = UPPER("{COL_NAME}") AND "{COL_NAME}" = LOWER("{COL_NAME}") THEN 1 ELSE 0 END) AS non_alpha_ct,
    SUM(CASE WHEN REGEXP_REPLACE("{COL_NAME}",
              '[' || CHR(160) || CHR(8201) || CHR(8203) || CHR(8204) || CHR(8205) || CHR(8206) || CHR(8207) || CHR(8239) || CHR(12288) || CHR(65279) || ']',
              'X', 'g') <> "{COL_NAME}" THEN 1 ELSE 0 END) AS non_printing_ct,
    SUM(<%IS_NUM;SUBSTR("{COL_NAME}", 1, 31)%>) AS numeric_ct,
    SUM(<%IS_DATE;SUBSTR("{COL_NAME}", 1, 26)%>) AS date_ct,
    CASE
      WHEN SUM( CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[0-9]{1,5}[a-zA-Z]?\s\w{1,5}\.?\s?\w*\s?\w*\s[a-zA-Z]{1,6}\.?\s?[0-9]{0,5}[A-Z]{0,1}$')
           THEN 1 END) > CAST(0.8 * COUNT("{COL_NAME}") AS BIGINT) THEN 'STREET_ADDR'
      WHEN SUM(CASE WHEN "{COL_NAME}" IN ('AL','AK','AS','AZ','AR','CA','CO','CT','DE','DC','FM','FL','GA','GU','HI','ID','IL','IN','IA','KS','KY','LA','ME','MH','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','MP','OH','OK','OR','PW','PA','PR','RI','SC','SD','TN','TX','UT','VT','VI','VA','WA','WV','WI','WY','AE','AP','AA')
           THEN 1 END) > CAST(0.9 * COUNT("{COL_NAME}") AS BIGINT) THEN 'STATE_USA'
      WHEN SUM( CASE WHEN REGEXP_LIKE("{COL_NAME}", '^(\+1|1)?[ .\-]?(\([2-9][0-9]{2}\)|[2-9][0-9]{2})[ .\-]?[2-9][0-9]{2}[ .\-]?[0-9]{4}$')
           THEN 1 END) > CAST(0.8 * COUNT("{COL_NAME}") AS BIGINT) THEN 'PHONE_USA'
      WHEN SUM( CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
                      AND "{COL_NAME}" NOT LIKE '%://%'
           THEN 1 END) > CAST(0.9 * COUNT("{COL_NAME}") AS BIGINT) THEN 'EMAIL'
      WHEN SUM( CASE WHEN REGEXP_LIKE(REGEXP_REPLACE("{COL_NAME}", '[0-9]', '9', 'g'), '^(99999|999999999|99999-9999)$')
           THEN 1 END) > CAST(0.9 * COUNT("{COL_NAME}") AS BIGINT) THEN 'ZIP_USA'
      WHEN SUM( CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[\w\s\-]+\.(txt|csv|tsv|dat|doc|pdf|xlsx)$')
           THEN 1 END) > CAST(0.9 * COUNT("{COL_NAME}") AS BIGINT) THEN 'FILE_NAME'
      WHEN SUM( CASE WHEN REGEXP_LIKE("{COL_NAME}", '^([0-9]{4}[- ]?){3}[0-9]{4}$')
           THEN 1 END) > CAST(0.8 * COUNT("{COL_NAME}") AS BIGINT) THEN 'CREDIT_CARD'
      WHEN SUM( CASE WHEN REGEXP_LIKE("{COL_NAME}", '^([^,|\t]{1,20}[,|\t]){2,}[^,|\t]{0,20}([,|\t]{0,1}[^,|\t]{0,20})*$')
                      AND NOT REGEXP_LIKE("{COL_NAME}", '\s(and|but|or|yet)\s')
           THEN 1 END) > CAST(0.8 * COUNT("{COL_NAME}") AS BIGINT) THEN 'DELIMITED_DATA'
      WHEN SUM ( CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[0-8][0-9]{2}-[0-9]{2}-[0-9]{4}$')
                       AND SUBSTR("{COL_NAME}", 1, 3) NOT BETWEEN '734' AND '749'
                       AND SUBSTR("{COL_NAME}", 1, 3) <> '666' THEN 1 END) > CAST(0.9 * COUNT("{COL_NAME}") AS BIGINT) THEN 'SSN'
    END AS std_pattern_match,
    SUM(CASE WHEN LENGTH(TRIM("{COL_NAME}")) - LENGTH(REGEXP_REPLACE(TRIM("{COL_NAME}"), ' ', '', 'g')) > 0 THEN 1 ELSE 0 END) AS embedded_space_ct,
    AVG(CAST(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REGEXP_REPLACE(TRIM("{COL_NAME}"), ' ', '', 'g')) AS DOUBLE)) AS avg_embedded_spaces
    FROM sampleable_rows
)
, pattern_counts AS (
  SELECT pattern,
         COUNT(*) AS pattern_ct,
         COUNT(value_length) AS value_ct,
         MAX(value_length) AS max_length
    FROM ( SELECT CASE
                    WHEN v > ' '
                      THEN REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
                             v, '[a-z]', 'a', 'g'),
                                '[A-Z]', 'A', 'g'),
                                '[0-9]', 'N', 'g')
                  END AS pattern,
                  LENGTH(v) AS value_length
             FROM pattern_rows ) patterned
   GROUP BY pattern
)
, ranked_patterns AS (
  SELECT pattern,
         pattern_ct,
         value_ct,
         CASE
           WHEN pattern IS NOT NULL AND MAX(max_length) OVER () BETWEEN 3 AND {MAX_PATTERN_LENGTH}
             THEN ROW_NUMBER() OVER (ORDER BY CASE WHEN pattern IS NULL THEN 1 ELSE 0 END, pattern_ct DESC, pattern)
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
  INNER JOIN sampleable_measures ON 1 = 1
  INNER JOIN pattern_measures ON 1 = 1
-- TG-ENDIF
-- TG-IF is_not_A
SELECT
  COUNT("{COL_NAME}") AS value_ct,
  COUNT(DISTINCT "{COL_NAME}") AS distinct_value_ct,
  SUM(CASE WHEN "{COL_NAME}" IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
-- TG-ENDIF
-- TG-IF is_type_DN
  MIN(LENGTH(CAST("{COL_NAME}" AS VARCHAR))) AS min_length,
  MAX(LENGTH(CAST("{COL_NAME}" AS VARCHAR))) AS max_length,
  AVG(CAST(NULLIF(LENGTH(CAST("{COL_NAME}" AS VARCHAR)), 0) AS DOUBLE)) AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_N
  SUM(CASE WHEN CAST("{COL_NAME}" AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS zero_value_ct,
  MIN("{COL_NAME}") AS min_value,
  MIN(CASE WHEN CAST("{COL_NAME}" AS DOUBLE) > 0 THEN "{COL_NAME}" ELSE NULL END) AS min_value_over_0,
  MAX("{COL_NAME}") AS max_value,
  AVG(CAST("{COL_NAME}" AS DOUBLE)) AS avg_value,
  STDDEV(CAST("{COL_NAME}" AS DOUBLE)) AS stdev_value,
  MIN(pctile.pct_25) AS percentile_25,
  MIN(pctile.pct_50) AS percentile_50,
  MIN(pctile.pct_75) AS percentile_75,
-- TG-ENDIF
-- TG-IF is_N_decimal
  SUM(ROUND(CAST(ABS(MOD(CAST("{COL_NAME}" AS DOUBLE), 1)) AS NUMERIC(38,8)), 5)) AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_type_D
  CASE
         WHEN MIN("{COL_NAME}") IS NULL THEN NULL
         ELSE GREATEST(MIN("{COL_NAME}"), CAST('0001-01-01' AS TIMESTAMP))
       END AS min_date,
  MAX("{COL_NAME}") AS max_date,
  SUM(CASE
        WHEN DATEDIFF('month', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP)) > 12 THEN 1
                                                            ELSE 0
      END) AS before_1yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF('month', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP)) > 60 THEN 1
                                                            ELSE 0
      END) AS before_5yr_date_ct,
  SUM(CASE
          WHEN DATEDIFF('month', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP)) > 240 THEN 1
                                                              ELSE 0
        END) AS before_20yr_date_ct,
  SUM(CASE
          WHEN DATEDIFF('month', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP)) > 1200 THEN 1
                                                              ELSE 0
        END) AS before_100yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF('day', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP)) BETWEEN 0 AND 365 THEN 1
                                                                         ELSE 0
      END) AS within_1yr_date_ct,
  SUM(CASE
        WHEN DATEDIFF('day', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP)) BETWEEN 0 AND 30 THEN 1
                                                                        ELSE 0
      END) AS within_1mo_date_ct,
  SUM(CASE
        WHEN "{COL_NAME}" > CAST('{RUN_DATE}' AS TIMESTAMP) THEN 1 ELSE 0
      END) AS future_date_ct,
  SUM(CASE
          WHEN DATEDIFF('month', CAST('{RUN_DATE}' AS TIMESTAMP), CAST("{COL_NAME}" AS TIMESTAMP)) > 240 THEN 1
                                                                                  ELSE 0
        END) AS distant_future_date_ct,
  COUNT(DISTINCT DATEDIFF('day', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP))) AS date_days_present,
  COUNT(DISTINCT DATEDIFF('week', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP))) AS date_weeks_present,
  COUNT(DISTINCT DATEDIFF('month', CAST("{COL_NAME}" AS TIMESTAMP), CAST('{RUN_DATE}' AS TIMESTAMP))) AS date_months_present,
-- TG-ENDIF
-- TG-IF is_type_B
  SUM(CAST("{COL_NAME}" AS INTEGER)) AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_not_A
  COUNT(*) AS record_ct
  FROM "{DATA_TABLE}"
-- TG-ENDIF
-- TG-IF is_type_N
  INNER JOIN (SELECT APPROX_PERCENTILE(CAST("{COL_NAME}" AS DOUBLE), 0.25) AS pct_25,
                     APPROX_PERCENTILE(CAST("{COL_NAME}" AS DOUBLE), 0.50) AS pct_50,
                     APPROX_PERCENTILE(CAST("{COL_NAME}" AS DOUBLE), 0.75) AS pct_75
                FROM "{DATA_TABLE}") pctile ON 1 = 1
-- TG-ENDIF
