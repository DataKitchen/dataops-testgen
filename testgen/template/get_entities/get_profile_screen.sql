WITH
   profiling as ( SELECT *
                    FROM profile_results
                   WHERE profile_run_id = '{PROFILE_RUN}'::UUID
                     AND table_name ILIKE '{TABLE_NAME}' ),
   profile_date as (SELECT MAX(run_date) as run_date
                      FROM profiling),
   mults AS ( SELECT p.project_code,
                      p.table_groups_id,
                      p.run_date,
                      p.schema_name,
                      p.column_name,
                      COUNT(*)                      AS column_ct,
                      COUNT(DISTINCT p.column_type) AS type_ct,
                      COUNT(DISTINCT p.general_type) AS general_type_ct,
                      MIN(p.column_type::TEXT)      AS min_type,
                      MAX(p.column_type::TEXT)      AS max_type,
                      MIN(p.distinct_pattern_ct)    AS min_pattern_ct,
                      MAX(p.distinct_pattern_ct)    AS max_pattern_ct,
                      SUM(p.distinct_pattern_ct)    AS sum_pattern_ct
                 FROM profile_results p
               INNER JOIN profile_date d
                  ON (p.run_date <= d.run_date)
                GROUP BY p.project_code, p.table_groups_id, p.run_date, p.schema_name, p.column_name
               HAVING COUNT(*) > 1 ),
   results as (SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Suggested Data Type'               AS qualification_test,
                      p.datatype_suggestion::VARCHAR(200) AS detail
                 FROM profiling p
                WHERE LOWER(p.column_type) <> LOWER(p.datatype_suggestion)
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Non-Standard Blank Values'   AS qualification_test,
                      (((('Filled Values: ' || p.filled_value_ct::VARCHAR(10)) || ', Null: ') ||
                        p.null_value_ct::VARCHAR(10)) || ', Empty String: ') ||
                      p.zero_length_ct::VARCHAR(10) AS detail
                 FROM profiling p
                WHERE p.filled_value_ct > 0
                   OR p.zero_length_ct > 0
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Invalid Zip Code Format'      AS qualification_test,
                      (((('Min Length: ' || p.min_length::VARCHAR(10)) || ', Max Length: ') ||
                        p.max_length::VARCHAR(10)) || ', Filled Values: ') ||
                      p.filled_value_ct::VARCHAR(10) AS detail
                 FROM profiling p
                WHERE p.column_name ILIKE '%zip%'
                  AND (p.general_type <> 'A' OR p.filled_value_ct > 0 OR p.min_length >= 1 AND p.min_length <= 4 OR
                       p.max_length > 10)
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Multiple Data Types per Column Name: Strict' AS qualification_test,
                      (((((('Found ' || m.column_ct::VARCHAR(10)) || ' columns, ') ||
                          m.type_ct::VARCHAR(10)) || ' types, ') || m.min_type) || ' to ') ||
                      m.max_type                            AS detail
                 FROM profiling p
                 INNER JOIN mults m
                           ON p.project_code = m.project_code
                                 AND p.table_groups_id = m.table_groups_id
                                 AND p.schema_name = m.schema_name
                                 AND p.column_name = m.column_name
                                 AND 1 < m.type_ct
                                 AND 1 = m.general_type_ct
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Multiple Data Types per Column Name: Loose' AS qualification_test,
                      (((((('Found ' || m.column_ct::VARCHAR(10)) || ' columns, ') ||
                          m.type_ct::VARCHAR(10)) || ' types, ') || m.min_type) || ' to ') ||
                      m.max_type                            AS detail
                 FROM profiling p
                 INNER JOIN mults m
                           ON p.project_code = m.project_code
                                 AND p.table_groups_id = m.table_groups_id
                                 AND p.schema_name = m.schema_name
                                 AND p.column_name = m.column_name
                  AND 1 < m.general_type_ct
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'No column values present'    AS qualification_test,
                      (((('Null: ' || p.null_value_ct::VARCHAR(10)) || ', Filled: ') ||
                        p.filled_value_ct::VARCHAR(10)) || ', Zero Len: ') ||
                      p.zero_length_ct::VARCHAR(10) AS detail
                 FROM profiling p
                WHERE (p.null_value_ct + p.filled_value_ct + p.zero_length_ct) = p.record_ct
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Pattern Inconsistency'       AS qualification_test,
                      'Pattern: ' || p.top_patterns AS detail
                 FROM profiling p
                      LEFT JOIN mults m
                                ON p.project_code = m.project_code
                                      AND p.table_groups_id = m.table_groups_id
                                      AND p.schema_name = m.schema_name
                                      AND p.column_name = m.column_name
                WHERE p.general_type = 'A'
                  AND p.max_length > 3
                  AND p.value_ct > (p.numeric_ct + p.filled_value_ct)
                  AND (p.distinct_pattern_ct < 3 OR m.min_pattern_ct < 3)
                  AND (p.distinct_pattern_ct > 1 OR m.sum_pattern_ct > m.column_ct::NUMERIC)
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Leading Spaces'                          AS qualification_test,
                      'Found: ' || p.lead_space_ct::VARCHAR(10) AS detail
                 FROM profiling p
                WHERE p.lead_space_ct > 0
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Quoted Values'                          AS qualification_test,
                      'Found: ' || p.quoted_value_ct::VARCHAR(10) AS detail
                 FROM profiling p
                WHERE quoted_value_ct > 0
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Mostly Numeric in String'                   AS qualification_test,
                      'Numeric Percent: ' || ROUND(100.0 * p.numeric_ct::NUMERIC(18, 5) / p.value_ct::NUMERIC(18, 5),
                                                   2)::VARCHAR(40) AS detail
                 FROM profiling p
                WHERE p.general_type = 'A'
                  AND p.column_name NOT ILIKE '%zip'
                  AND p.column_name NOT ILIKE '%id'
                  AND p.column_name NOT ILIKE '%num'
                  AND p.column_name NOT ILIKE '%sk'
                  AND p.value_ct > p.numeric_ct
                  AND p.numeric_ct::NUMERIC > (0.95 * p.value_ct::NUMERIC)
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Mostly Dates in String'                                                              AS qualification_test,
                      'Date Percent: ' ||
                      ROUND(100.0 * p.date_ct::NUMERIC(18, 5) / p.value_ct::NUMERIC(18, 5), 2)::VARCHAR(40) AS detail
                 FROM profiling p
                WHERE p.general_type = 'A'
                  AND p.value_ct > p.date_ct
                  AND p.date_ct::NUMERIC > (0.95 * p.value_ct::NUMERIC)
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Mostly not null, empty or filled values'             AS qualification_test,
                      (p.record_ct - (p.value_ct - p.zero_length_ct - p.filled_value_ct))::VARCHAR(20) ||
                      ' of ' || p.record_ct::VARCHAR(20) || ' blank values' AS detail
                 FROM profiling p
                WHERE (p.value_ct - p.zero_length_ct - p.filled_value_ct)::FLOAT / p.record_ct::FLOAT > 0.97
                  AND (p.value_ct - p.zero_length_ct - p.filled_value_ct) < p.record_ct
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Mostly one value'                  AS qualification_test,
                      'Freq | Value: ' || top_freq_values AS detail
                 FROM profiling p
                WHERE (100.0 * fn_parsefreq(p.top_freq_values, 1, 2)::FLOAT /
                       p.value_ct::FLOAT) > 97::FLOAT
                  AND (100.0 * fn_parsefreq(p.top_freq_values, 1, 2)::FLOAT /
                       p.value_ct::FLOAT) < 100::FLOAT
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Too many boolean values'         AS qualification_test,
                      'Top Freq: ' || p.top_freq_values AS detail
                 FROM profiling p
                WHERE p.general_type = 'A'
                  AND p.distinct_value_ct >= 3
                  AND p.distinct_value_ct <= 6
                  AND (LOWER(p.top_freq_values) ILIKE '%| true |%' AND
                       LOWER(p.top_freq_values) ILIKE '%| false |%' OR
                       LOWER(p.top_freq_values) ILIKE '%| yes |&' AND LOWER(p.top_freq_values) ILIKE '%| no |&')
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Potential Duplicates'            AS qualification_test,
                      'Top Freq: ' || p.top_freq_values AS detail
                 FROM profiling p
                WHERE p.distinct_value_ct > 1000
                  AND fn_parsefreq(p.top_freq_values, 1, 2)::BIGINT BETWEEN 2 AND 4
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Non-Standardized Values in Categories/Codes'   AS qualification_test,
                      'Distinct Values: ' || p.distinct_value_ct::VARCHAR
                         || ', Standardized: ' || p.distinct_std_value_ct::VARCHAR AS detail
                 FROM profiling p
                WHERE p.general_type = 'A'
                  AND p.distinct_std_value_ct <> p.distinct_value_ct
                  AND p.functional_data_type IN ('Category','Code')
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Unlikely Date Values out of normal range'   AS qualification_test,
                      'Date Range: ' || p.min_date::VARCHAR || ' thru ' || p.max_date AS detail
                 FROM profiling p
                WHERE p.general_type = 'D'
                  AND (p.min_date BETWEEN '0001-01-02'::DATE AND '1900-01-01'::DATE
                   OR p.max_date > CURRENT_DATE + INTERVAL '30 year')
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      '(Table-Wide)' as column_name,
                      '' as column_type,
                      'Recency - No Table Dates within 1 Year'   AS qualification_test,
                      'Most Recent Date: ' || MAX(p.max_date)::VARCHAR AS detail
                 FROM profiling p
                WHERE p.general_type = 'D'
               GROUP BY p.schema_name, p.table_name
               HAVING MAX(p.max_date) < CURRENT_DATE - INTERVAL '1 year'
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Unexpected column contains US States' AS qualification_test,
                      'Value Range: ' || p.min_text || ' thru ' || max_text AS detail
                 FROM profiling p
                WHERE p.std_pattern_match = 'STATE_USA'
                      AND p.distinct_value_ct > 5
                      AND NOT (p.column_name ILIKE '%state%' OR p.column_name ILIKE '%_st')
                UNION ALL
               SELECT p.schema_name,
                      p.table_name,
                      p.column_name,
                      p.column_type,
                      'Unexpected column contains emails' AS qualification_test,
                      'Value Range: ' || p.min_text || ' thru ' || max_text AS detail
                 FROM v_latest_profile_results p
                WHERE p.table_groups_id = 'a6b876b5-750b-49d3-b4e2-a599eceefe84'::UUID
                  AND p.std_pattern_match = 'EMAIL'
                      AND NOT (column_name ILIKE '%email%' OR column_name ILIKE '%addr%')
                )
SELECT table_name, column_name, column_type,
       qualification_test as screening_test, detail
  FROM results
 WHERE qualification_test <> 'Suggested Data Type'
 ORDER BY qualification_test, schema_name, table_name, column_name;
