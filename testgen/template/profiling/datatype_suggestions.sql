UPDATE profile_results
               SET datatype_suggestion =
                   CASE
                     WHEN record_ct > 500 AND column_name not ILIKE '%id' THEN
                            CASE
                              WHEN general_type = 'A' AND column_name ILIKE '%zip%'
                                 AND max_length <= 10 THEN 'VARCHAR(10)'
                              WHEN general_type = 'A'
                                AND numeric_ct > 0
                                AND value_ct = numeric_ct + zero_length_ct
                                AND POSITION('.' in top_freq_values) > 0  THEN 'DECIMAL(18,4)'
                              WHEN general_type = 'A'
                                AND numeric_ct > 0
                                AND value_ct = numeric_ct + zero_length_ct
                                AND max_length <= 6
                                AND POSITION('.' in top_freq_values) = 0  THEN 'INTEGER'
                              WHEN general_type = 'A'
                                AND numeric_ct > 0
                                AND value_ct = numeric_ct + zero_length_ct
                                AND max_length > 6
                                AND POSITION('.' in top_freq_values) = 0  THEN 'BIGINT'
                              WHEN general_type = 'A'
                                AND date_ct > 0
                                AND value_ct = date_ct + zero_length_ct THEN 'DATE'
                              WHEN general_type = 'A'
                                AND max_length <= 5 THEN 'VARCHAR(10)'
                              WHEN general_type = 'A'
                               AND max_length IS NOT NULL
                                   THEN 'VARCHAR('
                                    || ( (1 + TRUNC( (max_length + 10) /20.0, 0)) * 20)::VARCHAR(10)
                                    || ')'
                              WHEN general_type = 'N'
                               AND RTRIM(SPLIT_PART(column_type, ',', 2),')') > '0'
                               AND fractional_sum = 0
                               AND min_value >= -100
                               AND max_value <= 100
                                   THEN 'SMALLINT'
                              WHEN general_type = 'N'
                               AND RTRIM(SPLIT_PART(column_type, ',', 2),')') > '0'
                               AND fractional_sum = 0
                               AND min_value >= -100000000
                               AND max_value <= 100000000
                                   THEN 'INTEGER'
                              WHEN general_type = 'N'
                               AND RTRIM(SPLIT_PART(column_type, ',', 2),')') > '0'
                               AND fractional_sum = 0
                               AND (min_value < -100000000
                                OR  max_value > 100000000)
                                   THEN 'BIGINT'
                              ELSE LOWER(column_type)
                            END
                     ELSE LOWER(column_type)
                   END
             WHERE project_code = '{PROJECT_CODE}'
               AND schema_name = '{DATA_SCHEMA}'
               AND run_date = '{RUN_DATE}';
