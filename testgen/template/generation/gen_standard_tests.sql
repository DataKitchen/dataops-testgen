-- Insert new tests where a locked test is not already present
INSERT INTO test_definitions (table_groups_id, profile_run_id, test_type, test_suite_id,
                              schema_name, table_name, column_name,
                              skip_errors, test_active, last_auto_gen_date, profiling_as_of_date,
                              {DEFAULT_PARM_COLUMNS} )
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
     curprof AS (SELECT p.*, datediff('MM', p.min_date, p.max_date)  as min_max_months, datediff('week', '1800-01-05'::DATE, p.max_date) - datediff('week', '1800-01-05'::DATE, p.min_date) as min_max_weeks
                   FROM last_run lr
                 INNER JOIN profile_results p
                    ON (lr.table_groups_id = p.table_groups_id
                    AND lr.last_run_date = p.run_date) ),
     locked AS (SELECT schema_name, table_name, column_name
                  FROM test_definitions
				     WHERE table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                   AND test_suite_id = '{TEST_SUITE_ID}'
				       AND test_type = '{TEST_TYPE}'
                   AND lock_refresh = 'Y'),
     newtests AS (SELECT *
                  FROM curprof
                  WHERE schema_name = '{DATA_SCHEMA}'
                    AND {SELECTION_CRITERIA} )
SELECT '{TABLE_GROUPS_ID}'::UUID as table_groups_id,
       n.profile_run_id,
       '{TEST_TYPE}' AS test_type,
       '{TEST_SUITE_ID}' AS test_suite_id,
       n.schema_name, n.table_name, n.column_name,
       0 as skip_errors, 'Y' as test_active, '{RUN_DATE}'::TIMESTAMP as last_auto_gen_date,
       '{AS_OF_DATE}'::TIMESTAMP as profiling_as_of_date,
       {DEFAULT_PARM_VALUES}
FROM newtests n
LEFT JOIN locked l
  ON (n.schema_name = l.schema_name
 AND  n.table_name = l.table_name
 AND  n.column_name = l.column_name)
WHERE l.schema_name IS NULL;
