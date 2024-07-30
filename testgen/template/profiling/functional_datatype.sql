-- First Clear --
UPDATE profile_results
SET functional_data_type  = NULL,
    functional_table_type = NULL
WHERE profile_run_id = '{PROFILE_RUN_ID}';


-- 1. Assign CONSTANT and TBD - this is the first step of elimination
/*
 TBD - If record_ct in a table is zero. If we have less than 5 records or all records are blanks
 Constant - If the distinct_value_ct is 1 and more than 75% of the records are filled
 */

UPDATE profile_results
SET functional_data_type =
        CASE WHEN record_ct = 0 then 'TBD (Not enough data)'
             WHEN record_ct > 0 and ((value_ct < 5 OR zero_length_ct / nullif(value_ct, 0)::FLOAT = 1))
                    THEN 'TBD (Not enough data)'
            ELSE functional_data_type
        END
WHERE profile_run_id = '{PROFILE_RUN_ID}';


UPDATE profile_results
SET functional_data_type =
        CASE WHEN distinct_value_ct = 1
                AND (((value_ct :: float - coalesce(filled_value_ct, 0::bigint) :: float)/record_ct :: float) :: float *100.00 ) > 75
                    -- this tells us how much actual values we have filled in; threshold -> if there is only 1 value and it's 75% of the records -> then it's a constant
            THEN 'Constant'
        ELSE functional_data_type END
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL;

-- 1A.  Assign ID's based on masks
UPDATE profile_results
SET functional_data_type = 'ID-SK'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND column_name ILIKE '{PROFILE_SK_COLUMN_MASK}';

UPDATE profile_results
SET functional_data_type = 'ID'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND column_name ILIKE '{PROFILE_ID_COLUMN_MASK}';

-- 2. Assign DATE
/*
 . Historical Date - If more than 95% of records have 1 year ago date value
 . Future Date - If more than 95% of records have a future date value
 . Schedule Date - If more than 50% of records have a future date present
 . If we have 10-90% of records from (before 1 year ago and within a year and for future 1 year)
    then, classify further as the following :-
 Transactional Date - If the data has a record for everyday or at least twice a week
                        or we have at least 28 days of data in current year
                        or we have at least 28 days of data in last 5 years years
 Transactional Date (Wk) - If the data available is for every week of the year or at least twice a month
                            or 2 weeks a month from the last 5 years
 Transactional Date (Mo) - If the data available is for every month of the year or at least 5 months
                            or 5 month a year from the last 5 years
 Transactional Date (Qtr) - If the data available is for every quarter of the year
 Date (TBD) - If none of the above are satisfied
 . Check varchar attributes  (or attributes not give date datatype)
    Look at min_length and max_length to determine if a field is date or timestamp

 */

