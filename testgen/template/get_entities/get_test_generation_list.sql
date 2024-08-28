/*test-generation-list: project-code, test-suite
Output: list all test generation runs based on last_auto_run_date
Optional: n/a*/

  SELECT ts.test_suite AS test_suite_key,
         ts.table_groups_id,
         td.last_auto_gen_date,
         td.profiling_as_of_date,
         td.lock_refresh,
         COUNT(DISTINCT td.schema_name || '.' || td.table_name) as tables,
         COUNT(DISTINCT td.schema_name || '.' || td.table_name || '.' || td.column_name) as columns,
         COUNT(*) as tests
    FROM test_definitions td
    JOIN test_suites ts ON td.test_suite_id = ts.id
   WHERE ts.project_code = '{PROJECT_CODE}'
     AND ts.test_suite = '{TEST_SUITE}'
     AND td.last_auto_gen_date IS NOT NULL
GROUP BY ts.id, td.last_auto_gen_date, td.profiling_as_of_date, td.lock_refresh
ORDER BY td.last_auto_gen_date desc;
