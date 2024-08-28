-- Parses aggregated results and inserts into test_results table
WITH seq_digit  AS (
                 SELECT 0 as d UNION ALL
                 SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL
                 SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL
                 SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 ),
      seq_table_raw AS (
                 SELECT CAST(a.d + (10 * b.d) + (100 * c.d) + (1000 * d.d) as INT) as nbr
                 FROM seq_digit a CROSS JOIN seq_digit b CROSS JOIN seq_digit c CROSS JOIN seq_digit d
                 ORDER BY nbr LIMIT 1000),
      seq_table AS (
                 SELECT nbr FROM seq_table_raw WHERE nbr > 0),
      raw_results AS (
                 SELECT t.test_run_id, t.schema_name, t.table_name, t.cat_sequence, t.test_count,
                        t.test_time, t.start_time, t.end_time, t.column_names, t.test_types, t.test_definition_ids,
                        t.test_actions, t.test_descriptions,
                        t.test_parms, t.test_measures, t.test_conditions,
                        r.measure_results, r.test_results
                   FROM working_agg_cat_tests t
                 INNER JOIN working_agg_cat_results r
                    ON (t.test_run_id = r.test_run_id
                   AND  t.schema_name = r.schema_name
                   AND  t.table_name = r.table_name
                   AND  t.cat_sequence = r.cat_sequence)
                  WHERE t.test_run_id = '{TEST_RUN_ID}'
                    AND t.column_names > ''
      ),
      parsed_results AS (
                 SELECT t.schema_name,
                        t.table_name,
                        t.test_time,
                        t.start_time,
                        t.end_time,
                        nbr                                                        AS test_number,
                        SPLIT_PART(t.test_actions, '|,', s.nbr)                    AS test_action,
                        SPLIT_PART(t.test_descriptions, '|', s.nbr)                AS test_description,
                        SPLIT_PART(t.column_names, '~|~', s.nbr)                   AS column_name,
                        SPLIT_PART(t.test_types, ',', s.nbr)                       AS test_type,
                        SPLIT_PART(t.test_definition_ids, ',', s.nbr)              AS test_definition_id,
                        SPLIT_PART(t.test_parms, '|', s.nbr)                       AS test_parms,
                        SPLIT_PART(t.test_measures, '++', s.nbr)                   AS measure,
                        TRIM(SPLIT_PART(t.test_conditions, '++', s.nbr))           AS condition,
                        -- Restore encoded null value
                        NULLIF(SPLIT_PART(t.measure_results, '|', s.nbr), '<NULL>') AS measure_result,
                        SPLIT_PART(t.test_results, ',', s.nbr)                     AS test_result
                   FROM raw_results t
                        CROSS JOIN seq_table s
      )
INSERT INTO test_results
         (test_run_id, test_type, test_definition_id, test_suite_id,
          test_time, starttime, endtime, schema_name, table_name, column_names,
          skip_errors, input_parameters, result_code,
          result_measure, test_action, subset_condition, result_query, test_description)
SELECT '{TEST_RUN_ID}' as test_run_id,
        r.test_type, r.test_definition_id::UUID, '{TEST_SUITE_ID}'::UUID, r.test_time, r.start_time, r.end_time,
        r.schema_name, r.table_name, r.column_name,
        0 as skip_errors,
        r.test_parms as input_parameters,
        r.test_result::INT as result_code,
        r.measure_result as result_measure,
        r.test_action, NULL as subset_condition,
        'SELECT ' || LEFT(REPLACE(r.condition, '{RUN_' || 'DATE}', '{RUN_DATE}'), LENGTH(REPLACE(r.condition, '{RUN_' || 'DATE}', '{RUN_DATE}')) - LENGTH(' THEN ''0,'' ELSE ''1,'' END'))  || ' THEN 0 ELSE 1 END'
           || ' FROM ' || r.schema_name || '.' || r.table_name as result_query,
        COALESCE(r.test_description, c.test_description) as test_description
  FROM parsed_results r
   INNER JOIN test_types c
      ON r.test_type = c.test_type;