UPDATE profile_results
SET functional_data_type =
      CASE
            WHEN before_20yr_date_ct / NULLIF(value_ct::FLOAT, 0) * 100 >= 75 THEN 'Historical Date'
            WHEN future_date_ct / NULLIF(value_ct::FLOAT, 0) * 100 >= 95 THEN 'Future Date'
            WHEN future_date_ct / NULLIF(value_ct::FLOAT, 0) * 100 >= 50 THEN 'Schedule Date'
            WHEN before_1yr_date_ct / NULLIF(value_ct::FLOAT, 0) * 100 BETWEEN 10 AND 90
                AND within_1yr_date_ct / NULLIF(value_ct::FLOAT, 0) * 100 BETWEEN 10 AND 90
                AND future_date_ct / NULLIF(value_ct::FLOAT, 0) * 100 BETWEEN 0 AND 10
                THEN
                CASE
                    WHEN date_days_present = DATEDIFF('DAY', min_date, max_date) + 1 -- everyday
                        OR date_days_present >=
                           2 * (DATEDIFF('WEEK', min_date, max_date) + 1) -- 2 days a week based on overall data
                        OR ROUND(within_1yr_date_ct::FLOAT / value_ct * distinct_value_ct) /
                           LEAST(365, NULLIF(DATEDIFF('DAY', (run_date::DATE - 365):: TIMESTAMP, max_date), 0))::FLOAT * 100 >=
                                   28 -- current year
                                OR ROUND(distinct_value_ct * (1 - before_5yr_date_ct / NULLIF(value_ct::FLOAT, 0))) /
                                   LEAST(NULLIF(DATEDIFF('DAY', (run_date::DATE - 365 * 5)::TIMESTAMP, max_date) + 1, 0), 365 * 5) * 100 >=
                                   28 -- last 5 years
                        THEN 'Transactional Date'
                    WHEN date_weeks_present =
                                 NULLIF(DATEDIFF('WEEK', min_date, max_date), 0)::FLOAT + 1 -- 1 day a week
                        OR
                         date_weeks_present >= 2 * (DATEDIFF('MONTH', min_date, max_date) + 1) -- 2 weeks a month
                        OR ROUND(distinct_value_ct * (1 - before_5yr_date_ct / NULLIF(value_ct::FLOAT, 0))) >=
                           2 *
                           (DATEDIFF('MONTH', (run_date::DATE - 365)::TIMESTAMP, max_date) + 1) -- 2 weeks a month from the last 5 years to current
                        THEN 'Transactional Date (Wk)'
                    WHEN date_months_present =
                         NULLIF(DATEDIFF('MONTH', min_date, max_date), 0)::FLOAT + 1 -- every month
                        OR
                         date_months_present >= 5 * (DATEDIFF('YEAR', min_date, max_date) + 1) -- 5 months a year
                        OR ROUND(distinct_value_ct * (1 - before_5yr_date_ct / NULLIF(value_ct::FLOAT, 0))) >=
                           5 *
                           (DATEDIFF('YEAR', (run_date::DATE - 365*5)::TIMESTAMP, max_date) + 1) -- 5 months a year from the last 5 years to current
                        THEN 'Transactional Date (Mo)'
                    WHEN distinct_value_ct = DATEDIFF('QUARTER', min_date, max_date) + 1 -- every quarter
                        THEN 'Transactional Date (Qtr)'
                    ELSE 'Date (TBD)'
                END
            WHEN column_type = 'date'
                THEN 'Date Stamp'
            WHEN column_type = 'timestamp'
                THEN 'DateTime Stamp'
            ELSE functional_data_type
      END
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND (general_type = 'D' OR (value_ct = date_ct + zero_length_ct AND value_ct > 0));

-- Character Date
UPDATE profile_results
SET functional_data_type = 'Date Stamp'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND distinct_pattern_ct = 1
  AND min_text >= '1900' AND max_text <= '2200'
  AND TRIM(SPLIT_PART(top_patterns, '|', 2)) = 'NNNN-NN-NN';

-- Character Timestamp
UPDATE profile_results
SET functional_data_type = 'DateTime Stamp'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND distinct_pattern_ct = 1
  AND TRIM(SPLIT_PART(top_patterns, '|', 2)) = 'NNNN-NN-NN NN:NN:NN';
  
-- Assign PERIODS:  Period Year, Period Qtr, Period Month, Period Week, Period DOW
UPDATE profile_results
SET functional_data_type = 'Period Year'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND (column_name ILIKE '%year%' OR column_name ILIKE '%yr%')
  AND ( (min_value >= 1900
   AND    max_value <= DATE_PART('YEAR', NOW()) + 20
   AND    COALESCE(fractional_sum, 0) = 0)
         OR
         (min_text >= '1900'
   AND    max_text <= (DATE_PART('YEAR', NOW()) + 20)::VARCHAR
   AND    avg_length = 4
   AND    avg_embedded_spaces = 0)
      );

UPDATE profile_results
SET functional_data_type = 'Period Quarter'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND (column_name ILIKE '%qtr%' or column_name ILIKE '%quarter%')
  AND ( (min_value = 1 AND max_value = 4
  AND    COALESCE(fractional_sum, 0) = 0)
        OR
        (min_text >= '1900' AND max_text <= '2200'
  AND    avg_length BETWEEN 6 and 7
  AND    SPLIT_PART(top_patterns, '|', 2) ~ '^\s*NNNN[-_]AN\s*$')
      );

UPDATE profile_results
SET functional_data_type = 'Period Year-Mon'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND column_name ILIKE '%mo%'
  AND min_text >= '1900' AND max_text <= '2200'
  AND (
       (avg_length BETWEEN 6.8 AND 7.2
        AND SPLIT_PART(top_patterns, '|', 2) ~ '^\s*NNNN[-_]NN\s*$')
   OR  (avg_length BETWEEN 7.8 AND 8.2
        AND UPPER(SPLIT_PART(top_patterns, '|', 2)) ~ '^\s*NNNN[-_]AAA\s*$')
      );

