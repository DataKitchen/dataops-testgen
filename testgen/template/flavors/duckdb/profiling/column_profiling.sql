-- TG-IF is_type_A
-- Every part of the query reads the column from here: a part that names the table reads the source
-- again, and on a file source every read parses the whole file.
WITH column_rows AS MATERIALIZED (
  SELECT "{COL_NAME}"
    FROM "{DATA_SCHEMA}"."{DATA_TABLE}"
)
, whole_table_measures AS (
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
    MIN(LENGTH(CAST("{COL_NAME}" AS TEXT))) AS min_length,
    MAX(LENGTH(CAST("{COL_NAME}" AS TEXT))) AS max_length,
    AVG(NULLIF(LENGTH(CAST("{COL_NAME}" AS TEXT)), 0)::DOUBLE) AS avg_length,
    SUM(CASE
          WHEN TRIM("{COL_NAME}") ~ '^0(\.0*)?$' THEN 1 ELSE 0
        END) AS zero_value_ct,
    COUNT(DISTINCT UPPER(TRANSLATE("{COL_NAME}", ' '',.-', ''))) AS distinct_std_value_ct,
    LEFT(MIN(NULLIF("{COL_NAME}", '')), 100) AS min_text,
    LEFT(MAX(NULLIF("{COL_NAME}", '')), 100) AS max_text
    FROM column_rows
)
-- TG-ENDIF
-- TG-IF is_A_sampling
-- No REPEATABLE: a seed does not hold over a CTE, whose rows a parallel scan reorders on every run.
, sampleable_rows AS (
  SELECT "{COL_NAME}"
    FROM column_rows TABLESAMPLE BERNOULLI ({SAMPLE_PERCENT_CALC}%)
)
, pattern_rows AS (
  SELECT "{COL_NAME}" AS v
    FROM column_rows TABLESAMPLE BERNOULLI ({SAMPLE_PERCENT_CALC}%)
)
-- TG-ENDIF
-- TG-IF is_A_no_sampling
, sampleable_rows AS (
  SELECT "{COL_NAME}"
    FROM column_rows
)
, pattern_rows AS (
  SELECT "{COL_NAME}" AS v
    FROM column_rows
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
    SUM( CASE WHEN "{COL_NAME}" ILIKE '"%"' OR "{COL_NAME}" ILIKE '''%''' THEN 1 ELSE 0 END ) AS quoted_value_ct,
    -- regexp_matches searches; DuckDB's ~ operator requires the pattern to match the whole value,
    -- which for an unanchored pattern like this one would count nothing.
    SUM( CASE WHEN regexp_matches("{COL_NAME}", '[0-9]') THEN 1 ELSE 0 END ) AS includes_digit_ct,
    SUM( CASE
           -- The dot is escaped: DuckDB reads SIMILAR TO as a regex where an unescaped dot matches
           -- any character, which would count every filled value as a dummy one.
           WHEN LOWER("{COL_NAME}") SIMILAR TO '(\.{1,}|-{1,}|\?{1,}|\s{1,}|0{2,}|9{2,}|x{2,}|z{2,})' THEN 1
           WHEN LOWER("{COL_NAME}") IN ('blank','error','missing','tbd',
                                      'n/a','#na','none','null','unknown')           THEN 1
           WHEN LOWER("{COL_NAME}") IN ('(blank)','(error)','(missing)','(tbd)',
                                      '(n/a)','(#na)','(none)','(null)','(unknown)') THEN 1
           WHEN LOWER("{COL_NAME}") IN ('[blank]','[error]','[missing]','[tbd]',
                                      '[n/a]','[#na]','[none]','[null]','[unknown]') THEN 1
                                                                                     ELSE 0
         END ) AS filled_value_ct,
    SUM(CASE WHEN CAST("{COL_NAME}" AS VARCHAR) COLLATE "binary" = UPPER("{COL_NAME}") COLLATE "binary" AND CAST("{COL_NAME}" AS VARCHAR) COLLATE "binary" <> LOWER("{COL_NAME}") COLLATE "binary" THEN 1 ELSE 0 END) AS upper_case_ct,
    SUM(CASE WHEN CAST("{COL_NAME}" AS VARCHAR) COLLATE "binary" = LOWER("{COL_NAME}") COLLATE "binary" AND CAST("{COL_NAME}" AS VARCHAR) COLLATE "binary" <> UPPER("{COL_NAME}") COLLATE "binary" THEN 1 ELSE 0 END) AS lower_case_ct,
    SUM(CASE WHEN CAST("{COL_NAME}" AS VARCHAR) COLLATE "binary" = UPPER("{COL_NAME}") COLLATE "binary" AND CAST("{COL_NAME}" AS VARCHAR) COLLATE "binary" = LOWER("{COL_NAME}") COLLATE "binary" THEN 1 ELSE 0 END) AS non_alpha_ct,
    -- DuckDB's escape strings implement no \uXXXX escape, so the same ten code points
    -- (NBSP, thin/zero-width/directional marks, narrow NBSP, ideographic space, BOM) are spelled
    -- with chr() rather than embedded as invisible characters.
    COUNT( CASE WHEN TRANSLATE("{COL_NAME}", chr(160) || chr(8201) || chr(8203) || chr(8204) || chr(8205) || chr(8206) || chr(8207) || chr(8239) || chr(12288) || chr(65279), 'XXXXXXXXXX') <> "{COL_NAME}" THEN 1 END) AS non_printing_ct,
    SUM(<%IS_NUM;LEFT("{COL_NAME}", 31)%>) AS numeric_ct,
    SUM(<%IS_DATE;LEFT("{COL_NAME}", 26)%>) AS date_ct,
    CASE
      WHEN SUM( CASE WHEN "{COL_NAME}" ~ '^[0-9]{1,5}[a-zA-Z]?\s\w{1,5}\.?\s?\w*\s?\w*\s[a-zA-Z]{1,6}\.?\s?[0-9]{0,5}[A-Z]{0,1}$'
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.8 THEN 'STREET_ADDR'
      WHEN SUM(CASE WHEN "{COL_NAME}" IN ('AL','AK','AS','AZ','AR','CA','CO','CT','DE','DC','FM','FL','GA','GU','HI','ID','IL','IN','IA','KS','KY','LA','ME','MH','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','MP','OH','OK','OR','PW','PA','PR','RI','SC','SD','TN','TX','UT','VT','VI','VA','WA','WV','WI','WY','AE','AP','AA')
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.9 THEN 'STATE_USA'
      WHEN SUM( CASE WHEN "{COL_NAME}" ~ E'^(\\+1|1)?[ .-]?(\\([2-9][0-9]{2}\\)|[2-9][0-9]{2})[ .-]?[2-9][0-9]{2}[ .-]?[0-9]{4}$'
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.8 THEN 'PHONE_USA'
      WHEN SUM( CASE WHEN "{COL_NAME}" ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.9 THEN 'EMAIL'
      WHEN SUM( CASE WHEN TRANSLATE("{COL_NAME}",'012345678','999999999') IN ('99999', '999999999', '99999-9999')
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.9 THEN 'ZIP_USA'
      -- DuckDB's regex engine implements no lookaround, so the trailing (?<!\s) before the dot is
      -- written as a final non-space character instead. The two match the same strings.
      WHEN SUM( CASE WHEN "{COL_NAME}" ~ '^[\w\s\-]*[\w\-]\.(txt|csv|tsv|dat|doc|pdf|xlsx)$'
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.9 THEN 'FILE_NAME'
      WHEN SUM( CASE WHEN "{COL_NAME}" ~ '^([0-9]{4}[- ]?){3}[0-9]{4}$'
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.8 THEN 'CREDIT_CARD'
      WHEN SUM( CASE WHEN "{COL_NAME}" ~ '^([^,|\t]{1,20}[,|\t]){2,}[^,|\t]{0,20}([,|\t]{0,1}[^,|\t]{0,20})*$'
                      AND NOT regexp_matches("{COL_NAME}", '\s(and|but|or|yet)\s')
           THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.8 THEN 'DELIMITED_DATA'
      WHEN SUM ( CASE WHEN "{COL_NAME}" ~ '^[0-8][0-9]{2}-[0-9]{2}-[0-9]{4}$'
                       AND LEFT("{COL_NAME}", 3) NOT BETWEEN '734' AND '749'
                       AND LEFT("{COL_NAME}", 3) <> '666' THEN 1 END)::DOUBLE/COUNT("{COL_NAME}")::DOUBLE > 0.9 THEN 'SSN'
    END AS std_pattern_match,
    SUM(SIGN(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REGEXP_REPLACE(TRIM("{COL_NAME}"), ' ', '', 'g')))::BIGINT) AS embedded_space_ct,
    AVG(LENGTH(TRIM("{COL_NAME}")) - LENGTH(REGEXP_REPLACE(TRIM("{COL_NAME}"), ' ', '', 'g'))::DOUBLE) AS avg_embedded_spaces
    FROM sampleable_rows
)
, pattern_counts AS (
  SELECT pattern,
         COUNT(*) AS pattern_ct,
         COUNT(value_length) AS value_ct,
         MAX(value_length) AS max_length
    FROM ( SELECT CASE
                    WHEN v > ' '
                      THEN REGEXP_REPLACE(REGEXP_REPLACE( REGEXP_REPLACE(
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
  CROSS JOIN sampleable_measures
  CROSS JOIN pattern_measures
-- TG-ENDIF
-- TG-IF is_not_A
SELECT
  COUNT("{COL_NAME}") AS value_ct,
  COUNT(DISTINCT "{COL_NAME}") AS distinct_value_ct,
  SUM(CASE WHEN "{COL_NAME}" IS NULL THEN 1 ELSE 0 END) AS null_value_ct,
-- TG-ENDIF
-- TG-IF is_type_DN
  MIN(LENGTH(CAST("{COL_NAME}" AS TEXT))) AS min_length,
  MAX(LENGTH(CAST("{COL_NAME}" AS TEXT))) AS max_length,
  AVG(NULLIF(LENGTH(CAST("{COL_NAME}" AS TEXT)), 0)::DOUBLE) AS avg_length,
-- TG-ENDIF
-- TG-IF is_type_N
  SUM( 1 - ABS(SIGN("{COL_NAME}")) )::BIGINT AS zero_value_ct,
  MIN("{COL_NAME}") AS min_value,
  MIN(CASE WHEN "{COL_NAME}" > 0 THEN "{COL_NAME}" ELSE NULL END) AS min_value_over_0,
  MAX("{COL_NAME}") AS max_value,
  AVG(CAST("{COL_NAME}" AS DOUBLE)) AS avg_value,
  STDDEV(CAST("{COL_NAME}" AS DOUBLE)) AS stdev_value,
  -- Keep the percentiles in this SELECT: a derived table reads the source a second time. The list
  -- form builds one state for all three, and keeps a DECIMAL column's type where a scalar
  -- approx_quantile truncates it to an integer.
-- TG-ENDIF
-- TG-IF is_N_approx_pctile
  approx_quantile("{COL_NAME}", [0.25, 0.50, 0.75])[1] AS percentile_25,
  approx_quantile("{COL_NAME}", [0.25, 0.50, 0.75])[2] AS percentile_50,
  approx_quantile("{COL_NAME}", [0.25, 0.50, 0.75])[3] AS percentile_75,
-- TG-ENDIF
-- TG-IF is_N_exact_pctile
  (PERCENTILE_CONT([0.25, 0.50, 0.75]) WITHIN GROUP (ORDER BY "{COL_NAME}"))[1] AS percentile_25,
  (PERCENTILE_CONT([0.25, 0.50, 0.75]) WITHIN GROUP (ORDER BY "{COL_NAME}"))[2] AS percentile_50,
  (PERCENTILE_CONT([0.25, 0.50, 0.75]) WITHIN GROUP (ORDER BY "{COL_NAME}"))[3] AS percentile_75,
-- TG-ENDIF
-- TG-IF is_N_decimal
  SUM(ROUND(CAST(ABS(MOD("{COL_NAME}", 1)) AS DECIMAL(38,8)), 5)) AS fractional_sum,
-- TG-ENDIF
-- TG-IF is_N_exact_sum
  CASE WHEN MAX(ABS(CAST("{COL_NAME}" AS DOUBLE))) < 1e20 AND COUNT("{COL_NAME}") < 1e10
       THEN SUM(CASE WHEN ABS(CAST("{COL_NAME}" AS DOUBLE)) < 1e20 THEN CAST("{COL_NAME}" AS DECIMAL(38,8)) END)
  END AS sum_value,
-- TG-ENDIF
-- TG-IF is_type_D
  CASE
         WHEN MIN("{COL_NAME}") IS NULL THEN NULL
         -- Cast first: TIMESTAMP_NS cannot represent the floor (its range starts in 1677), so
         -- comparing against it raises. min_date is stored as a plain TIMESTAMP either way.
         ELSE GREATEST(MIN("{COL_NAME}")::TIMESTAMP, TIMESTAMP '0001-01-01')
       END AS min_date,
  MAX("{COL_NAME}") AS max_date,
  SUM(CASE
        WHEN <%DATEDIFF_MONTH;"{COL_NAME}";'{RUN_DATE}'%> > 12 THEN 1
                                                            ELSE 0
      END) AS before_1yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_MONTH;"{COL_NAME}";'{RUN_DATE}'%> > 60 THEN 1
                                                            ELSE 0
      END) AS before_5yr_date_ct,
  SUM(CASE
          WHEN <%DATEDIFF_MONTH;"{COL_NAME}";'{RUN_DATE}'%> > 240 THEN 1
                                                              ELSE 0
        END) AS before_20yr_date_ct,
  SUM(CASE
          WHEN <%DATEDIFF_MONTH;"{COL_NAME}";'{RUN_DATE}'%> > 1200 THEN 1
                                                              ELSE 0
        END) AS before_100yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_DAY;"{COL_NAME}";'{RUN_DATE}'%> BETWEEN 0 AND 365 THEN 1
                                                                         ELSE 0
      END) AS within_1yr_date_ct,
  SUM(CASE
        WHEN <%DATEDIFF_DAY;"{COL_NAME}";'{RUN_DATE}'%> BETWEEN 0 AND 30 THEN 1
                                                                        ELSE 0
      END) AS within_1mo_date_ct,
  SUM(CASE
        WHEN "{COL_NAME}" > '{RUN_DATE}' THEN 1 ELSE 0
      END) AS future_date_ct,
  SUM(CASE
          WHEN <%DATEDIFF_MONTH;'{RUN_DATE}';"{COL_NAME}"%> > 240 THEN 1
                                                                                  ELSE 0
        END) AS distant_future_date_ct,
  COUNT(DISTINCT <%DATEDIFF_DAY;"{COL_NAME}";'{RUN_DATE}'%>) AS date_days_present,
  COUNT(DISTINCT <%DATEDIFF_WEEK;"{COL_NAME}";'{RUN_DATE}'%>) AS date_weeks_present,
  COUNT(DISTINCT <%DATEDIFF_MONTH;"{COL_NAME}";'{RUN_DATE}'%>) AS date_months_present,
-- TG-ENDIF
-- TG-IF is_type_B
  SUM(CAST("{COL_NAME}" AS INTEGER)) AS boolean_true_ct,
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
