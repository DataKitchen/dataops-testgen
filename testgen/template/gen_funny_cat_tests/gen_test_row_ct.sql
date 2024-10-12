-- Insert new tests where a locked test is not already present
INSERT INTO test_definitions (table_groups_id, profile_run_id, test_type, test_suite_id,
                              schema_name, table_name,
                              skip_errors, threshold_value,
                              last_auto_gen_date, test_active, baseline_ct, profiling_as_of_date)
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
     curprof AS (SELECT p.*
                   FROM last_run lr
                 INNER JOIN profile_results p
                    ON (lr.table_groups_id = p.table_groups_id
                    AND lr.last_run_date = p.run_date) ),
     locked AS (SELECT schema_name, table_name, column_name, test_type
                  FROM test_definitions
				     WHERE table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                   AND test_suite_id = '{TEST_SUITE_ID}'
                   AND lock_refresh = 'Y'),
     newtests AS (SELECT table_groups_id, profile_run_id,
                         'Row_Ct' AS test_type,
                         '{TEST_SUITE_ID}'::UUID AS test_suite_id,
                         schema_name,
                         table_name,
                         MAX(record_ct) as record_ct
                    FROM curprof c
                  LEFT JOIN generation_sets s
                     ON ('Row_Ct' = s.test_type
                    AND  '{GENERATION_SET}' = s.generation_set)
                   WHERE schema_name = '{DATA_SCHEMA}'
                     AND functional_table_type LIKE '%cumulative%'
                     AND (s.generation_set IS NOT NULL
                      OR  '{GENERATION_SET}' = '')
                  GROUP BY project_code, table_groups_id, profile_run_id,
                           test_type, test_suite_id, schema_name, table_name )
SELECT n.table_groups_id, n.profile_run_id,
       n.test_type, n.test_suite_id,
       n.schema_name, n.table_name,
       0 as skip_errors, record_ct AS threshold_value,
       '{RUN_DATE}'::TIMESTAMP as last_auto_gen_date,
       'Y' as test_active, record_ct as baseline_ct,
       '{AS_OF_DATE}'::TIMESTAMP as profiling_as_of_date
FROM newtests n
LEFT JOIN locked l
  ON (n.schema_name = l.schema_name
 AND  n.table_name = l.table_name
 AND  n.test_type = l.test_type)
WHERE l.test_type IS NULL;