UPDATE profile_results
SET functional_data_type = 'Period Month'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND column_name ILIKE '%mo%'
   AND (
        (max_length = 2 AND (min_text = '01' OR min_text = '1') AND max_text = '12')
         OR (min_value = 1 AND max_value = 12 AND COALESCE(SIGN(fractional_sum), 0) = 0)
         OR (max_length = 9 AND min_text ILIKE 'April' AND max_text ILIKE 'SEPTEMBER')
         OR (max_length = 3 AND min_text ILIKE 'APR' AND max_text ILIKE 'SEP')
       );

UPDATE profile_results
SET functional_data_type = 'Period Mon-NN'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
   AND min_text ~ '(?i)^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[\s-]?\d{1,2}$'
   AND max_text ~ '(?i)^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[\s-]?\d{1,2}$'
   AND avg_length BETWEEN 5.8 AND 6.2
   AND TRIM(fn_parsefreq(top_patterns, 1, 2)) ~ '(?i)AAA[\s-]NN';

UPDATE profile_results
SET functional_data_type = 'Period Week'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND ( column_name ILIKE '%wk%' OR column_name ILIKE '%week%' )
   AND distinct_value_ct BETWEEN 10 AND 53
   AND ( ( min_text IN ('1', '01') AND max_text IN ('52','53') )
        OR ( min_value = 1 AND max_value IN (52, 53) AND COALESCE(SIGN(fractional_sum), 0) = 0 ) );

UPDATE profile_results
SET functional_data_type = 'Period DOW'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND ( column_name ILIKE '%day%' OR column_name ILIKE '%dow%')
   AND distinct_value_ct = 7
   AND ( ( min_text = '1' AND max_text = '7' )
        OR ( min_value = 1 AND max_value = 7 AND COALESCE(SIGN(fractional_sum), 0) = 0)
        OR ( min_text ILIKE 'FRIDAY' AND max_text ILIKE 'WEDNESDAY' AND max_length = 9)
        OR ( min_text ILIKE 'FRI' AND max_text ILIKE 'WED' AND max_length = 3) );


-- 3. Assign ADDRESS RELATED FIELDS, PHONE AND EMAIL
/*
 Zip - Length must be less than or equal to 11. We're also looking at the column name
 Email - Check column name and top patterns. top_patterns must have @ and .
 Phone - Length must be less than or equal to 11. We're also looking at the column name
 Address - Column name check. If the field is populated then it should have at least 4 distinct pattern count
 State - Column name must have 'state' in it. A valid state must have max_length greater than or equal to 2.
        To avoid confusing with a field serving different purpose, we've checking distinct_value_ct.
        Also, a valid state should not have a number in the data.

 */

UPDATE profile_results
SET functional_data_type =
        CASE WHEN (std_pattern_match = 'ZIP_USA' AND (column_name ILIKE '%zip%' OR column_name ILIKE '%postal%'))
                THEN 'Zip'
            WHEN std_pattern_match = 'EMAIL'
                THEN 'Email'
            WHEN (column_name ILIKE '%phone%' AND max_length BETWEEN 7 AND 11)
              OR std_pattern_match = 'PHONE_USA'
                THEN 'Phone'
            WHEN (column_name ILIKE '%address' AND column_name NOT ILIKE '%email%')
              OR std_pattern_match = 'STREET_ADDR'
                THEN 'Address'
            WHEN std_pattern_match = 'STATE_USA'
                THEN 'State'
            ELSE functional_data_type
        END
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL;

-- Update City based on position of State and Zip
UPDATE profile_results
   SET functional_data_type = 'City'
 FROM profile_results c
INNER JOIN profile_results z
   ON (c.profile_run_id = z.profile_run_id
  AND  c.table_name = z.table_name
  AND  c.position + 2 = z.position
  AND  'Zip' = z.functional_data_type)
