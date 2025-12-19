INSERT INTO test_definitions (table_groups_id, profile_run_id, test_type, test_suite_id,
                              schema_name, table_name,
                              skip_errors, test_active, last_auto_gen_date, profiling_as_of_date,
                              history_calculation, history_calculation_upper, history_lookback, subset_condition, custom_query)
WITH last_run AS (SELECT r.table_groups_id, MAX(run_date) AS last_run_date
                    FROM profile_results p
                  INNER JOIN profiling_runs r
                     ON (p.profile_run_id = r.id)
                    INNER JOIN test_suites ts
                       ON p.project_code = ts.project_code
                      AND p.connection_id = ts.connection_id
                   WHERE p.project_code = :PROJECT_CODE
                     AND r.table_groups_id = :TABLE_GROUPS_ID ::UUID
                     AND ts.id = :TEST_SUITE_ID
                     AND p.run_date::DATE <= :AS_OF_DATE
                  GROUP BY r.table_groups_id),
     curprof AS (SELECT p.schema_name, p.table_name, p.profile_run_id
                   FROM last_run lr
                 INNER JOIN profile_results p
                    ON (lr.table_groups_id = p.table_groups_id
                    AND lr.last_run_date = p.run_date)
                 GROUP BY p.schema_name, p.table_name, p.profile_run_id),
     locked AS (SELECT schema_name, table_name
                  FROM test_definitions
				     WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
                   AND test_suite_id = :TEST_SUITE_ID
				       AND test_type = 'Volume_Trend'
                   AND lock_refresh = 'Y'),
     newtests AS (SELECT *
                  FROM curprof p
                  INNER JOIN test_types t
                     ON ('Volume_Trend' = t.test_type
                    AND 'Y' = t.active)
                  LEFT JOIN generation_sets s
                     ON (t.test_type = s.test_type
                    AND :GENERATION_SET = s.generation_set)
                  WHERE p.schema_name = :DATA_SCHEMA
                    AND (s.generation_set IS NOT NULL
                     OR :GENERATION_SET = ''))
SELECT :TABLE_GROUPS_ID ::UUID AS table_groups_id,
       n.profile_run_id,
       'Volume_Trend' AS test_type,
       :TEST_SUITE_ID AS test_suite_id,
       n.schema_name, n.table_name,
       0 AS skip_errors, 'Y' AS test_active,
       :RUN_DATE ::TIMESTAMP AS last_auto_gen_date,
       :AS_OF_DATE ::TIMESTAMP AS profiling_as_of_date,
       'EXPR:[0.9*{AVERAGE}]' AS history_calculation,
       'EXPR:[1.1*{AVERAGE}]' AS history_calculation_upper,
       5 AS history_lookback,
       '1=1' AS subset_condition,
       'COUNT(CASE WHEN {SUBSET_CONDITION} THEN 1 END)' AS custom_query
FROM newtests n
LEFT JOIN locked l
  ON (n.schema_name = l.schema_name
 AND  n.table_name = l.table_name)
WHERE l.schema_name IS NULL;
