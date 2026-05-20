WITH target_table AS (
-- TG-IF do_sample
  SELECT *  FROM "{DATA_TABLE}" ORDER BY RANDOM() LIMIT {SAMPLE_SIZE}
-- TG-ELSE
  SELECT *  FROM "{DATA_TABLE}"
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
  COUNT("{COL_NAME}") AS value_ct,
  COUNT(DISTINCT "{COL_NAME}") AS distinct_value_ct,
  SUM(CASE WHEN "{COL_NAME}" IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
-- TG-IF is_type_ADN
  MIN(LENGTH(CAST("{COL_NAME}" AS VARCHAR))) AS min_length,
  MAX(LENGTH(CAST("{COL_NAME}" AS VARCHAR))) AS max_length,
  AVG(CAST(NULLIF(LENGTH(CAST("{COL_NAME}" AS VARCHAR)), 0) AS DOUBLE)) AS avg_length,
-- TG-ELSE
  NULL AS min_length,
  NULL AS max_length,
  NULL AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_A
  SUM(CASE
        WHEN REGEXP_LIKE(TRIM("{COL_NAME}"), '^0(\.0*)?$') THEN 1 ELSE 0
      END) AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_type_N
  SUM(CASE WHEN CAST("{COL_NAME}" AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A_not_N
  NULL AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_type_A
  COUNT(DISTINCT UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("{COL_NAME}", ' ', ''), '''', ''), ',', ''), '.', ''), '-', ''))) AS distinct_std_value_ct,
  SUM(CASE
        WHEN "{COL_NAME}" = '' THEN 1
                             ELSE 0
      END) AS zero_length_ct,
  SUM( CASE
         WHEN "{COL_NAME}" BETWEEN ' !' AND '!' THEN 1
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
  SUBSTR(MIN(NULLIF("{COL_NAME}", '')), 1, 100) AS min_text,
  SUBSTR(MAX(NULLIF("{COL_NAME}", '')), 1, 100) AS max_text,
  SUM(CASE
        WHEN REGEXP_REPLACE("{COL_NAME}", '[A-Za-z]', '', 'g') = "{COL_NAME}" THEN 0
        WHEN REGEXP_REPLACE("{COL_NAME}", '[a-z]', '', 'g') = "{COL_NAME}" THEN 1
        ELSE 0
      END) AS upper_case_ct,
  SUM(CASE
        WHEN REGEXP_REPLACE("{COL_NAME}", '[A-Za-z]', '', 'g') = "{COL_NAME}" THEN 0
        WHEN REGEXP_REPLACE("{COL_NAME}", '[A-Z]', '', 'g') = "{COL_NAME}" THEN 1
        ELSE 0
      END) AS lower_case_ct,
  SUM(CASE
        WHEN REGEXP_REPLACE("{COL_NAME}", '[A-Za-z]', '', 'g') = "{COL_NAME}" THEN 1
        ELSE 0
      END) AS non_alpha_ct,
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
  (SELECT SUBSTR(ARRAY_JOIN(ARRAY_AGG(pattern), ' | '), 1, 1000) AS concat_pats
      FROM (
            SELECT CAST(COUNT(*) AS VARCHAR) || ' | ' || pattern AS pattern,
                   COUNT(*) AS ct
              FROM (  SELECT REGEXP_REPLACE(REGEXP_REPLACE( REGEXP_REPLACE(
                        "{COL_NAME}", '[a-z]', 'a', 'g'),
                                    '[A-Z]', 'A', 'g'),
                                    '[0-9]', 'N', 'g') AS pattern
                       FROM target_table
                      WHERE "{COL_NAME}" > ' ' AND (SELECT MAX(LENGTH("{COL_NAME}"))
                                                      FROM target_table) BETWEEN 3 and {MAX_PATTERN_LENGTH}) p
            GROUP BY pattern
            HAVING pattern > ' '
            ORDER BY COUNT(*) DESC
            LIMIT 5
           ) ps) AS top_patterns,
-- TG-ELSE
  NULL AS top_patterns,
-- TG-ENDIF
-- TG-IF is_type_N
  MIN("{COL_NAME}") AS min_value,
  MIN(CASE WHEN CAST("{COL_NAME}" AS DOUBLE) > 0 THEN "{COL_NAME}" ELSE NULL END) AS min_value_over_0,
  MAX("{COL_NAME}") AS max_value,
  AVG(CAST("{COL_NAME}" AS DOUBLE)) AS avg_value,
  STDDEV(CAST("{COL_NAME}" AS DOUBLE)) AS stdev_value,
  APPROX_PERCENTILE(CAST("{COL_NAME}" AS DOUBLE), 0.25) AS percentile_25,
  APPROX_PERCENTILE(CAST("{COL_NAME}" AS DOUBLE), 0.50) AS percentile_50,
  APPROX_PERCENTILE(CAST("{COL_NAME}" AS DOUBLE), 0.75) AS percentile_75,
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
  SUM(ROUND(ABS(MOD(CAST("{COL_NAME}" AS DOUBLE), 1)), 5)) AS fractional_sum,
-- TG-ELSE
  NULL AS fractional_sum,
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
  (SELECT COUNT(DISTINCT REGEXP_REPLACE( REGEXP_REPLACE( REGEXP_REPLACE(
                          "{COL_NAME}", '[a-z]', 'a', 'g'),
                                      '[A-Z]', 'A', 'g'),
                                      '[0-9]', 'N', 'g')
                ) AS pattern_ct
     FROM target_table
    WHERE "{COL_NAME}" > ' ' ) AS distinct_pattern_ct,
  SUM(CASE WHEN LENGTH(TRIM("{COL_NAME}")) - LENGTH(REGEXP_REPLACE(TRIM("{COL_NAME}"), ' ', '', 'g')) > 0 THEN 1 ELSE 0 END) AS embedded_space_ct,
  AVG(CAST(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REGEXP_REPLACE(TRIM("{COL_NAME}"), ' ', '', 'g')) AS DOUBLE)) AS avg_embedded_spaces,
-- TG-ELSE
  NULL AS distinct_pattern_ct,
  NULL AS embedded_space_ct,
  NULL AS avg_embedded_spaces,
-- TG-ENDIF
  '{PROFILE_RUN_ID}' AS profile_run_id
  FROM target_table
