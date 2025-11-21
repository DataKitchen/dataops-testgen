INSERT INTO test_definitions (table_groups_id, profile_run_id, test_type, test_suite_id,
                              schema_name, table_name,
                              skip_errors, test_active, last_auto_gen_date, profiling_as_of_date,
                              lock_refresh, history_calculation, history_lookback, custom_query )
WITH last_run AS (SELECT r.table_groups_id, MAX(run_date) AS last_run_date
                    FROM profile_results p
                  INNER JOIN profiling_runs r
                     ON (p.profile_run_id = r.id)
                    INNER JOIN test_suites ts
                       ON p.project_code = ts.project_code
                      AND p.connection_id = ts.connection_id
                   WHERE p.project_code = '{PROJECT_CODE}'
                     AND r.table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                     AND ts.id = '{TEST_SUITE_ID}'
                     AND p.run_date::DATE <= '{AS_OF_DATE}'
                  GROUP BY r.table_groups_id),
curprof AS      (SELECT p.profile_run_id, schema_name, table_name, column_name, functional_data_type, general_type,
                        distinct_value_ct, record_ct, max_value, min_value, avg_value, stdev_value, null_value_ct
                   FROM last_run lr
                 INNER JOIN profile_results p
                    ON (lr.table_groups_id = p.table_groups_id
                    AND lr.last_run_date = p.run_date) ),
locked AS       (SELECT schema_name, table_name
                  FROM test_definitions
				     WHERE table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                   AND test_suite_id = '{TEST_SUITE_ID}'
				       AND test_type = 'Table_Freshness'
                   AND lock_refresh = 'Y'),
-- IDs - TOP 2
id_cols
   AS ( SELECT profile_run_id, schema_name, table_name, column_name, functional_data_type, general_type,
               distinct_value_ct,
               ROW_NUMBER() OVER (PARTITION BY schema_name, table_name
                  ORDER BY
                     CASE
                       WHEN functional_data_type ILIKE 'ID-Unique%' THEN 1
                       WHEN functional_data_type = 'ID-Secondary' THEN 2
                        ELSE 3
                     END, distinct_value_ct DESC, column_name) AS rank
          FROM curprof
         WHERE general_type IN ('A', 'D', 'N')
           AND functional_data_type ILIKE 'ID%'),
-- Process Date - TOP 1
process_date_cols
   AS (SELECT profile_run_id, schema_name, table_name, column_name, functional_data_type, general_type,
              distinct_value_ct,
       ROW_NUMBER() OVER (PARTITION BY schema_name, table_name
          ORDER BY
             CASE
               WHEN column_name ILIKE '%mod%' THEN 1
               WHEN column_name ILIKE '%up%'  THEN 1
               WHEN column_name ILIKE '%cr%'  THEN 2
               WHEN column_name ILIKE '%in%'  THEN 2
             END , distinct_value_ct DESC, column_name) AS rank
          FROM curprof
         WHERE general_type IN ('A', 'D', 'N')
           AND functional_data_type ILIKE 'process%'),
-- Transaction Date - TOP 1
tran_date_cols
   AS ( SELECT profile_run_id, schema_name, table_name, column_name, functional_data_type, general_type,
               distinct_value_ct,
               ROW_NUMBER() OVER (PARTITION BY schema_name, table_name
                  ORDER BY
                     distinct_value_ct DESC, column_name) AS rank
          FROM curprof
         WHERE general_type IN ('A', 'D', 'N')
           AND functional_data_type ILIKE 'transactional date%'
            OR functional_data_type ILIKE 'period%'
            OR functional_data_type = 'timestamp' ),

-- Numeric Measures
numeric_cols
   AS ( SELECT profile_run_id, schema_name, table_name, column_name, functional_data_type, general_type,
/*
               -- Subscores
               distinct_value_ct * 1.0 / NULLIF(record_ct, 0)                              AS cardinality_score,
               (max_value - min_value) / NULLIF(ABS(NULLIF(avg_value, 0)), 1)              AS range_score,
               LEAST(1, LOG(GREATEST(distinct_value_ct, 2))) / LOG(GREATEST(record_ct, 2)) AS nontriviality_score,
               stdev_value / NULLIF(ABS(NULLIF(avg_value, 0)), 1)                          AS variability_score,
               1.0 - (null_value_ct * 1.0 / NULLIF(NULLIF(record_ct, 0), 1))               AS null_penalty,
*/
               -- Weighted score
               (
                  0.25 * (distinct_value_ct * 1.0 / NULLIF(record_ct, 0)) +
                  0.15 * ((max_value - min_value) / NULLIF(ABS(NULLIF(avg_value, 0)), 1)) +
                  0.10 * (LEAST(1, LOG(GREATEST(distinct_value_ct, 2))) / LOG(GREATEST(record_ct, 2))) +
                  0.40 * (stdev_value / NULLIF(ABS(NULLIF(avg_value, 0)), 1)) +
                  0.10 * (1.0 - (null_value_ct * 1.0 / NULLIF(NULLIF(record_ct, 0), 1)))
                  )                                                                        AS change_detection_score
          FROM curprof
         WHERE general_type = 'N'
           AND (functional_data_type ILIKE 'Measure%' OR functional_data_type IN ('Sequence', 'Constant'))
           ),