INNER JOIN profile_results s
   ON (c.profile_run_id = s.profile_run_id
  AND  c.table_name = s.table_name
  AND  c.position + 1 = s.position
  AND  'State' = s.functional_data_type)
 WHERE c.profile_run_id = '{PROFILE_RUN_ID}'
   AND LOWER(c.column_name) SIMILAR TO '%c(|i)ty%'
   AND c.functional_data_type NOT IN ('State', 'Zip')
   AND profile_results.id = c.id;
  
-- Assign Name
UPDATE profile_results
   SET functional_data_type = 'Person Full Name'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND avg_length <= 20
  AND avg_embedded_spaces BETWEEN 0.9 AND 2.0
  AND ( column_name ~ '(approver|full|contact|emp|employee|hcp|manager|mgr_|party|person|preferred|rep|reviewer|salesperson|spouse)(_| |)(name|nm)$'
   OR   column_name IN ('name', 'nm') );

-- Assign First Name
UPDATE profile_results
   SET functional_data_type = 'Person Given Name'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
   AND avg_length <= 8
   AND avg_embedded_spaces < 0.2
   AND (LOWER(column_name) SIMILAR TO '%f(|i)rst(_| |)n(|a)m%%'
    OR  LOWER(column_name) SIMILAR TO '%(middle|mdl)(_| |)n(|a)m%%'
    OR  LOWER(column_name) SIMILAR TO '%nick(_| |)n(|a)m%%');

-- Assign Last Name
UPDATE profile_results
   SET functional_data_type = 'Person Last Name'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
   AND avg_length BETWEEN 5 and 8
   AND avg_embedded_spaces < 0.2
   AND (LOWER(column_name) SIMILAR TO '%l(|a)st(_| |)n(|a)m%'
    OR  LOWER(column_name) SIMILAR TO '%maiden(_| |)n(|a)m%'
    OR  LOWER(column_name) SIMILAR TO '%sur(_| |)n(|a)m%');

UPDATE profile_results
   SET functional_data_type = 'Entity Name'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND general_type = 'A'
  AND column_name ~ '(acct|account|affiliation|branch|business|co|comp|company|corp|corporate|cust|customer|distributor|employer|entity|firm|franchise|hco|org|organization|site|supplier|vendor|hospital|practice|clinic)(_| |)(name|nm)$';

-- Assign Boolean
/*
 Boolean - If distinct_value_ct is equal to (1 or 2) and (min_text and max_text) values fall in the categories specified
           Numeric column types are not boolean.
 */
UPDATE profile_results
SET functional_data_type =
        CASE WHEN general_type = 'B'
                OR (distinct_value_ct = 2
                    AND ((LOWER(min_text) = 'no' AND LOWER(max_text) = 'yes')
                        OR (LOWER(min_text) = 'n' AND LOWER(max_text) = 'y')
                        OR (LOWER(min_text) = 'false' AND LOWER(max_text) = 'true')
                        OR (LOWER(min_text) = '0' AND LOWER(max_text) = '1')
                        OR (min_value = 0 AND max_value = 1 AND lower(column_type) NOT ILIKE '%numeric%')))
                THEN 'Boolean'
          WHEN general_type = 'B'
                OR (distinct_value_ct = 1  -- we can have only 1 value populated but it can still be boolean
                    AND ( (LOWER(min_text) in ('no','yes') AND LOWER(max_text) in ('no','yes'))
                        OR (LOWER(min_text) in ('n','y') AND LOWER(max_text) in ('n','y'))
                        OR (LOWER(min_text) in ('false','true') AND LOWER(max_text) in ('f','t'))
                        OR (LOWER(min_text) in ('0','1') AND LOWER(max_text) in ('0','1'))
                        OR (min_value = 0 AND max_value = 1 AND lower(column_type) NOT ILIKE '%numeric%')))
                THEN 'Boolean'
          ELSE   functional_data_type
        END
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL;


-- 4. Assign CODE, CATEGORY, ID, ATTRIBUTE & DESCRIPTION
/*
 For character fields,
 Id - If more than 80% of records are populated and 95% are unique without spaces and consistent length
        and have a distinct record count of more than 200
 Code - If more than 80% of records are populated and 95% are unique without spaces and consistent length
        and have a distinct record count of less than or equal to 200.
 If distinct record count is more than 200 and the field has varying length,
  Attribute - Short length with less than 3 words
  Description - More than 3 words and longer length
 . If distinct record count is between 2 and 200,
  Code - No spaces (single word) with less than 15 maximum length
  Category - Spaces allowed, no restriction on length
 */
