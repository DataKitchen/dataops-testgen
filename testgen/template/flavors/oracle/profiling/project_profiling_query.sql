SELECT
  main.connection_id,
  main.project_code,
  main.table_groups_id,
  main.schema_name,
  main.run_date,
  main.table_name,
  main.position,
  main.column_name,
  main.column_type,
  main.db_data_type,
  main.general_type,
  main.record_ct,
  main.value_ct,
  main.distinct_value_ct,
  main.null_value_ct,
  main.min_length,
  main.max_length,
  main.avg_length,
  main.zero_value_ct,
  main.distinct_std_value_ct,
  main.zero_length_ct,
  main.lead_space_ct,
  main.quoted_value_ct,
  main.includes_digit_ct,
  main.filled_value_ct,
  main.min_text,
  main.max_text,
  main.upper_case_ct,
  main.lower_case_ct,
  main.non_alpha_ct,
  main.non_printing_ct,
  main.numeric_ct,
  main.date_ct,
  main.std_pattern_match,
-- TG-IF is_type_A
  patterns.top_patterns,
-- TG-ELSE
  NULL AS top_patterns,
-- TG-ENDIF
  main.min_value,
  main.min_value_over_0,
  main.max_value,
  main.avg_value,
  main.stdev_value,
  main.percentile_25,
  main.percentile_50,
  main.percentile_75,
  main.fractional_sum,
  main.min_date,
  main.max_date,
  main.before_1yr_date_ct,
  main.before_5yr_date_ct,
  main.before_20yr_date_ct,
  main.before_100yr_date_ct,
  main.within_1yr_date_ct,
  main.within_1mo_date_ct,
  main.future_date_ct,
  main.distant_future_date_ct,
  main.date_days_present,
  main.date_weeks_present,
  main.date_months_present,
  main.boolean_true_ct,
-- TG-IF is_type_A
  patterns.distinct_pattern_ct,
-- TG-ELSE
  NULL AS distinct_pattern_ct,
-- TG-ENDIF
  main.embedded_space_ct,
  main.avg_embedded_spaces,
  main.profile_run_id
