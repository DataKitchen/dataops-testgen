-- TG-IF is_type_A
WITH whole_table_measures AS (
  SELECT
    COUNT(*) AS record_ct,
-- TG-ENDIF
-- TG-IF is_A_hashed
    SUM({MULTISET_HASH_TERM}) AS multiset_hash,
-- TG-ENDIF
-- TG-IF is_type_A
    COUNT("{COL_NAME}") AS value_ct,
    COUNT(DISTINCT "{COL_NAME}") AS distinct_value_ct,
    SUM(CASE WHEN "{COL_NAME}" IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
    MIN(LENGTH(TO_CHAR("{COL_NAME}"))) AS min_length,
    MAX(LENGTH(TO_CHAR("{COL_NAME}"))) AS max_length,
    AVG(NULLIF(LENGTH(TO_CHAR("{COL_NAME}")), 0)) AS avg_length,
    SUM(CASE
          WHEN REGEXP_LIKE(TRIM("{COL_NAME}"), '^0(\.0*)?$') THEN 1 ELSE 0
        END) AS zero_value_ct,
    COUNT(DISTINCT UPPER(TRANSLATE("{COL_NAME}", 'X '',.-', 'X'))) AS distinct_std_value_ct,
    SUBSTR(MIN(CASE WHEN "{COL_NAME}" IS NOT NULL THEN "{COL_NAME}" END), 1, 100) AS min_text,
    SUBSTR(MAX(CASE WHEN "{COL_NAME}" IS NOT NULL THEN "{COL_NAME}" END), 1, 100) AS max_text
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
)
-- TG-ENDIF
-- TG-IF is_A_sampling
, sampleable_rows AS (
  SELECT "{COL_NAME}"
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" SAMPLE ({SAMPLE_PERCENT_CALC})
)
, pattern_rows AS (
  SELECT "{COL_NAME}" AS v
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}" SAMPLE ({SAMPLE_PERCENT_CALC})
)
-- TG-ENDIF
-- TG-IF is_A_no_sampling
, sampleable_rows AS (
  SELECT "{COL_NAME}"
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
)
, pattern_rows AS (
  SELECT "{COL_NAME}" AS v
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
)
-- TG-ENDIF
-- TG-IF is_type_A
, sampleable_measures AS (
  SELECT
    COUNT("{COL_NAME}") AS sample_value_ct,
    0 AS zero_length_ct,
    SUM(CASE
           WHEN ("{COL_NAME}" LIKE ' %' AND LTRIM("{COL_NAME}") IS NOT NULL) THEN 1
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
    SUM(CASE WHEN "{COL_NAME}" = UPPER("{COL_NAME}") AND "{COL_NAME}" <> LOWER("{COL_NAME}") THEN 1 ELSE 0 END) AS upper_case_ct,
    SUM(CASE WHEN "{COL_NAME}" = LOWER("{COL_NAME}") AND "{COL_NAME}" <> UPPER("{COL_NAME}") THEN 1 ELSE 0 END) AS lower_case_ct,
    SUM(CASE WHEN "{COL_NAME}" = UPPER("{COL_NAME}") AND "{COL_NAME}" = LOWER("{COL_NAME}") THEN 1 ELSE 0 END) AS non_alpha_ct,
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
                AND "{COL_NAME}" NOT LIKE '%://%'
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'EMAIL'
      WHEN SUM(CASE WHEN TRANSLATE("{COL_NAME}",'012345678','999999999') IN ('99999', '999999999', '99999-9999')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'ZIP_USA'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[[:alnum:]_[:space:]-]+\.(txt|csv|tsv|dat|doc|pdf|xlsx)$')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'FILE_NAME'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^([0-9]{4}[- ]?){3}[0-9]{4}$')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.8 THEN 'CREDIT_CARD'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^([^,|' || CHR(9) || ']{1,20}[,|' || CHR(9) || ']){2,}[^,|' || CHR(9) || ']{0,20}([,|' || CHR(9) || ']?[^,|' || CHR(9) || ']{0,20})*$')
                      AND NOT REGEXP_LIKE("{COL_NAME}", '[[:space:]](and|but|or|yet)[[:space:]]')
           THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.8 THEN 'DELIMITED_DATA'
      WHEN SUM(CASE WHEN REGEXP_LIKE("{COL_NAME}", '^[0-8][0-9]{2}-[0-9]{2}-[0-9]{4}$')
                       AND SUBSTR("{COL_NAME}", 1, 3) NOT BETWEEN '734' AND '749'
                       AND SUBSTR("{COL_NAME}", 1, 3) <> '666' THEN 1 ELSE 0 END) / NULLIF(COUNT("{COL_NAME}"), 0) > 0.9 THEN 'SSN'
    END AS std_pattern_match,
    SUM(SIGN(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REPLACE(TRIM("{COL_NAME}"), ' ', '')))) AS embedded_space_ct,
    AVG(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REPLACE(TRIM("{COL_NAME}"), ' ', ''))) AS avg_embedded_spaces
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
                             v, '[a-z]', 'a'),
                                '[A-Z]', 'A'),
                                '[0-9]', 'N')
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
             THEN ROW_NUMBER() OVER (ORDER BY CASE WHEN pattern IS NULL THEN 1 ELSE 0 END, pattern_ct DESC, NLSSORT(pattern, 'NLS_SORT=BINARY'))
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
  COUNT(CASE WHEN "{COL_NAME}" IS NOT NULL THEN 1 END) AS value_ct,
  SUM(CASE WHEN "{COL_NAME}" IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
-- TG-ENDIF
-- TG-IF is_not_A_or_X
  COUNT(DISTINCT "{COL_NAME}") AS distinct_value_ct,
-- TG-ENDIF
-- TG-IF is_type_B
  SUM(CAST("{COL_NAME}" AS NUMBER)) AS boolean_true_ct,
-- TG-ENDIF
-- TG-IF is_type_DN
  MIN(LENGTH(TO_CHAR("{COL_NAME}"))) AS min_length,
  MAX(LENGTH(TO_CHAR("{COL_NAME}"))) AS max_length,
  AVG(NULLIF(LENGTH(TO_CHAR("{COL_NAME}")), 0)) AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_N
  SUM(1 - ABS(SIGN("{COL_NAME}"))) AS zero_value_ct,
  MIN("{COL_NAME}") AS min_value,
  MIN(CASE WHEN "{COL_NAME}" > 0 THEN "{COL_NAME}" ELSE NULL END) AS min_value_over_0,
  MAX("{COL_NAME}") AS max_value,
  AVG(CAST("{COL_NAME}" AS NUMBER)) AS avg_value,
  STDDEV(CAST("{COL_NAME}" AS NUMBER)) AS stdev_value,
  MIN(pct_25) AS percentile_25,
  MIN(pct_50) AS percentile_50,
  MIN(pct_75) AS percentile_75,
-- TG-ENDIF
-- TG-IF is_N_decimal
  SUM(ROUND(CAST(ABS(MOD("{COL_NAME}", 1)) AS NUMBER(38,8)), 5)) AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_N_exact_sum
  CASE WHEN MAX(ABS(CAST("{COL_NAME}" AS BINARY_DOUBLE))) < 1e20 AND COUNT("{COL_NAME}") < 1e10
       THEN SUM(CASE WHEN ABS(CAST("{COL_NAME}" AS BINARY_DOUBLE)) < 1e20 THEN CAST("{COL_NAME}" AS NUMBER(38,8)) END)
  END AS sum_value,
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
-- TG-ENDIF
-- TG-IF is_DN_hashed
  SUM({MULTISET_HASH_TERM}) AS multiset_hash,
-- TG-ENDIF
-- TG-IF is_epoch_summed
  SUM({EPOCH_SUM_TERM}) AS epoch_sum,
-- TG-ENDIF
-- TG-IF is_not_A
  COUNT(*) AS record_ct
  FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
-- TG-ENDIF
-- TG-IF is_N_approx_pctile
  , (SELECT
             APPROX_PERCENTILE(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_25,
             APPROX_PERCENTILE(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_50,
             APPROX_PERCENTILE(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_75
        FROM "{DATA_SCHEMA}"."{DATA_TABLE}") pctile
-- TG-ENDIF
-- TG-IF is_N_exact_pctile
  , (SELECT
             PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_25,
             PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_50,
             PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{COL_NAME}") AS pct_75
        FROM "{DATA_SCHEMA}"."{DATA_TABLE}") pctile
-- TG-ENDIF