UPDATE profile_results
SET functional_data_type =
        CASE WHEN ( lower(column_name) ~ '_(average|avg|count|ct|sum|total|tot)$'
               OR   lower(column_name) ~ '^(average|avg|count|ct|sum|total|tot)_' )
              AND numeric_ct = value_ct
              AND value_ct > 1                                                         THEN 'Measurement Text'
             WHEN includes_digit_ct > 0
              AND ( (max_length <= 20 AND avg_embedded_spaces < 0.1   -- Short without spaces
                        AND value_ct / NULLIF(record_ct, 0)::FLOAT > 0.8 -- mostly populated
                        AND distinct_value_ct / NULLIF(value_ct, 0)::FLOAT > 0.95) -- mostly unique
                    OR (avg_embedded_spaces < 0.1 -- id should not have spaces and have consistent length
                        AND (round(max_length - avg_length) <= 1 OR round(avg_length - min_length) <= 1) ) )
                   THEN CASE WHEN distinct_value_ct > 200 THEN 'ID'
                             WHEN distinct_value_ct <= 200 AND avg_embedded_spaces < 1 THEN 'Code'
                             ELSE functional_data_type
                       END
             WHEN distinct_value_ct > 200
                   THEN CASE WHEN max_length - ROUND(avg_length) > 1 AND ROUND(avg_length) - min_length > 1 -- varies length => text
                                 THEN CASE WHEN avg_embedded_spaces BETWEEN 0 AND 3 -- less than 3 words
                                               AND max_length <= 30 -- and shorter length
                                               AND fn_charcount(max_text, ' ') < 5
                                           THEN 'Attribute'
                                           ELSE 'Description'
                                       END
                        END
             WHEN distinct_value_ct BETWEEN 2 AND 200
                   THEN CASE WHEN (avg_embedded_spaces < 1 AND max_length < 15)
                                    OR (fn_charcount(top_patterns, 'A') > 0 AND fn_charcount(top_patterns, 'N') > 0)
                             THEN 'Code'
                             ELSE 'Category'
                        END
              ELSE functional_data_type
        END
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL
  AND general_type='A'
  AND LOWER(datatype_suggestion) SIMILAR TO '(%varchar%)';

-- 5. Assign FLAG
/*
 Flag - is set only if there is an unknown data type or if it's null. Alpha values with distinct_value_ct between 3 and 5,
        Few, short words with only alpha characters.
 */

UPDATE profile_results
SET functional_data_type =
        CASE
          WHEN general_type = 'A' AND distinct_value_ct BETWEEN 3 AND 5
                    AND (lower(column_type) NOT ILIKE '%numeric%' OR lower(datatype_suggestion) NOT ILIKE '%numeric%')-- should not be decimal
                    AND (min_length > 1 AND max_length <= 7)
                    AND functional_data_type IS NULL
                    AND fn_charcount(top_patterns, 'A') > 0
                THEN 'Flag'
        END
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL;


-- 6. Assign the remaining types where functional data type is null

UPDATE profile_results
SET functional_data_type =
        CASE
            WHEN (max_value - min_value + 1 = distinct_value_ct) AND (fractional_sum IS NULL OR fractional_sum > 0)
                THEN 'Sequence'
            WHEN general_type='N'
             AND LOWER(column_name) SIMILAR TO '%(no|num|number|nbr)'
                     AND (column_type ILIKE '%int%'
                          OR
                          (RTRIM(SPLIT_PART(column_type, ',', 2), ')') > '0'
                             AND fractional_sum = 0) -- 0 implies integer;  null is float or non-numeric
                         ) THEN
                               CASE
                                 WHEN ROUND(100.0 * value_ct::FLOAT/NULLIF(record_ct, 0)) > 70 THEN 'ID'
                                                                                               ELSE 'Attribute-Numeric'
                            END
            WHEN general_type='N'
             AND (  column_type ILIKE '%int%'
                      OR
                    (RTRIM(SPLIT_PART(column_type, ',', 2), ')') > '0'
                       AND fractional_sum = 0) -- 0 implies integer;  null is float or non-numeric
                    ) THEN 'Measurement Discrete'
            WHEN general_type='N' and distinct_value_ct > 1 and min_value < 0
                then 'Measurement'
            WHEN general_type='N' and distinct_value_ct > 1 and min_value >= 0
                    and stdev_value/nullif(avg_value,0) >= 0.10
                then 'Measurement'
            ELSE 'UNKNOWN'
        END

WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IS NULL;

-- Assign City
UPDATE profile_results
   SET functional_data_type = 'City'
  FROM ( SELECT p.id
           FROM profile_results p
         LEFT JOIN profile_results pn
           ON p.profile_run_id = pn.profile_run_id
          AND p.table_name = pn.table_name
          AND p.position = pn.position - 1
         WHERE p.profile_run_id = '{PROFILE_RUN_ID}'
           AND p.includes_digit_ct::FLOAT/NULLIF(p.value_ct,0)::FLOAT < 0.05
           AND p.numeric_ct::FLOAT/NULLIF(p.value_ct,0)::FLOAT < 0.05
           AND p.date_ct::FLOAT/NULLIF(p.value_ct,0)::FLOAT < 0.05
           AND  pn.functional_data_type = 'State'
           AND p.avg_length BETWEEN 7 AND 12
           AND p.avg_embedded_spaces < 1
           AND p.distinct_value_ct BETWEEN 15 AND 40000 ) c
WHERE profile_results.id = c.id;

-- 7. Assign 'ID-Unique' functional data type to the columns that are identity columns

UPDATE profile_results
SET functional_data_type = 'ID-Unique'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type IN ('ID', 'ID-Secondary')
  AND record_ct = distinct_value_ct
  AND record_ct > 50;

-- Update alpha ID's to ID-Secondary and ID-Grouping

UPDATE profile_results
SET functional_data_type = CASE
                             WHEN ROUND(100.0 * value_ct::FLOAT/NULLIF(record_ct, 0)) > 70
                              AND ROUND(100.0 * distinct_value_ct::FLOAT/NULLIF(value_ct, 0)) >= 75  THEN 'ID-Secondary'
                             WHEN ROUND(100.0 * value_ct::FLOAT/NULLIF(record_ct, 0)) > 70
                              AND ROUND(100.0 * distinct_value_ct::FLOAT/NULLIF(value_ct, 0)) < 75 THEN 'ID-Group'
                             ELSE functional_data_type
                           END
 WHERE profile_run_id = '{PROFILE_RUN_ID}'
  AND functional_data_type = 'ID';

-- 8. Assign 'ID-FK' functional data type to the columns that are foreign keys of the identity columns identified in the previous step

UPDATE profile_results
SET functional_data_type = 'ID-FK'
FROM (Select table_groups_id, table_name, column_name
      from profile_results
      where functional_data_type = 'ID-Unique'
        and profile_run_id = '{PROFILE_RUN_ID}') ui
WHERE profile_results.profile_run_id = '{PROFILE_RUN_ID}'
  and profile_results.column_name = ui.column_name
  and profile_results.table_groups_id = ui.table_groups_id
  and profile_results.table_name <> ui.table_name
  and profile_results.functional_data_type <> 'ID-Unique';

-- Assign

-- 9. Functional Data Type: 'Measurement Pct'

UPDATE profile_results
SET functional_data_type = 'Measurement Pct'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
   AND functional_data_type IN ('Measurement', 'Measurement Discrete', 'UNKNOWN')
   AND general_type = 'N'
   AND min_value >= -200
   AND max_value <= 200
   AND (column_name ILIKE '%pct%' OR column_name ILIKE '%percent%');

UPDATE profile_results
SET functional_data_type = 'Measurement Pct'
WHERE profile_run_id = '{PROFILE_RUN_ID}'
   AND functional_data_type = 'Code'
   AND distinct_pattern_ct between 1 and 3
   AND value_ct = includes_digit_ct
   AND min_text >= '0'
   AND max_text <= '99'
   AND TRIM(SPLIT_PART(top_patterns, '|', 2)) ~ '^N{1,3}(\.N+)?%$'
   AND (TRIM(SPLIT_PART(top_patterns, '|', 4)) ~ '^N{1,3}(\.N+)?%$' OR distinct_pattern_ct < 2)
   AND (TRIM(SPLIT_PART(top_patterns, '|', 6)) ~ '^N{1,3}(\.N+)?%$' OR distinct_pattern_ct < 3);

--- END OF QUERY ---