FROM (
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
    MIN(LENGTH(TO_CHAR("{COL_NAME}"))) AS min_length,
    MAX(LENGTH(TO_CHAR("{COL_NAME}"))) AS max_length,
    AVG(NULLIF(LENGTH(TO_CHAR("{COL_NAME}")), 0)) AS avg_length,
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
    SUM(1 - ABS(SIGN("{COL_NAME}"))) AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A_not_N
    NULL AS zero_value_ct,
-- TG-ENDIF
-- TG-IF is_type_A
    COUNT(DISTINCT UPPER(TRANSLATE("{COL_NAME}", 'X '',.-', 'X'))) AS distinct_std_value_ct,
    0 AS zero_length_ct,
    SUM(CASE
           WHEN "{COL_NAME}" BETWEEN ' !' AND '!' THEN 1
                                                ELSE 0
         END) AS lead_space_ct,
    SUM(CASE WHEN "{COL_NAME}" LIKE '"%"' OR "{COL_NAME}" LIKE '''%''' THEN 1 ELSE 0 END) AS quoted_value_ct,
    SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '[0-9]') THEN 1 ELSE 0 END) AS includes_digit_ct,
    SUM(CASE
           WHEN REGEXP_LIKE(LOWER("{COL_NAME}"), '^(\.{1,}|-{1,}|\?{1,}|[[:space:]]{1,}|0{2,}|9{2,}|x{2,}|z{2,})$') THEN 1
           WHEN LOWER("{COL_NAME}") IN ('blank','error','missing','tbd',
                                      'n/a','#na','none','null','unknown')           THEN 1
           WHEN LOWER("{COL_NAME}") IN ('(blank)','(error)','(missing)','(tbd)',
                                      '(n/a)','(#na)','(none)','(null)','(unknown)') THEN 1
           WHEN LOWER("{COL_NAME}") IN ('[blank]','[error]','[missing]','[tbd]',
                                      '[n/a]','[#na]','[none]','[null]','[unknown]') THEN 1
                                                                                     ELSE 0
         END) AS filled_value_ct,
    SUBSTR(MIN(CASE WHEN "{COL_NAME}" IS NOT NULL THEN "{COL_NAME}" END), 1, 100) AS min_text,
    SUBSTR(MAX(CASE WHEN "{COL_NAME}" IS NOT NULL THEN "{COL_NAME}" END), 1, 100) AS max_text,
    SUM(CASE
          WHEN TRANSLATE("{COL_NAME}", 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz', ' ') = "{COL_NAME}" THEN 0
          WHEN TRANSLATE("{COL_NAME}", 'abcdefghijklmnopqrstuvwxyz', ' ') = "{COL_NAME}" THEN 1
          ELSE 0
        END) AS upper_case_ct,
    SUM(CASE
          WHEN TRANSLATE("{COL_NAME}", 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz', ' ') = "{COL_NAME}" THEN 0
          WHEN TRANSLATE("{COL_NAME}", 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', ' ') = "{COL_NAME}" THEN 1
          ELSE 0
        END) AS lower_case_ct,
    SUM(CASE
          WHEN TRANSLATE("{COL_NAME}", 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz', ' ') = "{COL_NAME}" THEN 1
          ELSE 0
        END) AS non_alpha_ct,
    COUNT(CASE WHEN TRANSLATE("{COL_NAME}",
        'X' || UNISTR('\00A0') || UNISTR('\2009') || UNISTR('\200B') || UNISTR('\200C') || UNISTR('\200D') || UNISTR('\200E') || UNISTR('\200F') || UNISTR('\202F') || UNISTR('\3000') || UNISTR('\FEFF'),
        'XXXXXXXXXXX') <> "{COL_NAME}" THEN 1 END) AS non_printing_ct,
    SUM(<%IS_NUM;SUBSTR("{COL_NAME}", 1, 31)%>) AS numeric_ct,
    SUM(<%IS_DATE;SUBSTR("{COL_NAME}", 1, 26)%>) AS date_ct,
    CASE
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[0-9]{1,5}[a-zA-Z]?[[:space:]][[:alnum:]_]{1,5}\.?[[:space:]]?[[:alnum:]_]*[[:space:]]?[[:alnum:]_]*[[:space:]][a-zA-Z]{1,6}\.?[[:space:]]?[0-9]{0,5}[A-Z]?$')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.8 THEN 'STREET_ADDR'
      WHEN SUM(CASE WHEN "{COL_NAME}" IN ('AL','AK','AS','AZ','AR','CA','CO','CT','DE','DC','FM','FL','GA','GU','HI','ID','IL','IN','IA','KS','KY','LA','ME','MH','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','MP','OH','OK','OR','PW','PA','PR','RI','SC','SD','TN','TX','UT','VT','VI','VA','WA','WV','WI','WY','AE','AP','AA')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'STATE_USA'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^(\+1|1)?[ .-]?(\([2-9][0-9]{2}\)|[2-9][0-9]{2})[ .-]?[2-9][0-9]{2}[ .-]?[0-9]{4}$')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.8 THEN 'PHONE_USA'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'EMAIL'
      WHEN SUM(CASE WHEN TRANSLATE("{COL_NAME}",'012345678','999999999') IN ('99999', '999999999', '99999-9999')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'ZIP_USA'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[[:alnum:]_[:space:]-]+\.(txt|csv|tsv|dat|doc|pdf|xlsx)$')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'FILE_NAME'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^([0-9]{4}[- ]){3}[0-9]{4}$')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.8 THEN 'CREDIT_CARD'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^([^,|' || CHR(9) || ']{1,20}[,|' || CHR(9) || ']){2,}[^,|' || CHR(9) || ']{0,20}([,|' || CHR(9) || ']?[^,|' || CHR(9) || ']{0,20})*$')
                      AND NOT REGEXP_LIKE("{COL_NAME}", '[[:space:]](and|but|or|yet)[[:space:]]')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.8 THEN 'DELIMITED_DATA'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[0-8][0-9]{2}-[0-9]{2}-[0-9]{4}$')
                       AND SUBSTR("{COL_NAME}", 1, 3) NOT BETWEEN '734' AND '749'
                       AND SUBSTR("{COL_NAME}", 1, 3) <> '666' THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'SSN'
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
-- TG-IF is_type_N
    MIN("{COL_NAME}") AS min_value,
    MIN(CASE WHEN "{COL_NAME}" > 0 THEN "{COL_NAME}" ELSE NULL END) AS min_value_over_0,
    MAX("{COL_NAME}") AS max_value,
    AVG(CAST("{COL_NAME}" AS NUMBER)) AS avg_value,
    STDDEV(CAST("{COL_NAME}" AS NUMBER)) AS stdev_value,
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
    SUM(ROUND(ABS(MOD("{COL_NAME}", 1)), 5)) AS fractional_sum,
-- TG-ELSE
    NULL AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_type_D
    CASE
           WHEN MIN("{COL_NAME}") IS NULL THEN NULL
           ELSE GREATEST(MIN("{COL_NAME}"), TO_DATE('0001-01-01', 'YYYY-MM-DD'))
         END AS min_date,
    MAX("{COL_NAME}") AS max_date,
    SUM(CASE
          WHEN <%DATEDIFF_MONTH;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%> > 12 THEN 1
                                                              ELSE 0
        END) AS before_1yr_date_ct,
    SUM(CASE
          WHEN <%DATEDIFF_MONTH;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%> > 60 THEN 1
                                                              ELSE 0
        END) AS before_5yr_date_ct,
    SUM(CASE
            WHEN <%DATEDIFF_MONTH;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%> > 240 THEN 1
                                                                ELSE 0
          END) AS before_20yr_date_ct,
    SUM(CASE
            WHEN <%DATEDIFF_MONTH;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%> > 1200 THEN 1
                                                                ELSE 0
          END) AS before_100yr_date_ct,
    SUM(CASE
          WHEN <%DATEDIFF_DAY;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%> BETWEEN 0 AND 365 THEN 1
                                                                           ELSE 0
        END) AS within_1yr_date_ct,
    SUM(CASE
          WHEN <%DATEDIFF_DAY;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%> BETWEEN 0 AND 30 THEN 1
                                                                          ELSE 0
        END) AS within_1mo_date_ct,
    SUM(CASE
          WHEN "{COL_NAME}" > TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS') THEN 1 ELSE 0
        END) AS future_date_ct,
    SUM(CASE
            WHEN <%DATEDIFF_MONTH;TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS');"{COL_NAME}"%> > 240 THEN 1
                                                                                    ELSE 0
          END) AS distant_future_date_ct,
    COUNT(DISTINCT <%DATEDIFF_DAY;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%>) AS date_days_present,
    COUNT(DISTINCT <%DATEDIFF_WEEK;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%>) AS date_weeks_present,
    COUNT(DISTINCT <%DATEDIFF_MONTH;"{COL_NAME}";TO_DATE('{RUN_DATE}', 'YYYY-MM-DD HH24:MI:SS')%>) AS date_months_present,
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
    SUM(CAST("{COL_NAME}" AS NUMBER)) AS boolean_true_ct,
-- TG-ELSE
    NULL AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_A_sampling
    SUM(SIGN(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REPLACE(TRIM("{COL_NAME}"), ' ', '')))) AS embedded_space_ct,
    AVG(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REPLACE(TRIM("{COL_NAME}"), ' ', ''))) AS avg_embedded_spaces,
-- TG-ENDIF
-- TG-IF is_A_no_sampling
    SUM(SIGN(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REPLACE(TRIM("{COL_NAME}"), ' ', '')))) AS embedded_space_ct,
    AVG(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REPLACE(TRIM("{COL_NAME}"), ' ', ''))) AS avg_embedded_spaces,
-- TG-ENDIF
-- TG-IF is_not_A
    NULL AS embedded_space_ct,
    NULL AS avg_embedded_spaces,
-- TG-ENDIF
    '{PROFILE_RUN_ID}' AS profile_run_id
-- TG-IF do_sample
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" SAMPLE ({SAMPLE_PERCENT_CALC})
-- TG-ELSE
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-ENDIF
-- TG-IF is_N_sampling
    , (SELECT
               PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_25,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_50,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_75
          FROM "{DATA_SCHEMA}"."{DATA_TABLE}" SAMPLE ({SAMPLE_PERCENT_CALC}) WHERE ROWNUM <= 1000000) pctile
-- TG-ENDIF
-- TG-IF is_N_no_sampling
    , (SELECT
               PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_25,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_50,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_75
          FROM "{DATA_SCHEMA}"."{DATA_TABLE}" WHERE ROWNUM <= 1000000) pctile
-- TG-ENDIF
) main
-- TG-IF is_A_sampling
CROSS JOIN (
  SELECT
    (SELECT SUBSTR(LISTAGG(formatted_pattern, ' | ') WITHIN GROUP (ORDER BY ct DESC), 1, 1000)
        FROM (
              SELECT TO_CHAR(COUNT(*)) || ' | ' || pattern AS formatted_pattern,
                     COUNT(*) AS ct
                FROM (SELECT REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
                          "{COL_NAME}", '[a-z]', 'a'),
                                      '[A-Z]', 'A'),
                                      '[0-9]', 'N') AS pattern
                         FROM "{DATA_SCHEMA}"."{DATA_TABLE}" SAMPLE ({SAMPLE_PERCENT_CALC})
                        WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' ' AND (SELECT MAX(LENGTH("{COL_NAME}"))
                          FROM "{DATA_SCHEMA}"."{DATA_TABLE}" SAMPLE ({SAMPLE_PERCENT_CALC})) BETWEEN 3 and {MAX_PATTERN_LENGTH}) p
              GROUP BY pattern
              HAVING pattern > ' '
              ORDER BY COUNT(*) DESC
              FETCH FIRST 5 ROWS ONLY
             ) ps) AS top_patterns,
    (SELECT COUNT(DISTINCT REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
                            "{COL_NAME}", '[a-z]', 'a'),
                                        '[A-Z]', 'A'),
                                        '[0-9]', 'N')
                  )
       FROM "{DATA_SCHEMA}"."{DATA_TABLE}" SAMPLE ({SAMPLE_PERCENT_CALC})
      WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' ') AS distinct_pattern_ct
  FROM DUAL
) patterns
-- TG-ENDIF
-- TG-IF is_A_no_sampling
CROSS JOIN (
  SELECT
    (SELECT SUBSTR(LISTAGG(formatted_pattern, ' | ') WITHIN GROUP (ORDER BY ct DESC), 1, 1000)
        FROM (
              SELECT TO_CHAR(COUNT(*)) || ' | ' || pattern AS formatted_pattern,
                     COUNT(*) AS ct
                FROM (SELECT REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
                          "{COL_NAME}", '[a-z]', 'a'),
                                      '[A-Z]', 'A'),
                                      '[0-9]', 'N') AS pattern
                         FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
                        WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' ' AND (SELECT MAX(LENGTH("{COL_NAME}"))
                         FROM "{DATA_SCHEMA}"."{DATA_TABLE}") BETWEEN 3 and {MAX_PATTERN_LENGTH}) p
              GROUP BY pattern
              HAVING pattern > ' '
              ORDER BY COUNT(*) DESC
              FETCH FIRST 5 ROWS ONLY
             ) ps) AS top_patterns,
    (SELECT COUNT(DISTINCT REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
                            "{COL_NAME}", '[a-z]', 'a'),
                                        '[A-Z]', 'A'),
                                        '[0-9]', 'N')
                  )
       FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
      WHERE "{COL_NAME}" IS NOT NULL AND "{COL_NAME}" > ' ') AS distinct_pattern_ct
  FROM DUAL
) patterns
-- TG-ENDIF
