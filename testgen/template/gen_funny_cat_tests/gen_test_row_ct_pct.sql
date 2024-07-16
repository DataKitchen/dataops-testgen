-- Insert new tests where a locked test is not already present
INSERT INTO test_definitions (project_code, table_groups_id, profile_run_id, test_type, test_suite, test_suite_id,
                              schema_name, table_name, skip_errors,
                              last_auto_gen_date, profiling_as_of_date, test_active,
                              baseline_ct, threshold_value)
WITH last_run AS (SELECT r.table_groups_id, MAX(run_date) AS last_run_date
                    FROM profile_results p
                  INNER JOIN profiling_runs r
                     ON (p.profile_run_id = r.id)
                    INNER JOIN test_suites tg
                       ON p.project_code = tg.project_code
                      AND p.connection_id = tg.connection_id
                   WHERE p.project_code = '{PROJECT_CODE}'
                     AND r.table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                     AND tg.test_suite = '{TEST_SUITE}'
                     AND p.run_date::DATE <= '{AS_OF_DATE}'
                  GROUP BY r.table_groups_id),
     curprof AS (SELECT p.*
                   FROM last_run lr
                 INNER JOIN profile_results p
                    ON (lr.table_groups_id = p.table_groups_id
                    AND lr.last_run_date = p.run_date) ),
     locked AS (SELECT schema_name, table_name, column_name, test_type
                  FROM test_definitions
				     WHERE table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                   AND test_suite = '{TEST_SUITE}'
                   AND lock_refresh = 'Y'),
       newtests AS (
                    SELECT project_code, table_groups_id, profile_run_id,
                           'Row_Ct_Pct' AS test_type,
                           '{TEST_SUITE}' AS test_suite,
                           '{TEST_SUITE_ID}'::UUID AS test_suite_id,
                           schema_name,
                           table_name,
                           MAX(record_ct) as record_ct
                      FROM curprof
                    LEFT JOIN generation_sets s
                           ON ('Row_Ct_Pct' = s.test_type
                          AND  '{GENERATION_SET}' = s.generation_set)
                     WHERE schema_name = '{DATA_SCHEMA}'
                       AND functional_table_type NOT ILIKE '%cumulative%'
                       AND (s.generation_set IS NOT NULL
                        OR  '{GENERATION_SET}' = '')
                    GROUP BY project_code, table_groups_id, profile_run_id,
                             test_type, test_suite, schema_name, table_name
                    HAVING MAX(record_ct) >= 500)
SELECT n.project_code, n.table_groups_id, n.profile_run_id,
       n.test_type, n.test_suite, n.test_suite_id,
       n.schema_name, n.table_name, 0 as skip_errors,
       '{RUN_DATE}'::TIMESTAMP as last_auto_gen_date,
       '{AS_OF_DATE}'::TIMESTAMP as profiling_as_of_date,
       'Y' as test_active,
       record_ct as baseline_ct, 0.5 AS threshold_value
  FROM newtests n
LEFT JOIN locked l
  ON (n.schema_name = l.schema_name
 AND  n.table_name = l.table_name
 AND  n.test_type = l.test_type)
WHERE l.test_type IS NULL;
