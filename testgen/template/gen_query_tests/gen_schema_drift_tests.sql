INSERT INTO test_definitions (table_groups_id, profile_run_id, test_type, test_suite_id,
                              schema_name,
                              skip_errors, test_active, last_auto_gen_date, profiling_as_of_date)
WITH last_run AS (SELECT r.table_groups_id, MAX(run_date) AS last_run_date, p.schema_name, p.profile_run_id
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
                  GROUP BY r.table_groups_id, p.schema_name, p.profile_run_id),
     locked AS (SELECT schema_name
                  FROM test_definitions
				     WHERE table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                   AND test_suite_id = '{TEST_SUITE_ID}'
				       AND test_type = 'Schema_Drift'
                   AND lock_refresh = 'Y'),
     newtests AS (SELECT *
                  FROM last_run lr
                  INNER JOIN test_types t
                     ON ('Schema_Drift' = t.test_type
                    AND   'Y' = t.active)
                  LEFT JOIN generation_sets s
                     ON (t.test_type = s.test_type
                    AND  '{GENERATION_SET}' = s.generation_set)
                  WHERE lr.schema_name = '{DATA_SCHEMA}'
                    AND (s.generation_set IS NOT NULL
                     OR  '{GENERATION_SET}' = '') )
SELECT '{TABLE_GROUPS_ID}'::UUID as table_groups_id,
       n.profile_run_id,
       'Schema_Drift' AS test_type,
       '{TEST_SUITE_ID}' AS test_suite_id,
       n.schema_name,
       0 as skip_errors, 'Y' as test_active,
       '{RUN_DATE}'::TIMESTAMP as last_auto_gen_date,
       '{AS_OF_DATE}'::TIMESTAMP as profiling_as_of_date
FROM newtests n
LEFT JOIN locked l
  ON (n.schema_name = l.schema_name)
WHERE l.schema_name IS NULL;
