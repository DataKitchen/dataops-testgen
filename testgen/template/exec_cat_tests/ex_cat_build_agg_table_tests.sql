-- Create one record per CAT query: all test sets against one table, split over max chars
INSERT INTO working_agg_cat_tests
 (test_run_id,
  schema_name, table_name, cat_sequence, test_count, test_time,
  column_names, test_types, test_definition_ids,
  test_actions, test_descriptions,
  test_parms, test_measures, test_conditions)
-- Test details from each test type
WITH test_detail
  AS (
       SELECT t.test_suite_id,
              '{SCHEMA_NAME}' as schema_name, '{TABLE_NAME}' as table_name,
              '{RUN_DATE}'::TIMESTAMP as test_time,
              t.column_name, t.test_type, t.id::VARCHAR as test_definition_id,
              t.test_action, t.test_description,

              SUBSTRING(
                        CASE WHEN t.baseline_ct > '' THEN ', Baseline_Ct=' || t.baseline_ct ELSE '' END
                        || CASE WHEN t.baseline_unique_ct > '' THEN ', Baseline_Unique_Ct=' || t.baseline_unique_ct ELSE '' END
                        || CASE WHEN t.baseline_value > '' THEN ', Baseline_Value=' || t.baseline_value ELSE '' END
                        || CASE WHEN t.baseline_value_ct > '' THEN ', Baseline_Value_Ct=' || t.baseline_value_ct ELSE '' END
                        || CASE WHEN t.baseline_sum > '' THEN ', Baseline_Sum=' || t.baseline_sum ELSE '' END
                        || CASE WHEN t.baseline_avg > '' THEN ', Baseline_Avg=' || t.baseline_avg ELSE '' END
                        || CASE WHEN t.baseline_sd > '' THEN ', Baseline_SD=' || t.baseline_sd ELSE '' END
                        || CASE WHEN t.threshold_value > '' THEN ', Threshold_Value=' || t.threshold_value ELSE '' END,
                        3, 999) || ' '
               as parms,

              -- Standard Measure start
              'CAST(' ||
                -- Nested parm replacements - part of query, not Python parms
                REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   c.measure,
                        '{COLUMN_NAME}', COALESCE(fn_PrepColumnName(t.column_name), '')),
                        '{DATA_QC_SCHEMA}', '{REPLACE_QC_SCHEMA}'),
                        '{BASELINE_CT}', COALESCE(t.baseline_ct, '')),
                        '{BASELINE_UNIQUE_CT}', COALESCE(t.baseline_unique_ct, '')),
                        '{BASELINE_VALUE}', COALESCE(t.baseline_value, '') ),
                        '{BASELINE_VALUE_CT}', COALESCE(t.baseline_value_ct, '') ),
                        '{BASELINE_SUM}', COALESCE(t.baseline_sum, '') ),
                        '{BASELINE_AVG}', COALESCE(t.baseline_avg, '') ),
                        '{BASELINE_SD}', COALESCE(t.baseline_sd, '') ),
                        '{CUSTOM_QUERY}', COALESCE(t.custom_query, '')),
                        '{THRESHOLD_VALUE}', COALESCE(t.threshold_value, '') )
                -- Standard measure end with pipe delimiter
                || ' AS VARCHAR(1000) ) {CONCAT_OPERATOR} ''|'' ' as measure,

              -- Standard CASE for condition starts
              'CASE WHEN ' ||
                -- Nested parm replacements - standard
                REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   c.measure || c.test_operator || c.test_condition,
                        '{COLUMN_NAME}', COALESCE(fn_PrepColumnName(t.column_name), '')),
                        '{DATA_QC_SCHEMA}', '{REPLACE_QC_SCHEMA}'),
                        '{BASELINE_CT}', COALESCE(t.baseline_ct, '')),
                        '{BASELINE_UNIQUE_CT}', COALESCE(t.baseline_unique_ct, '')),
                        '{BASELINE_VALUE}', COALESCE(t.baseline_value, '') ),
                        '{BASELINE_VALUE_CT}', COALESCE(t.baseline_value_ct, '') ),
                        '{BASELINE_SUM}', COALESCE(t.baseline_sum, '') ),
                        '{BASELINE_AVG}', COALESCE(t.baseline_avg, '') ),
                        '{BASELINE_SD}', COALESCE(t.baseline_sd, '') ),
                        '{CUSTOM_QUERY}', COALESCE(t.custom_query, '')),
                        '{THRESHOLD_VALUE}', COALESCE(t.threshold_value, '') )
                -- Standard case ends
                || ' THEN ''0,'' ELSE ''1,'' END' as condition
         FROM test_definitions t
       INNER JOIN cat_test_conditions c
          ON (t.test_type = c.test_type
         AND  '{SQL_FLAVOR}' = c.sql_flavor)
        WHERE t.test_suite_id = '{TEST_SUITE_ID}'
          AND t.schema_name = '{SCHEMA_NAME}'
          AND t.table_name = '{TABLE_NAME}'
          AND COALESCE(t.test_active, 'Y') = 'Y'
      ),
test_detail_split
   AS ( SELECT test_suite_id, schema_name, table_name, test_time,
               column_name, test_type, test_definition_id, test_action, test_description,
               parms, measure, condition,
               SUM(LENGTH(condition)) OVER (PARTITION BY t.schema_name, t.table_name
                                      ORDER BY t.column_name ROWS UNBOUNDED PRECEDING ) as run_total_chars,
               FLOOR( SUM(LENGTH(condition)) OVER (PARTITION BY t.schema_name, t.table_name
                                             ORDER BY t.column_name ROWS UNBOUNDED PRECEDING )
                  / {MAX_QUERY_CHARS} ) + 1 as query_split_no
          FROM test_detail t )
SELECT '{TEST_RUN_ID}' as test_run_id,
       d.schema_name, d.table_name,
       d.query_split_no as cat_sequence,
       COUNT(*) as test_count,
       '{RUN_DATE}'::TIMESTAMP as test_time,
       STRING_AGG(COALESCE(d.column_name, 'N/A'), '~|~' ORDER BY d.column_name) as column_names,
       STRING_AGG(d.test_type, ',' ORDER BY d.column_name) as test_types,
       STRING_AGG(d.test_definition_id, ',' ORDER BY d.column_name) as test_definition_ids,
       -- Pipe delimiter below, because commas may be embedded
       STRING_AGG(d.test_action, '|' ORDER BY d.column_name) as test_actions,
       STRING_AGG(d.test_description, '|' ORDER BY d.column_name) as test_descriptions,

       -- Consolidated Parms
       STRING_AGG( d.parms, '|' ORDER BY d.column_name) as parms,

       -- Consolidated Measures
       -- Encode Null as text to decode when freeing kittens
        STRING_AGG( 'COALESCE(' || d.measure || ',''' || '<NULL>' || '|'')',
                -- Use ++ as STRING_AGG delimiter -- replace with + later
                '++' ORDER BY d.column_name) as measures,

       -- Consolidated CASE statements
       STRING_AGG( d.condition,
                -- Use ++ as STRING_AGG delimiter -- replace with + later
                '++' ORDER BY d.column_name) as conditions

  FROM test_detail_split d
GROUP BY d.test_suite_id, d.schema_name, d.table_name, test_time, d.query_split_no;
