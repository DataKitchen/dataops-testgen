/*test-generation-list: project-code, test-suite
Output: list all test generation runs based on last_auto_run_date
Optional: n/a*/

Select test_suite as test_suite_key,
       table_groups_id,
       last_auto_gen_date,
       d.profiling_as_of_date,
       lock_refresh,
       COUNT(DISTINCT schema_name || '.' || table_name) as tables,
       COUNT(DISTINCT schema_name || '.' || table_name || '.' || column_name) as columns,
       COUNT(*) as tests
from test_definitions d
where d.project_code = '{PROJECT_CODE}'
  and test_suite = '{TEST_SUITE}'
  and last_auto_gen_date IS NOT NULL
GROUP BY table_groups_id, project_code, test_suite, last_auto_gen_date, d.profiling_as_of_date, lock_refresh
order by last_auto_gen_date desc;