numeric_cols_ranked
   AS ( SELECT *,
               ROW_NUMBER() OVER (PARTITION BY schema_name, table_name
                  ORDER BY change_detection_score DESC, column_name) as rank
          FROM numeric_cols
         WHERE change_detection_score IS NOT NULL),
combined
   AS ( SELECT profile_run_id, schema_name, table_name, column_name, 'ID' AS element_type, general_type, 10 + rank AS fingerprint_order
          FROM id_cols
         WHERE rank <= 2
         UNION ALL
        SELECT profile_run_id, schema_name, table_name, column_name, 'DATE_P' AS element_type, general_type, 20 + rank AS fingerprint_order
          FROM process_date_cols
         WHERE rank = 1
         UNION ALL
        SELECT profile_run_id, schema_name, table_name, column_name, 'DATE_T' AS element_type, general_type, 30 + rank AS fingerprint_order
          FROM tran_date_cols
         WHERE rank = 1
         UNION ALL
        SELECT profile_run_id, schema_name, table_name, column_name, 'MEAS' AS element_type, general_type, 40 + rank AS fingerprint_order
          FROM numeric_cols_ranked
         WHERE rank = 1 ),
newtests AS (
    SELECT profile_run_id, schema_name, table_name,
           'CAST(COUNT(*) AS STRING) || "|" || ' ||
           STRING_AGG(
              REPLACE(
                CASE
                  WHEN general_type = 'D' THEN
                       'CAST(MIN(@@@) AS STRING) || "|" || CAST(MAX(@@@) AS STRING) || "|" || CAST(COUNT(DISTINCT @@@) AS STRING)'
                  WHEN general_type = 'A' THEN
                       'CAST(MIN(@@@) AS STRING) || "|" || CAST(MAX(@@@) AS STRING) || "|" || CAST(COUNT(DISTINCT @@@) AS STRING) || "|" || CAST(SUM(LENGTH(@@@)) AS STRING)'
                  WHEN general_type = 'N' THEN
                     'ARRAY_TO_STRING([
                        CAST(COUNT(@@@) AS STRING),
                        CAST(COUNT(DISTINCT MOD(CAST(COALESCE(@@@,0) AS NUMERIC) * 1000000, CAST(1000003 AS NUMERIC))) AS STRING),
                        COALESCE(CAST(ROUND(MIN(CAST(@@@ AS NUMERIC)), 6) AS STRING), ''''),
                        COALESCE(CAST(ROUND(MAX(CAST(@@@ AS NUMERIC)), 6) AS STRING), ''''),
                        CAST(MOD(COALESCE(SUM(MOD(CAST(ABS(COALESCE(@@@,0)) AS NUMERIC) * 1000000, CAST(1000000007 AS NUMERIC))), CAST(0 AS NUMERIC)), CAST(1000000007 AS NUMERIC)) AS STRING),
                        CAST(MOD(COALESCE(SUM(MOD(CAST(ABS(COALESCE(@@@,0)) AS NUMERIC) * 1000000, CAST(1000000009 AS NUMERIC))), CAST(0 AS NUMERIC)), CAST(1000000009 AS NUMERIC)) AS STRING)
                     ], ''|'', '''')'
                END,
                '@@@', '`' || column_name || '`'),
              ' || "|" || '
              ORDER BY element_type, fingerprint_order, column_name
           ) as fingerprint
    FROM combined
    GROUP BY profile_run_id, schema_name, table_name
)
SELECT '{TABLE_GROUPS_ID}'::UUID as table_groups_id,
       n.profile_run_id,
       'Table_Freshness' AS test_type,
       '{TEST_SUITE_ID}' AS test_suite_id,
       n.schema_name, n.table_name,
       0 as skip_errors, 'Y' as test_active,

       '{RUN_DATE}'::TIMESTAMP as last_auto_gen_date,
       '{AS_OF_DATE}'::TIMESTAMP as profiling_as_of_date,
       'N' as lock_refresh,
       'Value' as history_calculation,
       1 as history_lookback,
       fingerprint as custom_query
FROM newtests n
INNER JOIN test_types t
   ON ('Table_Freshness' = t.test_type
  AND   'Y' = t.active)
LEFT JOIN generation_sets s
   ON (t.test_type = s.test_type
  AND  '{GENERATION_SET}' = s.generation_set)
LEFT JOIN locked l
  ON (n.schema_name = l.schema_name
 AND  n.table_name = l.table_name)
WHERE (s.generation_set IS NOT NULL
   OR  '{GENERATION_SET}' = '')
  AND l.schema_name IS NULL;
